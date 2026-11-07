"""Explicit, resumable local assistant setup. Downloads only pinned official code.

The managed engine lives beside user data, uses a private loopback port, and is
stopped with the app. Existing Ollama servers are reused and never terminated.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile

import ai_runtime

ENGINE_VERSION = 'v0.40.15'
ASSETS = {
    'darwin': {'name': 'ollama-darwin.tgz', 'bytes': 185971671,
               'sha256': '607c79d5d6315ef9d896db83adde736a4c0057196329843544e79b95afb260a8', 'space': 1000000000},
    'win32': {'name': 'ollama-windows-amd64.zip', 'bytes': 1614941966,
              'sha256': '9ca74a7ab66ec86870b1eecac7df160df08dc4e3a291ab5d2d59bcf9310221c6', 'space': 7000000000},
}
CATALOG = {
    'standard': {'model': 'qwen3:4b-instruct', 'label': '标准助手 · 故事表达更丰富', 'bytes': 2500000000},
    'light': {'model': 'qwen3:1.7b', 'label': '轻量助手 · 占用更小', 'bytes': 1400000000},
}


def memory_bytes():
    try:
        if sys.platform == 'darwin':
            return int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'], text=True, stderr=subprocess.DEVNULL))
        if sys.platform == 'win32':
            import ctypes
            class Status(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in
                    ('physical', 'available', 'page', 'available_page', 'virtual', 'available_virtual', 'extended')]
            status = Status(); status.length = ctypes.sizeof(Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.physical
        return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return 0


def installed_binary():
    found = shutil.which('ollama')
    if found:
        return Path(found)
    candidates = [Path('/Applications/Ollama.app/Contents/Resources/ollama')]
    if sys.platform == 'win32':
        candidates = [Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Ollama/ollama.exe']
    return next((p for p in candidates if p.is_file()), None)


def engine_alive(base):
    try:
        with urllib.request.urlopen(base + '/api/version', timeout=2) as r:
            return isinstance(json.load(r).get('version'), str)
    except (OSError, ValueError, AttributeError):
        return False


class Paused(Exception):
    pass


def safe_extract(archive, destination):
    root = Path(destination).resolve()
    def inside(name):
        # Check both path separators, even when validating a Windows zip on Mac.
        if ':' in name or name.startswith(('/', '\\')):
            raise ValueError('下载的引擎包包含无效路径。')
        path = (root / name.replace('\\', '/')).resolve()
        if path != root and root not in path.parents:
            raise ValueError('下载的引擎包包含无效路径。')
        return path
    if str(archive).endswith('.zip'):
        with zipfile.ZipFile(archive) as z:
            if sum(m.file_size for m in z.infolist()) > 12 * 1024 ** 3:
                raise ValueError('引擎包大小异常。')
            for m in z.infolist():
                inside(m.filename)
                if (m.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('引擎包包含无法读取的链接。')
            z.extractall(root)
    else:
        with tarfile.open(archive) as t:
            members = t.getmembers()
            if sum(m.size for m in members) > 4 * 1024 ** 3:
                raise ValueError('引擎包大小异常。')
            for m in members:
                target = inside(m.name)
                if not (m.isfile() or m.isdir() or m.issym() or m.islnk()):
                    raise ValueError('引擎包包含无效文件。')
                if m.issym() or m.islnk():
                    link = Path(m.linkname)
                    resolved = (target.parent / link if m.issym() else root / link).resolve()
                    if link.is_absolute() or (resolved != root and root not in resolved.parents):
                        raise ValueError('引擎包包含无效链接。')
            if sys.version_info >= (3, 12):
                t.extractall(root, filter='data')
            else:
                t.extractall(root)


class SetupManager:
    def __init__(self, home, save_model=lambda model: None, reuse_existing=True):
        self.home = Path(home)
        self.save_model = save_model
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.thread = None
        self.process = None
        self.reuse_existing = reuse_existing
        self.memory = None
        self.base = ai_runtime.OLLAMA_BASE if reuse_existing else 'http://127.0.0.1:9'
        self.state = {'phase': 'idle', 'message': '', 'completed': 0, 'total': 0, 'profile': 'standard'}
        try:
            saved = json.loads((self.home / 'setup.json').read_text(encoding='utf-8'))
            if saved.get('profile') in CATALOG:
                self.state.update(saved, phase='paused' if saved.get('phase') != 'done' else 'idle', message='')
        except (OSError, ValueError):
            pass

    @property
    def active(self):
        return bool(self.thread and self.thread.is_alive())

    def snapshot(self):
        with self.lock:
            return dict(self.state, active=self.active)

    def update(self, phase=None, **values):
        with self.lock:
            if phase:
                self.state.update(phase=phase, completed=0, total=0)
            self.state.update(values)
            if phase:
                self.home.mkdir(parents=True, exist_ok=True)
                path = self.home / 'setup.json'
                temp = path.with_suffix('.tmp')
                temp.write_text(json.dumps(self.state, ensure_ascii=False), encoding='utf-8')
                os.replace(temp, path)

    def options(self):
        asset = ASSETS.get(sys.platform)
        binary = installed_binary() if self.reuse_existing else None
        managed = self.binary_path()
        engine_size = 0 if binary or (managed and managed.is_file()) or engine_alive(self.base) else (asset['bytes'] if asset else 0)
        if self.memory is None:
            self.memory = memory_bytes()
        mem = self.memory
        supported = bool(asset or binary or engine_alive(self.base))
        reason = ''
        if sys.platform == 'darwin' and not binary and not engine_alive(self.base):
            version = platform.mac_ver()[0]
            if version and int(version.split('.')[0]) < 14:
                supported, reason = False, '自动准备需要 macOS 14 或更新版本；试听和词卡仍可使用。'
        if sys.platform == 'win32' and sys.getwindowsversion().build < 19045 and not engine_alive(self.base):
            supported, reason = False, '自动准备需要 Windows 10 22H2 或更新版本；试听和词卡仍可使用。'
        return {'catalog': CATALOG, 'recommended': 'standard' if mem >= 16 * 1024 ** 3 else 'light',
                'engine_bytes': engine_size, 'supported': supported,
                'reason': reason or ('' if supported else '此系统暂不支持自动安装引擎，可使用已安装的 Ollama。')}

    def binary_path(self):
        if sys.platform not in ASSETS:
            return None
        return self.home / ('engine-' + ENGINE_VERSION) / ('ollama.exe' if sys.platform == 'win32' else 'ollama')

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise Paused()

    def download_engine(self):
        asset = ASSETS.get(sys.platform)
        if not asset:
            raise ValueError('此系统需要先安装 Ollama，之后可以在这里下载模型。')
        self.home.mkdir(parents=True, exist_ok=True)
        archive = self.home / asset['name']
        offset = archive.stat().st_size if archive.exists() else 0
        if offset > asset['bytes']:
            archive.unlink(); offset = 0
        self.update('engine_download', message='1/3 · 正在下载助手引擎', completed=offset, total=asset['bytes'])
        if offset < asset['bytes']:
            url = 'https://github.com/ollama/ollama/releases/download/' + ENGINE_VERSION + '/' + asset['name']
            req = urllib.request.Request(url, headers={'Range': 'bytes=%d-' % offset} if offset else {})
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status != 206:
                    offset = 0
                elif not response.headers.get('Content-Range', '').startswith('bytes %d-' % offset):
                    raise ValueError('下载续传响应异常，请重试。')
                with archive.open('ab' if offset else 'wb') as f:
                    while True:
                        self.check_cancelled()
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        offset += len(block)
                        if offset > asset['bytes']:
                            raise ValueError('引擎下载大小异常，请重试。')
                        f.write(block)
                        self.update(completed=offset)
        self.check_cancelled()
        self.update('engine_verify', message='1/3 · 校验并整理助手引擎')
        digest = hashlib.sha256()
        with archive.open('rb') as f:
            for block in iter(lambda: f.read(1024 * 1024), b''):
                self.check_cancelled(); digest.update(block)
        if digest.hexdigest() != asset['sha256']:
            archive.unlink()
            raise ValueError('下载文件未通过校验，已清除这一份，请重新下载。')
        target = self.binary_path().parent
        with tempfile.TemporaryDirectory(dir=self.home) as tmp:
            extracted = Path(tmp) / 'engine'; extracted.mkdir()
            safe_extract(archive, extracted)
            self.check_cancelled()
            if not (extracted / self.binary_path().name).is_file():
                raise ValueError('引擎包不完整，请重试。')
            if target.exists():
                shutil.rmtree(target)
            os.replace(extracted, target)
        archive.unlink()
        return self.binary_path()

    def ensure_engine(self, allow_download=True):
        if engine_alive(self.base):
            ai_runtime.OLLAMA_BASE = self.base
            return True
        if self.reuse_existing and engine_alive(ai_runtime.OLLAMA_BASE):
            self.base = ai_runtime.OLLAMA_BASE
            return True
        binary = installed_binary() if self.reuse_existing else None
        managed = not bool(binary)
        if binary is None:
            binary = self.binary_path()
            if binary is None or not binary.is_file():
                if not allow_download:
                    return False
                binary = self.download_engine()
        self.check_cancelled()
        self.update('starting', message='正在打开故事助手…')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        self.base = 'http://127.0.0.1:%d' % port
        env = dict(os.environ, OLLAMA_HOST=self.base, OLLAMA_NO_CLOUD='1', OLLAMA_CONTEXT_LENGTH='4096',
                   OLLAMA_NUM_PARALLEL='1', OLLAMA_MAX_LOADED_MODELS='1')
        if managed:
            env['OLLAMA_MODELS'] = str(self.home / 'models')
        self.home.mkdir(parents=True, exist_ok=True)
        opts = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        with (self.home / 'engine.log').open('a', encoding='utf-8') as log:
            self.process = subprocess.Popen([str(binary), 'serve'], cwd=binary.parent, env=env, stdout=log, stderr=log, **opts)
        for _ in range(60):
            self.check_cancelled()
            if engine_alive(self.base):
                ai_runtime.OLLAMA_BASE = self.base
                return True
            if self.process.poll() is not None:
                raise ValueError('助手引擎没有启动成功，请重试或查看设置中的日志位置。')
            self.cancelled.wait(.5)
        raise ValueError('助手启动较慢，请稍后重试。')

    def pull_model(self, model):
        self.update('model_download', message='2/3 · 正在下载故事模型，下载一次后可离线使用')
        request = urllib.request.Request(self.base + '/api/pull', data=json.dumps({'model': model, 'stream': True}).encode(),
                                         headers={'Content-Type': 'application/json'})
        layers, success = {}, False
        with urllib.request.urlopen(request, timeout=60) as response:
            for line in response:
                self.check_cancelled()
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get('error'):
                    raise ValueError('模型下载暂未完成，请检查网络后点继续。')
                if event.get('digest') and event.get('total'):
                    layers[event['digest']] = (int(event.get('completed', 0)), int(event['total']))
                    self.update(completed=sum(x[0] for x in layers.values()), total=sum(x[1] for x in layers.values()))
                if event.get('status') == 'success':
                    success = True
        if not success:
            raise ValueError('连接中断，已下载的内容会保留，点继续即可重试。')

    def warm_model(self, model):
        self.update('checking', message='3/3 · 试运行一下，确认助手能正常写故事')
        payload = {'model': model, 'prompt': 'Reply with the word hello.', 'stream': False, 'think': False,
                   'options': {'num_ctx': 4096, 'num_predict': 32}}
        request = urllib.request.Request(self.base + '/api/generate', data=json.dumps(payload).encode(),
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
        self.check_cancelled()
        if not result.get('done') or not str(result.get('response', '')).strip():
            raise ValueError('助手没有完成试运行，可以改选轻量助手再试。')

    def start(self, profile):
        if profile not in CATALOG:
            raise ValueError('请选择标准助手或轻量助手。')
        with self.lock:
            if self.active:
                raise ValueError('助手正在准备，请等待完成或先暂停。')
            self.home.mkdir(parents=True, exist_ok=True)
            options = self.options()
            if not options['supported']:
                raise ValueError(options['reason'])
            need = CATALOG[profile]['bytes'] + 1000000000
            if options['engine_bytes']:
                need += ASSETS.get(sys.platform, {}).get('space', 0)
            if shutil.disk_usage(self.home).free < need:
                raise ValueError('空间不足，请先留出约 %.1f GB 可用空间，再点准备。' % (need / 1e9))
            self.cancelled.clear()
            self.update('starting', profile=profile, message='正在准备故事助手…')
            self.thread = threading.Thread(target=self._prepare, args=(profile,), daemon=True)
            self.thread.start()

    def _prepare(self, profile):
        try:
            self.ensure_engine()
            model = CATALOG[profile]['model']
            if model not in ai_runtime.inspect()['models']:
                self.pull_model(model)
            self.warm_model(model)
            self.check_cancelled()
            self.save_model(model)
            self.update('done', message='准备好了！回到窗边，点几个想学的词吧。')
        except Paused:
            self.update('paused', message='已暂停，下载内容会保留。下次点继续即可。')
        except Exception as error:
            if self.cancelled.is_set():
                self.update('paused', message='已暂停，下载内容会保留。')
            else:
                message = str(error) if isinstance(error, ValueError) else '暂时没有准备完成。请检查网络，再点继续重试；已下载的内容会保留。'
                self.update('error', message=message)
            with (self.home / 'setup-error.log').open('a', encoding='utf-8') as f:
                f.write('%s: %s\n' % (type(error).__name__, error))

    def resume_engine(self):
        """Reopen a previously prepared assistant, without downloading anything."""
        if not (self.home / 'setup.json').exists() or self.active:
            return
        def reopen():
            previous = dict(self.state)
            try:
                self.ensure_engine(allow_download=False)
                self.update(previous['phase'], message='')
            except Exception:
                self.update('error', message='故事助手没能打开，点准备可重试。')
        self.thread = threading.Thread(target=reopen, daemon=True)
        self.thread.start()

    def cancel(self):
        if self.active:
            self.cancelled.set()
            self.update(message='正在暂停，已下载的内容会保留…')

    def shutdown(self):
        self.cancel()
        if self.process and self.process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'], creationflags=subprocess.CREATE_NO_WINDOW,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                import signal
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=5)
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
