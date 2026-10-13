#!/usr/bin/env python3
"""maidcafe — calibration server (v1).

Zero-dependency local web app: parses Anki .apkg wordbooks in ./decks,
serves an audio-first triage UI, and records per-word mastery marks
(1 = unknown, 2 = known by eye only, 3 = known by ear) in SQLite.

Run:  python3 server.py   then open http://localhost:8770
"""

import bisect
import hashlib
import json
import math
import os
import random
import re
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
WORD_INDEX = {}     # word(lower) -> word dict（word_info / 导入查词用，免线性扫）
RANK_KEYS = []      # 牌组词按难度排好的 difficulty_key 列表（rank i 对应第 i 个）
_OFFDECK_RANK = {}  # 牌组外词 -> 插值难度序（缓存）


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


def difficulty_key(word, row):
    """难度尺子：(考纲段, 词频序, 词)。row = ECDICT 的 (frq, bnc, tag)，查不到
    为 None（排最后）。牌组词和牌组外的词（手动加/导入）共用同一把。"""
    if not row:
        return (UNTAGGED_TIER + 1, 10 ** 9, word.lower())
    frq, bnc, tag = row
    ranks = [x for x in (frq, bnc) if isinstance(x, int) and x > 0]
    band = UNTAGGED_TIER
    if tag:
        hit = [TAG_TIER[t] for t in tag.split() if t in TAG_TIER]
        if hit:
            band = min(hit)
    return (band, min(ranks) if ranks else 10 ** 9, word.lower())


def attach_tiers():
    """Order words by (exam-syllabus band, corpus frequency), cut into
    BLOCK_SIZE blocks, shuffle stably inside each block (md5 of the word,
    so order survives restarts)."""
    global WORDS, N_TIERS, WORD_INDEX, RANK_KEYS
    info = {}  # word(lower) -> ECDICT (frq, bnc, tag)
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
                if row:
                    info[lw] = row
        finally:
            con.close()
        print("ECDICT matched: %d/%d words" % (len(info), len(WORDS)))
    else:
        print("NOTE: %s missing — difficulty blocks fall back to load order" % ECDICT_DB)

    def sort_key(w):
        return difficulty_key(w["word"], info.get(w["word"].lower()))

    ordered = sorted(WORDS, key=sort_key)
    RANK_KEYS = [sort_key(w) for w in ordered]
    for i, w in enumerate(ordered):
        w["tier"] = i // BLOCK_SIZE + 1
        w["rank"] = i          # 全局难度序号（band+词频），生词池按它出词
        if w["word"].lower() in info:
            band, fr, _ = RANK_KEYS[i]
            w["band"], w["freq_rank"] = band, (fr if fr != 10 ** 9 else None)
        else:
            w["band"] = w["freq_rank"] = None
    WORD_INDEX = {w["word"].lower(): w for w in ordered}
    _OFFDECK_RANK.clear()
    N_TIERS = (len(WORDS) + BLOCK_SIZE - 1) // BLOCK_SIZE if WORDS else 1
    WORDS = sorted(
        ordered, key=lambda w: (w["tier"], hashlib.md5(w["word"].encode()).hexdigest()))


AUDIO_OUT = os.environ.get("MAIDCAFE_AUDIO_OUT",
                           os.path.join(ROOT, "audio_out"))
GEN_MODEL = os.environ.get("MAIDCAFE_MODEL", "qwen3.6:27b-mlx")
ECDICT_PATH = ECDICT_DB

# 权重模型（FLOW §4，2026-10-13 用户确认）：权重 = 记忆程度，打开时现算
#   w = 起点 × DECAY^(距上次考试天数 / 耐久)；耐久 = 从 100 掉到复习线要几天
DECAY = 0.7         # 每过一个耐久期，权重剩 70%
REVIEW_LINE = 70    # 权重 ≤ 70 的在学词才进这一份
LAPSE_FLOOR = 30    # 考挂减半后低于它 → 回生词池（只认考试证据，没来不算忘）
GRAD_STAB = 30      # 耐久 ≥ 30 天 → 毕业
GAIN = 3            # 考过：耐久 × (1 + GAIN × 这次间隔造成的衰减比例)
OLD_LADDER = [1, 3, 7, 15, 30]   # 旧固定梯子，仅用于迁移老数据
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
    # 上次考试时刻：权重衰减的起点，也是"每天只认第一次考试"的判据
    try:
        con.execute("alter table word_srs add column reviewed_ts real")
    except sqlite3.OperationalError:
        pass
    # 权重模型：stab=耐久（天），base=上次考试后的起点权重，reviewed_ts=上次考试
    for col in ("stab real", "base real"):
        try:
            con.execute("alter table word_srs add column " + col)
        except sqlite3.OperationalError:
            pass
    # 旧梯子行迁移：level n → 耐久 = 旧梯子第 n 格，起点 100，上次考试时刻
    # 倒推为 到期 − 耐久，于是原到期时刻恰好是权重落到复习线的时刻（不变）
    old = con.execute("select word, level, due_ts from word_srs"
                      " where stab is null").fetchall()
    for word, level, due in old:
        stab = float(OLD_LADDER[min(max(level or 1, 1), len(OLD_LADDER)) - 1])
        con.execute("update word_srs set stab=?, base=100, reviewed_ts=?"
                    " where word=?", (stab, (due or time.time()) - stab * DAY, word))
    if old:
        con.commit()
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


def srs_weight(base, stab, last, now):
    """权重（0-100）= 起点 × 0.7^(距上次考试天数 / 耐久)。打开时现算，不落库。"""
    return base * DECAY ** (max(0.0, (now - last) / DAY) / stab)


def srs_due_ts(base, stab, last):
    """权重落到复习线的时刻。派生字段，只为按时间查询方便（dialogue CLI 等）；
    起点已在复习线以下（考挂过）则立即。"""
    if base <= REVIEW_LINE:
        return last
    return last + stab * DAY * math.log(REVIEW_LINE / base) / math.log(DECAY)


def srs_map(con, now=None):
    """word -> 状态。state: learning 在学 / graduated 毕业 / lapsed 考挂回生词池。
    weight 只对在学词现算。"""
    now = now or time.time()
    out = {}
    for w, lvl, due, st, stab, base, last in con.execute(
            "select word, level, due_ts, state, stab, base, reviewed_ts"
            " from word_srs"):
        out[w] = {"level": lvl, "due_ts": due, "state": st, "stab": stab,
                  "base": base, "last": last,
                  "weight": (srs_weight(base, stab, last or now, now)
                             if st == "learning" else None)}
    return out


def same_day(a, b):
    return a and b and time.localtime(a)[:3] == time.localtime(b)[:3]


def srs_upsert_learning(con, word, level, stab, now):
    """考过后的落库：权重回满（起点 100），耐久=stab，上次考试=now。"""
    con.execute(
        "insert into word_srs(word, level, due_ts, state, added_ts,"
        " reviewed_ts, stab, base) values(?,?,?,'learning',?,?,?,100)"
        " on conflict(word) do update set level=excluded.level,"
        " due_ts=excluded.due_ts, state='learning',"
        " reviewed_ts=excluded.reviewed_ts, stab=excluded.stab, base=100",
        (word, level, srs_due_ts(100, stab, now), now, now, stab))


def srs_pass(con, word):
    """考过（FLOW §4）：新学（含回生词池后重学）→ 权重 100、耐久 1 天；
    在学 → 权重回满，耐久 × (1 + 3 × 这次间隔造成的衰减比例)——只看时间，
    越晚考过涨得越多；耐久 ≥ 30 天毕业。每个词每天只认第一次考试结果。"""
    now = time.time()
    row = con.execute(
        "select level, state, stab, reviewed_ts from word_srs where word=?",
        (word,)).fetchone()
    if row and row[1] == "graduated":
        return
    if row and same_day(row[3], now):
        return
    if row and row[1] == "learning":
        level = (row[0] or 0) + 1
        decayed = DECAY ** (max(0.0, (now - (row[3] or now)) / DAY) / row[2])
        stab = row[2] * (1 + GAIN * (1 - decayed))
    else:
        level, stab = 1, 1.0
    if stab >= GRAD_STAB:
        con.execute(
            "update word_srs set level=?, stab=?, base=100, reviewed_ts=?,"
            " state='graduated' where word=?", (level, stab, now, word))
        con.execute(
            "update marks set status=3, ts=? where word=?", (now, word))
        return
    srs_upsert_learning(con, word, level, stab, now)


def srs_fail(con, word, manual=False):
    """考挂（FLOW §4）：在学词权重、耐久减半（耐久最少 1 天），静默生效；
    减半后 < 30 → 回生词池（lapsed）。新词/生词池/毕业词零记录。
    manual=生词本「还是不熟」：明示操作，不受同日只认第一次的限制。"""
    now = time.time()
    row = con.execute(
        "select stab, base, reviewed_ts, state from word_srs where word=?",
        (word,)).fetchone()
    if not row or row[3] != "learning":
        return
    stab, base, last = row[0], row[1], row[2] or now
    if not manual and same_day(last, now):
        return
    nb = srs_weight(base, stab, last, now) / 2
    ns = max(1.0, stab / 2)
    if nb < LAPSE_FLOOR:
        con.execute(
            "update word_srs set state='lapsed', base=?, stab=?, reviewed_ts=?"
            " where word=?", (nb, ns, now, word))
        # 回生词池要靠生词标记才进 backlog：兜底补行/翻回 1
        con.execute("insert or ignore into marks(word,status,ts,src)"
                    " values(?,1,?,'add')", (word, now))
        con.execute("update marks set status=1 where word=?"
                    " and status not in (1,2)", (word,))
        return
    con.execute(
        "update word_srs set base=?, stab=?, reviewed_ts=?, due_ts=?"
        " where word=?", (nb, ns, now, srs_due_ts(nb, ns, now), word))


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
    """一份学习会话（无「每天/任务」概念，打开一次抓一份，零落库；FLOW §4）：
    总量由用户设（默认 20）——先放复习词（权重 ≤ 70，最低优先，最多占满），
    新词按难度序补满（不预注册，考过才进入在学）。离开再久也不变多：
    没轮上的复习词只是权重继续降、下次排更前。复习占满整份 = 休息一份（rest）。"""
    con = db()
    try:
        now = time.time()
        srs = srs_map(con, now)
        total = int(kv_get("new_quota", 20))   # 设置里的「每份词数（复习+新词）」
        # 同日只认第一次考试：今天考过的（含今天考挂回池的）今天不再端上来
        today = {w for w, s in srs.items() if same_day(s["last"], now)}
        due = sorted((w for w, s in srs.items()
                      if s["state"] == "learning" and w not in today
                      and s["weight"] <= REVIEW_LINE),
                     key=lambda w: srs[w]["weight"])[:total]
        quota = total - len(due)
        candidates = [w for w in get_backlog(con) if w not in today]
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
        fresh = sorted(candidates, key=word_rank)[:quota]
    finally:
        con.close()
    return {"words": ([session_word_out(w, False) for w in due] +
                      [session_word_out(w, True) for w in fresh]),
            "rest": len(due) >= total}


def get_backlog(con):
    """生词池：标了生词、还没在学的词（含考挂回池的 lapsed），严格难度序
    (global band+frequency rank, not just block number)."""
    srs = srs_map(con)
    rows = con.execute(
        "select word from marks where status in (1,2)").fetchall()
    backlog = [r[0] for r in rows
               if r[0] not in srs or srs[r[0]]["state"] == "lapsed"]
    backlog.sort(key=word_rank)
    return backlog


def write_known_snapshot():
    """已知词集快照，dialogue.py 校验已知占比用。"""
    with open(os.path.join(CACHE_DIR, "known_words.json"), "w",
              encoding="utf-8") as f:
        json.dump(sorted(known_set()), f, ensure_ascii=False)


def known_set():
    """核心定义（用户定稿）：已知 = 边界块之内的**全部**单词（推定已知）
    + 显式标记认识的词 − 显式标记不认识的词。边界由探针无状态重放得出。"""
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
    return known


# ---------------------------------------------------------------- 词表导入
IMPORT_MAX_ITEMS = 5000
IMPORT_MAX_BYTES = 512 * 1024
_CJK = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")
_LEAD = re.compile(r"[\s\d.)）、\-*•·#]+")
_HEAD = re.compile(r"^\s*([A-Za-z][A-Za-z0-9'\-]*(?:[ \t]+[A-Za-z][A-Za-z0-9'\-]*){0,3})")


def parse_wordlist(text):
    """词表文本 → [(原文, [前导英文词…])]。一行一个；去行首编号/符号；
    不含中文的行可用逗号/分号写多个词（含中文的行，逗号多半在释义里，不拆）。"""
    items = []
    for line in text.splitlines():
        line = _LEAD.sub("", line, count=1) if _LEAD.match(line) else line
        parts = [line] if _CJK.search(line) else re.split(r"[,;，；]", line)
        for part in parts:
            m = _HEAD.match(part)
            if m:
                items.append((part.strip(), m.group(1).split()))
    return items


def resolve_entry(tokens, ec):
    """最长匹配词典：give up 放弃 → give up；abandon v. → abandon。"""
    for k in range(len(tokens), 0, -1):
        cand = " ".join(tokens[:k]).lower()
        if cand in WORD_INDEX:
            return cand
        if ec is not None and ec.execute(
                "select 1 from stardict where word = ?", (cand,)).fetchone():
            return cand
    return None


def import_wordlist(text, include_known=False):
    """生词本词表导入（FLOW 工具页）：只进生词池，不建在学行，不计分。
    按测定边界推定已认识的词默认不加（include_known=True 才加）。"""
    items = parse_wordlist(text)
    if len(items) > IMPORT_MAX_ITEMS:
        raise ValueError("too many items")
    ec = sqlite3.connect(ECDICT_PATH) if os.path.exists(ECDICT_PATH) else None
    con = db()
    try:
        marks = get_marks()
        srs = srs_map(con)
        known = known_set()
        out = {"added": [], "already": [], "learned": [], "presumed": [],
               "missing": []}
        seen = set()
        now = time.time()
        for raw, toks in items:
            w = resolve_entry(toks, ec)
            if w is None:
                if raw not in out["missing"]:
                    out["missing"].append(raw)
                continue
            if w in seen:
                continue
            seen.add(w)
            st = srs.get(w, {}).get("state")
            m = marks.get(w)
            if m in (1, 2) or st in ("learning", "lapsed"):
                out["already"].append(w)
            elif m == 3 or st == "graduated":
                out["learned"].append(w)
            elif w in known and not include_known:
                out["presumed"].append(w)
            else:
                con.execute(
                    "insert into marks(word,status,ts,src) values(?,1,?,'add')"
                    " on conflict(word) do update set status=1, ts=excluded.ts,"
                    " src='add'", (w, now))
                out["added"].append(w)
        con.commit()
    finally:
        con.close()
        if ec is not None:
            ec.close()
    return out


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
    w = WORD_INDEX.get(lw)
    if w:
        return {"word": word, "phonetic": w.get("phonetic", ""),
                "definition": (w.get("definition") or "")[:200],
                "has_audio": lw in AUDIO}
    return {"word": word, "phonetic": "", "definition": "", "has_audio": False}


def word_rank(lw, ec=None):
    """全局难度序。牌组词 = attach_tiers 的 rank；牌组外的词（手动加/导入，
    只有 ECDICT 有）用同一把尺子插进牌组词之间（x.5）。否则它们序号无穷大，
    前沿推定生词永远排在前面，这些词永远轮不到。ec = 可复用的 ECDICT 连接。"""
    w = WORD_INDEX.get(lw)
    if w is not None:
        return w["rank"]
    if lw not in _OFFDECK_RANK:
        row = None
        con = ec or (sqlite3.connect(ECDICT_PATH)
                     if os.path.exists(ECDICT_PATH) else None)
        if con is not None:
            try:
                row = con.execute("select frq, bnc, tag from stardict"
                                  " where word = ?", (lw,)).fetchone()
            finally:
                if ec is None:
                    con.close()
        _OFFDECK_RANK[lw] = (
            bisect.bisect_left(RANK_KEYS, difficulty_key(lw, row)) - 0.5)
    return _OFFDECK_RANK[lw]


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
            out = []
            for w, s in words:
                info = word_info(w)
                info["status"] = s
                info["dialogues"] = appearances.get(w.lower(), [])
                st = srs.get(w)
                if st and st["state"] == "learning":
                    # 只给记忆程度，不给"到期/几天后"——不预告（FLOW §4）
                    info["srs"] = {"weight": round(st["weight"]),
                                   "level": st["level"]}
                else:
                    info["srs"] = None  # 还在生词池（含考挂回池的）
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
            learning = [w for w, s in srs.items() if s["state"] == "learning"]
            due = [w for w in learning if srs[w]["weight"] <= REVIEW_LINE]
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
            # 考试通过——整个产品唯一的加分动作（权重回满、耐久变长，FLOW §4）
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
                srs_pass(con, word)
                con.commit()
            finally:
                con.close()
            return self._send(200, {"ok": True})

        if parsed.path == "/api/word_fail":
            # 考挂（FLOW §4）：在学词静默降权（权重、耐久减半，太低回生词池）；
            # 新词零记录。界面零提示，不记挂科史
            word = (payload.get("word") or "").lower()
            if not word:
                return self._send(400, {"error": "bad word"})
            con = db()
            try:
                srs_fail(con, word)
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
            con = db()
            try:
                srs = srs_map(con)
                due = [w for w, s in srs.items()
                       if s["state"] == "learning"
                       and s["weight"] <= REVIEW_LINE]
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
                    "insert into word_srs(word, level, due_ts, state, added_ts,"
                    " reviewed_ts, stab, base) values(?,99,?,'graduated',?,?,?,100)"
                    " on conflict(word) do update set state='graduated'",
                    (word, now, now, now, float(GRAD_STAB)))
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
            # 「还是不熟」= 按考挂处理（FLOW §4）；生词池/回池的词本来就在池里，无变化
            con = db()
            try:
                srs_fail(con, word, manual=True)
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
                srs_upsert_learning(con, word, 1, 1.0, now)  # 按刚学会处理
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

        if parsed.path == "/api/wordbook_import":
            # 词表导入（FLOW 工具页）：只进生词池，工具页不计分
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                return self._send(400, {"error": "empty"})
            if len(text.encode("utf-8")) > IMPORT_MAX_BYTES:
                return self._send(400, {"error": "词表太大（上限 512KB）"})
            try:
                out = import_wordlist(text, bool(payload.get("include_known")))
            except ValueError:
                return self._send(400, {"error": "一次最多 %d 个词" % IMPORT_MAX_ITEMS})
            return self._send(200, {
                **{k + "_count": len(v) for k, v in out.items()},
                **{k: v[:100] for k, v in out.items()}})

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
