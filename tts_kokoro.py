#!/usr/bin/env python3
"""Kokoro TTS worker — runs inside .venv-tts, called by dialogue.py.

Usage: .venv-tts/bin/python tts_kokoro.py <job.json>
job.json: {"turns": [{"speaker": "...", "text": "..."}],
           "voice_map": {"name-lower": "kokoro_voice"},
           "default_voice": "af_sarah",
           "out_dir": "/abs/path"}
Writes turn_NN.wav files; prints one filename per line.
"""

import json
import os
import sys

from kokoro_onnx import Kokoro
import soundfile as sf

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(ROOT, "data", "kokoro-v1.0.onnx")
VOICES = os.path.join(ROOT, "data", "voices-v1.0.bin")


def main(job_path):
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    out_dir = job["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    kokoro = Kokoro(MODEL, VOICES)
    vmap = job.get("voice_map", {})
    default = job.get("default_voice", "af_sarah")
    for i, turn in enumerate(job["turns"]):
        voice = vmap.get(turn["speaker"].lower(), default)
        samples, sr = kokoro.create(turn["text"], voice=voice, speed=1.0, lang="en-us")
        name = "turn_%02d.wav" % i
        sf.write(os.path.join(out_dir, name), samples, sr)
        print(name, flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
