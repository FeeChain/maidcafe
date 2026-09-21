#!/usr/bin/env python3
"""maidcafe — calibration server (v1).

Zero-dependency local web app: parses Anki .apkg wordbooks in ./decks,
serves an audio-first triage UI, and records per-word mastery marks
(1 = unknown, 2 = known by eye only, 3 = known by ear) in SQLite.

Run:  python3 server.py   then open http://localhost:8770
"""

import hashlib
import json
import math
import os
import random
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
CACHE_DIR = os.environ.get("MAIDCAFE_CACHE", os.path.join(ROOT, "cache"))
STATIC_DIR = os.path.join(ROOT, "static")
DB_PATH = os.environ.get("MAIDCAFE_DB", os.path.join(ROOT, "progress.db"))
WORDS_CACHE = os.path.join(CACHE_DIR, "words_cache.json")
ECDICT_DB = os.environ.get("MAIDCAFE_ECDICT", os.path.join(ROOT, "data", "stardict.db"))
PORT = int(os.environ.get("MAIDCAFE_PORT", "8770"))
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
        w["rank"] = i          # 全局难度序号（band+词频），生词池按它出词
        band, rank = info.get(w["word"].lower(), (None, None))
        w["band"] = band
        w["freq_rank"] = rank
    N_TIERS = (len(WORDS) + BLOCK_SIZE - 1) // BLOCK_SIZE if WORDS else 1
    WORDS = sorted(
        ordered, key=lambda w: (w["tier"], hashlib.md5(w["word"].encode()).hexdigest()))


AUDIO_OUT = os.environ.get("MAIDCAFE_AUDIO_OUT",
                           os.path.join(ROOT, "audio_out"))
GEN_MODEL = os.environ.get("MAIDCAFE_MODEL", "qwen3.6:27b-mlx")
ECDICT_PATH = ECDICT_DB

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
    # mark provenance: scan(全扫)/probe(探针)=随机样本 · add(手动加词)=有偏
    try:
        con.execute("alter table marks add column src text")
    except sqlite3.OperationalError:
        pass  # column already exists
    con.execute(
        "create table if not exists dialogues("
        "id integer primary key autoincrement, ts real, scene text,"
        "characters text, target_words text, turns text, report text,"
        "status text)")
    con.execute(
        "create table if not exists word_srs("
        "word text primary key, level integer, due_ts real,"
        "state text, added_ts real)")
    # 盲测档案：重测的标记独立存放，不碰主记录；用户测完自选
    # 「采用为主记录」（合并覆写）或仅存档/删除
    con.execute(
        "create table if not exists probe_sessions("
        "id integer primary key autoincrement, ts real, kind text,"
        "status text, result text)")
    con.execute(
        "create table if not exists probe_marks("
        "session integer, word text, status integer, ts real,"
        "primary key(session, word))")
    con.execute(
        "create table if not exists kv(key text primary key, value text)")
    # 操作日志：前端每次点击/按键/视图跳转都记一行，测试回放用
    con.execute(
        "create table if not exists events("
        "id integer primary key autoincrement, ts real, page text,"
        "view text, event text, detail text)")
    # 同一天内重复复习不重复爬梯（听完对话 + 考试通过只算一次）
    try:
        con.execute("alter table word_srs add column reviewed_ts real")
    except sqlite3.OperationalError:
        pass
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


def same_day(a, b):
    return a and b and time.localtime(a)[:3] == time.localtime(b)[:3]


def srs_review(con, word):
    """One completed review for a learning word: climb the ladder.
    Idempotent per calendar day — 听完对话与考试通过同天只爬一级。"""
    now = time.time()
    row = con.execute(
        "select level, state, reviewed_ts from word_srs where word=?",
        (word,)).fetchone()
    if row and row[1] == "graduated":
        return
    if row and same_day(row[2], now):
        return
    con.execute("update word_srs set reviewed_ts=? where word=?", (now, word))
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
            "insert into word_srs(word, level, due_ts, state, added_ts, reviewed_ts)"
            " values(?,?,?,'learning',?,?)"
            " on conflict(word) do update set level=?, due_ts=?, reviewed_ts=?",
            (word, level, due, now, now, level, due, now))


def kv_get(key, default=None):
    con = db()
    try:
        row = con.execute("select value from kv where key=?", (key,)).fetchone()
        return row[0] if row else default
    finally:
        con.close()


def kv_set(key, value):
    con = db()
    try:
        con.execute("insert into kv(key,value) values(?,?) "
                    "on conflict(key) do update set value=excluded.value",
                    (key, str(value)))
        con.commit()
    finally:
        con.close()


def session_word_out(word, is_new):
    info = word_info(word)
    return {"word": word, "phonetic": info.get("phonetic", ""),
            "definition": (info.get("definition") or "")[:400],
            "has_audio": word in AUDIO, "is_new": is_new}


def build_session():
    """一份学习会话（无「每天/任务」概念，打开一次抓一份，零落库）：
    到期复习全部上桌（最早到期在前）+ 新词取配额个（不预注册，考过才进梯）。
    背完就是背完；没背完的什么都不记——复习词照旧到期、新词留在生词池，
    下次打开（当天或十天后）自然回来。"""
    con = db()
    try:
        now = time.time()
        srs = srs_map(con)
        due = [w for w, s in sorted(srs.items(), key=lambda x: x[1]["due_ts"])
               if s["state"] == "learning" and s["due_ts"] <= now]
        quota = int(kv_get("new_quota", 20))
        candidates = get_backlog(con)
        if len(candidates) < quota and has_probe_evidence():
            # 生词池不够一份：探针已定位边界，边界之外没标过的词
            # 本来就推定为生词——按难度顺序补满（考过才进梯，其余零记录）。
            # 证据门槛（>=3 样本的块存在）不满足时不结算边界（S0 会先拦住）
            nxt = probe_next("all", settle=True)
            if nxt.get("done"):
                frontier = nxt["bracket"][1]  # 第一个生词侧的块
                marks = get_marks()
                taken = set(candidates)
                for w in sorted(WORDS, key=lambda x: x.get("rank", 10 ** 9)):
                    lw = w["word"].lower()
                    if (w.get("tier", 1) >= frontier and lw not in marks
                            and lw not in srs and lw not in taken):
                        candidates.append(lw)
                        taken.add(lw)
                        if len(candidates) >= quota:
                            break
        rank_of = {w["word"].lower(): w.get("rank", 10 ** 9) for w in WORDS}
        fresh = sorted(candidates, key=lambda w: rank_of.get(w, 10 ** 9))[:quota]
    finally:
        con.close()
    return {"words": ([session_word_out(w, False) for w in due] +
                      [session_word_out(w, True) for w in fresh])}


def get_backlog(con):
    """Marked unknown but not yet in the SRS ladder, strict difficulty order
    (global band+frequency rank, not just block number)."""
    srs = srs_map(con)
    rank_of = {w["word"].lower(): w.get("rank", 10 ** 9) for w in WORDS}
    rows = con.execute(
        "select word from marks where status in (1,2)").fetchall()
    backlog = [r[0] for r in rows if r[0] not in srs]
    backlog.sort(key=lambda w: rank_of.get(w, 10 ** 9))
    return backlog


def write_known_snapshot():
    """已知词集快照，dialogue.py 校验已知占比用。
    核心定义（用户定稿）：已知 = 边界块之内的**全部**单词（推定已知）
    + 显式标记认识的词。边界由探针无状态重放得出。"""
    known = set()
    try:
        if has_probe_evidence():
            nxt = probe_next("all", settle=True)
            if nxt.get("done"):
                frontier = nxt["bracket"][1]  # 第一个生词侧的块
                known.update(w["word"].lower() for w in WORDS
                             if w.get("tier", 1) < frontier)
    except Exception:
        pass
    marks = get_marks()
    known.update(w for w, s in marks.items() if s == 3)
    # 全扫在边界内逐词揪出的漏词：显式标了不认识的，推定失效，从已知集剔除
    known.difference_update(w for w, s in marks.items() if s in (1, 2))
    with open(os.path.join(CACHE_DIR, "known_words.json"), "w",
              encoding="utf-8") as f:
        json.dump(sorted(known), f, ensure_ascii=False)


def spawn_generation(words):
    write_known_snapshot()
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


def set_mark(word, status, src=None):
    con = db()
    try:
        if status is None:
            con.execute("delete from marks where word=?", (word,))
        else:
            con.execute(
                "insert into marks(word,status,ts,src) values(?,?,?,?) "
                "on conflict(word) do update set status=excluded.status, "
                "ts=excluded.ts, src=excluded.src",
                (word, status, time.time(), src))
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------- probe mode
# 探针式词汇量测定（v1.5 抽样估算）：每块凑满 per 个真实标记（已有标记直接
# 算样本，所以全扫过的块自动跳过）。估算时精确块用精确计数、抽样块按比例
# 推定——某块之后被全扫，估算自动切换成精确值，无需任何迁移。

PROBE_PER_BLOCK = 3


def words_of_deck(deck):
    by_tier = {}
    for w in WORDS:
        if deck != "all" and deck not in w.get("sources", []):
            continue
        by_tier.setdefault(w.get("tier", 1), []).append(w)
    return by_tier


def get_marks_src():
    con = db()
    try:
        return {w: (s, src) for w, s, src in
                con.execute("select word, status, src from marks").fetchall()}
    finally:
        con.close()


def session_marks_src(session):
    """盲测档案的标记，形状与 get_marks_src 一致（全部视为随机样本）。"""
    con = db()
    try:
        return {w: (s, "probe") for w, s in con.execute(
            "select word, status from probe_marks where session=?",
            (session,)).fetchall()}
    finally:
        con.close()


def marks_src_for(qs):
    sess = qs.get("session", [None])[0]
    return session_marks_src(int(sess)) if sess else get_marks_src()


def block_samples(ws, marks_src):
    """一个块里可当随机样本的标记。规则：
    - src=scan/probe 一定是随机样本；
    - src=add（手动加词，只有生词才会被加）是有偏样本，永远排除；
    - 历史 NULL src：块覆盖率 >=30% 视为早期全扫的中途存档（块内 md5 乱序，
      前缀即随机样本），零散的视为加词，排除。"""
    hits = [(w, marks_src[w["word"].lower()]) for w in ws
            if w["word"].lower() in marks_src]
    coverage = len(hits) / len(ws) if ws else 0
    out = []
    for w, (status, src) in hits:
        if src == "add":
            continue
        if src is None and coverage < 0.3:
            continue
        out.append(status)
    return out, len(hits)


def probe_word_out(w, tier):
    return {
        "word": w["word"],
        "phonetic": w.get("phonetic", ""),
        "definition": (w.get("definition") or "")[:400],
        "example_en": w.get("example_en", ""),
        "example_cn": w.get("example_cn", ""),
        "sources": w.get("sources", []),
        "tier": tier,
        "has_audio": w["word"].lower() in AUDIO,
        "status": None,
    }


def block_class(ws, marks_src):
    """块判定（用户定的动态规则，known = 听得出 status 3）：
    3 全会 -> high；3 中 >=2 不会 -> low；3 中 1 不会 -> need_more（再抽 3）；
    6 词里 <=1 不会 -> high、>=4 不会 -> low、否则 mid（这块就是边界带）。
    全扫过的块按真实认识率归类。"""
    samples, n_all = block_samples(ws, marks_src)
    total = len(ws)
    if total and n_all == total:
        r = sum(1 for w in ws if marks_src[w["word"].lower()][0] == 3) / total
        return "high" if r >= 0.85 else ("low" if r <= 0.5 else "mid")
    n = len(samples)
    if n < 3:
        return "unsampled"
    u = sum(1 for s in samples if s != 3)
    if n < 6:
        if u == 0:
            return "high"
        if u >= 2:
            return "low"
        return "need_more"
    return "high" if u <= 1 else ("low" if u >= 4 else "mid")


def pick_block_words(ws, marks_src, deck, tier, k):
    unmarked = [w for w in ws if w["word"].lower() not in marks_src]
    rng = random.Random("probe:%s:%d" % (deck, tier))
    rng.shuffle(unmarked)
    return [probe_word_out(w, tier) for w in unmarked[:k]]


def has_probe_evidence(marks_src=None):
    """边界推定的证据门槛：至少有一个块攒到 >=3 个无偏样本
    （零星一两个标记不足以"结算"出边界——防止 settle 模式过度推定）。"""
    if marks_src is None:
        marks_src = get_marks_src()
    for _, ws in words_of_deck("all").items():
        samples, _ = block_samples(ws, marks_src)
        if len(samples) >= 3:
            return True
    return False


def probe_next(deck, marks_src=None, settle=False):
    """动态探针：对按难度排好的块做折半查找，把「已知侧/生词侧」的边界
    夹到相邻两块，区间中点即真实边界。无状态——每次调用从现有标记重放
    整个搜索，中断随时可续。
    settle=True：结算模式（算已知集快照用）——含糊/缺样本的块按现有样本
    多数硬归类，绝不返回「还要再测几个词」。"""
    if marks_src is None:
        marks_src = get_marks_src()
    by = words_of_deck(deck)
    tiers = sorted(by)
    n_words = lambda: sum(1 for w, (s, src) in marks_src.items()
                          if src == "probe")
    lo, hi = 0, len(tiers) + 1          # 1-based bracket over tiers[]
    while hi - lo > 1:
        mid = (lo + hi) // 2
        t = tiers[mid - 1]
        c = block_class(by[t], marks_src)
        if c in ("unsampled", "need_more"):
            words = None if settle else pick_block_words(by[t], marks_src, deck, t, 3)
            if not words:               # 结算模式/块抽干了：按现有样本硬归类
                samples, _ = block_samples(by[t], marks_src)
                u = sum(1 for s in samples if s != 3)
                c = "high" if samples and u * 2 < len(samples) else "low"
            else:
                return {"done": False, "tier": t, "phase": c,
                        "bracket": [tiers[lo - 1] if lo else 0,
                                    tiers[hi - 1] if hi <= len(tiers) else tiers[-1] + 1],
                        "words": words}
        if c == "high":
            lo = mid
        elif c == "low":
            hi = mid
        else:                            # mid：这块本身就是边界带
            lo, hi = mid, mid + 1
            break
    b_lo = tiers[lo - 1] if lo else 0
    b_hi = tiers[hi - 1] if hi <= len(tiers) else (tiers[-1] + 1 if tiers else 1)
    boundary = (b_lo + b_hi) / 2.0
    bands = [w.get("band") for w in by.get(int(round(boundary)) or (tiers[0] if tiers else 1), [])
             if w.get("band") is not None]
    if not bands and tiers:
        near = min(tiers, key=lambda t: abs(t - boundary))
        bands = [w.get("band") for w in by[near] if w.get("band") is not None]
    return {"done": True, "boundary": boundary,
            "bracket": [b_lo, b_hi],
            "boundary_band": min(bands) if bands else None,
            "probe_words": n_words()}


def probe_queue(deck, per, marks_src=None):
    if marks_src is None:
        marks_src = get_marks_src()
    out = []
    for tier, ws in sorted(words_of_deck(deck).items()):
        samples, n_all = block_samples(ws, marks_src)
        unmarked = [w for w in ws if w["word"].lower() not in marks_src]
        need = min(per - len(samples), len(unmarked))
        if need <= 0:
            continue
        # deterministic per-block shuffle: refresh mid-probe keeps the sample
        rng = random.Random("probe:%s:%d" % (deck, tier))
        rng.shuffle(unmarked)
        for w in unmarked[:need]:
            out.append({
                "word": w["word"],
                "phonetic": w.get("phonetic", ""),
                "definition": (w.get("definition") or "")[:400],
                "example_en": w.get("example_en", ""),
                "example_cn": w.get("example_cn", ""),
                "sources": w.get("sources", []),
                "tier": tier,
                "has_audio": w["word"].lower() in AUDIO,
                "status": None,
            })
    return out


def vocab_estimate(deck, marks_src=None):
    if marks_src is None:
        marks_src = get_marks_src()
    blocks = []
    for tier, ws in sorted(words_of_deck(deck).items()):
        total = len(ws)
        bands = [w.get("band") for w in ws if w.get("band") is not None]
        samples, n_all = block_samples(ws, marks_src)
        n = len(samples)
        k_listen = sum(1 for s in samples if s == 3)
        k_read = sum(1 for s in samples if s in (2, 3))
        b = {"tier": tier, "total": total, "n": n,
             "band": min(bands) if bands else UNTAGGED_TIER,
             "var_listen": 0.0, "var_read": 0.0}
        if n_all == total:
            # census: every word marked — use the true counts, any src
            k_listen = sum(1 for w in ws if marks_src[w["word"].lower()][0] == 3)
            k_read = sum(1 for w in ws if marks_src[w["word"].lower()][0] in (2, 3))
            b["n"] = total
            b.update(method="exact", est_listen=float(k_listen),
                     est_read=float(k_read))
        elif n > 0:
            b.update(method="probe", est_listen=k_listen / n * total,
                     est_read=k_read / n * total)
            # variance of the block estimate (finite population corrected);
            # +0.5 smoothing so a tiny all-yes/all-no sample doesn't claim
            # zero uncertainty
            fpc = (total - n) / max(total - 1, 1)
            for key, k in (("var_listen", k_listen), ("var_read", k_read)):
                p = (k + 0.5) / (n + 1)
                b[key] = total * total * p * (1 - p) / n * fpc
        else:
            b.update(method="none", est_listen=None, est_read=None)
        blocks.append(b)

    # unmeasured blocks: interpolate the knowledge-rate curve from the
    # nearest measured neighbours (difficulty is monotonic-ish across tiers)
    measured = [i for i, b in enumerate(blocks) if b["method"] != "none"]
    for i, b in enumerate(blocks):
        if b["method"] != "none":
            continue
        lo = max((j for j in measured if j < i), default=None)
        hi = min((j for j in measured if j > i), default=None)
        def ratio(j, key):
            return blocks[j]["est_" + key] / blocks[j]["total"]
        for key in ("listen", "read"):
            if lo is not None and hi is not None:
                t = (i - lo) / (hi - lo)
                r = ratio(lo, key) * (1 - t) + ratio(hi, key) * t
            elif lo is not None:
                r = ratio(lo, key)
            elif hi is not None:
                r = ratio(hi, key)
            else:
                r = 0.0
            b["est_" + key] = r * b["total"]

    band_agg = {}
    for b in blocks:
        d = band_agg.setdefault(b["band"], {"band": b["band"], "total": 0,
                                            "listen": 0.0, "read": 0.0})
        d["total"] += b["total"]
        d["listen"] += b["est_listen"]
        d["read"] += b["est_read"]
    return {
        "listening": round(sum(b["est_listen"] for b in blocks)),
        "reading": round(sum(b["est_read"] for b in blocks)),
        "ci95_listen": round(1.96 * math.sqrt(sum(b["var_listen"] for b in blocks))),
        "ci95_read": round(1.96 * math.sqrt(sum(b["var_read"] for b in blocks))),
        "total_words": sum(b["total"] for b in blocks),
        "sampled": sum(b["n"] for b in blocks),
        "exact_blocks": sum(1 for b in blocks if b["method"] == "exact"),
        "probe_blocks": sum(1 for b in blocks if b["method"] == "probe"),
        "unmeasured_blocks": sum(1 for b in blocks if b["method"] == "none"),
        "bands": [{"band": d["band"], "total": d["total"],
                   "listen": round(d["listen"]), "read": round(d["read"])}
                  for d in (band_agg[k] for k in sorted(band_agg))],
        "per_block": [{"tier": b["tier"], "method": b["method"], "n": b["n"],
                       "ratio_listen": round(b["est_listen"] / b["total"], 3),
                       "ratio_read": round(b["est_read"] / b["total"], 3)}
                      for b in blocks if b["total"]],
    }


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
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".gif": "image/gif",
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
        # 本地应用：页面与脚本永远要最新，否则改版后浏览器跑旧 JS（幽灵 bug）
        if ext in (".html", ".js", ".css"):
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/":
            return self._send_file(os.path.join(STATIC_DIR, "home.html"))

        if path == "/calibrate":
            return self._send_file(os.path.join(STATIC_DIR, "calibrate.html"))

        if path.startswith("/static/"):
            # allow subdirectories (static/art/...) but never path traversal
            rel = os.path.normpath(unquote(path[len("/static/"):]))
            if rel.startswith("..") or os.path.isabs(rel):
                return self._send(404, {"error": "not found"})
            return self._send_file(os.path.join(STATIC_DIR, rel))

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

        if path == "/api/probe_next":
            deck = qs.get("deck", ["all"])[0]
            return self._send(200, probe_next(deck, marks_src_for(qs)))

        if path == "/api/probe_queue":
            deck = qs.get("deck", ["all"])[0]
            per = int(qs.get("per", [PROBE_PER_BLOCK])[0])
            return self._send(200, probe_queue(deck, per, marks_src_for(qs)))

        if path == "/api/vocab_estimate":
            deck = qs.get("deck", ["all"])[0]
            return self._send(200, vocab_estimate(deck, marks_src_for(qs)))

        if path == "/api/probe_sessions":
            con = db()
            try:
                rows = con.execute(
                    "select id, ts, kind, status, result from probe_sessions "
                    "where status in ('done','adopted') order by id desc").fetchall()
            finally:
                con.close()
            return self._send(200, [
                {"id": r[0], "ts": r[1], "kind": r[2], "status": r[3],
                 "result": json.loads(r[4]) if r[4] else None} for r in rows])

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
                    "select id, ts, scene, characters, target_words, status,"
                    " turns, report from dialogues order by id desc").fetchall()
            finally:
                con.close()
            out = []
            for r in rows:
                rep = json.loads(r[7] or "{}")
                out.append({
                    "id": r[0], "ts": r[1], "scene": r[2],
                    "characters": json.loads(r[3] or "[]"),
                    "targets": json.loads(r[4] or "[]"),
                    "status": r[5],
                    "n_turns": len(json.loads(r[6] or "[]")),
                    "progress": rep.get("progress"),
                    "error": rep.get("error"),
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
                s = con.execute("select state from word_srs where word=?",
                                (word.lower(),)).fetchone()
            finally:
                con.close()
            # 身份以 marks ∪ word_srs 合并判定：毕业记录在梯上，
            # marks 可能无行（边界外推定词直接学会的场景）
            info["in_wordbook"] = bool(m and m[0] in (1, 2)) or \
                bool(s and s[0] == "learning")
            info["known"] = bool(m and m[0] == 3) or \
                bool(s and s[0] == "graduated")
            return self._send(200, info)

        if path == "/api/home_status":
            con = db()
            try:
                n_all = con.execute(
                    "select count(*) from marks where src in ('scan','probe') "
                    "or src is null").fetchone()[0]
                n_sessions = con.execute(
                    "select count(*) from probe_sessions "
                    "where status in ('done','adopted')").fetchone()[0]
            finally:
                con.close()
            # 已校准 = 动态探针已收敛（无状态重放判定，任意词库规模都成立）
            #         或 全扫过 50+ 词 或 有盲测档案
            probe_done = bool(probe_next("all").get("done"))
            return self._send(200, {
                "calibrated": probe_done or n_all >= 50 or n_sessions > 0,
                "new_quota": int(kv_get("new_quota", 20))})

        if path == "/api/session":
            return self._send(200, build_session())

        if path == "/api/log":
            limit = min(int(qs.get("limit", ["300"])[0]), 2000)
            con = db()
            try:
                rows = con.execute(
                    "select ts, page, view, event, detail from events "
                    "order by id desc limit ?", (limit,)).fetchall()
            finally:
                con.close()
            return self._send(200, [
                {"ts": r[0], "page": r[1], "view": r[2],
                 "event": r[3], "detail": r[4]} for r in reversed(rows)])

        if path == "/api/config":
            return self._send(200, {"new_quota": int(kv_get("new_quota", 20))})

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
            session = payload.get("session")
            if session:  # 盲测档案：写独立表，不碰主记录
                con = db()
                try:
                    if status is None:
                        con.execute("delete from probe_marks where session=? and word=?",
                                    (session, word))
                    else:
                        con.execute(
                            "insert into probe_marks(session,word,status,ts) "
                            "values(?,?,?,?) on conflict(session,word) do update "
                            "set status=excluded.status, ts=excluded.ts",
                            (session, word, status, time.time()))
                    con.commit()
                finally:
                    con.close()
                return self._send(200, {"ok": True})
            src = payload.get("src")
            set_mark(word, status, src if src in ("scan", "probe", "add") else None)
            return self._send(200, {"ok": True})

        if parsed.path == "/api/probe_session_start":
            con = db()
            try:
                cur = con.execute(
                    "insert into probe_sessions(ts,kind,status) values(?,?,?)",
                    (time.time(), payload.get("kind", "dyn"), "open"))
                con.commit()
                sid = cur.lastrowid
            finally:
                con.close()
            return self._send(200, {"session": sid})

        if parsed.path == "/api/probe_session_finish":
            sid = payload.get("session")
            if not sid:
                return self._send(400, {"error": "bad session"})
            ms = session_marks_src(sid)
            est = vocab_estimate("all", ms)
            nxt = probe_next("all", ms)
            result = {
                "listening": est["listening"], "reading": est["reading"],
                "ci95_listen": est["ci95_listen"], "ci95_read": est["ci95_read"],
                "sampled": est["sampled"],
                "unmeasured_blocks": est["unmeasured_blocks"],
                "boundary": nxt.get("boundary") if nxt.get("done") else None,
                "boundary_band": nxt.get("boundary_band") if nxt.get("done") else None,
            }
            con = db()
            try:
                con.execute("update probe_sessions set status='done', result=? where id=?",
                            (json.dumps(result, ensure_ascii=False), sid))
                con.commit()
            finally:
                con.close()
            return self._send(200, result)

        if parsed.path == "/api/probe_session_adopt":
            sid = payload.get("session")
            if not sid:
                return self._send(400, {"error": "bad session"})
            con = db()
            try:
                rows = con.execute(
                    "select word, status from probe_marks where session=?",
                    (sid,)).fetchall()
            finally:
                con.close()
            for word, status in rows:  # 覆写主记录，来源记为 probe（随机样本）
                set_mark(word, status, "probe")
            con = db()
            try:
                con.execute("update probe_sessions set status='adopted' where id=?", (sid,))
                con.commit()
            finally:
                con.close()
            return self._send(200, {"ok": True, "merged": len(rows)})

        if parsed.path == "/api/probe_session_discard":
            sid = payload.get("session")
            if not sid:
                return self._send(400, {"error": "bad session"})
            con = db()
            try:
                con.execute("delete from probe_marks where session=?", (sid,))
                con.execute("delete from probe_sessions where id=?", (sid,))
                con.commit()
            finally:
                con.close()
            return self._send(200, {"ok": True})

        if parsed.path == "/api/generate":
            words = payload.get("words") or []
            write_known_snapshot()
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

        if parsed.path == "/api/log":
            events = payload.get("events") or []
            if not isinstance(events, list) or len(events) > 200:
                return self._send(400, {"error": "bad events"})
            now = time.time()
            con = db()
            try:
                for e in events:
                    con.execute(
                        "insert into events(ts,page,view,event,detail) "
                        "values(?,?,?,?,?)",
                        (float(e.get("t") or now), str(e.get("page", ""))[:120],
                         str(e.get("view", ""))[:40], str(e.get("event", ""))[:40],
                         str(e.get("detail", ""))[:200]))
                # 滚动保留最近 10000 条
                con.execute("delete from events where id <= "
                            "(select max(id) from events) - 10000")
                con.commit()
            finally:
                con.close()
            return self._send(200, {"ok": True})

        if parsed.path == "/api/word_pass":
            # 考试通过——整个产品唯一的学习落库动作（SRS 爬梯即实时记录）
            word = (payload.get("word") or "").lower()
            if not word:
                return self._send(400, {"error": "bad word"})
            con = db()
            try:
                # 边界外推定生词此前 marks 无行：补 status1/src=add，
                # 生词本可见、不进统计样本、不入已知集（毕业时会翻成3）
                con.execute(
                    "insert or ignore into marks(word,status,ts,src) "
                    "values(?,1,?,'add')", (word, time.time()))
                srs_review(con, word)
                con.commit()
            finally:
                con.close()
            return self._send(200, {"ok": True})

        if parsed.path == "/api/config":
            q = payload.get("new_quota")
            if not isinstance(q, int) or not (1 <= q <= 100):
                return self._send(400, {"error": "new_quota must be 1-100"})
            kv_set("new_quota", q)
            return self._send(200, {"ok": True, "new_quota": q})

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
                # 不预注册：新词考过才进梯（FLOW 不变量——过词只有考试一条路）
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
            # 听完对话不再计分（用户裁决：学没学会考试说了算，对话只是学习辅助）
            did = payload.get("id")
            if not isinstance(did, int):
                return self._send(400, {"error": "bad id"})
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
                    "insert into marks(word,status,ts,src) values(?,3,?,NULL) "
                    "on conflict(word) do update set status=3, ts=excluded.ts",
                    (word, now))
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
                    "insert into marks(word,status,ts,src) values(?,1,?,'add') "
                    "on conflict(word) do update set status=1, ts=excluded.ts",
                    (word, now))
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
            set_mark(word, 1, "add")
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
