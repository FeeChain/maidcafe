"""Local AI readiness. Never downloads a model or runs an installer implicitly."""
import json
import os
from pathlib import Path
import shutil
import sys
import urllib.error
import urllib.request

from app_paths import ROOT

OLLAMA_BASE = 'http://127.0.0.1:11434'
DEFAULT_MODEL = 'qwen3.6:27b-mlx'


def audio_backend():
    data = Path(os.environ.get('MAIDCAFE_DATA_DIR', ROOT / 'data'))
    python = Path(os.environ.get('MAIDCAFE_TTS_PY', ROOT / '.venv-tts/bin/python'))
    if python.is_file() and (data / 'kokoro-v1.0.onnx').is_file() and (data / 'voices-v1.0.bin').is_file():
        return 'kokoro'
    if sys.platform == 'darwin' and shutil.which('say') and shutil.which('afconvert'):
        return 'system'
    if sys.platform == 'win32':
        from windows_speech import voice_names
        if voice_names():
            return 'system'
    return 'text'


def inspect(saved_model=''):
    explicit = os.environ.get('MAIDCAFE_MODEL', '')
    selected = explicit or saved_model
    result = {'connected': False, 'models': [], 'model': selected, 'ready': False,
              'locked': bool(explicit), 'audio': audio_backend()}
    try:
        with urllib.request.urlopen(OLLAMA_BASE + '/api/tags', timeout=2) as r:
            payload = json.load(r)
        names = sorted({m['name'] for m in payload.get('models', [])
                        if isinstance(m, dict) and isinstance(m.get('name'), str)
                        and not m.get('remote_host') and not m['name'].endswith('-cloud')})
        result.update(connected=True, models=names)
        if not selected:
            # Keep an existing installation working. Otherwise let the guest choose.
            selected = DEFAULT_MODEL if DEFAULT_MODEL in names else (names[0] if len(names) == 1 else '')
        result['model'] = selected
        result['ready'] = bool(selected and selected in names)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if not result['connected']:
        result.update(code='offline', message='本地 AI 还没打开。先打开 Ollama，再点重新检测。你仍然可以试听和翻词卡。')
    elif not result['models']:
        result.update(code='no_models', message='已连接 Ollama，还需要一个本地聊天模型。下载好后，回这里重新检测。')
    elif selected and selected not in result['models']:
        result.update(code='missing_model', message='Ollama 中找不到当前选择的模型，请在故事设置中重新选择。')
    elif not result['ready']:
        result.update(code='choose_model', message='选择一位故事助手，保存后就能开始点词。')
    else:
        result.update(code='ready', message='故事助手已准备好。')
    return result
