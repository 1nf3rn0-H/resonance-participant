"""Spotify allowlist parser. Original files, paths and account/device fields are not retained."""
from datetime import datetime,timezone,timedelta
from hashlib import sha256 as byte_sha
from zipfile import ZipFile,BadZipFile
from pathlib import PurePosixPath
import io
import json
import stat
from contracts.offline_bundle.v1.canonical import loads,sha256

MAX_UPLOAD=64*1024*1024
MAX_EXPANDED=128*1024*1024
MAX_EVENTS=10000
# These scientific fields have no legal slot in the frozen M0 record schema.
# Reject enriched histories rather than silently freezing an incomplete dataset.
UNSUPPORTED_EVIDENCE={'duration_ms','track_duration_ms','trackDurationMs','context_uri',
    'playlist_uri','playlist_name','playback_source','manual_selection'}

def timestamp(raw,legacy=False):
    if not isinstance(raw,str) or len(raw)>100:raise ValueError('Missing or invalid provider timestamp')
    try:
        t=datetime.fromisoformat(raw.replace('Z','+00:00'))
        if t.tzinfo is None:
            if not legacy:raise ValueError('Extended-history timestamps must include a timezone')
            t=t.replace(tzinfo=timezone.utc)
        return t.astimezone(timezone.utc)
    except ValueError as error:raise ValueError('Invalid provider playback timestamp') from error

def stamp(t):return t.isoformat(timespec='milliseconds').replace('+00:00','Z')

def files(payload,is_zip):
    if len(payload)>MAX_UPLOAD:raise ValueError('History upload exceeds 64 MiB')
    if not is_zip:return [payload]
    try:
        with ZipFile(io.BytesIO(payload)) as z:
            entries=z.infolist()
            if len(entries)>2000 or sum(x.file_size for x in entries)>MAX_EXPANDED:raise ValueError('History ZIP exceeds expansion limits')
            output=[];names=set()
            for x in entries:
                path=PurePosixPath(x.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in x.filename or x.filename in names or stat.S_ISLNK(x.external_attr>>16) or x.flag_bits&1:raise ValueError('Unsafe history ZIP')
                names.add(x.filename)
                if x.is_dir() or not x.filename.lower().endswith('.json'):continue
                # Ignore unrelated account metadata instead of parsing or retaining it.
                name=path.name.lower()
                if not any(word in name for word in ('streaming','audio','history')):continue
                if x.file_size>MAX_UPLOAD or x.file_size>max(1024,x.compress_size)*200:raise ValueError('History ZIP expansion ratio too large')
                with z.open(x) as source:data=source.read(MAX_UPLOAD+1)
                if len(data)>MAX_UPLOAD:raise ValueError('History file exceeds limits')
                output.append(data)
            if not output:raise ValueError('ZIP has no Spotify streaming history JSON files')
            return output
    except BadZipFile as error:raise ValueError('Invalid history ZIP') from error

def opportunity(reason_start,shuffle):
    # Describe the provider action/mode, never a participant's intent or preference.
    # Frozen sampler adapters do not consume this capture-only field.
    if reason_start in {'clickrow','playbtn','fwdbtn','backbtn'}:return 'MANUAL'
    if shuffle is True:return 'SHUFFLE'
    return 'UNKNOWN'

def parse(payload,is_zip,imported_at,start=None,end=None,capture_h6=False):
    if start and end and start>end:raise ValueError('History end date precedes start')
    if start:datetime.strptime(start,'%Y-%m-%d')
    if end:datetime.strptime(end,'%Y-%m-%d')
    h6_events=[]
    imports=[];tracks={};events=[];seen_fingerprints=set();seen_files=set();skipped=0;duplicates=0
    for raw in sorted(files(payload,is_zip),key=lambda b:byte_sha(b).hexdigest()):
        file_hash=byte_sha(raw).hexdigest()
        if file_hash in seen_files:duplicates+=1;continue
        seen_files.add(file_hash)
        try:rows=loads(raw)
        except (ValueError,RecursionError) as error:raise ValueError('History must be valid UTF-8 JSON with no duplicate keys') from error
        if not isinstance(rows,list):raise ValueError('Spotify streaming history must be a JSON array')
        selected=[]
        for ordinal,row in enumerate(rows):
            if not isinstance(row,dict):raise ValueError('Invalid listening record')
            title=row.get('master_metadata_track_name',row.get('trackName'));artist=row.get('master_metadata_album_artist_name',row.get('artistName'))
            if title is None or artist is None:skipped+=1;continue
            if not isinstance(title,str) or not isinstance(artist,str) or not title or len(title)>1000 or len(artist)>1000:raise ValueError('Invalid recording metadata')
            legacy='ts' not in row
            raw_time=row.get('endTime') if legacy else row.get('ts')
            date=timestamp(raw_time,legacy);occurred=stamp(date)
            if start and occurred[:10]<start or end and occurred[:10]>end:continue
            if occurred>imported_at:raise ValueError('Playback appears after actual import time; check your device clock')
            if not capture_h6 and any(k in row and row[k] is not None and row[k]!='' for k in UNSUPPORTED_EVIDENCE):
                raise ValueError('This history includes track duration or playback context that the current study format cannot preserve. Import cancelled without saving. Keep your original file and ask your researcher for a compatible study release.')
            played=row.get('msPlayed') if legacy else row.get('ms_played')
            if type(played) is not int or not 0<=played<=86400000:raise ValueError('Invalid ms_played')
            skipped_value=row.get('skipped')
            if skipped_value is not None and type(skipped_value) is not bool:raise ValueError('Skip state must be true, false or unknown')
            shuffle=row.get('shuffle')
            if shuffle is not None and type(shuffle) is not bool:raise ValueError('Invalid shuffle state')
            provider_ref=row.get('spotify_track_uri') or 'spotify-metadata:'+sha256({'title':title,'artist':artist})
            if not isinstance(provider_ref,str) or len(provider_ref)>512 or not provider_ref.startswith(('spotify:track:','spotify-metadata:')):raise ValueError('Invalid Spotify recording reference')
            track_id='track-'+sha256(provider_ref)
            tracks[track_id]={'record_id':track_id,'provider_ref':provider_ref,'title':title,'artist':artist}
            key=sha256({'source_file_sha256':file_hash,'source_ordinal':ordinal})
            def reason(name):
                value=row.get(name)
                if value is not None and (not isinstance(value,str) or len(value)>100):raise ValueError('Invalid navigation reason')
                return value
            event={'record_id':'event-'+key,'event_key':key,'import_id':'import-'+file_hash,'track_id':track_id,'source_ordinal':ordinal,
                'provider_timestamp_raw':raw_time,'provider_timestamp_semantics':'END','occurred_at':occurred,
                'observed_start_at':None,'observed_end_at':occurred,'estimated_start_at':stamp(date-timedelta(milliseconds=played)),
                'estimated_end_at':None,'time_estimation_method':'PROVIDER_END_MINUS_PLAYED_UNCERTAIN','time_quality':'ESTIMATED',
                'source_available_at':imported_at,'played_ms':played,'skipped':skipped_value,'reason_start':reason('reason_start'),'reason_end':reason('reason_end'),
                'shuffle':shuffle,'opportunity':opportunity(row.get('reason_start'),shuffle)}
            fingerprint=sha256({k:v for k,v in event.items() if k not in {'record_id','event_key','import_id','source_ordinal','source_available_at'}})
            evidence=None
            if capture_h6:
                from contracts.h6_bundle.v1.capture import event_evidence,SCHEMA
                from jsonschema import Draft202012Validator
                evidence=event_evidence(row,event,file_hash)
                native_schema=SCHEMA['properties']['extension']['properties']['event_evidence']['items']['properties']['native']
                if not Draft202012Validator(native_schema).is_valid(evidence['native']):raise ValueError('Invalid H6 provider evidence')
                fingerprint=sha256({'core':fingerprint,'native':evidence['native']})
            if fingerprint in seen_fingerprints:duplicates+=1;continue
            seen_fingerprints.add(fingerprint);selected.append(event)
            if evidence:h6_events.append(evidence)
        if selected:
            imports.append({'record_id':'import-'+file_hash,'provider':'SPOTIFY','source_file_sha256':file_hash,'parser_version':'spotify-h6-1.0.0' if capture_h6 else 'spotify-offline-1.0.1',
                'actual_imported_at':imported_at,'coverage_start_at':min(e['occurred_at'] for e in selected),'coverage_end_at':max(e['occurred_at'] for e in selected)})
            events.extend(selected)
    if not events:raise ValueError('No music plays in this history/date range')
    if len(events)>MAX_EVENTS:raise ValueError('This pilot supports 10,000 plays per study. Choose a smaller historical date range before importing.')
    if len(events)<3:raise ValueError('At least three music plays are needed')
    used={e['track_id'] for e in events}
    events.sort(key=lambda e:(e['occurred_at'],e['source_ordinal'],e['event_key']))
    return {'history_imports':imports,'tracks':[t for key,t in sorted(tracks.items()) if key in used],'events':events,**({'h6_event_evidence':h6_events} if capture_h6 else {}),'summary':{'music_events':len(events),'non_music_ignored':skipped,'duplicates_ignored':duplicates}}
