#!/usr/bin/env python3
"""Kokoro TTS worker — runs inside .venv-tts, called by dialogue.py.

Usage: .venv-tts/bin/python tts_kokoro.py <job.json>
job.json: {"turns": [{"speaker": "...", "text": "..."}],
           "voice_map": {"name-lower": "kokoro_voice"},
           "lang_map": {"name-lower": "en-us" | "en-gb"},
           "default_voice": "af_sarah",
           "out_dir": "/abs/path"}
Writes turn_NN.wav files; prints one filename per line.
"""

import json
import os
import sys
import threading
from functools import lru_cache
from pathlib import Path

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(os.environ.get("MAIDCAFE_DATA_DIR", os.path.join(ROOT, "data")), "kokoro-v1.0.onnx")
VOICES = os.path.join(os.environ.get("MAIDCAFE_DATA_DIR", os.path.join(ROOT, "data")), "voices-v1.0.bin")
LOCK = threading.Lock()


def resource(name):
    for folder in (Path(os.environ.get('MAIDCAFE_DATA_DIR', ROOT+'/data')), Path(ROOT)/'resources/kokoro'):
        path = folder/name
        if path.is_file():
            return str(path)
    raise RuntimeError('Kokoro 配音资源缺失，请重新安装完整版本。')


def available():
    try:
        import importlib.util
        resource('kokoro-v1.0.onnx'); resource('voices-v1.0.bin')
        return importlib.util.find_spec('kokoro_onnx') is not None
    except (RuntimeError, ImportError, ValueError):
        return False


@lru_cache(maxsize=1)
def engine():
    from kokoro_onnx import Kokoro
    return Kokoro(resource('kokoro-v1.0.onnx'), resource('voices-v1.0.bin'))


def speak(text, path, voice='af_sarah'):
    import soundfile as sf
    if not voice.startswith(('af_', 'am_', 'bf_', 'bm_')):
        raise ValueError('配音只允许英音和美音。')
    with LOCK:
        samples, rate = engine().create(text, voice=voice, speed=1.0,
                                       lang='en-gb' if voice.startswith('b') else 'en-us')
        sf.write(str(path), samples, rate, format='WAV')


def main(job_path):
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    out_dir = job["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    vmap = job.get("voice_map", {})
    default = job.get("default_voice", "af_sarah")
    for i, turn in enumerate(job["turns"]):
        voice = vmap.get(turn["speaker"].lower(), default)
        name = "turn_%02d.wav" % i
        speak(turn['text'], os.path.join(out_dir, name), voice)
        print(name, flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
