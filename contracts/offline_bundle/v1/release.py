"""Verify this exact vendored release without contacting a registry."""
from pathlib import Path
import hashlib
from .canonical import loads,sha256
ROOT=Path(__file__).resolve().parent

def artifacts():
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ROOT.rglob('*'))
        if p.is_file() and not {'__pycache__','node_modules','.venv','.git'} & set(p.parts) and p.suffix!='.pyc' and p.name!='RELEASE.json'}

def verify_release():
    manifest=loads((ROOT/'RELEASE.json').read_bytes())
    if manifest['files']!=artifacts():raise ValueError('Frozen contract files differ from RELEASE.json; do not edit vendored copies')
    expected=sha256({k:v for k,v in manifest.items() if k!='content_hash'})
    if manifest['content_hash']!=expected:raise ValueError('Release manifest hash mismatch')
    return manifest['content_hash']
