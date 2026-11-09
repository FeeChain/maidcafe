"""Small ECDICT inflection index shipped with the base vocabulary."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def index():
    path=Path(__file__).resolve().parent/'resources/inflections.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def lemma(word):
    return index().get(word.lower(),word.lower())
