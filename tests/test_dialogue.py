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
import re
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="maidcafe-dlg-")
os.environ["MAIDCAFE_DB"] = os.path.join(TMP, "dlg.db")
os.environ["MAIDCAFE_CACHE"] = os.path.join(TMP, "cache")
os.environ["MAIDCAFE_ECDICT"] = os.path.join(TMP, "no-ecdict.db")
os.environ["MAIDCAFE_AUDIO_OUT"] = os.path.join(TMP, "audio_out")
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
        r = self._v(turns("Momo said thanks guest okay the"), [], set())
        self.assertEqual(r["checkable_tokens"], 0)
        self.assertEqual(r["known_ratio"], 1.0)

    def test_contractions_not_unknown(self):
        # 10-13 真模型日志：don't/isn't 曾被当生词，白白触发修复轮
        r = self._v(turns("I don't know, isn't it fine? We're sure you'll "
                          "like it. I'd say they've won't couldn't"),
                    [], {"know", "fine", "sure", "like", "say"})
        self.assertEqual(r["unknown_words"], [])
        self.assertEqual(r["known_ratio"], 1.0)

    def test_honorifics_setting_words_interjections_not_unknown(self):
        r = self._v(turns("Ooh, Momo-san and Suzu-chan run the maid cafe!",
                          "Phew! Alright, whew."),
                    [], {"run"})
        self.assertEqual(r["unknown_words"], [])
        self.assertEqual(r["known_ratio"], 1.0)

    def test_per_turn_cap_excludes_targets_and_dedupes(self):
        # 单句生词上限（10-14 用户裁决）：硬线 2、偏好 1，目标词不算，同句重复只算一次
        r = self._v(turns("the zymurgy calx quux is warm",     # 3 个 → 超线
                          "nice blorp and blorp tea",          # blorp 重复 → 1 个
                          "nice frob grok tea",                # 2 个 → 只扣分
                          "the mania flib flob warm"),         # mania 是目标词 → 2 个
                    ["mania"], {"warm", "nice", "tea"})
        self.assertEqual(r["dense_turns"],
                         [{"turn": 1, "speaker": "Momo",
                           "words": ["zymurgy", "calx", "quux"]}])
        self.assertEqual(r["busy_turns"], 3, "turns 1, 3 and 4 exceed the preferred 1")

    def test_banned_address_flagged_not_counted(self):
        # 女仆称客人：master/mistress 单独报出，不混进生词与已知率
        r = self._v(turns("Welcome back, Master! Masters love tea. Yes sir, ma'am, madam."),
                    [], {"welcome", "love", "tea", "yes"})
        self.assertEqual(r["banned_address"],
                         ["ma'am", "madam", "master", "masters", "sir"])
        self.assertNotIn("master", r["unknown_words"])
        self.assertEqual(r["known_ratio"], 1.0)

    def test_banned_address_allowed_as_target(self):
        r = self._v(turns("you will master this song"), ["master"],
                    {"song"})
        self.assertEqual(r["banned_address"], [])
        self.assertEqual(r["missing_targets"], [])

    def test_name_or_no_title_is_clean(self):
        # 英语口语里称客人 = 叫名字或不加称呼（2026-10-13 用户裁决）
        r = self._v(turns("Welcome back, Mr. Sato! Your usual tea?",
                          "Here you go! We have a new guest today."),
                    [], {"welcome", "sato", "your", "usual", "tea", "here",
                         "have", "today"})
        self.assertEqual(r["banned_address"], [])
        self.assertEqual(r["known_ratio"], 1.0)

    def test_dear_guest_phrase_flagged(self):
        # "dear guest" 是告示腔，不是口语称呼；单说 guest（叙述用）不违规
        r = self._v(turns("Welcome back, dear guest!"), [], {"welcome", "dear"})
        self.assertEqual(r["banned_address"], ["dear guest"])

    def test_score_prefers_coverage_then_ratio(self):
        good = {"missing_targets": [], "known_ratio": 0.9}
        miss = {"missing_targets": ["x"], "known_ratio": 1.0}
        self.assertGreater(dialogue.score(good), dialogue.score(miss))
        banned = dict(good, banned_address=["master"])
        self.assertGreater(dialogue.score(good), dialogue.score(banned))
        dense = dict(good, dense_turns=[{"turn": 2, "speaker": "Suzu", "words": ["a", "b", "c"]}])
        busy = dict(good, busy_turns=1)
        self.assertGreater(dialogue.score(busy), dialogue.score(dense),
                           "a hard-cap breach costs more than a 2-word line")
        self.assertGreater(dialogue.score(good), dialogue.score(busy))

    def test_repair_message_contents(self):
        m = dialogue.repair_message(
            {"missing_targets": ["seldom"], "unknown_words": ["zymurgy"]})
        self.assertEqual(m["role"], "user")
        self.assertIn("seldom", m["content"])
        self.assertIn("zymurgy", m["content"])
        self.assertIn("JSON", m["content"])
        self.assertNotIn("by name", m["content"], "no address note when clean")

    def test_repair_message_names_dense_lines(self):
        m = dialogue.repair_message(
            {"missing_targets": [], "unknown_words": ["calx"],
             "dense_turns": [{"turn": 3, "speaker": "Suzu",
                              "words": ["zymurgy", "calx", "quux"]}]})
        self.assertIn("line 3 (Suzu): zymurgy, calx, quux", m["content"])
        self.assertIn("at most 2 per line", m["content"])

    def test_repair_message_banned_address(self):
        m = dialogue.repair_message(
            {"missing_targets": [], "unknown_words": [],
             "banned_address": ["master"]})
        self.assertIn("by name", m["content"])
        self.assertIn("master", m["content"])


class TestGuestAddress(unittest.TestCase):
    """女仆称客人（2026-10-13 裁决）：角色卡、prompt、生成循环三处一致。"""

    def test_no_card_teaches_a_banned_address(self):
        bad = re.compile(r"\b(master|mistress|sir|madam|ma'am|dear guest)\b", re.I)
        for c in dialogue.ROSTER["characters"]:
            for field in ("card", "hidden_side"):
                self.assertIsNone(bad.search(c.get(field, "")), c["name"])

    def test_system_prompt_sets_guest_rule(self):
        rng = random.Random(1)
        cast, guest, hid = dialogue.build_cast(rng)
        msgs = dialogue.build_messages(cast, guest, hid, "a quiet morning",
                                       ["seldom"])
        system = msgs[0]["content"]
        self.assertIn("by name", system)
        for word in ("'master'", "'sir'", "'ma'am'", "'dear guest'"):
            self.assertIn(word, system)

    def test_guest_card_fixes_how_maids_call_them(self):
        # 10-13 真模型：叫名字规则下，没姓的 Old Tom 被叫成编造的 "Mr. Smith"
        seen = {}
        for seed in range(400):
            _, guest, _ = dialogue.build_cast(random.Random(seed))
            if guest:
                seen[guest["name"]] = guest["card"]
        self.assertEqual(set(seen), {n for n, _ in dialogue.GUESTS})
        for name, call in dialogue.GUESTS:
            self.assertIn("call this customer '%s'" % call, seen[name])
            self.assertIn("never invent a surname", seen[name])
        self.assertIn("'Tom'", seen["Old Tom"])

    def test_generate_repairs_master_until_name(self):
        calls = []
        replies = [
            [{"speaker": "Momo", "text": "Welcome back, Master! Tea?"}],
            [{"speaker": "Momo", "text": "Welcome back, Mr. Sato! Tea?"}],
        ]

        def fake_ollama(messages):
            calls.append([dict(m) for m in messages])
            return replies[len(calls) - 1]

        db_path = os.path.join(TMP, "gen.db")   # 独立库，不污染已知集用例
        con = sqlite3.connect(db_path)
        con.execute("create table marks(word text primary key,"
                    " status integer, ts real)")
        con.executemany("insert into marks values(?,3,0)",
                        [("welcome",), ("dear",)])
        con.commit()
        con.close()
        orig = (dialogue.call_ollama, dialogue.synthesize, dialogue.DB_PATH)
        dialogue.call_ollama = fake_ollama
        dialogue.synthesize = lambda turns, vmap, out_dir: []
        dialogue.DB_PATH = db_path
        try:
            did = dialogue.generate(["tea"], seed=7)
        finally:
            (dialogue.call_ollama, dialogue.synthesize,
             dialogue.DB_PATH) = orig
        self.assertEqual(len(calls), 2, "master must trigger exactly one repair")
        self.assertIn("by name", calls[1][-1]["content"])
        con = sqlite3.connect(db_path)
        row = con.execute("select turns, report, status from dialogues"
                          " where id=?", (did,)).fetchone()
        con.close()
        self.assertEqual(row[2], "done")
        self.assertIn("Mr. Sato", row[0])
        self.assertEqual(json.loads(row[1])["banned_address"], [])


class TestPerTurnCap(unittest.TestCase):
    """单句生词上限进了生成循环：整段已知率过线，只因一句扎堆也要退稿重写。"""

    def test_prompt_asks_for_one_hard_word_per_line(self):
        cast, guest, hid = dialogue.build_cast(random.Random(1))
        user = dialogue.build_messages(cast, guest, hid, "s", ["tea"])[1]["content"]
        self.assertIn("at most ONE less common word in any single line", user)

    def test_generate_rejects_a_dense_line_even_when_ratio_passes(self):
        good = {"speaker": "Momo", "text": "Welcome! The warm sweet tea is nice."}
        dense = {"speaker": "Suzu", "text": "The zymurgy calx quux."}
        plain = {"speaker": "Suzu", "text": "The tea is nice."}
        replies = [[good] * 10 + [dense],      # 40/43 = 0.93 过线，但第 11 句 3 个生词
                   [good] * 10 + [plain]]
        calls = []

        def fake_ollama(messages):
            calls.append([dict(m) for m in messages])
            return replies[len(calls) - 1]

        db_path = os.path.join(TMP, "cap.db")
        con = sqlite3.connect(db_path)
        con.execute("create table marks(word text primary key, status integer, ts real)")
        con.executemany("insert into marks values(?,3,0)",
                        [(w,) for w in ("welcome", "warm", "sweet", "nice")])
        con.commit()
        con.close()
        orig = (dialogue.call_ollama, dialogue.synthesize, dialogue.DB_PATH)
        dialogue.call_ollama = fake_ollama
        dialogue.synthesize = lambda turns, vmap, out_dir: []
        dialogue.DB_PATH = db_path
        try:
            dialogue.generate(["tea"], seed=3)
        finally:
            (dialogue.call_ollama, dialogue.synthesize, dialogue.DB_PATH) = orig
        self.assertEqual(len(calls), 2, "the dense line alone must force a rewrite")
        self.assertIn("line 11 (Suzu): zymurgy, calx, quux", calls[1][-1]["content"])


class TestBestDraftSelection(unittest.TestCase):
    def test_passing_draft_wins_even_with_lower_score(self):
        # 第 1 稿：已知率 1.0 但一句扎堆（它同时也算 1 句超偏好）→ 0.88；
        # 第 2 稿达标但三句各 2 个生词 → 0.87
        reports = [
            {"missing_targets": [], "unknown_words": [], "banned_address": [],
             "dense_turns": [{"turn": 1, "speaker": "Momo", "words": ["a", "b", "c"]}],
             "busy_turns": 1, "known_ratio": 1.0, "checkable_tokens": 40},
            {"missing_targets": [], "unknown_words": ["x", "y"], "banned_address": [],
             "dense_turns": [], "busy_turns": 3, "known_ratio": 0.93,
             "checkable_tokens": 40},
        ]
        self.assertGreater(dialogue.score(reports[0]), dialogue.score(reports[1]))
        drafts = [[{"speaker": "Momo", "text": "draft one"}],
                  [{"speaker": "Momo", "text": "draft two"}]]
        n = {"call": 0, "verify": 0}

        def fake_ollama(messages):
            n["call"] += 1
            return drafts[n["call"] - 1]

        def fake_verify(*a, **k):
            n["verify"] += 1
            return dict(reports[n["verify"] - 1])

        db_path = os.path.join(TMP, "best.db")
        con = sqlite3.connect(db_path)
        con.execute("create table marks(word text primary key, status integer, ts real)")
        con.commit()
        con.close()
        orig = (dialogue.call_ollama, dialogue.verify, dialogue.synthesize, dialogue.DB_PATH)
        dialogue.call_ollama, dialogue.verify = fake_ollama, fake_verify
        dialogue.synthesize = lambda turns, vmap, out_dir: []
        dialogue.DB_PATH = db_path
        try:
            did = dialogue.generate(["tea"], seed=5)
        finally:
            (dialogue.call_ollama, dialogue.verify, dialogue.synthesize,
             dialogue.DB_PATH) = orig
        con = sqlite3.connect(db_path)
        shipped = con.execute("select turns from dialogues where id=?", (did,)).fetchone()[0]
        con.close()
        self.assertEqual(n["call"], 2)
        self.assertIn("draft two", shipped, "the passing draft must be the one shipped")


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
