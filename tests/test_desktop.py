"""First installation, local setup, importing and portable records; no real user data."""
import io
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import ai_runtime
import app_paths
import portability
import server


class RuntimeTests(unittest.TestCase):
    def inspect_models(self, names, saved='', **env):
        payload = {'models': [{'name': name} for name in names]}
        with patch.dict(os.environ, env, clear=True), patch('ai_runtime.audio_backend', return_value='text'), \
                patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
            return ai_runtime.inspect(saved)

    def test_new_install_single_local_model_and_cloud_exclusion(self):
        state = self.inspect_models(['small:latest', 'huge-cloud'])
        self.assertTrue(state['ready'])
        self.assertEqual(state['model'], 'small:latest')
        self.assertEqual(state['models'], ['small:latest'])

    def test_explicit_missing_model_does_not_silently_switch(self):
        state = self.inspect_models(['small:latest'], MAIDCAFE_MODEL='missing')
        self.assertFalse(state['ready'])
        self.assertTrue(state['locked'])
        self.assertEqual(state['code'], 'missing_model')

    def test_multiple_models_require_choice_and_remember_it(self):
        self.assertEqual(self.inspect_models(['a', 'b'])['code'], 'choose_model')
        self.assertEqual(self.inspect_models(['a', 'b'], saved='b')['model'], 'b')

    def test_offline_has_actionable_message(self):
        with patch('urllib.request.urlopen', side_effect=OSError), patch('ai_runtime.audio_backend', return_value='text'):
            state = ai_runtime.inspect()
        self.assertEqual(state['code'], 'offline')
        self.assertIn('Ollama', state['message'])

    def test_desktop_data_survives_relaunch_outside_bundle(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'MAIDCAFE_HOME': tmp}, clear=True):
            home = app_paths.configure_desktop()
            db = Path(os.environ['MAIDCAFE_DB'])
            db.write_text('progress', encoding='utf-8')
            self.assertEqual(app_paths.configure_desktop(), home)
            self.assertEqual(db.read_text(), 'progress')
            self.assertNotEqual(home, app_paths.ROOT)


class DesktopAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        paths = {'DB_PATH': str(root / 'progress.db'), 'DECKS_DIR': str(root / 'decks'),
                 'CACHE_DIR': str(root / 'cache'), 'WORDS_CACHE': str(root / 'cache/words_cache.json'),
                 'ECDICT_DB': str(root / 'none.db'), 'ECDICT_PATH': str(root / 'none.db'),
                 'LOG_DIR': str(root / 'logs'), 'AUDIO_OUT': str(root / 'audio'),
                 'WORDROOT_PATH': str(root / 'none.txt'), 'GEN_PROCESS': None, '_MORPH': None}
        patcher = patch.multiple(server, **paths)
        patcher.start()
        self.addCleanup(patcher.stop)
        server.build_words()
        server.db().close()
        self.httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.base = 'http://127.0.0.1:%d' % self.httpd.server_port
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()

    def call(self, path, data=None, headers=None):
        if isinstance(data, dict):
            data = json.dumps(data).encode()
        request = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.code, json.load(response)

    def test_unready_generation_creates_no_placeholder(self):
        with patch('ai_runtime.inspect', return_value={'ready': False, 'message': 'Open Ollama'}), \
                patch('server.subprocess.Popen') as spawn:
            code, data = self.call('/api/generate', {'words': ['refill']})
        self.assertEqual(code, 503)
        self.assertEqual(data['code'], 'setup_required')
        spawn.assert_not_called()
        with closing(server.db()) as con:
            self.assertEqual(con.execute('select count(*) from dialogues').fetchone()[0], 0)

    def test_model_selection_saved_and_invalid_rejected(self):
        with patch('ai_runtime.inspect', return_value={'models': ['local'], 'locked': False}):
            self.assertEqual(self.call('/api/setup', {'model': 'missing'})[0], 400)
            self.assertEqual(self.call('/api/setup', {'model': 'local'})[0], 200)
        self.assertEqual(server.kv_get('model'), 'local')

    def test_frozen_worker_dispatch_and_duplicate_order(self):
        proc = Mock()
        proc.poll.return_value = None
        with patch('ai_runtime.inspect', return_value={'ready': True, 'model': 'local'}), \
                patch('server.subprocess.Popen', return_value=proc) as spawn, \
                patch.object(sys, 'frozen', True, create=True):
            self.assertEqual(self.call('/api/generate', {'words': ['give up']})[0], 200)
            args, kwargs = spawn.call_args
            self.assertEqual(args[0][1:], ['--generate', '["give up"]'])
            self.assertEqual(kwargs['env']['MAIDCAFE_MODEL'], 'local')
            self.assertEqual(kwargs['env']['MAIDCAFE_OLLAMA_BASE'], ai_runtime.OLLAMA_BASE)
            self.assertEqual(self.call('/api/generate', {'words': ['refill']})[0], 409)
            self.assertEqual(spawn.call_count, 1)

    def test_one_click_endpoint_starts_only_allowed_local_task(self):
        manager = Mock(active=False)
        with patch.dict(os.environ, {}, clear=True), patch('server.get_setup', return_value=manager):
            self.assertEqual(self.call('/api/setup/prepare', {'profile': 'light'})[0], 202)
            manager.start.assert_called_once_with('light')
            self.assertEqual(self.call('/api/setup/cancel', {})[0], 200)
            manager.cancel.assert_called_once()
            self.assertEqual(self.call('/api/setup/prepare', {'profile': 'light'}, {'Origin':'https://example.org'})[0], 403)
            self.assertEqual(manager.start.call_count, 1)
        with patch.dict(os.environ, {'MAIDCAFE_MODEL':'locked'}), patch('server.get_setup', return_value=manager):
            self.assertEqual(self.call('/api/setup/prepare', {'profile': 'light'})[0], 409)
            self.assertEqual(manager.start.call_count, 1)

    def test_preparing_blocks_model_change_and_story_generation(self):
        with patch('server.get_setup', return_value=Mock(active=True)), patch('server.subprocess.Popen') as spawn:
            self.assertEqual(self.call('/api/setup', {'model':'local'})[0], 409)
            self.assertEqual(self.call('/api/generate', {'words':['refill']})[0], 409)
            spawn.assert_not_called()

    def test_import_valid_pack_and_preserve_progress(self):
        self.call('/api/word_pass', {'word': 'refill'})
        before = self.call('/api/backup')[1]['tables']['marks']
        code, data = self.call('/api/decks/import?name=lesson.apkg', (ROOT / 'resources/window-seat.apkg').read_bytes())
        self.assertEqual(code, 200)
        self.assertEqual(data['words'], 24)
        self.assertEqual(self.call('/api/backup')[1]['tables']['marks'], before)
        self.assertEqual(self.call('/api/decks/import?name=bad.apkg', b'not a zip')[0], 400)
        self.assertEqual(len(list(Path(server.DECKS_DIR).glob('*.apkg'))), 1)

    def test_import_rejects_windows_path_traversal(self):
        import zipfile
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, 'w') as z:
            z.writestr('collection.anki2', '')
            z.writestr('..\\outside', 'bad')
        self.assertEqual(self.call('/api/decks/import?name=bad.apkg', blob.getvalue())[0], 400)

    def test_restore_round_trip_and_no_overwrite(self):
        self.call('/api/word_pass', {'word': 'refill'})
        backup = self.call('/api/backup')[1]
        self.assertEqual(self.call('/api/restore', backup)[0], 400)
        fresh = str(Path(self.tmp.name) / 'fresh.db')
        with patch.object(server, 'DB_PATH', fresh):
            self.assertEqual(self.call('/api/restore', backup)[0], 200)
            self.assertEqual(self.call('/api/backup')[1]['tables'], backup['tables'])

    def test_bad_backup_rolls_back_every_table(self):
        backup = self.call('/api/backup')[1]
        backup['tables']['marks']['rows'] = [['refill', 1, 1, 'add']] * 2
        self.assertEqual(self.call('/api/restore', backup)[0], 400)
        self.assertEqual(self.call('/api/backup')[1]['tables']['marks']['rows'], [])

    def test_cross_origin_request_cannot_read_or_write(self):
        self.assertEqual(self.call('/api/backup', headers={'Origin': 'https://example.org'})[0], 403)
        self.assertEqual(self.call('/api/visit', {}, {'Origin': 'https://example.org'})[0], 403)


if __name__ == '__main__':
    unittest.main(verbosity=2)
