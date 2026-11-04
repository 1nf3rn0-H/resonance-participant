"""Generate only synthetic test data and an ephemeral TEST encryption identity outside the repo."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import json
import pyrage
from contracts.offline_bundle.v1.canonical import sha256
from contracts.offline_bundle.v1.crypto import recipient_fingerprint
from contracts.offline_bundle.v1.release import verify_release
from datetime import datetime,timezone,timedelta
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
identity=pyrage.x25519.Identity.generate();recipient=str(identity.to_public())
config={'version':'participant-study-1.0.0','study_id':'synthetic-browser-test','participant_pseudonym':'P-SYNTHETIC','recipient':recipient,
    'recipient_fingerprint':recipient_fingerprint(recipient),'contract_release_hash':verify_release(),'researcher_contact':'Synthetic test contact, no real participant data'}
h6='--h6' in sys.argv
if h6:
    from contracts.h6_bundle.v1.release import verify_release as h6_release
    from contracts.h6_bundle.v1.contract import PROTOCOL
    config.update(version='participant-study-h6-1.0.0',h6_contract_release_hash=h6_release(),protocol_version=PROTOCOL)
config_path=out/'synthetic-public-config.json';config_path.write_text(json.dumps(config,indent=2));key=out/'synthetic-test-identity.txt';key.write_text(str(identity));key.chmod(0o600)
rows=[]
for day in range(4):
    for i in range(16):
        rows.append({'ts':(datetime(2026,3,1+day,10,tzinfo=timezone.utc)+timedelta(minutes=i*2)).isoformat().replace('+00:00','Z'),
            'ms_played':60000,'master_metadata_track_name':'Synthetic track '+str(i%4),'master_metadata_album_artist_name':'Synthetic artist',
            'spotify_track_uri':'spotify:track:synthetic'+str(i%4),'skipped':i%4==0,'reason_start':'clickrow','reason_end':'trackdone','shuffle':False,
            'username':'NEVER_EXPORT_ACCOUNT','ip_addr':'192.0.2.10'})
if h6:
    for row in rows:row.update(duration_ms=180000,track_duration_ms=180000,playback_source='PLAYLIST',manual_selection=False,shuffle=True,playlist_name='Synthetic H6 playlist',playlist_uri='spotify:playlist:SYNTHETIC',context_uri='spotify:playlist:SYNTHETIC')
history=out/'Streaming_History_Audio_synthetic.json';history.write_text(json.dumps(rows))
print(json.dumps({'config_path':str(config_path),'config_hash':sha256(config),'history_path':str(history),'identity_path':str(key),'recipient_fingerprint':config['recipient_fingerprint']}))
