"""Fetch this project's published data and verify the recorded SHA256 values."""
from pathlib import Path
from urllib.request import Request, urlopen
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parent

def fetch(url,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists():
        request=Request(url,headers={'User-Agent':'Mozilla/5.0 (public-data-research)'})
        with urlopen(request,timeout=180) as response:
            content=response.read()
        temporary=target.with_suffix(target.suffix+'.part')
        temporary.write_bytes(content)
        temporary.replace(target)

def verify():
    manifest=json.loads((ROOT/'data_manifest.json').read_text(encoding='utf-8'))
    for entry in manifest['files']:
        path=ROOT/entry['file']
        actual=hashlib.sha256(path.read_bytes()).hexdigest()
        if actual!=entry['sha256']:
            raise ValueError('Source file changed or download corrupted: '+entry['file'])
    print('Verified',len(manifest['files']),'source files against the recorded manifest.')

def main():
    archive=ROOT/'data/raw/olist.zip'
    fetch('https://www.kaggle.com/api/v1/datasets/download/olistbr/brazilian-ecommerce',archive)
    with zipfile.ZipFile(archive) as z:
        for member in z.namelist():
            name=Path(member).name
            if name.endswith('.csv'):
                (archive.parent/name).write_bytes(z.read(member))
    verify()

if __name__=='__main__': main()
