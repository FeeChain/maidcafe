"""Test the files users download, then record their checksums and exact source."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from release_tools import ROOT, version_info, installer_name, digest

target = sys.argv[1]
version = version_info()['version']
installer = ROOT / 'dist' / installer_name(version, target)
commit = os.environ.get('GITHUB_SHA') or subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
with tempfile.TemporaryDirectory(prefix='maidcafe-install-') as tmp:
    work = Path(tmp)
    if sys.platform == 'darwin':
        mount = work / 'volume'; mount.mkdir()
        subprocess.run(['hdiutil', 'verify', str(installer)], check=True)
        subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mount), str(installer)], check=True)
        try:
            shutil.copytree(mount / 'maidcafe.app', work / 'maidcafe.app', symlinks=True)
        finally:
            subprocess.run(['hdiutil', 'detach', str(mount)], check=True)
        exe = work / 'maidcafe.app/Contents/MacOS/maidcafe'
    elif sys.platform == 'win32':
        subprocess.run([str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/DIR=' + str(work / 'app')], check=True)
        exe = work / 'app/maidcafe.exe'
    else:
        raise SystemExit('Installer tests need Mac or Windows')
    native, assistant = work / 'native.json', work / 'assistant.json'
    subprocess.run([sys.executable, str(ROOT / 'packaging/smoke_desktop.py'), str(exe), str(native)], check=True)
    profile = 'engine' if target == 'macOS-x86_64' else 'light'
    subprocess.run([sys.executable, str(ROOT / 'packaging/smoke_assistant.py'), str(exe), profile, str(assistant)], check=True)
    if sys.platform == 'win32':
        subprocess.run([str(work / 'app/unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], check=True)
    report = {'version': version, 'commit': commit, 'platform': target, 'filename': installer.name,
              'size': installer.stat().st_size, 'sha256': digest(installer),
              'native': json.loads(native.read_text(encoding='utf-8')),
              'assistant': json.loads(assistant.read_text(encoding='utf-8'))}
    output = ROOT / 'dist' / ('build-report-' + target + '.json')
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)
