#!/usr/bin/env python3
"""maidcafe — calibration server (v1).

Zero-dependency local web app: parses Anki .apkg wordbooks in ./decks,
serves an audio-first triage UI, and records per-word mastery marks
(1 = unknown, 2 = known by eye only, 3 = known by ear) in SQLite.

Run:  python3 server.py   then open http://localhost:8770
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckparse  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
DECKS_DIR = os.path.join(ROOT, "decks")
CACHE_DIR = os.path.join(ROOT, "cache")
STATIC_DIR = os.path.join(ROOT, "static")
DB_PATH = os.path.join(ROOT, "progress.db")
WORDS_CACHE = os.path.join(CACHE_DIR, "words_cache.json")
ECDICT_DB = os.path.join(ROOT, "data", "stardict.db")
PORT = 8770
BLOCK_SIZE = 100    # words per difficulty block

WORDS = []          # list of word dicts, difficulty-block order
AUDIO = {}          # word(lower) -> absolute audio path
N_TIERS = 1


def build_words():
    global WORDS, AUDIO
    os.makedirs(CACHE_DIR, exist_ok=True)
    if os.path.exists(WORDS_CACHE):
        with open(WORDS_CACHE, "r", encoding="utf-8") as f:
            WORDS = json.load(f)
    else:
        print("First run: extracting and parsing decks (may take a minute)...")
        t0 = time.time()
        WORDS = deckparse.load_all_decks(DECKS_DIR, CACHE_DIR)
        with open(WORDS_CACHE, "w", encoding="utf-8") as f:
            json.dump(WORDS, f, ensure_ascii=False)
        print("Parsed %d words in %.1fs" % (len(WORDS), time.time() - t0))
    AUDIO = {w["word"].lower(): w.get("audio_path")
             for w in WORDS if w.get("audio_path")}
    attach_tiers()


# Chinese exam-syllabus progression: primary sort key. Within one band, corpus
# frequency (BNC/COCA) sorts common -> rare. Untagged words land after GRE,
# frequency-sorted — the "taught nowhere but natives use it daily" band.
TAG_TIER = {"zk": 1, "gk": 2, "cet4": 3, "cet6": 4, "ky": 5,
            "toefl": 6, "ielts": 6, "gre": 7}
UNTAGGED_TIER = 8


def attach_tiers():
    """Order words by (exam-syllabus band, corpus frequency), cut into
    BLOCK_SIZE blocks, shuffle stably inside each block (md5 of the word,
    so order survives restarts)."""
    global WORDS, N_TIERS
    info = {}  # word(lower) -> (band, freq_rank)
    if os.path.exists(ECDICT_DB):
        con = sqlite3.connect(ECDICT_DB)
        try:
            for w in WORDS:
                lw = w["word"].lower()
                row = con.execute(
                    "select frq, bnc, tag from stardict where word = ?", (lw,)
                ).fetchone()
                if not row:
                    row = con.execute(
                        "select frq, bnc, tag from stardict where word = ?",
                        (w["word"],)).fetchone()
                if not row:
                    continue
                frq, bnc, tag = row
                ranks = [x for x in (frq, bnc) if isinstance(x, int) and x > 0]
                band = UNTAGGED_TIER
                if tag:
                    tiers_hit = [TAG_TIER[t] for t in tag.split() if t in TAG_TIER]
                    if tiers_hit:
                        band = min(tiers_hit)
                info[lw] = (band, min(ranks) if ranks else None)
        finally:
            con.close()
        print("ECDICT matched: %d/%d words" % (len(info), len(WORDS)))
    else:
        print("NOTE: %s missing — difficulty blocks fall back to load order" % ECDICT_DB)

    big = 10 ** 9

    def sort_key(w):
        band, rank = info.get(w["word"].lower(), (UNTAGGED_TIER + 1, None))
        return (band, rank if rank is not None else big, w["word"].lower())

    ordered = sorted(WORDS, key=sort_key)
    for i, w in enumerate(ordered):
        w["tier"] = i // BLOCK_SIZE + 1
        band, rank = info.get(w["word"].lower(), (None, None))
        w["band"] = band
        w["freq_rank"] = rank
    N_TIERS = (len(WORDS) + BLOCK_SIZE - 1) // BLOCK_SIZE if WORDS else 1
    WORDS = sorted(
        ordered, key=lambda w: (w["tier"], hashlib.md5(w["word"].encode()).hexdigest()))


AUDIO_OUT = os.path.join(ROOT, "audio_out")
GEN_MODEL = os.environ.get("MAIDCAFE_MODEL", "qwen3.6:27b-mlx")
ECDICT_PATH = os.path.join(ROOT, "data", "stardict.db")

# 复习梯子: 第 N 次听完后，下次到期 = INTERVALS[N-1] 天后；爬完毕业
INTERVALS = [1, 3, 7, 15, 30]
DAY = 86400
NEW_QUOTA_DEFAULT = 5
CHUNK = 7  # 每段对话目标词数


def db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "create table if not exists marks("
        "word text primary key, status integer, ts real)")
    con.execute(
        "create table if not exists dialogues("
        "id integer primary key autoincrement, ts real, scene text,"
        "characters text, target_words text, turns text, report text,"
        "status text)")
    con.execute(
        "create table if not exists word_srs("
        "word text primary key, level integer, due_ts real,"
        "state text, added_ts real)")
    return con


def ecdict_lookup(word):
    if not os.path.exists(ECDICT_PATH):
        return None
    con = sqlite3.connect(ECDICT_PATH)
    try:
        row = con.execute(
            "select phonetic, translation from stardict where word = ?",
            (word.lower(),)).fetchone()
    finally:
        con.close()
    if not row:
        return None
    return {"phonetic": "[%s]" % row[0] if row[0] else "",
            "definition": (row[1] or "").strip()[:200]}


def srs_map(con):
    return {w: {"level": l, "due_ts": d, "state": s}
            for w, l, d, s in con.execute(
                "select word, level, due_ts, state from word_srs")}


def srs_review(con, word):
    """One completed listen for a learning word: climb the ladder."""
    now = time.time()
    row = con.execute(
        "select level, state from word_srs where word=?", (word,)).fetchone()
    if row and row[1] == "graduated":
        return
    level = (row[0] if row else 0) + 1
    if level > len(INTERVALS):
        con.execute(
            "update word_srs set level=?, state='graduated' where word=?",
            (level, word))
        con.execute(
            "update marks set status=3, ts=? where word=?", (now, word))
    else:
        due = now + INTERVALS[level - 1] * DAY
        con.execute(
            "insert into word_srs(word, level, due_ts, state, added_ts)"
            " values(?,?,?,'learning',?)"
            " on conflict(word) do update set level=?, due_ts=?",
            (word, level, due, now, level, due))


def get_backlog(con):
    """Marked unknown but not yet in the SRS ladder, easiest tier first."""
    srs = srs_map(con)
    tier_of = {w["word"].lower(): w.get("tier", 999) for w in WORDS}
    rows = con.execute(
        "select word from marks where status in (1,2)").fetchall()
    backlog = [r[0] for r in rows if r[0] not in srs]
    backlog.sort(key=lambda w: tier_of.get(w, 999))
    return backlog


def spawn_generation(words):
    cmd = [sys.executable, os.path.join(ROOT, "dialogue.py"),
           "--words", ",".join(words)]
    env = dict(os.environ, MAIDCAFE_MODEL=GEN_MODEL)
    log = open(os.path.join(ROOT, "generate.log"), "a")
    subprocess.Popen(cmd, env=env, stdout=log, stderr=log,
                     start_new_session=True)


def word_info(word):
    """phonetic + definition for the 释义卡, from the deck data in memory."""
    lw = word.lower()
    for w in WORDS:
        if w["word"].lower() == lw:
            return {"word": word, "phonetic": w.get("phonetic", ""),
                    "definition": (w.get("definition") or "")[:200],
                    "has_audio": lw in AUDIO}
    return {"word": word, "phonetic": "", "definition": "", "has_audio": False}


def get_marks():
    con = db()
    try:
        return dict(con.execute("select word, status from marks").fetchall())
    finally:
        con.close()


def set_mark(word, status):
    con = db()
    try:
        if status is None:
            con.execute("delete from marks where word=?", (word,))
        else:
            con.execute(
                "insert into marks(word,status,ts) values(?,?,?) "
                "on conflict(word) do update set status=excluded.status, ts=excluded.ts",
                (word, status, time.time()))
        con.commit()
    finally:
        con.close()


def word_match(w, deck, tier):
    if deck != "all" and deck not in w.get("sources", []):
        return False
    if tier != "all" and w.get("tier", 1) != int(tier):
        return False
    return True


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".mp3": "audio/mpeg",
    ".json": "application/json; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass  # keep the console quiet

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        if not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        ext = os.path.splitext(path)[1].lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/":
            return self._send_file(os.path.join(STATIC_DIR, "index.html"))

        if path.startswith("/static/"):
            fname = os.path.basename(unquote(path))
            return self._send_file(os.path.join(STATIC_DIR, fname))

        if path.startswith("/audio/"):
            word = unquote(path[len("/audio/"):]).lower()
            audio_path = AUDIO.get(word)
            if not audio_path or not os.path.isfile(audio_path):
                return self._send(404, {"error": "no audio"})
            with open(audio_path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/words":
            deck = qs.get("deck", ["all"])[0]
            mode = qs.get("mode", ["unmarked"])[0]
            tier = qs.get("tier", ["all"])[0]
            marks = get_marks()
            out = []
            for w in WORDS:
                if not word_match(w, deck, tier):
                    continue
                status = marks.get(w["word"].lower())
                if mode == "unmarked" and status is not None:
                    continue
                out.append({
                    "word": w["word"],
                    "phonetic": w.get("phonetic", ""),
                    "definition": (w.get("definition") or "")[:400],
                    "example_en": w.get("example_en", ""),
                    "example_cn": w.get("example_cn", ""),
                    "sources": w.get("sources", []),
                    "tier": w.get("tier", 1),
                    "has_audio": w["word"].lower() in AUDIO,
                    "status": status,
                })
            return self._send(200, out)

        if path == "/api/stats":
            marks = get_marks()
            deck = qs.get("deck", ["all"])[0]
            tier = qs.get("tier", ["all"])[0]
            words = [w for w in WORDS if word_match(w, deck, tier)]
            counts = {1: 0, 2: 0, 3: 0}
            marked = 0
            for w in words:
                s = marks.get(w["word"].lower())
                if s in counts:
                    counts[s] += 1
                    marked += 1
            # real marking pace: median gap (<=30s) between recent marks
            con = db()
            try:
                rows = con.execute(
                    "select ts from marks order by ts desc limit 300").fetchall()
            finally:
                con.close()
            tss = sorted(r[0] for r in rows if r[0])
            gaps = [b - a for a, b in zip(tss, tss[1:]) if 0 < b - a <= 30]
            pace = round(sorted(gaps)[len(gaps) // 2], 2) if len(gaps) >= 10 else 4.5
            overall_marked = sum(1 for w in WORDS if w["word"].lower() in marks)
            return self._send(200, {
                "total": len(words),
                "marked": marked,
                "unknown": counts[1],
                "eye_only": counts[2],
                "ear_known": counts[3],
                "pace": pace,
                "overall_total": len(WORDS),
                "overall_marked": overall_marked,
            })

        if path == "/api/tiers":
            marks = get_marks()
            deck = qs.get("deck", ["all"])[0]
            tiers = {}
            for w in WORDS:
                if deck != "all" and deck not in w.get("sources", []):
                    continue
                t = w.get("tier", 1)
                d = tiers.setdefault(t, {"tier": t, "total": 0, "marked": 0,
                                         "unknown": 0, "bmin": None, "bmax": None})
                d["total"] += 1
                b = w.get("band")
                if b is not None:
                    d["bmin"] = b if d["bmin"] is None else min(d["bmin"], b)
                    d["bmax"] = b if d["bmax"] is None else max(d["bmax"], b)
                s = marks.get(w["word"].lower())
                if s is not None:
                    d["marked"] += 1
                    if s in (1, 2):  # any J = 生词
                        d["unknown"] += 1
            return self._send(200, [tiers[t] for t in sorted(tiers)])

        if path == "/listen":
            return self._send_file(os.path.join(STATIC_DIR, "listen.html"))

        if path.startswith("/dialogue_audio/"):
            parts = unquote(path).split("/")
            if len(parts) == 4 and parts[2].isdigit():
                fpath = os.path.join(AUDIO_OUT, parts[2], os.path.basename(parts[3]))
                return self._send_file(fpath)
            return self._send(404, {"error": "bad path"})

        if path == "/api/dialogues":
            con = db()
            try:
                rows = con.execute(
                    "select id, ts, scene, characters, target_words, status, turns"
                    " from dialogues order by id desc").fetchall()
            finally:
                con.close()
            out = []
            for r in rows:
                out.append({
                    "id": r[0], "ts": r[1], "scene": r[2],
                    "characters": json.loads(r[3] or "[]"),
                    "targets": json.loads(r[4] or "[]"),
                    "status": r[5],
                    "n_turns": len(json.loads(r[6] or "[]")),
                })
            return self._send(200, out)

        if path.startswith("/api/dialogue/"):
            did = path.rsplit("/", 1)[-1]
            if not did.isdigit():
                return self._send(404, {"error": "bad id"})
            con = db()
            try:
                r = con.execute(
                    "select id, ts, scene, characters, target_words, turns, report,"
                    " status from dialogues where id=?", (int(did),)).fetchone()
            finally:
                con.close()
            if not r:
                return self._send(404, {"error": "not found"})
            adir = os.path.join(AUDIO_OUT, did)
            files = sorted(f for f in os.listdir(adir)
                           if f.startswith("turn_")) if os.path.isdir(adir) else []
            targets = json.loads(r[4] or "[]")
            return self._send(200, {
                "id": r[0], "ts": r[1], "scene": r[2],
                "characters": json.loads(r[3] or "[]"),
                "targets": [word_info(t) for t in targets],
                "turns": json.loads(r[5] or "[]"),
                "report": json.loads(r[6] or "{}"),
                "status": r[7], "files": files,
            })

        if path == "/api/wordbook":
            con = db()
            try:
                words = con.execute(
                    "select word, status from marks where status in (1,2)"
                    " order by ts desc").fetchall()
                drows = con.execute(
                    "select id, target_words, scene from dialogues").fetchall()
                srs = srs_map(con)
                grad_rows = con.execute(
                    "select word from word_srs where state='graduated'"
                    " order by added_ts desc").fetchall()
            finally:
                con.close()
            appearances = {}
            for did, tw, scene in drows:
                for t in json.loads(tw or "[]"):
                    appearances.setdefault(t.lower(), []).append(
                        {"id": did, "scene": scene})
            now = time.time()
            out = []
            for w, s in words:
                info = word_info(w)
                info["status"] = s
                info["dialogues"] = appearances.get(w.lower(), [])
                st = srs.get(w)
                if st:
                    info["srs"] = {
                        "level": st["level"],
                        "due_in_days": round((st["due_ts"] - now) / DAY, 1),
                        "due": st["due_ts"] <= now,
                    }
                else:
                    info["srs"] = None  # 还在生词池
                out.append(info)
            graduated = [word_info(r[0]) for r in grad_rows]
            return self._send(200, {"learning": out, "graduated": graduated})

        if path == "/api/lookup":
            word = qs.get("word", [""])[0].strip()
            if not word:
                return self._send(400, {"error": "no word"})
            info = word_info(word)
            if not info["definition"]:
                ec = ecdict_lookup(word)
                if ec:
                    info["phonetic"] = info["phonetic"] or ec["phonetic"]
                    info["definition"] = ec["definition"]
            con = db()
            try:
                m = con.execute("select status from marks where word=?",
                                (word.lower(),)).fetchone()
            finally:
                con.close()
            info["in_wordbook"] = bool(m and m[0] in (1, 2))
            info["known"] = bool(m and m[0] == 3)
            return self._send(200, info)

        if path == "/api/daily_status":
            con = db()
            try:
                srs = srs_map(con)
                backlog = get_backlog(con)
            finally:
                con.close()
            now = time.time()
            learning = [w for w, s in srs.items() if s["state"] == "learning"]
            due = [w for w in learning if srs[w]["due_ts"] <= now]
            graduated = [w for w, s in srs.items() if s["state"] == "graduated"]
            return self._send(200, {
                "due": len(due), "backlog": len(backlog),
                "learning": len(learning), "graduated": len(graduated),
            })

        if path == "/api/decks":
            decks = []
            seen = set()
            for w in WORDS:
                for s in w.get("sources", []):
                    if s not in seen:
                        seen.add(s)
                        decks.append(s)
            return self._send(200, decks)

        return self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})

        if parsed.path == "/api/mark":
            word = (payload.get("word") or "").lower()
            status = payload.get("status")  # 1 / 2 / 3 / None(=undo)
            if not word or status not in (1, 2, 3, None):
                return self._send(400, {"error": "bad params"})
            set_mark(word, status)
            return self._send(200, {"ok": True})

        if parsed.path == "/api/generate":
            words = payload.get("words") or []
            cmd = [sys.executable, os.path.join(ROOT, "dialogue.py")]
            if words:
                cmd += ["--words", ",".join(words)]
            else:
                cmd += ["--auto", str(payload.get("auto", 6))]
            env = dict(os.environ, MAIDCAFE_MODEL=GEN_MODEL)
            log = open(os.path.join(ROOT, "generate.log"), "a")
            subprocess.Popen(cmd, env=env, stdout=log, stderr=log,
                             start_new_session=True)
            return self._send(200, {"started": True})

        if parsed.path == "/api/daily_task":
            quota = payload.get("new_quota", NEW_QUOTA_DEFAULT)
            now = time.time()
            con = db()
            try:
                srs = srs_map(con)
                due = [w for w, s in srs.items()
                       if s["state"] == "learning" and s["due_ts"] <= now]
                backlog = get_backlog(con)
                fresh = backlog[:quota]
                # 新词立刻挂上梯子(level 0, 到期=现在)，从此纳入调度
                for w in fresh:
                    con.execute(
                        "insert or ignore into word_srs"
                        "(word, level, due_ts, state, added_ts)"
                        " values(?,0,?, 'learning', ?)", (w, now, now))
                con.commit()
            finally:
                con.close()
            pool = due + fresh
            if not pool:
                return self._send(200, {"chunks": [], "message": "今天没有到期词"})
            chunks = [pool[i:i + CHUNK] for i in range(0, len(pool), CHUNK)]
            for chunk in chunks:
                spawn_generation(chunk)
            return self._send(200, {"chunks": chunks, "started": True})

        if parsed.path == "/api/listened":
            did = payload.get("id")
            if not isinstance(did, int):
                return self._send(400, {"error": "bad id"})
            con = db()
            try:
                row = con.execute(
                    "select target_words from dialogues where id=?",
                    (did,)).fetchone()
                if not row:
                    return self._send(404, {"error": "not found"})
                for w in json.loads(row[0] or "[]"):
                    srs_review(con, w.lower())
                con.commit()
            finally:
                con.close()
            return self._send(200, {"ok": True})

        if parsed.path == "/api/word/learned":
            word = (payload.get("word") or "").lower()
            if not word:
                return self._send(400, {"error": "no word"})
            now = time.time()
            con = db()
            try:
                con.execute(
                    "insert into word_srs(word, level, due_ts, state, added_ts)"
                    " values(?,99,?, 'graduated', ?)"
                    " on conflict(word) do update set state='graduated'",
                    (word, now, now))
                con.execute(
                    "update marks set status=3, ts=? where word=?", (now, word))
                con.commit()
            finally:
                con.close()
            return self._send(200, {"ok": True})

        if parsed.path == "/api/word/unfamiliar":
            word = (payload.get("word") or "").lower()
            if not word:
                return self._send(400, {"error": "no word"})
            now = time.time()
            con = db()
            try:
                con.execute(
                    "insert into word_srs(word, level, due_ts, state, added_ts)"
                    " values(?,0,?, 'learning', ?)"
                    " on conflict(word) do update set"
                    " level=0, due_ts=?, state='learning'",
                    (word, now, now, now))
                con.commit()
            finally:
                con.close()
            return self._send(200, {"ok": True})

        if parsed.path == "/api/word/readd":
            word = (payload.get("word") or "").lower()
            if not word:
                return self._send(400, {"error": "no word"})
            now = time.time()
            con = db()
            try:
                con.execute(
                    "update marks set status=1, ts=? where word=?", (now, word))
                con.execute(
                    "insert into word_srs(word, level, due_ts, state, added_ts)"
                    " values(?,0,?, 'learning', ?)"
                    " on conflict(word) do update set"
                    " level=0, due_ts=?, state='learning'",
                    (word, now, now, now))
                con.commit()
            finally:
                con.close()
            return self._send(200, {"ok": True})

        if parsed.path == "/api/wordbook_add":
            word = (payload.get("word") or "").strip().lower()
            if not word or not word.replace("-", "").replace("'", "").isalpha():
                return self._send(400, {"error": "bad word"})
            info = word_info(word)
            if not info["definition"] and not ecdict_lookup(word):
                return self._send(404, {"error": "词典里查不到这个词"})
            set_mark(word, 1)
            return self._send(200, {"ok": True})

        if parsed.path == "/api/dialogue_delete":
            did = payload.get("id")
            if not isinstance(did, int):
                return self._send(400, {"error": "bad id"})
            con = db()
            try:
                con.execute("delete from dialogues where id=?", (did,))
                con.commit()
            finally:
                con.close()
            adir = os.path.join(AUDIO_OUT, str(did))
            if os.path.isdir(adir):
                shutil.rmtree(adir)
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})


def main():
    build_words()
    print("maidcafe ready: %d words, %d with audio" % (len(WORDS), len(AUDIO)))
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Serving on http://localhost:%d" % PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
