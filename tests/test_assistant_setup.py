"""No external downloads: interrupted installs, archive safety and activation."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assistant_setup as setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saved = []
        self.manager = setup.SetupManager(self.tmp.name, self.saved.append, reuse_existing=False)
        self.home = Path(self.tmp.name)

    def archive(self):
        blob = io.BytesIO()
        with tarfile.open(fileobj=blob, mode='w:gz') as tar:
            item = tarfile.TarInfo('ollama'); item.size = 6; item.mode = 0o755
            tar.addfile(item, io.BytesIO(b'engine'))
        return blob.getvalue()

    def download(self, content, response=None):
        asset = {'name': 'engine.tgz', 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
        with patch.object(setup.sys, 'platform', 'darwin'), patch.dict(setup.ASSETS, {'darwin': asset}), \
                patch('urllib.request.urlopen', return_value=response) as request:
            result = self.manager.download_engine()
        return result, request

    def test_resume_engine_download_checks_range_and_checksum(self):
        content = self.archive()
        (self.home / 'engine.tgz').write_bytes(content[:20])
        response = io.BytesIO(content[20:]); response.status = 206
        response.headers = {'Content-Range': 'bytes 20-%d/%d' % (len(content)-1, len(content))}
        binary, request = self.download(content, response)
        self.assertEqual(request.call_args.args[0].get_header('Range'), 'bytes=20-')
        self.assertEqual(binary.read_bytes(), b'engine')
        self.assertFalse((self.home / 'engine.tgz').exists())

    def test_server_ignoring_range_restarts_without_appending(self):
        content = self.archive()
        (self.home / 'engine.tgz').write_bytes(content[:20])
        response = io.BytesIO(content); response.status = 200
        binary, _ = self.download(content, response)
        self.assertEqual(binary.read_bytes(), b'engine')

    def test_wrong_range_and_corrupt_download_never_install(self):
        content = self.archive()
        (self.home / 'engine.tgz').write_bytes(content[:20])
        response = io.BytesIO(content[20:]); response.status = 206; response.headers = {'Content-Range': 'bytes 0-100/100'}
        with self.assertRaises(ValueError):
            self.download(content, response)
        response = io.BytesIO(b'x' * len(content)); response.status = 200
        with self.assertRaisesRegex(ValueError, '校验'):
            self.download(content, response)
        self.assertFalse((self.home / 'engine.tgz').exists())
        self.assertFalse((self.home / ('engine-' + setup.ENGINE_VERSION)).exists())

    def test_pause_keeps_partial_download_and_relaunch_keeps_resume_state(self):
        content = self.archive()
        (self.home / 'engine.tgz').write_bytes(content[:20])
        response = io.BytesIO(content[20:]); response.status = 206; response.headers = {'Content-Range': 'bytes 20-100/100'}
        self.manager.cancelled.set()
        with self.assertRaises(setup.Paused):
            self.download(content, response)
        self.assertEqual((self.home / 'engine.tgz').stat().st_size, 20)
        reopened = setup.SetupManager(self.home, reuse_existing=False)
        with patch.object(reopened, 'ensure_engine', return_value=False) as ensure:
            reopened.resume_engine(); reopened.thread.join(3)
        ensure.assert_called_once_with(allow_download=False)
        self.assertEqual(reopened.snapshot()['phase'], 'paused')

    def test_archive_traversal_and_outside_symlink_rejected(self):
        for name in ('../outside', '..\\outside', '/absolute', 'C:\\outside'):
            archive = self.home / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr(name, 'bad')
            with self.assertRaises(ValueError):
                setup.safe_extract(archive, self.home / 'out')
        archive = self.home / 'bad.tgz'
        with tarfile.open(archive, 'w:gz') as tar:
            item = tarfile.TarInfo('link'); item.type = tarfile.SYMTYPE; item.linkname = '../../outside'
            tar.addfile(item)
        with self.assertRaises(ValueError):
            setup.safe_extract(archive, self.home / 'out')

    def test_official_style_internal_library_links_are_allowed(self):
        if sys.platform == 'win32':
            self.skipTest('Mac tar layout only')
        archive = self.home / 'good.tgz'
        with tarfile.open(archive, 'w:gz') as tar:
            item = tarfile.TarInfo('lib.1.dylib'); item.size = 3
            tar.addfile(item, io.BytesIO(b'lib'))
            item = tarfile.TarInfo('lib.dylib'); item.type = tarfile.SYMTYPE; item.linkname = 'lib.1.dylib'
            tar.addfile(item)
        setup.safe_extract(archive, self.home / 'out')
        self.assertEqual((self.home / 'out/lib.dylib').read_bytes(), b'lib')

    def test_pull_requires_final_success_and_tracks_layers(self):
        events = [{'digest':'a','total':100,'completed':100}, {'digest':'b','total':50,'completed':25}]
        payload = b'\n'.join(json.dumps(e).encode() for e in events) + b'\n'
        with patch('urllib.request.urlopen', return_value=io.BytesIO(payload)):
            with self.assertRaisesRegex(ValueError, '连接中断'):
                self.manager.pull_model('test')
        self.assertEqual(self.manager.snapshot()['completed'], 125)
        self.assertEqual(self.manager.snapshot()['total'], 150)
        with patch('urllib.request.urlopen', return_value=io.BytesIO(payload + b'{"status":"success"}\n')):
            self.manager.pull_model('test')

    def test_activation_requires_successful_warmup(self):
        with patch.object(self.manager, 'ensure_engine'), patch.object(self.manager, 'pull_model') as pull, \
                patch.object(self.manager, 'warm_model', side_effect=ValueError('insufficient memory')), \
                patch('ai_runtime.inspect', return_value={'models': []}):
            self.manager._prepare('light')
        self.assertEqual(self.saved, [])
        self.assertEqual(self.manager.snapshot()['phase'], 'error')
        pull.assert_called_once_with(setup.CATALOG['light']['model'])
        with patch.object(self.manager, 'ensure_engine'), patch.object(self.manager, 'pull_model') as pull, \
                patch.object(self.manager, 'warm_model'), \
                patch('ai_runtime.inspect', return_value={'models': [setup.CATALOG['light']['model']]}):
            self.manager._prepare('light')
        pull.assert_not_called()
        self.assertEqual(self.saved, [setup.CATALOG['light']['model']])
        self.assertEqual(self.manager.snapshot()['phase'], 'done')

    def test_empty_warmup_cannot_activate(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'{"done":true,"response":""}')):
            with self.assertRaises(ValueError):
                self.manager.warm_model('test')

    def test_cancelled_warmup_does_not_save_model(self):
        with patch.object(self.manager, 'ensure_engine'), patch.object(self.manager, 'pull_model'), \
                patch.object(self.manager, 'warm_model', side_effect=lambda model: self.manager.cancelled.set()), \
                patch('ai_runtime.inspect', return_value={'models': []}):
            self.manager._prepare('light')
        self.assertEqual(self.saved, [])
        self.assertEqual(self.manager.snapshot()['phase'], 'paused')

    def test_invalid_profile_low_disk_and_duplicate_cannot_start(self):
        with self.assertRaises(ValueError):
            self.manager.start('arbitrary-model')
        with patch.object(self.manager, 'options', return_value={'supported':True,'engine_bytes':0}), \
                patch('shutil.disk_usage', return_value=Mock(free=10)):
            with self.assertRaisesRegex(ValueError, '空间不足'):
                self.manager.start('light')
        self.manager.thread = Mock(); self.manager.thread.is_alive.return_value = True
        with self.assertRaisesRegex(ValueError, '正在准备'):
            self.manager.start('light')

    def test_existing_external_engine_is_never_spawned_or_stopped(self):
        with patch('assistant_setup.engine_alive', return_value=True), \
                patch('assistant_setup.subprocess.Popen') as spawn, patch('assistant_setup.subprocess.run') as stop, \
                patch('ai_runtime.OLLAMA_BASE', self.manager.base):
            self.manager.ensure_engine(); self.manager.shutdown()
        spawn.assert_not_called(); stop.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
