"""Fetch hash-pinned English Kokoro resources during the build, never at first launch."""
import hashlib
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    'kokoro-v1.0.onnx': ('7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5', 325532387),
    'voices-v1.0.bin': ('bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d', 28214398),
}


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def prepare():
    folder=ROOT/'resources/kokoro'
    folder.mkdir(parents=True,exist_ok=True)
    for name,(sha,size) in FILES.items():
        target=folder/name
        if target.is_file() and target.stat().st_size==size and digest(target)==sha:
            continue
        temporary=target.with_suffix(target.suffix+'.part')
        url='https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/'+name
        print('Fetching '+name,flush=True)
        with urllib.request.urlopen(url,timeout=90) as response,temporary.open('wb') as output:
            for block in iter(lambda:response.read(1024*1024),b''):
                output.write(block)
        if temporary.stat().st_size!=size or digest(temporary)!=sha:
            temporary.unlink()
            raise RuntimeError('Kokoro resource checksum mismatch: '+name)
        temporary.replace(target)


if __name__=='__main__':
    prepare()
