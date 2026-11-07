"""Prepare the single version field and matching release notes together."""
import argparse
import re
from release_tools import ROOT, version_info, version_key

parser = argparse.ArgumentParser()
parser.add_argument('version')
parser.add_argument('--note', action='append', required=True, help='User-facing change; repeat for multiple changes')
args = parser.parse_args()
version_info(args.version)
if version_key(args.version) <= version_key(version_info()['version']):
    parser.error('The new version must be higher than the current version')
notes = ROOT / 'packaging/notes' / (args.version + '.md')
if notes.exists() or any(not note.strip() for note in args.note):
    parser.error('Notes already exist or a note is empty')
source = ROOT / 'app_paths.py'
text, count = re.subn(r'^VERSION = .+$', 'VERSION = ' + repr(args.version), source.read_text(encoding='utf-8'), flags=re.M)
if count != 1:
    parser.error('Could not locate the version field')
notes.parent.mkdir(exist_ok=True)
notes.write_text('# ' + args.version + '\n\n' + '\n'.join('- ' + note.strip() for note in args.note) + '\n', encoding='utf-8')
source.write_text(text, encoding='utf-8')
print('Updated app_paths.py and ' + str(notes.relative_to(ROOT)))
