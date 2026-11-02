"""Portable acceptance runner, shared verbatim by participant and admin CI."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from .canonical import loads,dumps,sha256
from .validate import validate,QUESTIONS,SAMPLING
from .archive import decode
from .crypto import decrypt_bundle,recipient_fingerprint
from .release import verify_release
ROOT=Path(__file__).resolve().parent

def run():
    release=verify_release();catalog=loads((ROOT/'fixtures/catalog.json').read_bytes());passed=0
    keys=loads((ROOT/'fixtures/PUBLIC_TEST_KEYS.json').read_bytes())
    for item in catalog:
        payload=(ROOT/'fixtures'/item['file']).read_bytes()
        try:
            if item['kind']=='archive':decode(payload)
            elif item['kind']=='encrypted':decrypt_bundle(payload,keys['identity'],recipient_fingerprint(keys['recipient']))
            else:validate(loads(payload))
            valid=True
        except ValueError:valid=False
        if valid!=item['valid']:raise AssertionError('Fixture expectation differs: '+item['file'])
        passed+=1
    vectors=loads((ROOT/'vectors/canonical.json').read_bytes())
    for vector in vectors:
        if dumps(vector['input']).decode()!=vector['canonical_utf8'] or sha256(vector['input'])!=vector['sha256']:raise AssertionError('Canonical vector mismatch')
    for file in (ROOT/'schemas').glob('*.json'):Draft202012Validator.check_schema(loads(file.read_bytes()))
    return {'status':'PASS','contract_version':'1.0.0','release_hash':release,'fixture_cases':passed,'canonical_vectors':len(vectors),'protocol_status':'DRAFT_NOT_PREREGISTERED'}

if __name__=='__main__':print(json.dumps(run(),indent=2))
