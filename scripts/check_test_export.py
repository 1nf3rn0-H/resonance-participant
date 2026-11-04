"""CI-only decrypt/validate helper; the running participant app never receives a private key."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from contracts.h6_bundle.v1.transport import decrypt_any as decrypt_bundle
from contracts.offline_bundle.v1.validate import validate
bundle=decrypt_bundle(Path(sys.argv[1]).read_bytes(),Path(sys.argv[2]).read_text(),sys.argv[3]);h6=bundle['manifest']['format']=='resonance-h6-bundle'
if h6:
    from contracts.h6_bundle.v1.contract import validate as validate_h6
    result=validate_h6(bundle);extension=bundle['extension'];bundle=bundle['core']
else:result=validate(bundle)
print(json.dumps({'status':'PASS','validation':result,'events':len(bundle['events']),'neutral_answers':next(s['answers'] for s in bundle['submissions'] if s['stage']=='NEUTRAL'),
    'h6':h6,'sessions':len(extension['sessions']) if h6 else None,'extended_events':len(extension['event_evidence']) if h6 else None,'followups_shown':len(extension['followup_exposures']) if h6 else sum(e['event_type']=='FOLLOWUP_SHOWN' for e in bundle['prompt_events']),'temporal_mode':bundle['manifest']['temporal_mode']}))
