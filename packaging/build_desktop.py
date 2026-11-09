#!/usr/bin/env python3
"""Build the current platform locally. No credentials or model downloads required."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from release_tools import version_info, installer_name, render_install_guide
from prepare_speech import prepare

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('MAIDCAFE_DIST', ROOT / 'dist')).resolve()
WORK = ROOT / 'build'
VERSION = version_info()
OUT.mkdir(parents=True, exist_ok=True)
WORK.mkdir(exist_ok=True)
prepare()
cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed',
       '--name', 'maidcafe', '--distpath', str(OUT), '--workpath', str(WORK / 'pyinstaller'),
       '--specpath', str(WORK), '--collect-data', 'webview']
for package in ('kokoro_onnx', 'espeakng_loader', 'phonemizer', 'onnxruntime', 'soundfile'):
    cmd += ['--collect-all', package]
for name in ('static', 'resources', 'roster.json', 'scenes.json', 'tts_kokoro.py', 'LICENSE'):
    cmd += ['--add-data', str(ROOT / name) + ':' + (name if (ROOT / name).is_dir() else '.')]
if sys.platform == 'darwin':
    iconset = WORK / 'maidcafe.iconset'
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            filename = 'icon_%dx%d%s.png' % (size, size, '@2x' if scale == 2 else '')
            subprocess.run(['sips', '-z', str(size * scale), str(size * scale),
                            str(ROOT / 'static/art/A1_logo.png'), '--out', str(iconset / filename)],
                           check=True, stdout=subprocess.DEVNULL)
    icon = WORK / 'maidcafe.icns'
    subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(icon)], check=True)
    cmd += ['--icon', str(icon), '--osx-bundle-identifier', 'com.feechain.maidcafe']
cmd.append(str(ROOT / 'desktop.py'))
subprocess.run(cmd, cwd=ROOT, check=True)
if sys.platform == 'darwin':
    import plistlib
    plist = OUT / 'maidcafe.app/Contents/Info.plist'
    data = plistlib.loads(plist.read_bytes())
    data.update(CFBundleShortVersionString=VERSION['base'], CFBundleVersion=os.environ.get('GITHUB_RUN_NUMBER', '1'),
                NSHighResolutionCapable=True, NSAppTransportSecurity={'NSAllowsLocalNetworking': True})
    plist.write_bytes(plistlib.dumps(data))
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(OUT / 'maidcafe.app')], check=True)
    image = WORK / 'dmg-root'
    if image.exists():
        shutil.rmtree(image)
    image.mkdir(exist_ok=True)
    shutil.copytree(OUT / 'maidcafe.app', image / 'maidcafe.app', dirs_exist_ok=True, symlinks=True)
    applications = image / 'Applications'
    if not applications.exists():
        applications.symlink_to('/Applications')
    (image / '开始使用.txt').write_text(render_install_guide(), encoding='utf-8')
    dmg = OUT / installer_name(VERSION['version'], 'macOS-' + platform.machine())
    subprocess.run(['hdiutil', 'create', '-ov', '-volname', 'maidcafe', '-srcfolder', str(image),
                    '-format', 'UDZO', str(dmg)], check=True)
    print(dmg)
else:
    (OUT / 'maidcafe/开始使用.txt').write_text(render_install_guide(), encoding='utf-8')
    print(shutil.make_archive(str(OUT / ('maidcafe-' + VERSION['version'] + '-' + platform.system())), 'zip', OUT, 'maidcafe'))
    if sys.platform == 'win32':
        compiler = shutil.which('ISCC') or r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
        subprocess.run([compiler, '/DBuildRoot=' + str(OUT), '/DAppVersion=' + VERSION['version'],
                        str(ROOT / 'packaging/windows.iss')], check=True)
