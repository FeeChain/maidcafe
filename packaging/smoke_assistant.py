"""Exercise the frozen app's real official engine/model downloads in isolated data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

with tempfile.TemporaryDirectory(prefix='maidcafe-assistant-') as tmp:
    home = Path(tmp)
    command = [str(Path(sys.argv[1]).resolve()), '--prepare-check', sys.argv[2]]
    process = subprocess.Popen(command, env=dict(os.environ, MAIDCAFE_HOME=tmp))
    deadline = time.monotonic() + 1320
    previous = ''
    while process.poll() is None and time.monotonic() < deadline:
        try:
            state = json.loads((home / 'prepare-progress.json').read_text(encoding='utf-8'))
            progress = '%s %d%%' % (state['phase'], 100 * state.get('completed', 0) // max(state.get('total', 0), 1))
            if progress != previous:
                print(progress, flush=True); previous = progress
        except (OSError, ValueError):
            pass
        time.sleep(5)
    if process.poll() is None:
        process.kill(); process.wait()
    result = home / 'prepare-check.json'
    if process.returncode != 0 or not result.exists():
        for log in (home / 'logs/desktop.log', home / 'assistant/setup-error.log', home / 'assistant/engine.log'):
            if log.exists():
                print(log.name, log.read_text(encoding='utf-8', errors='replace')[-6000:])
        raise SystemExit('Frozen assistant setup failed')
    check = json.loads(result.read_text(encoding='utf-8'))
    assert check['ready'] and check['base'].startswith('http://127.0.0.1:')
    if sys.argv[2] != 'engine':
        assert check['phase'] == 'done' and len(check['model']) == 1
    print(json.dumps(check), flush=True)
