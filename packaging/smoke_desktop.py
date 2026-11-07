"""Exercise the frozen app in disposable storage, including its actual native window."""
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

exe = Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory(prefix='maidcafe-package-') as tmp:
    home = Path(tmp)
    env = {k: v for k, v in os.environ.items() if not k.startswith('MAIDCAFE_')}
    env.update(MAIDCAFE_HOME=tmp, MAIDCAFE_MODEL='maidcafe-missing-smoke-model')
    for flag in ('--self-check', '--smoke-test', '--speech-check'):
        try:
            subprocess.run([str(exe), flag], env=env, check=True, timeout=120)
        except Exception:
            log = home / 'logs/desktop.log'
            if log.exists():
                print(log.read_text(encoding='utf-8', errors='replace')[-10000:])
            raise
    result = json.loads((home / 'self-check.json').read_text(encoding='utf-8'))
    assert result['words'] == result['audio'] == 24, result
    native = json.loads((home / 'native-smoke.json').read_text(encoding='utf-8'))
    assert native['welcome'] and native['bridge'], native
    audio = json.loads((home / 'speech-check.json').read_text(encoding='utf-8'))
    assert audio and (home / 'speech-check' / audio[0]).stat().st_size > 44
    # The worker must execute generation, not recursively open another app window.
    worker = subprocess.run([str(exe), '--generate', '["refill"]'], env=env, timeout=30)
    assert worker.returncode != 0, 'Missing model should fail cleanly'
    with closing(sqlite3.connect(home / 'progress.db')) as con:
        assert con.execute('select status from dialogues').fetchone()[0] == 'error'
    print(json.dumps({'self_check': result, 'native': native, 'speech': audio, 'worker': 'error recorded'}, ensure_ascii=False))
