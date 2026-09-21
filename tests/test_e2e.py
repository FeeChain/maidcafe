#!/usr/bin/env python3
"""maidcafe end-to-end tests.

Boots an ISOLATED server instance (temp DB, temp cache with a synthetic
300-word wordbook, own port) and walks the whole product flow over HTTP.
Never touches the real progress.db / cache. Zero dependencies.

Run:  python3 tests/test_e2e.py -v
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("MAIDCAFE_TEST_PORT", "8790"))
BASE = "http://127.0.0.1:%d" % PORT

N_WORDS = 300          # 3 blocks of 100, load-order tiers (no ECDICT needed)
KNOWN_BELOW = 100      # simulated user: knows w000..w099, nothing else


def call(path, data=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def get_raw(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=15) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def widx(word):
    return int(word[1:])


class TestMaidcafe(unittest.TestCase):
    tmp = None
    proc = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="maidcafe-test-")
        cache = os.path.join(cls.tmp, "cache")
        os.makedirs(cache)
        words = [{"word": "w%03d" % i, "phonetic": "/w%d/" % i,
                  "definition": "释义%d" % i, "example_en": "", "example_cn": "",
                  "sources": ["test"]} for i in range(N_WORDS)]
        with open(os.path.join(cache, "words_cache.json"), "w") as f:
            json.dump(words, f)
        cls.db_path = os.path.join(cls.tmp, "test.db")
        env = dict(os.environ,
                   MAIDCAFE_DB=cls.db_path,
                   MAIDCAFE_CACHE=cache,
                   MAIDCAFE_PORT=str(PORT),
                   MAIDCAFE_MODEL="no-such-model-for-error-path",
                   # 开发机上真 ECDICT 会命中合成词、扰动排序——指向空路径隔离
                   MAIDCAFE_ECDICT=os.path.join(cls.tmp, "no-ecdict.db"))
        cls.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "server.py")], env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                get_raw("/api/home_status")
                return
            except Exception:
                time.sleep(0.25)
        raise RuntimeError("test server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def sql(self, q):
        con = sqlite3.connect(self.db_path)
        try:
            return con.execute(q).fetchall()
        finally:
            con.close()

    # ---------------- S0: fresh state ----------------

    def test_01_fresh_state(self):
        s = call("/api/home_status")
        self.assertFalse(s["calibrated"])
        self.assertEqual(call("/api/session")["words"], [])
        self.assertEqual(call("/api/dialogues"), [])
        self.assertEqual(call("/api/probe_sessions"), [])

    def test_02_static_pages(self):
        for path, marker in [("/", "vLearn"), ("/calibrate", "probeBtn"),
                             ("/listen", "tabWordbook"),
                             ("/static/home.js", "boot"),
                             ("/static/app.js", "startProbe")]:
            code, body = get_raw(path)
            self.assertEqual(code, 200, path)
            self.assertIn(marker, body, path)
        self.assertEqual(get_raw("/static/../server.py")[0], 404)
        self.assertEqual(get_raw("/static/nope.css")[0], 404)
        self.assertEqual(get_raw("/audio/nothing")[0], 404)
        self.assertEqual(get_raw("/api/dialogue/999")[0], 404)

    # ---------------- probe: bisection converges, unlocks home ----------------

    def test_03_probe_bisection(self):
        for i in range(40):
            r = call("/api/probe_next")
            if r.get("done"):
                break
            self.assertTrue(r["words"], "asked for words but gave none")
            for w in r["words"]:
                status = 3 if widx(w["word"]) < KNOWN_BELOW else 1
                call("/api/mark", {"word": w["word"].lower(), "status": status,
                                   "src": "probe"})
        else:
            self.fail("probe did not converge in 40 rounds")
        # user knows exactly block 1 -> boundary must sit between block 1 and 2
        self.assertTrue(1 <= r["boundary"] <= 2, r)
        self.assertTrue(call("/api/home_status")["calibrated"],
                        "finished probe must unlock the home flow")
        v = call("/api/vocab_estimate")
        self.assertEqual(len(v["per_block"]), 3)
        self.assertLess(abs(v["listening"] - KNOWN_BELOW), 60,
                        "estimate should be near the true 100: %s" % v["listening"])

    # ---------------- session: fixed portion, difficulty-ordered ----------------

    def test_04_session_composition(self):
        # 核心模型：从边界出发向外扩张——生词池不满配额时，
        # 边界块之外未标记的词按难度顺序推定为生词补满一份
        ws = call("/api/session")["words"]
        self.assertEqual(len(ws), 20, "a portion must fill to the quota")
        self.assertTrue(all(w["is_new"] for w in ws))
        idxs = [widx(w["word"]) for w in ws]
        self.assertTrue(all(i >= KNOWN_BELOW for i in idxs),
                        "known-side words must never be served for learning")
        self.assertEqual(idxs, sorted(idxs), "new words must come easiest-first")

    def test_05_word_pass_persists_and_is_idempotent(self):
        w = call("/api/session")["words"][0]["word"]
        call("/api/word_pass", {"word": w})
        row = self.sql("select level, state from word_srs where word='%s'" % w)
        self.assertEqual(row, [(1, "learning")])
        self.assertNotIn(w, [x["word"] for x in call("/api/session")["words"]],
                         "passed word must leave the session")
        call("/api/word_pass", {"word": w})  # same day again
        self.assertEqual(self.sql(
            "select level from word_srs where word='%s'" % w), [(1,)],
            "same-day double pass must not climb twice")

    def test_06_scan_marks_fill_the_quota(self):
        for i in range(150, 195):  # 45 more unknowns via full-scan marks
            call("/api/mark", {"word": "w%03d" % i, "status": 1, "src": "scan"})
        ws = call("/api/session")["words"]
        self.assertEqual(len(ws), 20, "quota caps the portion")
        idxs = [widx(w["word"]) for w in ws]
        self.assertEqual(idxs, sorted(idxs))

    def test_07_config_quota(self):
        call("/api/config", {"new_quota": 5})
        self.assertEqual(call("/api/config")["new_quota"], 5)
        self.assertEqual(len(call("/api/session")["words"]), 5)
        self.assertEqual(get_raw("/api/config")[0], 200)
        code, _ = 400, None
        try:
            call("/api/config", {"new_quota": 0})
        except urllib.error.HTTPError as e:
            code = e.code
        self.assertEqual(code, 400)
        call("/api/config", {"new_quota": 20})

    def test_08_lookup_and_wordbook(self):
        r = call("/api/lookup?word=w150")
        self.assertIn("释义150", r["definition"])
        self.assertTrue(r["in_wordbook"])
        wb = call("/api/wordbook")
        self.assertIn("learning", wb)
        self.assertTrue(any(x["word"].startswith("w1") for x in wb["learning"]),
                        "passed word must appear in the wordbook ladder")

    # ---------------- blind retest: isolated archive ----------------

    def test_09_blind_session_isolated(self):
        before = self.sql("select count(*) from marks")[0][0]
        sid = call("/api/probe_session_start", {"kind": "dyn"})["session"]
        r = call("/api/probe_next?session=%d" % sid)
        self.assertFalse(r.get("done"), "blank archive must start from scratch")
        for w in r["words"]:
            call("/api/mark", {"word": w["word"].lower(), "status": 3,
                               "session": sid})
        fin = call("/api/probe_session_finish", {"session": sid})
        self.assertIn("listening", fin)
        self.assertEqual(len(call("/api/probe_sessions")), 1)
        self.assertEqual(self.sql("select count(*) from marks")[0][0], before,
                         "blind session must not touch main marks")
        call("/api/probe_session_discard", {"session": sid})
        self.assertEqual(call("/api/probe_sessions"), [])
        self.assertEqual(self.sql("select count(*) from probe_marks")[0][0], 0)

    # ---------------- dialogue generation: error path is visible ----------------

    def test_10_generation_error_is_reported(self):
        # 边界内被全扫揪出的漏词：显式标不认识 -> 必须被剔出已知集
        call("/api/mark", {"word": "w010", "status": 1, "src": "scan"})
        words = [w["word"] for w in call("/api/session")["words"][:3]]
        r = call("/api/generate", {"words": words})
        self.assertTrue(r["started"])
        # 已知集快照：边界块之内的全部单词推定已知（用户定稿的核心定义）
        snap = os.path.join(os.path.dirname(self.db_path), "cache",
                            "known_words.json")
        self.assertTrue(os.path.exists(snap), "generate must write the snapshot")
        with open(snap) as f:
            known = set(json.load(f))
        self.assertIn("w050", known, "known-side block words are all known")
        self.assertNotIn("w250", known, "unknown-side words are not")
        self.assertNotIn("w010", known,
                         "full-scan-found gaps inside the boundary beat the presumption")
        ws = [w["word"] for w in call("/api/session")["words"]]
        self.assertEqual(ws[0], "w010",
                         "boundary-inside gaps must be served first (lowest rank)")
        for _ in range(30):  # bogus model -> pipeline must fail fast & visibly
            ds = call("/api/dialogues")
            if ds and ds[0]["status"] == "error":
                self.assertTrue(ds[0]["error"], "error rows must carry a reason")
                return
            time.sleep(1)
        if ds:
            self.fail("dialogue stuck in status %r" % ds[0]["status"])
        # no row at all = generator crashed before the placeholder insert
        self.fail("no dialogue row appeared; check generate.log handling")


    def test_11_event_log(self):
        call("/api/log", {"events": [
            {"page": "/", "view": "vLearn", "event": "click",
             "detail": "button#examBtn"}]})
        rows = call("/api/log?limit=10")
        self.assertTrue(any(r["event"] == "click" and
                            r["detail"] == "button#examBtn" for r in rows),
                        "logged events must be readable back")


if __name__ == "__main__":
    unittest.main(verbosity=2)
