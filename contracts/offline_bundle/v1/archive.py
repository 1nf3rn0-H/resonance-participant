"""Portable, bounded offline ZIP codec. No extraction, execution or network access."""
from __future__ import annotations
import hashlib
import io
import stat
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile
from .canonical import dumps,loads
from .validate import validate

MAX_ARCHIVE=16*1024*1024
MAX_EXPANDED=32*1024*1024
MAX_FILE=8*1024*1024
MAX_LINE=1024*1024
MAX_RECORDS=100000
SINGLES={'manifest':'manifest.json','consent':'consent/record.json','provenance':'provenance/input_manifest.json',
         'export_preview':'export/preview.json','export_authorization':'export/authorization.json'}
LINES={'history_imports':'ingestion/imports.jsonl','tracks':'ingestion/tracks.jsonl','events':'ingestion/events.jsonl',
       'episode_snapshots':'sampling/episode_snapshots.jsonl','eligible_windows':'sampling/eligible_windows.jsonl',
       'native_candidates':'sampling/native_candidates.jsonl','mappings':'sampling/mappings.jsonl','assignments':'sampling/assignments.jsonl',
       'prompt_packets':'prompts/prompt_packets.jsonl','prompt_events':'prompts/prompt_events.jsonl','submissions':'prompts/submissions.jsonl','locks':'prompts/locks.jsonl'}
HISTORY={'history_imports','tracks','events'}

def encode(bundle):
    validate(bundle)
    files={path:dumps(bundle[key])+b'\n' for key,path in SINGLES.items()}
    for key,path in LINES.items():
        if key in HISTORY and bundle['manifest']['export_scope']=='RESPONSES_ONLY':continue
        files[path]=b''.join(dumps(row)+b'\n' for row in bundle[key])
    files['checksums.json']=dumps({'algorithm':'SHA-256','files':{p:hashlib.sha256(data).hexdigest() for p,data in files.items()}})+b'\n'
    result=io.BytesIO()
    with ZipFile(result,'w',compression=ZIP_DEFLATED) as archive:
        for name,data in sorted(files.items()): archive.writestr(name,data)
    return result.getvalue()


def decode(payload):
    if len(payload)>MAX_ARCHIVE:raise ValueError('ARCHIVE_SIZE')
    try:
        with ZipFile(io.BytesIO(payload)) as archive:
            entries=archive.infolist();names=[entry.filename for entry in entries]
            allowed=set(SINGLES.values())|set(LINES.values())|{'checksums.json'}
            if len(names)!=len(set(names)):raise ValueError('DUPLICATE_ARCHIVE_ENTRY')
            if not set(names)<=allowed:raise ValueError('UNEXPECTED_ARCHIVE_PATH')
            if sum(e.file_size for e in entries)>MAX_EXPANDED:raise ValueError('ARCHIVE_EXPANSION_LIMIT')
            data={}
            for entry in entries:
                if entry.flag_bits&1 or stat.S_ISLNK(entry.external_attr>>16):raise ValueError('ENCRYPTED_ZIP_OR_SYMLINK')
                if entry.file_size>MAX_FILE or entry.file_size>max(1024,entry.compress_size)*200:raise ValueError('ARCHIVE_COMPRESSION_LIMIT')
                with archive.open(entry) as handle: content=handle.read(MAX_FILE+1)
                if len(content)!=entry.file_size or len(content)>MAX_FILE:raise ValueError('ARCHIVE_FILE_SIZE')
                data[entry.filename]=content
            if 'checksums.json' not in data:raise ValueError('MISSING_CHECKSUMS')
            checksums=loads(data.pop('checksums.json'))
            if checksums!={'algorithm':'SHA-256','files':{name:hashlib.sha256(value).hexdigest() for name,value in data.items()}}:
                raise ValueError('ARCHIVE_CHECKSUMS')
            if not set(SINGLES.values())<=data.keys():raise ValueError('MISSING_ARCHIVE_FILE')
            bundle={key:loads(data[path]) for key,path in SINGLES.items()}
            history=bundle['manifest'].get('export_scope')=='HISTORY_AND_RESPONSES'
            expected=set(SINGLES.values())|{path for key,path in LINES.items() if history or key not in HISTORY}
            if set(data)!=expected:raise ValueError('ARCHIVE_SCOPE_OR_MISSING_FILE')
            for key,path in LINES.items():
                if path not in data:bundle[key]=[];continue
                rows=data[path].splitlines()
                if len(rows)>MAX_RECORDS or any(len(line)>MAX_LINE or not line for line in rows):raise ValueError('JSONL_LIMIT')
                bundle[key]=[loads(line) for line in rows]
            validate(bundle)
            return bundle
    except (BadZipFile,RuntimeError,KeyError,RecursionError,UnicodeError) as error:
        raise ValueError('INVALID_ARCHIVE') from error
