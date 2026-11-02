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
a=p.parse_args();pyrage.x25519.Recipient.from_str(a.recipient)
config={'version':'participant-study-1.0.0','study_id':a.study_id,'participant_pseudonym':a.participant_alias,'recipient':a.recipient,'recipient_fingerprint':recipient_fingerprint(a.recipient),
    'contract_release_hash':verify_release(),'researcher_contact':a.contact}
a.output.write_text(json.dumps(config,indent=2)+'\n');print('Study configuration SHA-256: '+sha256(config))
