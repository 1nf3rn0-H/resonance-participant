"""Adapters around the two byte-identical, pinned behavioral implementations only."""
from pathlib import Path
from hashlib import sha256 as byte_sha
from dataclasses import asdict
import json
import subprocess
from contracts.offline_bundle.v1.canonical import sha256
from .samplers.ped import surface,PedConfig

ROOT=Path(__file__).resolve().parent

def verify_native():
    pins=json.loads((ROOT.parent/'contracts/offline_bundle/v1/native-surfacer-pins.json').read_text())
    for kind,name in [('v03','v03.ts'),('ped','ped.py')]:
        if byte_sha((ROOT/'samplers'/name).read_bytes()).hexdigest()!=pins[kind]['source_sha256']:raise ValueError('Frozen native sampler changed; use a verified release')
    return pins

def observations(events,tracks):
    index={t['record_id']:t for t in tracks}
    return [{'id':e['record_id'],'occurredAt':e['occurred_at'],'provider':'SPOTIFY','providerTrackId':index[e['track_id']]['provider_ref'],
        'trackName':index[e['track_id']]['title'],'artistName':index[e['track_id']]['artist'],'albumName':'','millisecondsPlayed':e['played_ms'],
        'skipped':e['skipped'],'startReason':e['reason_start'],'endReason':e['reason_end'],'shuffle':e['shuffle'],'playbackSource':'UNKNOWN','deviceClass':'UNKNOWN',
        'providerTimestampRaw':e['provider_timestamp_raw'],'providerTimestampSemantics':e['provider_timestamp_semantics'],
        'observedStartAt':e['observed_start_at'],'observedEndAt':e['observed_end_at'],'estimatedStartAt':e['estimated_start_at'],'estimatedEndAt':e['estimated_end_at'],
        'timeEstimationMethod':e['time_estimation_method'],'timeQuality':e['time_quality'],'actualSourceAvailableAt':e['source_available_at']} for e in events]

def native_results(events,tracks,seed,generated_at,include_history=True):
    pins=verify_native();items=observations(events,tracks);by_id={e['record_id']:e for e in events}
    legacy=subprocess.run(['node','--experimental-strip-types',str(ROOT/'samplers/v03_driver.mjs')],input=json.dumps({'events':items}),text=True,capture_output=True,timeout=180)
    if legacy.returncode:raise ValueError('Frozen v0.3 sampler failed; check the supported Node version')
    v03=json.loads(legacy.stdout)
    config=PedConfig(seed=seed,execution_mode='RETROSPECTIVE_REPLAY')
    ped=surface(items,{e['id'] for e in items},generated_at,config,generated_at)
    out=[]
    for candidate in v03['candidates']:
        key=sha256({'version':'music-episode-surfacing-0.3.0','candidate':candidate})
        out.append({'record_id':'native-'+key,'candidate_key':key,'arm':'V0_3','algorithm_version':'music-episode-surfacing-0.3.0',
            'implementation_hash':pins['v03']['source_sha256'],'event_refs':[by_id[e]['event_key'] for e in candidate['eventIds']],
            'score':candidate['surprisal'],'reason_codes':candidate['reasonCodes'],'prediction_as_of_at':None,'training_coverage_end_at':None,'target_outcome_at':None,
            'native_payload':{'candidate':candidate,'native_selection':next((x for x in v03['selectionAudit'] if x['episodeId']==candidate['id']),None),
                              'parameters':{'analysis_scope':'ALL_FROZEN_HISTORY','maxEpisodes':10}}})
    events_by_key={e['key']:e for e in ped['events']};forecasts={p['event_key']:p for p in ped['predictions']}
    for candidate in ped['candidates']:
        p=forecasts[candidate['anchor_key']];model=ped['models'][p['model_content_hash']]
        key=candidate['content_hash']
        out.append({'record_id':'native-'+key,'candidate_key':key,'arm':'PED','algorithm_version':ped['version'],'implementation_hash':pins['ped']['source_sha256'],
            'event_refs':[by_id[events_by_key[e]['source_id']]['event_key'] for e in candidate['event_keys']],
            'score':candidate['score'],'reason_codes':[candidate['family']],
            'prediction_as_of_at':p['prediction_as_of_at'],'training_coverage_end_at':p['training_coverage_end_at'],'target_outcome_at':events_by_key[candidate['anchor_key']]['outcome_at'],
            'native_payload':{'candidate':candidate,'forecast':{k:v for k,v in p.items() if k!='artifact_generated_at'},
                'model':{k:v for k,v in model.items() if k!='artifact_generated_at'},'generated_at':p['artifact_generated_at'],
                'native_selection':ped['decisions'][key],'parameters':asdict(config)}})
    if not include_history:
        for record in out:
            record['native_payload']={k:v for k,v in record['native_payload'].items() if k not in {'forecast','model'}}
    return out,{'legacy':v03,'ped':{k:v for k,v in ped.items() if k!='packets'},'implementation_pins':pins}
