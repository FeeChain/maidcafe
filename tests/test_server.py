#!/usr/bin/env python3
"""maidcafe server-layer UNIT tests.

Imports server.py directly (module import is side-effect free; env must be
set BEFORE import) and exercises core functions branch by branch:
tier/rank assignment, every block_class rule, probe bisection against
simulated users, settle mode, the estimator (exact/probe/interpolated/CI),
session recipe + evidence gate, the weight model (FLOW §4), and the
known-set algebra.

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
os.environ["MAIDCAFE_AUDIO_OUT"] = os.path.join(TMP, "audio_out")
os.environ["MAIDCAFE_WORDROOT"] = os.path.join(TMP, "no-wordroot.json")

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

    def _learning(self, word, weight_days_ago, stab=1.0, base=100.0):
        """插一条在学行：last = 现在 − weight_days_ago 天。"""
        now = time.time()
        last = now - weight_days_ago * server.DAY
        con = server.db()
        con.execute("insert into word_srs(word,level,due_ts,state,added_ts,"
                    "reviewed_ts,stab,base) values(?,1,?,'learning',0,?,?,?)",
                    (word, server.srs_due_ts(base, stab, last), last, stab, base))
        con.commit()
        con.close()

    def test_reviews_first_lowest_weight_then_new(self):
        # G12：复习词（权重≤70）按权重从低到高先上，权重>70 不上桌，新词补满总量
        sim_probe(known_below=100)
        self._learning("w180", 1.5)   # w≈58.6
        self._learning("w181", 2.0)   # w=49
        self._learning("w182", 0.5)   # w≈83.7 —— 还新鲜，不上桌
        r = server.build_session()
        ws = r["words"]
        self.assertEqual([w["word"] for w in ws[:2]], ["w181", "w180"],
                         "lowest weight first")
        self.assertFalse(ws[0]["is_new"])
        self.assertNotIn("w182", [w["word"] for w in ws])
        self.assertEqual(len(ws), 20, "total stays at the user's portion size")
        self.assertTrue(all(w["is_new"] for w in ws[2:]))
        self.assertFalse(r["rest"])

    def test_reviews_cap_the_portion_and_flag_rest(self):
        # G12/G13：复习词多于总量 → 只取权重最低的总量个，零新词，rest=True
        sim_probe(known_below=100)
        server.kv_set("new_quota", 5)
        for i, days in enumerate((1.2, 3.0, 1.6, 2.5, 1.1, 4.0, 2.0)):
            self._learning("w19%d" % i, days)
        r = server.build_session()
        server.kv_set("new_quota", 20)
        self.assertEqual([w["word"] for w in r["words"]],
                         ["w195", "w191", "w193", "w196", "w192"])
        self.assertFalse(any(w["is_new"] for w in r["words"]))
        self.assertTrue(r["rest"])

    def test_quota_config(self):
        sim_probe(known_below=100)
        server.kv_set("new_quota", 7)
        self.assertEqual(len(server.build_session()["words"]), 7)
        server.kv_set("new_quota", 20)


BASE = time.mktime((2026, 10, 1, 12, 0, 0, 0, 0, -1))   # 固定在中午，避开跨日边界


class TestWeightModel(unittest.TestCase):
    """FLOW §4 权重模型（TESTPLAN G01-G11），假时钟逐日推进。"""

    def setUp(self):
        wipe_db()
        server.set_mark("w200", 1, "scan")
        self.real_time = time.time

    def tearDown(self):
        time.time = self.real_time

    def at(self, day):
        time.time = lambda: BASE + day * server.DAY

    def act(self, day, fn, word="w200", **kw):
        self.at(day)
        con = server.db()
        try:
            fn(con, word, **kw)
            con.commit()
        finally:
            con.close()

    def passes(self, day, word="w200"):
        self.act(day, server.srs_pass, word)

    def fails(self, day, word="w200", manual=False):
        self.act(day, server.srs_fail, word, manual=manual)

    def st(self, day, word="w200"):
        self.at(day)
        con = server.db()
        try:
            return server.srs_map(con).get(word)
        finally:
            con.close()

    def test_g01_learn_full_weight_one_day(self):
        self.passes(0)
        s = self.st(0)
        self.assertEqual((s["state"], s["level"], s["stab"]), ("learning", 1, 1.0))
        self.assertAlmostEqual(s["weight"], 100)
        self.assertAlmostEqual(self.st(1)["weight"], 70, "one day later = review line")

    def test_g02_decay_is_computed_not_stored(self):
        self.passes(0)
        self.assertAlmostEqual(self.st(2)["weight"], 49)
        self.assertEqual(self.st(2)["base"], 100, "reading never writes")
        self.assertAlmostEqual(server.srs_weight(100, 4, 0, 4 * server.DAY), 70)

    def test_g03_pass_growth_uses_elapsed_time_only(self):
        self.passes(0)
        self.passes(1)
        self.assertAlmostEqual(self.st(1)["stab"], 1.9)          # 1 × (1 + 3 × 0.3)
        # 同样耐久 1.9：隔 1 天就考 vs 隔 4 天才考 —— 越晚考过涨得越多
        self.passes(2)
        early = self.st(2)["stab"] / 1.9
        self.passes(0, "w201")
        self.passes(1, "w201")
        self.passes(5, "w201")
        late = self.st(5, "w201")["stab"] / 1.9
        self.assertGreater(late, early)
        self.assertAlmostEqual(early, 1 + 3 * (1 - 0.7 ** (1 / 1.9)))
        # 挂过之后再考过：涨幅只看时间，不因挂科扣低的起点而多涨
        self.passes(0, "w202")
        self.passes(1, "w202")                 # S=1.9
        self.fails(3, "w202")                  # S → 1（最少 1 天）
        self.passes(4, "w202")                 # 隔 1 天、S=1 → ×1.9
        self.assertAlmostEqual(self.st(4, "w202")["stab"], 1.9)

    def test_g04_same_day_only_first_result_counts(self):
        self.passes(0)
        self.passes(0)
        self.assertEqual(self.st(0)["level"], 1, "pass→pass same day")
        self.passes(1)
        self.fails(1)
        s = self.st(1)
        self.assertEqual((s["base"], round(s["stab"], 6)), (100, 1.9), "pass→fail same day")
        self.fails(2)
        b = self.st(2)["base"]
        self.passes(2)
        self.assertEqual(self.st(2)["base"], b, "fail→pass same day")

    def test_g04b_tested_today_not_served_again_today(self):
        # 挂了→当天重考过不算数→加餐若再端上来就会每份都缠着用户
        self.passes(0)
        self.passes(0, "w201")
        self.fails(1)                          # 70 → 35，在学但今天考过
        self.fails(2, "w201")                  # 49 → 24.5，今天回生词池
        self.at(2)
        ws = [w["word"] for w in server.build_session()["words"]]
        self.assertIn("w200", ws, "failed yesterday -> served today")
        self.assertNotIn("w201", ws, "lapsed today -> not again today")
        self.at(1)
        self.assertNotIn("w200", [w["word"] for w in server.build_session()["words"]],
                         "failed today -> not again today")
        self.at(3)
        self.assertIn("w201", [w["word"] for w in server.build_session()["words"]],
                      "lapsed word returns as a new word the next day")

    def test_g05_fail_halves_weight_and_stability(self):
        self.passes(0)
        self.passes(1)
        self.passes(3)
        s3 = self.st(3)["stab"]
        w = self.st(6)["weight"]
        self.fails(6)
        s = self.st(6)
        self.assertAlmostEqual(s["base"], w / 2)
        self.assertAlmostEqual(s["stab"], s3 / 2)
        self.assertLessEqual(s["weight"], server.REVIEW_LINE, "failed word is due at once")
        self.assertEqual(s["state"], "learning")
        # 耐久最少 1 天
        self.passes(0, "w201")
        self.fails(1, "w201")
        self.assertEqual(self.st(1, "w201")["stab"], 1.0)

    def test_g06_lapse_back_to_pool_then_relearn(self):
        self.passes(0)
        self.fails(2)                          # 49 → 24.5 < 30
        self.assertEqual(self.st(2)["state"], "lapsed")
        con = server.db()
        self.assertIn("w200", server.get_backlog(con), "lapsed = in the new-word pool")
        con.close()
        self.passes(2)
        self.assertEqual(self.st(2)["state"], "lapsed", "no same-day revival")
        self.passes(3)
        s = self.st(3)
        self.assertEqual((s["state"], s["level"], s["stab"], s["base"]),
                         ("learning", 1, 1.0, 100), "relearned from scratch")

    def test_g07_graduation_at_30_day_stability(self):
        self.passes(0)
        for day in (1, 3, 7, 15, 30, 58):
            self.passes(day)
        self.assertEqual(self.st(58)["state"], "graduated")
        con = server.db()
        mark = con.execute("select status from marks where word='w200'").fetchone()[0]
        con.close()
        self.assertEqual(mark, 3, "graduation flips the mark to known")
        self.passes(90)
        self.fails(91)
        self.assertEqual(self.st(91)["state"], "graduated", "graduates are final")

    def test_g08_absence_never_drops_a_word(self):
        self.passes(0)
        s = self.st(60)
        self.assertEqual(s["state"], "learning")
        self.assertLess(s["weight"], 1)
        self.at(60)
        ws = server.build_session()["words"]
        self.assertEqual(ws[0]["word"], "w200")
        self.assertFalse(ws[0]["is_new"])

    def test_g09_fail_on_new_or_graduated_is_noop(self):
        self.fails(0, "w201")
        self.assertIsNone(self.st(0, "w201"), "new word fail leaves no record")
        self.fails(0, "w201", manual=True)
        self.assertIsNone(self.st(0, "w201"))

    def test_g10_migration_keeps_old_due_times(self):
        wipe_db()
        con = sqlite3.connect(server.DB_PATH)
        con.execute("create table word_srs(word text primary key, level integer,"
                    " due_ts real, state text, added_ts real, reviewed_ts real)")
        due = BASE + 0.3 * server.DAY
        for lvl in (0, 1, 2, 3, 4, 5):
            con.execute("insert into word_srs values(?,?,?,'learning',0,NULL)",
                        ("m%d" % lvl, lvl, due))
        con.commit()
        con.close()
        con = server.db()
        srs = server.srs_map(con, due)
        con.close()
        for lvl, stab in ((0, 1), (1, 1), (2, 3), (3, 7), (4, 15), (5, 30)):
            s = srs["m%d" % lvl]
            self.assertEqual((s["stab"], s["base"]), (stab, 100))
            self.assertAlmostEqual(s["weight"], 70, msg="old due time = review line")
            self.assertAlmostEqual(server.srs_due_ts(s["base"], s["stab"], s["last"]), due)

    def _simulate(self, open_days, fail_at=()):
        """FLOW §4 模拟表：第 0 天学会，之后按来法打开；权重≤70 才出现并考。"""
        word = "w250"
        self.passes(0, word)
        n = 0
        for d in open_days:
            s = self.st(d, word)
            if s["state"] == "graduated":
                break
            if s["weight"] > server.REVIEW_LINE:
                continue
            n += 1
            (self.fails if n in fail_at else self.passes)(d, word)
            if self.st(d, word)["state"] == "graduated":
                return d, n
        return None, n

    def test_g11_flow_table_numbers(self):
        self.assertEqual(self._simulate(range(1, 400)), (58, 6), "every day")
        wipe_db()
        self.assertEqual(self._simulate(range(1, 400, 3)), (43, 5), "every 3 days")
        wipe_db()
        self.assertEqual(self._simulate(range(1, 400, 7)), (57, 5), "weekly")
        wipe_db()
        self.assertEqual(self._simulate(range(1, 400, 30)), (91, 4), "monthly")
        wipe_db()
        self.assertEqual(self._simulate(range(1, 400), fail_at=(3,))[1], 8,
                         "one fail costs two extra reviews")


class TestWordlistImport(unittest.TestCase):
    """词表导入 + 牌组外词排序（TESTPLAN H01-H03/H07）。假 ECDICT：只含几个词。"""

    def setUp(self):
        wipe_db()
        self.ec_path = os.path.join(TMP, "fake_ecdict.db")
        if os.path.exists(self.ec_path):
            os.remove(self.ec_path)
        con = sqlite3.connect(self.ec_path)
        con.execute("create table stardict(word text collate nocase unique,"
                    " phonetic text, translation text, frq int, bnc int, tag text)")
        con.executemany("insert into stardict values(?,?,?,?,?,?)", [
            ("give up", "", "放弃", 900, 0, "cet4"),
            ("give", "", "给", 50, 0, "zk"),
            ("abandon", "", "放弃", 2000, 0, "cet4"),
            ("zebra", "", "斑马", 9000, 0, "cet6"),
        ])
        con.commit()
        con.close()
        self.real_path = server.ECDICT_PATH
        server.ECDICT_PATH = self.ec_path
        server._OFFDECK_RANK.clear()

    def tearDown(self):
        server.ECDICT_PATH = self.real_path
        server._OFFDECK_RANK.clear()

    def test_h01_parse_lines(self):
        p = server.parse_wordlist(
            "1. abandon v. 放弃\n  23) w150 [x] adj. 仁慈的\n"
            "w151, w152; w153\n放弃，抛弃\n\n•\tself-esteem\tn.\n"
            "give up 放弃，抛弃")
        self.assertEqual([t for _, t in p], [
            ["abandon", "v"], ["w150"], ["w151"], ["w152"], ["w153"],
            ["self-esteem", "n"], ["give", "up"]],
            "numbering stripped; comma lists split only without Chinese")

    def test_h02_longest_dictionary_match(self):
        ec = sqlite3.connect(self.ec_path)
        try:
            self.assertEqual(server.resolve_entry(["give", "up"], ec), "give up")
            self.assertEqual(server.resolve_entry(["abandon", "v"], ec), "abandon")
            self.assertEqual(server.resolve_entry(["w150", "adj"], ec), "w150",
                             "deck words resolve without ECDICT")
            self.assertIsNone(server.resolve_entry(["zzqq"], ec))
        finally:
            ec.close()

    def test_h03_five_way_classification(self):
        sim_probe(known_below=100)
        server.set_mark("w150", 1, "scan")          # 已在生词本
        server.set_mark("w160", 3, "scan")          # 已学会（显式认识）
        out = server.import_wordlist(
            "w150\nw160\nw050\nw200\nw200\nzzqq 什么\ngive up 放弃")
        self.assertEqual(out["already"], ["w150"])
        self.assertEqual(out["learned"], ["w160"])
        self.assertEqual(out["presumed"], ["w050"], "inside the boundary: not added")
        self.assertEqual(out["added"], ["w200", "give up"], "duplicates count once")
        self.assertEqual(out["missing"], ["zzqq 什么"])
        marks = server.get_marks()
        self.assertEqual((marks.get("w200"), marks.get("give up")), (1, 1))
        self.assertNotIn("w050", marks)
        again = server.import_wordlist("w050\nw160", include_known=True)
        self.assertEqual((again["added"], again["learned"]), (["w050"], ["w160"]))

    def test_h07_offdeck_words_rank_between_deck_words(self):
        # 牌组外词（只有 ECDICT 有）：修复前序号 10^9 → 永远排在前沿推定生词后面
        self.assertEqual(server.word_rank("w123"), 123)
        r = server.word_rank("zebra")
        self.assertIsInstance(r, float)
        self.assertLess(r, 10 ** 9)
        self.assertEqual(r % 1, 0.5, "slots between two deck ranks")
        sim_probe(known_below=100)
        server.import_wordlist("zebra")
        ws = [w["word"] for w in server.build_session()["words"]]
        self.assertIn("zebra", ws, "an imported off-deck word must actually be served")
        card = [w for w in server.build_session()["words"] if w["word"] == "zebra"][0]
        self.assertEqual(card["definition"], "斑马",
                         "off-deck words take ECDICT's gloss, not a blank card")


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
        server.set_mark("w140", 1, "probe")
        con = server.db()
        con.execute("insert into word_srs(word,level,due_ts,state,added_ts,"
                    "reviewed_ts,stab,base) values('w168',1,0,'learning',0,0,1,100)")
        con.execute("insert into word_srs(word,level,due_ts,state,added_ts,"
                    "reviewed_ts,stab,base) values('w140',1,0,'lapsed',0,0,1,20)")
        con.commit()
        self.assertEqual(server.get_backlog(con), ["w105", "w140", "w172"],
                         "learning words leave the pool; lapsed ones are back in")
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
