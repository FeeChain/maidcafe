"""Shared version and release validation; stdlib only, no network side effects."""
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = {'macOS-arm64': 'dmg', 'macOS-x86_64': 'dmg', 'Windows-x64': 'exe'}
VERSION_RE = re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(alpha|beta|preview|rc)(?:\.(0|[1-9]\d*))?)?$', re.ASCII)


def version_info(value=None):
    if value is None:
        tree = ast.parse((ROOT / 'app_paths.py').read_text(encoding='utf-8'))
        value = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == 'VERSION' for t in n.targets))
    match = VERSION_RE.fullmatch(value)
    if not match:
        raise ValueError('Use a version such as 0.3.1-preview, 0.4.0-rc.1 or 1.0.0')
    return {'version': value, 'base': '.'.join(match.groups()[:3]), 'tag': 'v' + value,
            'prerelease': bool(match[4])}


def version_key(value):
    match = VERSION_RE.fullmatch(version_info(value)['version'])
    stage = {'alpha': 0, 'beta': 1, 'preview': 2, 'rc': 3, None: 4}[match[4]]
    return tuple(map(int, match.groups()[:3])) + (stage, int(match[5] or 0))


def installer_name(version, target):
    version_info(version)
    suffix = target + ('-Setup.exe' if target == 'Windows-x64' else '.dmg')
    if target not in PLATFORMS:
        raise ValueError('Unknown platform')
    return 'maidcafe-' + version + '-' + suffix


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def validate_artifacts(folder, version, commit):
    """Require one tested installer per platform, all from the exact release commit."""
    folder = Path(folder)
    reports = {}
    for target in PLATFORMS:
        matches = list(folder.rglob('build-report-' + target + '.json'))
        if len(matches) != 1:
            raise ValueError('Missing or duplicate test report: ' + target)
        report = json.loads(matches[0].read_text(encoding='utf-8'))
        if (report.get('platform'), report.get('version'), report.get('commit')) != (target, version, commit):
            raise ValueError('Installer source/version mismatch: ' + target)
        filename = installer_name(version, target)
        matches = list(folder.rglob(filename))
        if len(matches) != 1:
            raise ValueError('Missing or duplicate installer: ' + filename)
        path = matches[0]
        if report.get('filename') != filename or report.get('size') != path.stat().st_size or report.get('sha256') != digest(path):
            raise ValueError('Installer checksum mismatch: ' + filename)
        native, assistant = report.get('native', {}), report.get('assistant', {})
        if not native.get('native', {}).get('welcome') or not native.get('native', {}).get('bridge'):
            raise ValueError('Native window not verified: ' + target)
        if native.get('self_check', {}).get('version') != version or native.get('worker') != 'error recorded':
            raise ValueError('Frozen app not verified: ' + target)
        if native['self_check'].get('words', 0) < 20000 or native['self_check'].get('audio', 0) < 24:
            raise ValueError('Bundled vocabulary not verified: ' + target)
        if native.get('speech', {}).get('backend') != 'kokoro' or not native.get('speech', {}).get('files'):
            raise ValueError('Bundled English speech not verified: ' + target)
        if native.get('native', {}).get('art') != {'count':25,'failed':[],'ready':True}:
            raise ValueError('Group artwork not verified: ' + target)
        if not assistant.get('ready'):
            raise ValueError('Assistant engine not verified: ' + target)
        if target != 'macOS-x86_64' and (assistant.get('phase') != 'done' or not assistant.get('model')):
            raise ValueError('Assistant model not verified: ' + target)
        reports[target] = dict(report, path=path)
    return reports


def render_install_guide():
    guide = (ROOT / 'packaging/开始使用.txt').read_text(encoding='utf-8')
    return guide.replace('{VERSION}', version_info()['version'])


if __name__ == '__main__':
    print(json.dumps(version_info()))
