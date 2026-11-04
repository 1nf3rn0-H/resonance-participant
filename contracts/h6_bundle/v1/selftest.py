from pathlib import Path
from .contract import validate,content_hash,integrity_hash
from .transport import encode,decode
from .release import verify_release
from contracts.offline_bundle.v1.canonical import loads
ROOT=Path(__file__).parent

def main():
    vectors=loads((ROOT/'vectors/hashes.json').read_bytes())
    for v in vectors:
        bundle=loads((ROOT/v['fixture']).read_bytes());validate(bundle)
        assert content_hash(bundle)==v['content_hash'] and integrity_hash(bundle)==v['integrity_hash']
        assert decode(encode(bundle))==bundle
    print({'status':'PASS','h6_contract':'1.0.0','release_hash':verify_release(),'bundle_vectors':len(vectors)})
if __name__=='__main__':main()
