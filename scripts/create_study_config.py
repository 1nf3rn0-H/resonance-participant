"""Prepare a PUBLIC enrollment config from a researcher-supplied PUBLIC age recipient only."""
import sys,argparse,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import pyrage
from contracts.offline_bundle.v1.canonical import sha256
from contracts.offline_bundle.v1.crypto import recipient_fingerprint
from contracts.offline_bundle.v1.release import verify_release
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--study-id',required=True);p.add_argument('--participant-alias',required=True);p.add_argument('--recipient',required=True);p.add_argument('--contact',required=True);p.add_argument('--output',type=Path,required=True)
p.add_argument('--legacy-m0',action='store_true',help='Keep a new configuration on the unchanged M0 protocol')
a=p.parse_args();pyrage.x25519.Recipient.from_str(a.recipient)
config={'version':'participant-study-1.0.0','study_id':a.study_id,'participant_pseudonym':a.participant_alias,'recipient':a.recipient,'recipient_fingerprint':recipient_fingerprint(a.recipient),
    'contract_release_hash':verify_release(),'researcher_contact':a.contact}
if not a.legacy_m0:
    from contracts.h6_bundle.v1.release import verify_release as h6_release
    from contracts.h6_bundle.v1.contract import PROTOCOL
    from contracts.offline_bundle.v1.canonical import loads
    activation=loads((Path(__file__).resolve().parents[1]/'contracts/h6_bundle/v1/activation.json').read_bytes())
    if activation['status']!='ACTIVE_RETROSPECTIVE_PILOT':raise SystemExit('H6 release has not passed activation checks; use --legacy-m0 for the existing protocol')
    config.update(version='participant-study-h6-1.0.0',h6_contract_release_hash=h6_release(),protocol_version=PROTOCOL)
a.output.write_text(json.dumps(config,indent=2)+'\n');print('Study configuration SHA-256: '+sha256(config))
