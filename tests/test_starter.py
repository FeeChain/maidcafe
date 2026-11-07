#!/usr/bin/env python3
"""Clean checkout and Anki cache regressions, without external wordbooks."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import deckparse


class TestStarter(unittest.TestCase):
    def test_clean_checkout_serves_words_and_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, MAIDCAFE_DECKS=tmp + '/missing',
                       MAIDCAFE_CACHE=tmp + '/cache', MAIDCAFE_DB=tmp + '/progress.db',
                       MAIDCAFE_ECDICT=tmp + '/none.db')
            code = """
import server
server.build_words()
server.kv_set('seated', 1)
assert len(server.WORDS) == 24
words = server.build_session()['words']
assert len(words) == 20
assert all(w['definition'] and w['has_audio'] for w in words)
assert server.word_info('refill')['definition']
"""
            subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, check=True)

    def test_replacing_and_removing_a_pack_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            decks = tmp / 'decks'
            decks.mkdir()
            pack = decks / 'custom.apkg'
            shutil.copyfile(ROOT / 'resources/window-seat.apkg', pack)
            env = dict(os.environ, MAIDCAFE_DECKS=str(decks),
                       MAIDCAFE_CACHE=str(tmp / 'cache'), MAIDCAFE_DB=str(tmp / 'progress.db'),
                       MAIDCAFE_ECDICT=str(tmp / 'none.db'))
            def words():
                code = "import server,json;server.build_words();print(json.dumps([w['word'] for w in server.WORDS]))"
                output = subprocess.check_output([sys.executable, '-c', code], cwd=ROOT, env=env, text=True)
                return json.loads(output.splitlines()[-1])
            self.assertIn('refill', words())
            extracted = tmp / 'edited'
            with zipfile.ZipFile(pack) as z:
                z.extractall(extracted)
            con = sqlite3.connect(extracted / 'collection.anki2')
            for nid, fields in con.execute('select id,flds from notes').fetchall():
                fs = fields.split('\x1f')
                if fs[0] == 'refill':
                    fs[0] = 'topup'
                    con.execute('update notes set flds=? where id=?', ('\x1f'.join(fs), nid))
            con.commit()
            con.close()
            with zipfile.ZipFile(pack, 'w') as z:
                for path in extracted.iterdir():
                    z.write(path, path.name)
            updated = words()
            self.assertIn('topup', updated)
            self.assertNotIn('refill', updated)
            pack.unlink()
            self.assertNotIn('topup', words())
            self.assertIn('refill', words())


if __name__ == '__main__':
    unittest.main(verbosity=2)
