"""Immutable application resources and writable per-user desktop data."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
VERSION = '0.3.2-preview'


def user_data_dir():
    override = os.environ.get('MAIDCAFE_HOME')
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/maidcafe'
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) / 'maidcafe'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'maidcafe'


def configure_desktop():
    home = user_data_dir()
    home.mkdir(parents=True, exist_ok=True)
    defaults = {'MAIDCAFE_DB': home / 'progress.db', 'MAIDCAFE_CACHE': home / 'cache',
                'MAIDCAFE_DECKS': home / 'decks', 'MAIDCAFE_AUDIO_OUT': home / 'audio_out',
                'MAIDCAFE_ECDICT': home / 'data/stardict.db',
                'MAIDCAFE_WORDROOT': home / 'data/wordroot.txt',
                'MAIDCAFE_LOG_DIR': home / 'logs', 'MAIDCAFE_DATA_DIR': home / 'data'}
    for name, path in defaults.items():
        os.environ.setdefault(name, str(path))
    for name in ('MAIDCAFE_CACHE', 'MAIDCAFE_DECKS', 'MAIDCAFE_AUDIO_OUT', 'MAIDCAFE_LOG_DIR', 'MAIDCAFE_DATA_DIR'):
        Path(os.environ[name]).mkdir(parents=True, exist_ok=True)
    return home
