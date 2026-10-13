#!/usr/bin/env python3
"""maidcafe 词根词缀拆分（FLOW 工具页 · 2026-10-13）。纯 stdlib。

数据：ECDICT 仓库的 wordroot.txt（MIT，611 条：词根 / 前缀 / 后缀，英文释义 +
例词），放 data/wordroot.txt（同 stardict.db：用户下载，不入库）。缺文件 → None。

两条路，宁缺毋滥：
1. 例词表：词根表自带的例词是人工整理的 → 直接列出它的前缀/词根/后缀。
2. 词干 + 后缀：例词表里没有时才自动拆，三道过滤全过才算——词干是常用真词、
   词性对得上后缀类别（同形后缀 -ful1 "full of" / -ful2 "an amount that fills"
   意思不同）、中文释义有共同的汉字（flourish 繁荣 ≠ flour 面粉）。
   前缀不靠规则拆（abroad ≠ ab + road）。
释义保持英文原文（用户裁决）。
"""

import json
import os
import re
import sqlite3

CJK = re.compile(r"[一-鿿]")
# 释义里太常见、不代表词义相通的字
STOP_CHARS = set("的地得了是之一不使可有人者性化")
# ECDICT 词性标记：形容词写 "a."、副词 "adv."（偶见 "ad."）、动词 v./vt./vi.
POS = re.compile(r"^(adj|a|adv|ad|n|vt|vi|v)\.", re.M)
POS_NORM = {"a": "adj", "ad": "adv", "vt": "v", "vi": "v"}
SUFFIX_POS = {
    "adjective-forming suffix": {"adj"},
    "noun-forming suffix": {"n"},
    "adverb-forming suffix": {"adv"},
    "verb-forming suffix": {"v"},
    "adjective- and noun-forming suffix": {"adj", "n"},
}
COMMON_RANK = 20000          # 词干 / 派生词须是牌组词或词频前 2 万
MAX_FAMILY, MAX_DERIVED = 5, 6
MIN_SHARED = 2               # 词干与派生词的中文释义至少共享 2 个字（只共享 1 个多是巧合）
DOMAIN_TAG = re.compile(r"\[[^\]]*\]")   # ECDICT 领域标记 [计] [医]…：标记字本身不算词义


def plain(form):
    """去同形编号：'a-3' → 'a-'，'batter3' → 'batter'。编号恒为紧跟字母或连字符
    的一位 1-9；多位数字（如合成测试词 w150）不是编号，原样保留。"""
    return re.sub(r"(?<=[a-z\-])[1-9]$", "", form.strip().lower())


class Morph:
    def __init__(self, wordroot_path, ecdict_path, deck_words):
        self.ecdict_path = ecdict_path
        self.deck = set(deck_words)
        self.cache = {}
        self.rows = {}
        self.entries = {}
        self.by_example = {}     # 例词 -> [条目 key]
        self.suffixes = []       # (不带 - 的后缀, key, 词性集合)，长的先试
        self.prefixes = []       # (不带 - 的前缀, key)
        self.ok = os.path.exists(wordroot_path)
        if not self.ok:
            return
        with open(wordroot_path, encoding="utf-8") as f:
            self.entries = json.load(f)
        for key, e in self.entries.items():
            for ex in e.get("example", []):
                self.by_example.setdefault(plain(ex), []).append(key)
            forms = self.forms(key)
            cls = e.get("class", "")
            if cls == "prefix":
                self.prefixes += [(f[:-1], key) for f in forms
                                  if f.endswith("-") and len(f) > 2]
            elif "suffix" in cls:
                kinds = SUFFIX_POS.get(cls, set())
                self.suffixes += [(f[1:], key, kinds) for f in forms
                                  if f.startswith("-") and len(f) > 2]
        self.suffixes.sort(key=lambda x: -len(x[0]))
        self.prefixes.sort(key=lambda x: -len(x[0]))

    def forms(self, key):
        return [plain(x) for x in self.entries[key].get("root", key).split(",")]

    # ---------------------------------------------------------- ECDICT
    def row(self, w, con):
        if w not in self.rows:
            self.rows[w] = con.execute(
                "select translation, frq, bnc from stardict where word = ?",
                (w,)).fetchone()
        return self.rows[w]

    def freq(self, w, con):
        r = self.row(w, con)
        ranks = [x for x in (r[1], r[2]) if isinstance(x, int) and x > 0] if r else []
        return min(ranks) if ranks else 10 ** 9

    def common(self, w, con):
        return (w in self.deck and self.row(w, con) is not None) \
            or self.freq(w, con) <= COMMON_RANK

    def zh(self, w, con):
        r = self.row(w, con)
        if not r:
            return set()
        return set(CJK.findall(DOMAIN_TAG.sub("", r[0] or ""))) - STOP_CHARS

    def pos(self, w, con):
        r = self.row(w, con)
        return {POS_NORM.get(p, p) for p in POS.findall(r[0] or "")} if r else set()

    def related(self, a, b, con):
        # 10-13 真机审计：notify≠not+-ify 只共享 [计] 标记里的"计"，stagger≠stag+-er
        # 只共享 1 个字；正确的拆分普遍共享 3-6 个字（attachment/attach 共 6 个）
        return len(self.zh(a, con) & self.zh(b, con)) >= MIN_SHARED

    def clipped(self, w, con):
        """口语截短/缩写不是词干：sched「n. [口]…」之于 schedule（10-13 真机抓到
        schedule = sched + -ule "small"）。ECDICT 用 [口] / abbr. 标出它们。"""
        r = self.row(w, con)
        t = (r[0] or "") if r else ""
        return "[口]" in t or t.startswith("abbr.")

    # ---------------------------------------------------------- 拆分
    def from_examples(self, word):
        parts = []
        for key in self.by_example.get(word, []):
            e = self.entries[key]
            cls = e.get("class", "")
            forms = self.forms(key)
            if cls == "prefix":
                kind = "prefix"
                hits = [f for f in forms if word.startswith(f.rstrip("-"))]
            elif "suffix" in cls:
                kind = "suffix"
                hits = [f for f in forms if word.endswith(f.lstrip("-"))]
            else:
                kind = "root"
                hits = [f for f in forms if f and f in word]
            form = max(hits, key=len) if hits else forms[0]
            at = {"prefix": -1, "suffix": len(word) + 1}.get(
                kind, word.find(form) if hits else len(word) // 2)
            parts.append({"form": form, "meaning": e.get("meaning", ""),
                          "kind": kind, "key": key, "at": at})
        parts.sort(key=lambda p: p["at"])
        return parts

    @staticmethod
    def stems(s):
        out = [s, s + "e"]                       # invitation -> invite
        if s.endswith("i"):
            out.append(s[:-1] + "y")             # happily -> happy
        if len(s) > 2 and s[-1] == s[-2]:
            out.append(s[:-1])                   # running -> run
        return out

    def split_suffix(self, word, con):
        wpos = self.pos(word, con)
        for sfx, key, kinds in self.suffixes:
            if not word.endswith(sfx) or len(word) - len(sfx) < 3:
                continue
            if not kinds & wpos:                 # 同形后缀按词性选，对不上就不拆
                continue
            for st in self.stems(word[:-len(sfx)]):
                if (len(st) >= 3 and st != word and self.common(st, con)
                        and not self.clipped(st, con)
                        and self.related(st, word, con)):
                    return st, sfx, key
        return None

    def derived(self, word, con):
        cands = []
        for sfx, _key, kinds in self.suffixes:
            bases = {word}
            if word.endswith("e"):
                bases.add(word[:-1])
            if word.endswith("y"):
                bases.add(word[:-1] + "i")
            if (len(word) >= 3 and word[-1] not in "aeiouwxy"
                    and word[-2] in "aeiou" and word[-3] not in "aeiou"):
                bases.add(word + word[-1])
            cands += [(b + sfx, kinds) for b in bases]
        cands += [(pre + word, None) for pre, _key in self.prefixes]
        out, seen = [], {word}
        for c, kinds in cands:
            if c in seen:
                continue
            seen.add(c)
            if not self.common(c, con):
                continue
            if kinds is not None and not kinds & self.pos(c, con):
                continue
            if self.related(word, c, con):
                out.append(c)
        out.sort(key=lambda c: (c not in self.deck, self.freq(c, con), c))
        return out[:MAX_DERIVED]

    def family(self, word, parts):
        out = []
        for p in parts:
            if p["kind"] != "root":
                continue                          # 词缀家族太大、没信息量
            for ex in self.entries[p["key"]].get("example", []):
                ex = plain(ex)
                if ex != word and ex not in out and " " not in ex:
                    out.append(ex)
        out.sort(key=lambda x: x not in self.deck)   # 牌组词优先（稳定排序）
        return out[:MAX_FAMILY]

    def analyze(self, word):
        """-> {"parts": [{form, meaning, kind}], "family", "derived", "auto"}
        或 None（缺数据 / 拆不出也没有派生——宁缺毋滥）。"""
        if not self.ok:
            return None
        w = (word or "").strip().lower()
        if w in self.cache:
            return self.cache[w]
        parts = self.from_examples(w)
        auto, derived = False, []
        if os.path.exists(self.ecdict_path):
            con = sqlite3.connect(self.ecdict_path)
            try:
                sp = self.split_suffix(w, con)
                if sp:
                    st, sfx, key = sp
                    stem = {"form": st, "meaning": "", "kind": "stem"}
                    if not parts:                # 例词表没有：自动拆
                        parts = [stem, {"form": "-" + sfx, "kind": "suffix",
                                        "meaning": self.entries[key].get("meaning", "")}]
                        auto = True
                    elif [p["kind"] for p in parts] == ["suffix"]:
                        parts = [stem] + parts   # 例词表只给了后缀：补上词干
                derived = self.derived(w, con)
            finally:
                con.close()
        result = None
        if parts or derived:
            result = {"parts": [{k: p[k] for k in ("form", "meaning", "kind")}
                                for p in parts],
                      "family": self.family(w, parts),
                      "derived": derived, "auto": auto}
        self.cache[w] = result
        return result
