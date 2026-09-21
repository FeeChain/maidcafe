#!/usr/bin/env python3
"""maidcafe dialogue-pipeline UNIT tests (pure functions, no LLM/TTS).

Covers the verifier that guards comprehensible input, tokenisation,
lemma fallback, the repair prompt, cast-size discipline, and the
known-set snapshot union.

Run:  python3 tests/test_dialogue.py -v
"""

import json
import os
import random
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="maidcafe-dlg-")
os.environ["MAIDCAFE_DB"] = os.path.join(TMP, "dlg.db")
os.environ["MAIDCAFE_CACHE"] = os.path.join(TMP, "cache")
os.environ["MAIDCAFE_ECDICT"] = os.path.join(TMP, "no-ecdict.db")
os.makedirs(os.environ["MAIDCAFE_CACHE"])

sys.path.insert(0, ROOT)
import dialogue  # noqa: E402

LEM = dialogue.Lemma(os.environ["MAIDCAFE_ECDICT"])   # no db -> identity
CHARS = {"momo", "suzu"}


def turns(*texts):
    return [{"speaker": "Momo", "text": t} for t in texts]


class TestTokenize(unittest.TestCase):
    def test_norm_and_tokenize(self):
        self.assertEqual(dialogue.norm("Cat's"), "cat")
        self.assertEqual(dialogue.norm("'ello'"), "ello")
        self.assertEqual(dialogue.tokenize("Momo's cup, it's FINE-ish!"),
                         ["momo", "cup", "it", "fine", "ish"])

    def test_lemma_identity_without_ecdict(self):
        self.assertEqual(LEM.lemma("running"), "running")


class TestVerifier(unittest.TestCase):
    def _v(self, ts, targets, known):
        return dialogue.verify(ts, targets, set(known), LEM, CHARS)

    def test_all_known_ratio_one(self):
        r = self._v(turns("the coffee is warm today"), ["coffee"],
                    {"warm", "today"})
        self.assertEqual(r["known_ratio"], 1.0)
        self.assertEqual(r["missing_targets"], [])

    def test_unknown_words_counted_and_ranked(self):
        r = self._v(turns("the zymurgy zymurgy calx is warm"), [],
                    {"warm"})
        self.assertEqual(r["unknown_words"][0], "zymurgy",
                         "most frequent unknown first")
        self.assertIn("calx", r["unknown_words"])
        self.assertAlmostEqual(r["known_ratio"], 1 / 4)

    def test_targets_never_count_as_unknown(self):
        r = self._v(turns("she felt the mania rising"), ["mania"],
                    {"felt", "rising"})
        self.assertEqual(r["known_ratio"], 1.0)
        self.assertEqual(r["missing_targets"], [])

    def test_inflection_needs_lemma_db(self):
        # 记录真实语义：校验器只靠 Lemma 还原词形（无前缀规则）。
        # 无 ECDICT -> praised 不命中 praise（missing）；有词形映射 -> 命中。
        r = self._v(turns("Haruka praised the tidy shelf"), ["praise"],
                    {"tidy", "shelf", "haruka"})
        self.assertEqual(r["missing_targets"], ["praise"])

        class StubLemma:
            def lemma(self, tok):
                return {"praised": "praise"}.get(tok, tok)
        r2 = dialogue.verify(turns("Haruka praised the tidy shelf"),
                             ["praise"], {"tidy", "shelf", "haruka"},
                             StubLemma(), CHARS)
        self.assertEqual(r2["missing_targets"], [])
        self.assertEqual(r2["known_ratio"], 1.0)

    def test_missing_target_detected(self):
        r = self._v(turns("nothing to see"), ["seldom"], {"see"})
        self.assertEqual(r["missing_targets"], ["seldom"])

    def test_function_words_and_names_skipped(self):
        r = self._v(turns("Momo said thanks master okay the"), [], set())
        self.assertEqual(r["checkable_tokens"], 0)
        self.assertEqual(r["known_ratio"], 1.0)

    def test_score_prefers_coverage_then_ratio(self):
        good = {"missing_targets": [], "known_ratio": 0.9}
        miss = {"missing_targets": ["x"], "known_ratio": 1.0}
        self.assertGreater(dialogue.score(good), dialogue.score(miss))

    def test_repair_message_contents(self):
        m = dialogue.repair_message(
            {"missing_targets": ["seldom"], "unknown_words": ["zymurgy"]})
        self.assertEqual(m["role"], "user")
        self.assertIn("seldom", m["content"])
        self.assertIn("zymurgy", m["content"])
        self.assertIn("JSON", m["content"])


class TestCastDiscipline(unittest.TestCase):
    def test_size_distribution_and_guest_rule(self):
        counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        guests = hidden = guest_when_big = 0
        for seed in range(3000):
            rng = random.Random(seed)
            cast, guest, hid = dialogue.build_cast(rng)
            counts[len(cast)] += 1
            if guest:
                guests += 1
                if len(cast) > 2:
                    guest_when_big += 1
                self.assertIn(guest["name"],
                              ["Mr. Sato", "Ms. Lin", "Old Tom", "Anna", "Ken"])
            if hid:
                hidden += 1
                self.assertIn(hid, cast)
        n = 3000
        # 人数纪律 2/3/1/4/5 = 65/20/10/4/1（±4 个百分点容差）
        for k, pct in ((2, .65), (3, .20), (1, .10), (4, .04), (5, .01)):
            self.assertLess(abs(counts[k] / n - pct), .04,
                            "size %d off: %s" % (k, counts))
        self.assertEqual(guest_when_big, 0, "guests only when cast <= 2")
        self.assertLess(abs(hidden / n - .10), .03, "hidden side ~10%")

    def test_target_briefs_without_ecdict(self):
        out = dialogue.target_briefs(["seldom", "praise"])
        self.assertIsInstance(out, str)
        self.assertIn("seldom", out)
        self.assertIn("praise", out)


class TestKnownSetUnion(unittest.TestCase):
    def test_marks_plus_snapshot(self):
        con = sqlite3.connect(os.environ["MAIDCAFE_DB"])
        con.execute("create table if not exists marks("
                    "word text primary key, status integer, ts real)")
        con.execute("insert or replace into marks values('alpha',3,0)")
        con.execute("insert or replace into marks values('beta',1,0)")
        con.commit()
        snap = os.path.join(os.environ["MAIDCAFE_CACHE"], "known_words.json")
        with open(snap, "w") as f:
            json.dump(["gamma", "delta"], f)
        known = dialogue.get_known_set(con)
        con.close()
        self.assertEqual(known, {"alpha", "gamma", "delta"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
