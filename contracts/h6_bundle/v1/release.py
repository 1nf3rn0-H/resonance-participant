from pathlib import Path
import hashlib
from contracts.offline_bundle.v1.canonical import loads,sha256
ROOT=Path(__file__).parent

def verify_release():
    release=loads((ROOT/'RELEASE.json').read_bytes())
    if sha256({k:v for k,v in release.items() if k!='content_hash'})!=release['content_hash']:raise ValueError('H6 release manifest changed')
    for name,expected in release['files'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=expected:raise ValueError('H6 release file changed: '+name)
    return release['content_hash']
