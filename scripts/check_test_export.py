"""CI-only decrypt/validate helper; the running participant app never receives a private key."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from contracts.offline_bundle.v1.crypto import decrypt_bundle
from contracts.offline_bundle.v1.validate import validate
bundle=decrypt_bundle(Path(sys.argv[1]).read_bytes(),Path(sys.argv[2]).read_text(),sys.argv[3]);result=validate(bundle)
print(json.dumps({'status':'PASS','validation':result,'events':len(bundle['events']),'neutral_answers':next(s['answers'] for s in bundle['submissions'] if s['stage']=='NEUTRAL'),
    'followups_shown':sum(e['event_type']=='FOLLOWUP_SHOWN' for e in bundle['prompt_events']),'temporal_mode':bundle['manifest']['temporal_mode']}))
