"""Allowlisted provider evidence and observed session membership; no inferred motives."""
from datetime import datetime
from .contract import schema_path
from contracts.offline_bundle.v1.canonical import sha256
import json
from jsonschema import Draft202012Validator
SCHEMA=json.loads(schema_path().read_text())
# This allowlist is executable in both producer and receiver.
NATIVE_FIELDS=set(SCHEMA['properties']['extension']['properties']['event_evidence']['items']['properties']['native']['properties'])
PLAYLIST_FIELDS={'context_uri','playlist_uri','playlist_name'}
PARAMETERS={'gap_seconds':1800,'clock_basis':'PROVIDER_OUTCOME_TIME','order':['occurred_at','source_ordinal','event_key']}

def normalized(native,event):
    durations={native[k] for k in ('duration_ms','track_duration_ms','trackDurationMs') if native.get(k) is not None}
    return {'recording_duration_ms':next(iter(durations)) if len(durations)==1 else None,
        'duration_quality':'PROVIDER_SUPPLIED' if len(durations)==1 else 'CONFLICTING_SOURCE_VALUES' if durations else 'UNKNOWN',
        'skip_outcome':'SKIPPED' if event['skipped'] is True else 'RETAINED' if event['skipped'] is False else 'UNKNOWN',
        'termination_kind':'PROVIDER_NAVIGATION' if event['reason_end'] in {'fwdbtn','backbtn'} else 'PROVIDER_TRACK_DONE' if event['reason_end']=='trackdone' else 'OTHER_PROVIDER_REASON' if event['reason_end'] is not None else 'UNKNOWN',
        'playback_source':native.get('playback_source'),'manual_selection':native.get('manual_selection'),'position_evidence':'NOT_ESTABLISHED'}

def event_evidence(row,event,file_hash):
    native={key:value for key,value in row.items() if key in NATIVE_FIELDS}
    native_schema=SCHEMA['properties']['extension']['properties']['event_evidence']['items']['properties']['native']
    if not Draft202012Validator(native_schema).is_valid(native):raise ValueError('Invalid H6 native evidence')
    return {'record_id':'h6event-'+event['event_key'],'event_id':event['record_id'],'event_key':event['event_key'],
        'source_file_sha256':file_hash,'source_ordinal':event['source_ordinal'],'parser_version':'spotify-h6-1.0.0',
        'native':native,'normalized':normalized(native,event),'withheld_native_fields':[]}

def dt(value):return datetime.fromisoformat(value.replace('Z','+00:00'))

def sessions(events):
    ordered=sorted(events,key=lambda e:(e['occurred_at'],e['source_ordinal'],e['event_key']))
    refs=[e['event_key'] for e in ordered];run_id='h6run-'+sha256({'refs':refs,'parameters':PARAMETERS})
    run={'record_id':run_id,'version':'participant-sessionizer-1.0.0','input_event_refs':refs,'input_hash':sha256(events),'parameters':PARAMETERS}
    groups=[]
    for event in ordered:
        if not groups or (dt(event['occurred_at'])-dt(groups[-1][-1]['occurred_at'])).total_seconds()>1800:groups.append([])
        groups[-1].append(event)
    output=[]
    for group in groups:
        members=[e['event_key'] for e in group];key=sha256(members)
        transitions=[{'from_event_ref':a['event_key'],'to_event_ref':b['event_key'],
            'gap_ms':round((dt(b['occurred_at'])-dt(a['occurred_at'])).total_seconds()*1000),
            'order_quality':'DETERMINISTIC_TIE_UNCERTAIN' if a['occurred_at']==b['occurred_at'] else 'PROVIDER_TIME_ORDER'} for a,b in zip(group,group[1:])]
        output.append({'record_id':'h6session-'+key,'run_id':run_id,'session_key':key,'event_refs':members,'transitions':transitions,'time_quality':'PROVIDER_TIMES_WITH_UNCERTAIN_STARTS'})
    return run,output
