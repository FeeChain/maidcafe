#!/usr/bin/env python3
"""maidcafe server-layer UNIT tests.

Imports server.py directly (module import is side-effect free; env must be
set BEFORE import) and exercises core functions branch by branch:
tier/rank assignment, every block_class rule, probe bisection against
simulated users, settle mode, the estimator (exact/probe/interpolated/CI),
session recipe + evidence gate, the SRS ladder, and the known-set algebra.

Run:  python3 tests/test_server.py -v
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="maidcafe-unit-")
CACHE = os.path.join(TMP, "cache")
os.makedirs(CACHE)
N_WORDS = 300
_words = [{"word": "w%03d" % i, "phonetic": "", "definition": "释义%d" % i,
           "example_en": "", "example_cn": "", "sources": ["test"]}
          for i in range(N_WORDS)]
with open(os.path.join(CACHE, "words_cache.json"), "w") as f:
    json.dump(_words, f)

os.environ["MAIDCAFE_DB"] = os.path.join(TMP, "unit.db")
os.environ["MAIDCAFE_CACHE"] = CACHE
os.environ["MAIDCAFE_ECDICT"] = os.path.join(TMP, "no-ecdict.db")

sys.path.insert(0, ROOT)
import server  # noqa: E402

server.build_words()


def wipe_db():
    if os.path.exists(server.DB_PATH):
        os.remove(server.DB_PATH)


def probe_mark(word, status):
    server.set_mark(word, status, "probe")


def sim_probe(known_below, max_rounds=40):
    """跑完整折半：模拟'认识 rank < known_below'的用户，返回最终 done 结果。"""
    for _ in range(max_rounds):
        r = server.probe_next("all")
        if r.get("done"):
            return r
        for w in r["words"]:
            probe_mark(w["word"].lower(),
                       3 if int(w["word"][1:]) < known_below else 1)
    raise AssertionError("probe did not converge")


class TestTiersAndRank(unittest.TestCase):
    def test_block_and_rank_assignment(self):
        by_tier = {}
        for w in server.WORDS:
            by_tier.setdefault(w["tier"], []).append(w)
        self.assertEqual(sorted(by_tier), [1, 2, 3])
        self.assertTrue(all(len(v) == 100 for v in by_tier.values()))
        # rank = 全局难度序（无 ECDICT 时按词名，即数字序）
        for w in server.WORDS:
            self.assertEqual(w["rank"], int(w["word"][1:]))
        # 块内呈 md5 乱序：展示顺序 != rank 顺序，但集合一致
        t1 = [w["rank"] for w in server.WORDS if w["tier"] == 1]
        self.assertEqual(sorted(t1), list(range(100)))
        self.assertNotEqual(t1, sorted(t1), "in-block md5 shuffle must exist")


class TestBlockClass(unittest.TestCase):
    def _cls(self, statuses, total=100):
        ws = [{"word": "x%02d" % i} for i in range(total)]
        ms = {("x%02d" % i): (s, "probe") for i, s in enumerate(statuses)}
        return server.block_class(ws, ms)

    def test_all_rules(self):
        self.assertEqual(self._cls([]), "unsampled")
        self.assertEqual(self._cls([3, 3]), "unsampled")          # n<3
        self.assertEqual(self._cls([3, 3, 3]), "high")            # 3 全会
        self.assertEqual(self._cls([3, 1, 1]), "low")             # 2 不会
        self.assertEqual(self._cls([3, 3, 1]), "need_more")       # 含糊
        self.assertEqual(self._cls([3, 3, 1, 3, 3]), "need_more")  # n<6 u=1
        self.assertEqual(self._cls([3, 3, 1, 3, 3, 3]), "high")   # 6 词 u<=1
        self.assertEqual(self._cls([1, 1, 1, 1, 3, 3]), "low")    # 6 词 u>=4
        self.assertEqual(self._cls([3, 3, 3, 1, 1, 2]), "mid")    # 边界带
        # 全扫块按真实认识率
        self.assertEqual(self._cls([3] * 90 + [1] * 10), "high")   # .90
        self.assertEqual(self._cls([3] * 50 + [1] * 50), "low")    # .50
        self.assertEqual(self._cls([3] * 70 + [1] * 30), "mid")    # .70


class TestProbeBisection(unittest.TestCase):
    def setUp(self):
        wipe_db()

    def test_converges_low_boundary(self):
        r = sim_probe(known_below=100)
        self.assertEqual(r["bracket"], [1, 2])
        self.assertEqual(r["boundary"], 1.5)

    def test_knows_everything(self):
        r = sim_probe(known_below=10 ** 6)
        self.assertEqual(r["bracket"][0], 3, "top block must be known side")

    def test_knows_nothing(self):
        r = sim_probe(known_below=-1)
        self.assertEqual(r["bracket"], [0, 1])

    def test_need_more_asks_same_tier_again(self):
        # 第 2 块答成 2会1不会 -> 追问同一块
        r1 = server.probe_next("all")
        self.assertEqual(r1["tier"], 2)
        for w, s in zip(r1["words"], (3, 3, 1)):
            probe_mark(w["word"].lower(), s)
        r2 = server.probe_next("all")
        self.assertFalse(r2.get("done"))
        self.assertEqual(r2["tier"], 2, "ambiguous block must be re-asked")
        self.assertEqual(r2["phase"], "need_more")

    def test_settle_never_asks(self):
        r1 = server.probe_next("all")
        for w, s in zip(r1["words"], (3, 3, 1)):   # 留下含糊块
            probe_mark(w["word"].lower(), s)
        r = server.probe_next("all", settle=True)
        self.assertTrue(r["done"], "settle mode must classify, not ask")

    def test_blind_session_marks_are_separate(self):
        sim_probe(known_below=100)
        ms = server.session_marks_src(12345)   # 空档案
        r = server.probe_next("all", ms)
        self.assertFalse(r.get("done"), "blank archive must start from scratch")


class TestVocabEstimate(unittest.TestCase):
    def setUp(self):
        wipe_db()

    def test_exact_probe_and_interpolation(self):
        # 块1 全扫：73 认识；块3 抽 3 全不会；块2 无样本 -> 邻块插值
        for i in range(100):
            server.set_mark("w%03d" % i, 3 if i < 73 else 1, "scan")
        for w in ("w250", "w260", "w270"):
            server.set_mark(w, 1, "probe")
        v = server.vocab_estimate("all")
        pb = {b["tier"]: b for b in v["per_block"]}
        self.assertEqual(pb[1]["method"], "exact")
        self.assertAlmostEqual(pb[1]["ratio_listen"], 0.73)
        self.assertEqual(pb[3]["method"], "probe")
        self.assertEqual(pb[2]["method"], "none")
        self.assertTrue(0 < pb[2]["ratio_listen"] < 0.73,
                        "unsampled block interpolates between neighbours")
        self.assertEqual(v["unmeasured_blocks"], 1)
        self.assertGreater(v["ci95_listen"], 0,
                           "smoothed variance must never claim certainty")

    def test_biased_add_marks_are_excluded(self):
        for w in ("w150", "w151"):
            server.set_mark(w, 1, "add")     # 手动加词=有偏样本
        v = server.vocab_estimate("all")
        self.assertEqual(v["sampled"], 0)


class TestSessionRecipe(unittest.TestCase):
    def setUp(self):
        wipe_db()

    def test_evidence_gate(self):
        self.assertEqual(server.build_session()["words"], [],
                         "no calibration evidence -> serve nothing")

    def test_fill_from_frontier_in_rank_order(self):
        sim_probe(known_below=100)
        ws = server.build_session()["words"]
        self.assertEqual(len(ws), 20)
        idxs = [int(w["word"][1:]) for w in ws]
        self.assertEqual(idxs, sorted(idxs))
        self.assertTrue(all(i >= 100 for i in idxs))

    def test_due_reviews_ride_on_top(self):
        sim_probe(known_below=100)
        con = server.db()
        con.execute("insert into word_srs(word,level,due_ts,state,added_ts)"
                    " values('w180',2,?, 'learning',0)", (time.time() - 5,))
        con.execute("insert into word_srs(word,level,due_ts,state,added_ts)"
                    " values('w181',1,?, 'learning',0)", (time.time() - 99,))
        con.commit()
        con.close()
        ws = server.build_session()["words"]
        self.assertEqual([w["word"] for w in ws[:2]], ["w181", "w180"],
                         "due reviews first, oldest due first")
        self.assertFalse(ws[0]["is_new"])
        self.assertEqual(len(ws), 22, "reviews ride on top of the quota")

    def test_quota_config(self):
        sim_probe(known_below=100)
        server.kv_set("new_quota", 7)
        self.assertEqual(len(server.build_session()["words"]), 7)
        server.kv_set("new_quota", 20)


class TestSrsLadder(unittest.TestCase):
    def setUp(self):
        wipe_db()
        server.set_mark("w200", 1, "scan")

    def _review(self, day_offset):
        con = server.db()
        real_time = time.time
        time.time = lambda: real_time() + day_offset * server.DAY
        try:
            server.srs_review(con, "w200")
            con.commit()
            row = con.execute("select level, state from word_srs"
                              " where word='w200'").fetchone()
        finally:
            time.time = real_time
            con.close()
        return row

    def test_climb_graduate_and_idempotency(self):
        self.assertEqual(self._review(0), (1, "learning"))
        self.assertEqual(self._review(0), (1, "learning"),
                         "same-day review must not double-climb")
        for day, lvl in ((1, 2), (4, 3), (11, 4), (26, 5)):
            self.assertEqual(self._review(day), (lvl, "learning"))
        self.assertEqual(self._review(60)[1], "graduated")
        con = server.db()
        st = con.execute("select status from marks where word='w200'"
                         ).fetchone()[0]
        con.close()
        self.assertEqual(st, 3, "graduation flips the mark to known")
        self.assertEqual(self._review(90)[1], "graduated",
                         "graduated words never climb again")


class TestKnownSnapshot(unittest.TestCase):
    def setUp(self):
        wipe_db()

    def _snap(self):
        server.write_known_snapshot()
        with open(os.path.join(CACHE, "known_words.json")) as f:
            return set(json.load(f))

    def test_set_algebra(self):
        sim_probe(known_below=100)
        server.set_mark("w010", 1, "scan")    # 边界内被全扫揪出的漏词
        server.set_mark("w150", 3, "scan")    # 边界外显式认识
        s = self._snap()
        self.assertIn("w050", s, "boundary-inside presumed known")
        self.assertIn("w150", s, "explicit known beyond boundary")
        self.assertNotIn("w010", s, "explicit unknown beats presumption")
        self.assertNotIn("w250", s)

    def test_no_probe_falls_back_to_marks(self):
        server.set_mark("w005", 3, "scan")
        s = self._snap()
        self.assertEqual(s, {"w005"})


class TestBacklogAndHelpers(unittest.TestCase):
    def setUp(self):
        wipe_db()

    def test_backlog_rank_order_and_srs_exclusion(self):
        for w in ("w172", "w105", "w168"):
            server.set_mark(w, 1, "probe")
        con = server.db()
        con.execute("insert into word_srs(word,level,due_ts,state,added_ts)"
                    " values('w168',1,0,'learning',0)")
        con.commit()
        self.assertEqual(server.get_backlog(con), ["w105", "w172"])
        con.close()

    def test_same_day(self):
        base = time.mktime((2026, 9, 21, 23, 59, 0, 0, 0, -1))
        self.assertTrue(server.same_day(base, base - 3600))
        self.assertFalse(server.same_day(base, base + 120))

    def test_word_match_filters(self):
        w = {"sources": ["test"], "tier": 2}
        self.assertTrue(server.word_match(w, "all", "all"))
        self.assertTrue(server.word_match(w, "test", "2"))
        self.assertFalse(server.word_match(w, "other", "all"))
        self.assertFalse(server.word_match(w, "all", "3"))

    def test_ecdict_lookup_missing_db(self):
        self.assertIsNone(server.ecdict_lookup("anything"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
