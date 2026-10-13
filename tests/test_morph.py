#!/usr/bin/env python3
"""maidcafe 词根词缀拆分 UNIT tests（morph.py，TESTPLAN J01-J07）。

小号词根表 + 假 ECDICT，复现真实数据里踩过的坑：同形后缀（-ful1/-ful2）、
ECDICT 形容词写 "a."、flourish≠flour、abroad≠ab+road、冷僻词干 fave。

Run:  python3 tests/test_morph.py -v
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import morph  # noqa: E402

TMP = tempfile.mkdtemp(prefix="maidcafe-morph-")
WORDROOT = os.path.join(TMP, "wordroot.json")
ECDICT = os.path.join(TMP, "ecdict.db")

ENTRIES = {
    "a-3": {"class": "prefix", "root": "a-3", "meaning": "to, toward",
            "example": ["ascend", "amass"]},
    "ab-, abs-": {"class": "prefix", "root": "ab-, abs-", "meaning": "away from",
                  "example": ["abstain"]},
    "dis-": {"class": "prefix", "root": "dis-", "meaning": "not; apart",
             "example": ["disable"]},
    "scen, scend": {"class": "root", "root": "scen, scend", "meaning": "climb",
                    "example": ["ascend", "descend", "transcend2", "condescend",
                                "descent", "ascent", "scansion"]},
    "-ment": {"class": "noun-forming suffix", "root": "-ment",
              "meaning": "act, process, or instance of", "example": ["agreement"]},
    "-ful1": {"class": "adjective-forming suffix", "root": "-ful1",
              "meaning": "full of", "example": ["joyful"]},
    "-ful2": {"class": "noun-forming suffix", "root": "-ful2",
              "meaning": "an amount that fills", "example": ["cupful"]},
    "-ly1": {"class": "adverb-forming suffix", "root": "-ly1",
             "meaning": "in such a way or manner", "example": ["boldly"]},
    "-ify": {"class": "verb-forming suffix", "root": "-ify",
             "meaning": "to make", "example": ["purify"]},
    "-ion, -ation": {"class": "noun-forming suffix", "root": "-ion, -ation",
                     "meaning": "the act, process, or result of", "example": ["action"]},
    "-ule": {"class": "noun-forming suffix", "root": "-ule",
             "meaning": "small", "example": ["globule"]},
    "-ish": {"class": "adjective-forming suffix", "root": "-ish",
             "meaning": "of, resembling; somewhat", "example": ["childish"]},
    "-er, -or, -ar2": {"class": "noun-forming suffix", "root": "-er, -or, -ar2",
                       "meaning": "a person or thing that does", "example": ["actor"]},
}
# word: (translation, frq) —— 形容词按 ECDICT 真实写法用 "a."
DICT = {
    "ascend": ("v. 上升, 攀登", 5000), "descend": ("v. 下降", 4000),
    "descent": ("n. 下降, 血统", 6000), "agree": ("v. 同意, 赞成", 500),
    "agreement": ("n. 协议, 同意", 900), "disagree": ("vi. 不同意", 6000),
    "achieve": ("vt. 达到, 完成", 800), "achievement": ("n. 完成, 成就", 1500),
    "shame": ("n. 羞耻, 耻辱, 丢脸", 3000), "shameful": ("a. 可耻的, 丢脸的", 9000),
    "hand": ("n. 手, 人手, 把手, 少量", 100), "handful": ("n. 一把, 少量", 7000),
    "not": ("adv. 不, 没有 | [计] 非", 13), "notify": ("vt. 通知, 通告 | [计] 非", 5665),
    "natural": ("a. 自然的, 天生的", 700), "naturally": ("adv. 自然地, 天生地", 1200),
    "happy": ("a. 快乐的, 幸福的", 300), "happily": ("adv. 幸福地, 快乐地", 4000),
    "invite": ("vt. 邀请", 2000), "invitation": ("n. 邀请, 请帖", 3500),
    "flour": ("n. 面粉", 8000), "flourish": ("vi. 繁荣, 茂盛", 9000),
    "road": ("n. 路, 道路", 200), "abroad": ("adv. 在国外, 到海外", 2500),
    "fave": ("a. 最喜欢的", 90000), "favor": ("n. 喜爱, 恩惠", 1000),
    "plain": ("a. 平的, 简单的", 1500), "plainly": ("a. 平的", 9500),
    "span": ("n. 跨度, 一段时间", 3000), "spanish": ("a. 西班牙的", 4000),
    "sched": ("n. [口]（无线电）固定播送时间", 18253),
    "schedule": ("n. 时刻表, 进度表; 预定计划", 2000),
}


def setUpModule():
    with open(WORDROOT, "w", encoding="utf-8") as f:
        json.dump(ENTRIES, f)
    con = sqlite3.connect(ECDICT)
    con.execute("create table stardict(word text collate nocase unique,"
                " translation text, frq int, bnc int)")
    con.executemany("insert into stardict values(?,?,?,0)",
                    [(w, t, f) for w, (t, f) in DICT.items()])
    con.commit()
    con.close()


def new(deck=("ascend", "descend", "agree", "achieve", "natural")):
    return morph.Morph(WORDROOT, ECDICT, set(deck))


def forms(r):
    return [(p["form"], p["kind"]) for p in r["parts"]]


class TestMorph(unittest.TestCase):
    def test_j01_example_parts_in_word_order(self):
        r = new().analyze("Ascend")
        self.assertEqual(forms(r), [("a-", "prefix"), ("scend", "root")],
                         "homograph digit stripped; longest variant that occurs")
        self.assertEqual([p["meaning"] for p in r["parts"]], ["to, toward", "climb"])
        self.assertFalse(r["auto"], "curated example lists are not auto-split")

    def test_j02_family_from_root_examples(self):
        r = new().analyze("ascend")
        self.assertEqual(r["family"][0], "descend", "deck words first")
        self.assertIn("transcend", r["family"], "digit stripped")
        self.assertNotIn("ascend", r["family"])
        self.assertLessEqual(len(r["family"]), morph.MAX_FAMILY)

    def test_j03_stem_plus_suffix_with_restorations(self):
        m = new()
        self.assertEqual(forms(m.analyze("achievement")),
                         [("achieve", "stem"), ("-ment", "suffix")])
        self.assertTrue(m.analyze("achievement")["auto"])
        self.assertEqual(m.analyze("invitation")["parts"][0]["form"], "invite",
                         "e restored")
        self.assertEqual(m.analyze("happily")["parts"][0]["form"], "happy",
                         "i -> y restored")
        # 例词表只给了后缀：补上词干
        self.assertEqual(forms(m.analyze("agreement")),
                         [("agree", "stem"), ("-ment", "suffix")])

    def test_j04_homograph_suffix_chosen_by_part_of_speech(self):
        m = new()
        self.assertEqual(m.analyze("shameful")["parts"][1]["meaning"], "full of",
                         "ECDICT 'a.' = adjective -> -ful1")
        self.assertEqual(m.analyze("handful")["parts"][1]["meaning"],
                         "an amount that fills", "noun -> -ful2")
        self.assertEqual(m.analyze("naturally")["parts"][1]["meaning"],
                         "in such a way or manner")
        # plainly 在假词典里只有 "a."：-ly1 只造副词 → 对不上就不拆
        self.assertIsNone(m.analyze("plainly"))

    def test_j05_rejections(self):
        m = new()
        self.assertIsNone(m.analyze("flourish"), "no shared meaning with flour")
        self.assertIsNone(m.analyze("notify"),
                          "10-13 live: shared only a domain-tag glyph / one char")
        self.assertIsNone(m.analyze("schedule"),
                          "10-13 live: 'sched' is a colloquial clipping, not a stem")
        self.assertIsNone(m.analyze("spanish"),
                          "adjective + common stem, but 西班牙 ≠ 跨度: meaning filter alone")
        self.assertIsNone(m.analyze("abroad"), "prefixes are never rule-split")
        self.assertIsNone(m.analyze("favor"), "rare stem 'fave' rejected")
        self.assertIsNone(m.analyze("zzqq"))

    def test_j06_derived_words(self):
        r = new().analyze("agree")
        self.assertEqual(r["parts"], [])
        self.assertEqual(r["derived"], ["agreement", "disagree"],
                         "suffix and prefix derivations, deck/frequency order")
        self.assertIn("shameful", new().analyze("shame")["derived"])
        self.assertNotIn("flourish", new().analyze("flour") or {"derived": []})

    def test_j07_missing_data_is_silent(self):
        m = morph.Morph(os.path.join(TMP, "nope.json"), ECDICT, set())
        self.assertIsNone(m.analyze("ascend"))
        no_dict = morph.Morph(WORDROOT, os.path.join(TMP, "nope.db"), set())
        self.assertEqual(forms(no_dict.analyze("ascend")),
                         [("a-", "prefix"), ("scend", "root")],
                         "example lists still work without ECDICT")
        self.assertIsNone(no_dict.analyze("achievement"))

    def test_plain_strips_only_homograph_markers(self):
        self.assertEqual([morph.plain(x) for x in ("a-3", "-ly2", "batter3", "Transcend2")],
                         ["a-", "-ly", "batter", "transcend"])
        self.assertEqual(morph.plain("w150"), "w150", "multi-digit is not a marker")

    def test_results_are_cached(self):
        m = new()
        self.assertIs(m.analyze("ascend"), m.analyze("ASCEND"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
