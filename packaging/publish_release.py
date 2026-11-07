"""Assemble verified artifacts; publish an immutable version from main only.

Run without --publish to validate and assemble locally. Publishing uses the
job-scoped GH_TOKEN through gh, never a developer's personal token in the repo.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from release_tools import ROOT, digest, render_install_guide, validate_artifacts, version_info, version_key


def gh(*args, payload=None):
    result = subprocess.run(['gh', *args], input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def api(path, method='GET', payload=None):
    args = ['api', path, '--method', method]
    if payload is not None:
        args += ['--input', '-']
    return json.loads(gh(*args, payload=payload))


def release_decision(releases, version, commit):
    tag = 'v' + version
    for release in releases:
        if release['tag_name'] == tag:
            if not release['draft']:
                return 'skip', release
            marker = '<!-- maidcafe-source:' + commit + ' -->'
            if release.get('target_commitish') != commit or marker not in (release.get('body') or ''):
                raise ValueError('An unrelated draft already uses this version. Bump the version before publishing changed code.')
            return 'resume', release
    current = version_key(version)
    for release in releases:
        if release['draft']:
            continue
        try:
            previous = version_key(release['tag_name'].removeprefix('v'))
        except ValueError:
            continue
        if previous >= current:
            raise ValueError('New releases must have a higher version than all published releases.')
    return 'create', None


def verify_uploads(assets, files):
    expected = {p.name: p for p in files}
    if len(assets) != len(expected) or {a['name'] for a in assets} != set(expected):
        raise ValueError('Release is incomplete or has unexpected attachments')
    for asset in assets:
        path = expected[asset['name']]
        if asset['size'] != path.stat().st_size or asset.get('digest') != 'sha256:' + digest(path):
            raise ValueError('Uploaded checksum/size mismatch: ' + path.name)


def assemble(artifacts, output, commit, repository, run_url):
    if not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('Release requires an exact Git commit SHA')
    info = version_info()
    reports = validate_artifacts(artifacts, info['version'], commit)
    notes = (ROOT / 'packaging/notes' / (info['version'] + '.md')).read_text(encoding='utf-8').strip()
    if not notes.startswith('# ' + info['version'] + '\n') or len(notes) < 40:
        raise ValueError('Add release notes for the current version')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Use an empty release output directory')
    prefix = 'maidcafe-' + info['version']
    for report in reports.values():
        shutil.copyfile(report['path'], output / report['filename'])
    subprocess.run(['git', 'archive', '--format=zip', '--prefix=maidcafe/',
                    '-o', str((output / (prefix + '-source.zip')).resolve()), commit], cwd=ROOT, check=True)
    shutil.copyfile(ROOT / 'resources/window-seat.apkg', output / 'maidcafe-window-seat.apkg')
    (output / (prefix + '-README.txt')).write_text(render_install_guide(), encoding='utf-8')
    manifest = {'version': info['version'], 'commit': commit, 'run_url': run_url,
                'installers': [{k:v for k,v in report.items() if k != 'path'} for report in reports.values()]}
    (output / (prefix + '-verification.json')).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    files = sorted(output.iterdir())
    sums = output / (prefix + '-SHA256SUMS.txt')
    sums.write_text(''.join(digest(p) + '  ' + p.name + '\n' for p in files), encoding='utf-8')
    files.append(sums)
    base = 'https://github.com/' + repository + '/releases/download/' + info['tag'] + '/'
    rows = ['| 电脑 | 下载 |', '|---|---|']
    labels = {'macOS-arm64':'Mac M 系列', 'macOS-x86_64':'Intel Mac', 'Windows-x64':'Windows 64 位'}
    for target, report in reports.items():
        rows.append('| %s | [下载安装包 · %.1f MB](%s%s) |' %
                    (labels[target], report['size'] / 1e6, base, report['filename']))
    body = notes + '\n\n' + '\n'.join(rows)
    body += ('\n\nMac 打开 DMG 后拖入 Applications；Windows 运行安装程序。无需 Python。'
             '首次可直接试听、翻词卡；生成故事时点「故事设置 → 一键准备」。\n\n'
             '轻量模型约 1.4 GB、标准约 2.5 GB；首次引擎 Mac 约 186 MB、Windows 约 1.6 GB。'
             '自动准备需 macOS 14+ / Windows 10 22H2+，建议至少 8 GB 内存；下载后可离线使用。\n\n'
             '当前安装包尚未完成发行签名/公证，首次打开可能出现系统来源提示。'
             'AI 生成的词义与语法仍需抽查。\n\n'
             '三个安装包均经实际安装、原生窗口、内置词库、系统配音与助手引擎检查；'
             'Mac ARM / Windows 还实际下载并试运行轻量模型。'
             '附件提供源码、安装说明、词包、验证记录和 SHA-256 校验文件。\n\n')
    body += '[构建与测试记录](%s) · 源码 `%s`\n' % (run_url, commit)
    body += '<!-- maidcafe-source:' + commit + ' -->'
    return info, files, body


def publish(repository, info, commit, files, body):
    pages = json.loads(gh('api', '--paginate', '--slurp', 'repos/' + repository + '/releases?per_page=100'))
    action, release = release_decision([r for page in pages for r in page], info['version'], commit)
    if action == 'skip':
        return 'Version already published; no files changed: ' + release['html_url']
    endpoint = 'repos/' + repository + '/releases'
    if action == 'create':
        # A tag created elsewhere must also point at this exact tested source.
        refs = api('repos/' + repository + '/git/matching-refs/tags/' + info['tag'])
        for ref in refs:
            if ref['ref'] != 'refs/tags/' + info['tag']:
                continue
            obj = ref['object']
            if obj['type'] == 'tag':
                obj = api('repos/' + repository + '/git/tags/' + obj['sha'])['object']
            if obj['type'] != 'commit' or obj['sha'] != commit:
                raise ValueError('Existing version tag points to a different source commit')
        release = api(endpoint, 'POST', {'tag_name':info['tag'], 'target_commitish':commit,
                      'name':'maidcafe ' + info['version'], 'body':body, 'draft':True,
                      'prerelease':info['prerelease'], 'make_latest':'false'})
    expected = {p.name for p in files}
    if any(a['name'] not in expected for a in release.get('assets', [])):
        raise ValueError('Draft contains unrelated attachments; refusing to change it')
    gh('release', 'upload', info['tag'], '--repo', repository, '--clobber', *[str(p) for p in files])
    release = api(endpoint + '/' + str(release['id']))
    verify_uploads(release['assets'], files)
    release = api(endpoint + '/' + str(release['id']), 'PATCH', {'body':body, 'draft':False,
                  'prerelease':info['prerelease'], 'make_latest':'false' if info['prerelease'] else 'true'})
    if release['draft']:
        raise ValueError('Release did not become public')
    return 'Published: ' + release['html_url']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts', default='artifacts')
    parser.add_argument('--output', default='release-output')
    parser.add_argument('--commit', default=os.environ.get('GITHUB_SHA', ''))
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    repository = os.environ.get('GITHUB_REPOSITORY', 'FeeChain/maidcafe')
    run_url = 'https://github.com/' + repository + '/actions/runs/' + os.environ.get('GITHUB_RUN_ID', '')
    if args.publish and (os.environ.get('GITHUB_REF') != 'refs/heads/main' or
                         os.environ.get('GITHUB_EVENT_NAME') not in ('push', 'workflow_dispatch')):
        raise ValueError('Public releases can only be made by the main workflow')
    info, files, body = assemble(args.artifacts, args.output, args.commit, repository, run_url)
    message = publish(repository, info, args.commit, files, body) if args.publish else 'Verified release files: ' + str(len(files))
    print(message)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as out:
            out.write(message + '\n')


if __name__ == '__main__':
    main()
