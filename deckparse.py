"""Parse Anki .apkg files (they're just zips of a SQLite collection + media) with
zero external dependencies. Not a general-purpose Anki parser — tuned for the
common 有道/词汇书-style note layout: word / phonetic / short definition /
example EN / example CN / ... / [sound:xxx.mp3] somewhere in the fields.
"""

import json
import os
import re
import sqlite3
import zipfile

SOUND_RE = re.compile(r"\[sound:([^\]]+)\]")
HTML_TAG_RE = re.compile(r"<[^>]+>")
PHONETIC_HINT_RE = re.compile(r"[ˈˌːɪʊəæʃʒθðŋɔɑɜɒ]")
IPA_RE = re.compile(r"\[([^\[\]]{1,60})\]")
POS_RE = re.compile(r"\b(n|v|vt|vi|adj|adv|prep|conj|pron|aux|num|art|int)\s*\.")
CJK_RE = re.compile(r"[一-鿿]")
PAREN_RE = re.compile(r"[（(][^（）()]*[）)]")


def strip_html(text):
    return HTML_TAG_RE.sub("", text or "").replace("&nbsp;", " ").strip()


def extract_apkg(apkg_path, cache_dir):
    """Unzip an .apkg into cache_dir/<basename> if not already done. Returns that dir."""
    name = os.path.splitext(os.path.basename(apkg_path))[0]
    out_dir = os.path.join(cache_dir, name)
    marker = os.path.join(out_dir, "collection.anki2")
    if not os.path.exists(marker):
        os.makedirs(out_dir, exist_ok=True)
        with zipfile.ZipFile(apkg_path) as z:
            z.extractall(out_dir)
    return out_dir, name


def load_media_map(deck_dir):
    """media file in an extracted apkg is a JSON manifest: {"3": "original.mp3", ...}."""
    media_path = os.path.join(deck_dir, "media")
    if not os.path.exists(media_path):
        return {}
    try:
        with open(media_path, "r", encoding="utf-8") as f:
            id_to_name = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    # we want name -> id (the on-disk numeric filename), for resolving [sound:name] tags
    return {v: k for k, v in id_to_name.items()}


def clean_definition(text):
    for cut in ("分布：", "分布:", "→来自", "→ 来自"):
        i = text.find(cut)
        if i > 0:
            text = text[:i]
    text = re.sub(r"\n{2,}", "\n", text).strip()
    return text[:400]


def looks_like_definition(text):
    if POS_RE.search(text):
        return True
    # >=3 CJK chars outside parentheses (avoids tags like "(中高 893/733)")
    stripped = PAREN_RE.sub("", text)
    return len(CJK_RE.findall(stripped)) >= 3


def parse_note_fields(flds):
    fields = flds.split("\x1f")
    word = strip_html(fields[0]).split("\n")[0].strip() if fields else ""

    audio_name = None
    for f in fields:
        m = SOUND_RE.search(f)
        if m:
            audio_name = m.group(1)
            break

    body = []
    for f in fields[1:]:
        t = strip_html(SOUND_RE.sub("", f))
        t = t.replace("\r\n", "\n").replace("\r", "\n").strip()
        if t:
            body.append(t)

    # phonetic: first IPA-looking [...] in the first two body fields
    phonetic = ""
    for f in body[:2]:
        for m in IPA_RE.finditer(f):
            inner = m.group(1)
            if PHONETIC_HINT_RE.search(inner) or "'" in inner:
                phonetic = "[%s]" % inner
                break
        if phonetic:
            break

    # definition: first field that looks like one
    definition = ""
    def_idx = -1
    for i, f in enumerate(body):
        if looks_like_definition(f):
            definition = clean_definition(f)
            def_idx = i
            break

    # examples: short pure-English line followed soon after by a short CJK line
    example_en, example_cn = "", ""
    for i, f in enumerate(body):
        if i == def_idx:
            continue
        first_line = f.split("\n")[0].strip()
        if (len(first_line) < 200 and re.search(r"[A-Za-z] [A-Za-z]", first_line)
                and not CJK_RE.search(first_line)):
            example_en = first_line
            for g in body[i + 1:i + 3]:
                g_line = g.split("\n")[0].strip()
                if len(g_line) < 200 and CJK_RE.search(g_line):
                    example_cn = g_line
                    break
            break

    return {
        "word": word,
        "phonetic": phonetic,
        "definition": definition,
        "example_en": example_en,
        "example_cn": example_cn,
        "audio_name": audio_name,
    }


def load_deck(apkg_path, cache_dir):
    deck_dir, deck_name = extract_apkg(apkg_path, cache_dir)
    media_map = load_media_map(deck_dir)  # original filename -> on-disk numeric id

    db_path = os.path.join(deck_dir, "collection.anki2")
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("select flds from notes").fetchall()
    finally:
        con.close()

    notes = []
    for (flds,) in rows:
        parsed = parse_note_fields(flds)
        if not parsed["word"]:
            continue
        audio_path = None
        if parsed["audio_name"] and parsed["audio_name"] in media_map:
            audio_path = os.path.join(deck_dir, media_map[parsed["audio_name"]])
        parsed["audio_path"] = audio_path
        parsed["deck"] = deck_name
        notes.append(parsed)
    return notes


def load_all_decks(decks_dir, cache_dir):
    """Load every .apkg in decks_dir, merge, dedupe by lowercase word (first wins)."""
    merged = {}
    for fname in sorted(os.listdir(decks_dir)):
        if not fname.endswith(".apkg"):
            continue
        apkg_path = os.path.join(decks_dir, fname)
        for note in load_deck(apkg_path, cache_dir):
            key = note["word"].lower()
            if key not in merged:
                merged[key] = note
                merged[key]["sources"] = [note["deck"]]
            else:
                if note["deck"] not in merged[key]["sources"]:
                    merged[key]["sources"].append(note["deck"])
                if not merged[key].get("audio_path") and note.get("audio_path"):
                    merged[key]["audio_path"] = note["audio_path"]
    return list(merged.values())
