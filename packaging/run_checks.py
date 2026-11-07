"""The same core checks locally and in CI, stopping on the first failure."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
for name in ('server', 'dialogue', 'morph', 'starter', 'desktop', 'assistant_setup', 'release', 'e2e'):
    print('Checking ' + name, flush=True)
    subprocess.run([sys.executable, str(root / ('tests/test_' + name + '.py'))], cwd=root, check=True)
