#!/usr/bin/env python3
"""maidcafe dialogue generator — the generate -> verify -> repair loop.

LLM (local Ollama) writes maid-cafe dialogue embedding the target words;
a pure-code verifier checks target coverage and known-vocabulary ratio
(lemmatised via ECDICT); violations go back to the LLM as structured
feedback, bounded retries. TTS via macOS `say`, one file per turn.

CLI:  python3 dialogue.py --words seldom,praise,pale
      python3 dialogue.py --auto 6          # pick 6 recent unknown words
"""

import argparse
import json
import os
import random
import re
import sqlite3
import subprocess
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "progress.db")
ECDICT_DB = os.path.join(ROOT, "data", "stardict.db")
ROSTER = json.load(open(os.path.join(ROOT, "roster.json"), encoding="utf-8"))
SCENES = json.load(open(os.path.join(ROOT, "scenes.json"), encoding="utf-8"))
AUDIO_OUT = os.path.join(ROOT, "audio_out")

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = os.environ.get("MAIDCAFE_MODEL", "qwen3.5:9b-mlx")
KNOWN_RATIO_TARGET = 0.92
MAX_REPAIR = 3

FUNCTION_WORDS = set("""
a an the and or but if so of to in on at by for with from as is are was were be
been being am do does did done have has had having will would can could shall
should may might must not no nor yes i you he she it we they me him her us them
my your his its our their mine yours this that these those there here what which
who whom whose when where why how all any both each few more most other some
such only own same than too very just about into over after before between
during under again further then once out up down off above below oh ah hey wow
hmm okay ok please thanks thank sorry well let lets don didn doesn can couldn
won wouldn isn aren wasn weren im ive ill youre youve its thats whats hes shes
were theyre id youd hed shed wed theyd get got go goes going went come comes
coming came say says said see sees seeing saw look looks looking looked make
makes making made take takes taking took one two three right now today really
little good new like want wants wanted know knows knew think thinks thought
time day way things thing something anything nothing everyone someone maybe
back still even also always never again master miss madam sir mr mrs
""".split())


def db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "create table if not exists dialogues("
        "id integer primary key autoincrement, ts real, scene text,"
        "characters text, target_words text, turns text, report text,"
        "status text)")
    return con


def norm(token):
    t = token.lower().strip("'")
    if t.endswith("'s"):
        t = t[:-2]
    return t


def tokenize(text):
    return [norm(t) for t in re.findall(r"[A-Za-z][A-Za-z']*", text)]


class Lemma:
    """Inflection -> lemma via ECDICT's exchange field ('0:lemma')."""

    def __init__(self, path):
        self.con = sqlite3.connect(path) if os.path.exists(path) else None
        self.cache = {}

    def lemma(self, token):
        if token in self.cache:
            return self.cache[token]
        out = token
        if self.con:
            row = self.con.execute(
                "select exchange from stardict where word = ?", (token,)).fetchone()
            if row and row[0]:
                for part in row[0].split("/"):
                    if part.startswith("0:"):
                        out = part[2:].lower()
                        break
        self.cache[token] = out
        return out


def get_known_set(con):
    rows = con.execute("select word from marks where status = 3").fetchall()
    return {r[0] for r in rows}


def get_auto_targets(con, n):
    """Due-for-review words first, then recently marked unknown words."""
    now = time.time()
    try:
        due = [r[0] for r in con.execute(
            "select word from word_srs where state='learning' and due_ts<=?"
            " order by due_ts limit ?", (now, n)).fetchall()]
    except sqlite3.OperationalError:
        due = []
    if len(due) >= n:
        return due[:n]
    picked = set(due)
    rows = con.execute(
        "select word from marks where status in (1,2) order by ts desc"
    ).fetchall()
    for (w,) in rows:
        if w not in picked:
            due.append(w)
            picked.add(w)
        if len(due) >= n:
            break
    return due


# ---------------------------------------------------------------- verifier
def verify(turns, targets, known, lemmatizer, char_names):
    text_tokens = []
    for t in turns:
        text_tokens.extend(tokenize(t.get("text", "")))

    target_set = {t.lower() for t in targets}
    target_lemmas = {lemmatizer.lemma(t) for t in target_set}

    found_targets = set()
    unknown = {}
    checkable = 0
    known_count = 0
    for tok in text_tokens:
        lem = lemmatizer.lemma(tok)
        if tok in target_set or lem in target_lemmas:
            found_targets.add(lem if lem in target_lemmas else tok)
            continue
        if tok in char_names or tok in FUNCTION_WORDS or len(tok) <= 2:
            continue
        checkable += 1
        if tok in known or lem in known:
            known_count += 1
        else:
            unknown[tok] = unknown.get(tok, 0) + 1

    missing = [t for t in target_set
               if t not in found_targets and lemmatizer.lemma(t) not in found_targets]
    ratio = (known_count / checkable) if checkable else 1.0
    return {
        "missing_targets": missing,
        "unknown_words": sorted(unknown, key=unknown.get, reverse=True),
        "known_ratio": round(ratio, 4),
        "checkable_tokens": checkable,
    }


def score(report):
    return report["known_ratio"] - 0.2 * len(report["missing_targets"])


# ---------------------------------------------------------------- prompts
def build_cast(rng):
    chars = ROSTER["characters"]
    # mostly 2 speakers; 3 is the normal ceiling; 4-5 are rare set pieces
    k = rng.choices([2, 3, 1, 4, 5], weights=[65, 20, 10, 4, 1])[0]
    cast = rng.sample(chars, k)
    guest = None
    if k <= 2 and rng.random() < SCENES.get("guest_probability", 0.3):
        guest = {
            "name": rng.choice(["Mr. Sato", "Ms. Lin", "Old Tom", "Anna", "Ken"]),
            "voice": rng.choice(ROSTER["guest_voices"]),
            "card": "A walk-in customer: %s, %s. Keep their lines short and natural."
                    % (rng.choice(["young", "middle-aged", "elderly"]),
                       rng.choice(["cheerful", "shy", "grumpy but soft-hearted",
                                   "curious", "very talkative"])),
        }
    hidden = None
    if rng.random() < SCENES.get("hidden_side_probability", 0.1):
        hidden = rng.choice(cast)
    return cast, guest, hidden


def target_briefs(targets):
    """word -> short usage brief (EN definition + CN gloss) from ECDICT, so the
    model uses each target word CORRECTLY instead of forcing it in."""
    briefs = []
    con = sqlite3.connect(ECDICT_DB) if os.path.exists(ECDICT_DB) else None
    for w in targets:
        line = w
        if con:
            row = con.execute(
                "select pos, definition, translation from stardict where word=?",
                (w.lower(),)).fetchone()
            if row:
                pos, definition, translation = row
                en = (definition or "").split("\n")[0].strip()
                cn = (translation or "").split("\n")[0].strip()
                bits = [b for b in (en, cn) if b]
                if bits:
                    line = "%s — %s" % (w, " / ".join(bits[:2]))
        briefs.append("- " + line)
    if con:
        con.close()
    return "\n".join(briefs)


def build_messages(cast, guest, hidden, scene, targets):
    cards = "\n\n".join("### %s\n%s" % (c["name"], c["card"]) for c in cast)
    if guest:
        cards += "\n\n### %s (guest)\n%s" % (guest["name"], guest["card"])
    hidden_note = ""
    if hidden:
        hidden_note = ("\nSPECIAL, subtle, this time only: let %s's hidden side "
                       "briefly show. %s Keep it understated.\n"
                       % (hidden["name"], hidden["hidden_side"]))
    speakers = [c["name"] for c in cast] + ([guest["name"]] if guest else [])
    system = (
        "/no_think You write short slice-of-life dialogues set in a cozy "
        "Japanese-style anime maid cafe. Style: light, warm, a little funny. "
        "Use ONLY simple everyday English (CEFR A2-B1). Short sentences. "
        "Stay strictly in character. Characters are normal adults with common "
        "sense: they NEVER ask what an everyday object is. Surprise must come "
        "from the situation ('why is this here?'), never from fake ignorance.")
    user = (
        "Characters on shift right now:\n\n%s\n%s\n"
        "Scene: %s.\n\n"
        "Write a natural dialogue of 8-12 turns between: %s.\n"
        "REQUIREMENTS:\n"
        "1. Each of these words MUST appear at least once, used CORRECTLY "
        "with its real meaning (do not force poetic or wrong usages):\n%s\n"
        "2. All OTHER words must be simple, common everyday English.\n"
        "3. Reply as JSON only: {\"turns\": [{\"speaker\": \"Name\", \"text\": \"...\"}]}\n"
        % (cards, hidden_note, scene, ", ".join(speakers), target_briefs(targets)))
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def repair_message(report):
    parts = []
    if report["missing_targets"]:
        parts.append("These required words are MISSING, work them in naturally: %s."
                     % ", ".join(report["missing_targets"]))
    if report["unknown_words"]:
        parts.append("These words are too difficult, replace them with very "
                     "simple everyday words or rephrase: %s."
                     % ", ".join(report["unknown_words"][:15]))
    parts.append("Rewrite the FULL dialogue, same characters and scene, "
                 "same JSON format only.")
    return {"role": "user", "content": " ".join(parts)}


# ---------------------------------------------------------------- ollama
def call_ollama(messages):
    payload = json.dumps({
        "model": MODEL, "messages": messages, "stream": False,
        "format": "json", "think": False,
        "options": {"temperature": 0.9, "num_predict": 1200},
    }).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.loads(r.read())
    content = data["message"]["content"]
    obj = json.loads(content)
    turns = obj.get("turns") or obj.get("dialogue") or []
    return [t for t in turns
            if isinstance(t, dict) and t.get("speaker") and t.get("text")]


# ---------------------------------------------------------------- tts
KOKORO_PY = os.path.join(ROOT, ".venv-tts", "bin", "python")
KOKORO_MODEL = os.path.join(ROOT, "data", "kokoro-v1.0.onnx")


def kokoro_available():
    return os.path.exists(KOKORO_PY) and os.path.exists(KOKORO_MODEL)


def synthesize(turns, guest_voice_map, out_dir):
    """guest_voice_map: {speaker-lower: {"say": v, "kokoro": v}} for guests."""
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):  # clear stale audio from previous backend
        if f.startswith("turn_"):
            os.remove(os.path.join(out_dir, f))
    if kokoro_available():
        vmap = {c["name"].lower(): c["kokoro_voice"] for c in ROSTER["characters"]}
        for name, v in guest_voice_map.items():
            vmap[name] = v["kokoro"]
        job = {"turns": turns, "voice_map": vmap,
               "default_voice": "af_sarah", "out_dir": out_dir}
        job_path = os.path.join(out_dir, "job.json")
        with open(job_path, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False)
        res = subprocess.run([KOKORO_PY, os.path.join(ROOT, "tts_kokoro.py"), job_path],
                             capture_output=True, text=True)
        if res.returncode == 0:
            os.remove(job_path)
            return [line for line in res.stdout.split() if line.endswith(".wav")]
        print("kokoro failed, falling back to say:\n" + res.stderr[-800:])

    vmap = {c["name"].lower(): c["voice"] for c in ROSTER["characters"]}
    for name, v in guest_voice_map.items():
        vmap[name] = v["say"]
    files = []
    for i, t in enumerate(turns):
        voice = vmap.get(t["speaker"].lower(), "Samantha")
        aiff = os.path.join(out_dir, "turn_%02d.aiff" % i)
        m4a = os.path.join(out_dir, "turn_%02d.m4a" % i)
        subprocess.run(["say", "-v", voice, "-o", aiff, t["text"]], check=True)
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", aiff, m4a],
                       check=True, capture_output=True)
        os.remove(aiff)
        files.append(os.path.basename(m4a))
    return files


# ---------------------------------------------------------------- main
def generate(targets, seed=None):
    rng = random.Random(seed)
    con = db()
    known = get_known_set(con)
    lem = Lemma(ECDICT_DB)
    char_names = {c["name"].lower() for c in ROSTER["characters"]}
    char_names.update({"sato", "lin", "tom", "anna", "ken"})

    cast, guest, hidden = build_cast(rng)
    guest_vmap = {}
    if guest:
        guest_vmap[guest["name"].lower()] = {
            "say": guest["voice"],
            "kokoro": rng.choice(ROSTER.get("guest_kokoro_voices", ["am_adam"]))}
    scene = rng.choice(SCENES["scenes"])
    messages = build_messages(cast, guest, hidden, scene, targets)

    best = None
    for attempt in range(1 + MAX_REPAIR):
        t0 = time.time()
        turns = call_ollama(messages)
        report = verify(turns, targets, known, lem, char_names)
        report["attempt"] = attempt + 1
        report["gen_seconds"] = round(time.time() - t0, 1)
        print("attempt %d: ratio=%.3f missing=%s unknown=%s (%.1fs)" % (
            attempt + 1, report["known_ratio"], report["missing_targets"],
            report["unknown_words"][:8], report["gen_seconds"]))
        if best is None or score(report) > score(best[1]):
            best = (turns, report)
        if not report["missing_targets"] and report["known_ratio"] >= KNOWN_RATIO_TARGET:
            break
        messages.append({"role": "assistant",
                         "content": json.dumps({"turns": turns})})
        messages.append(repair_message(report))

    turns, report = best
    cur = con.execute(
        "insert into dialogues(ts, scene, characters, target_words, turns, report, status)"
        " values(?,?,?,?,?,?,?)",
        (time.time(), scene,
         json.dumps([c["name"] for c in cast] + ([guest["name"]] if guest else [])),
         json.dumps(targets), json.dumps(turns, ensure_ascii=False),
         json.dumps(report), "tts"))
    did = cur.lastrowid
    con.commit()

    files = synthesize(turns, guest_vmap, os.path.join(AUDIO_OUT, str(did)))
    con.execute("update dialogues set status='done' where id=?", (did,))
    con.commit()
    con.close()

    print("\n=== dialogue #%d · %s ===" % (did, scene))
    for t in turns:
        print("%-9s %s" % (t["speaker"] + ":", t["text"]))
    print("=== targets: %s | ratio %.3f | %d turns, %d audio files ===" % (
        ", ".join(targets), report["known_ratio"], len(turns), len(files)))
    return did


def resynth(did):
    """Re-run TTS for an existing dialogue (e.g., after switching backends)."""
    con = db()
    row = con.execute(
        "select turns from dialogues where id=?", (did,)).fetchone()
    con.close()
    if not row:
        raise SystemExit("no dialogue #%d" % did)
    turns = json.loads(row[0])
    files = synthesize(turns, {}, os.path.join(AUDIO_OUT, str(did)))
    print("resynthesized #%d: %d files (%s)" % (
        did, len(files), "kokoro" if kokoro_available() else "say"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--words", help="comma-separated target words")
    ap.add_argument("--auto", type=int, default=0, help="pick N recent unknown words")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--resynth", type=int, default=0, help="re-TTS existing dialogue id")
    args = ap.parse_args()
    if args.resynth:
        resynth(args.resynth)
        raise SystemExit(0)
    if args.words:
        targets = [w.strip() for w in args.words.split(",") if w.strip()]
    else:
        con = db()
        targets = get_auto_targets(con, args.auto or 6)
        con.close()
    if not targets:
        raise SystemExit("no target words — calibrate some 生词 first")
    generate(targets)
