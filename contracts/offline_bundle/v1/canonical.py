"""RFC 8785, strict I-JSON parsing and explicitly separate hash domains."""
from __future__ import annotations
import hashlib
import json
import math
import rfc8785

MAX_SAFE_INTEGER=9007199254740991


def _pairs(items):
    result={}
    for key,value in items:
        if key in result: raise ValueError('Duplicate JSON property')
        result[key]=value
    return result


def _constant(value): raise ValueError('Non-finite JSON number')


def _integer(value):
    parsed=int(value)
    # Exact identifiers/durations use safe integer range. RFC numeric vectors may use float tokens.
    return float(parsed) if abs(parsed)>MAX_SAFE_INTEGER else parsed


def loads(raw):
    try:
        value=json.loads(raw,object_pairs_hook=_pairs,parse_constant=_constant,parse_int=_integer)
        dumps(value)
        return value
    except (UnicodeError,TypeError,ValueError,rfc8785.CanonicalizationError) as error:
        raise ValueError('Invalid I-JSON: '+str(error)) from error


def dumps(value):
    return rfc8785.dumps(value)


def sha256(value): return hashlib.sha256(dumps(value)).hexdigest()


def record_hash(record):
    """Exact content integrity; exclude ONLY this record's containing record_hash."""
    return sha256({k:v for k,v in record.items() if k!='record_hash'})


def integrity_hash(bundle):
    """Exact logical bundle integrity, including all audit timestamps and source identities."""
    return sha256({**bundle,'manifest':{k:v for k,v in bundle['manifest'].items() if k!='integrity_hash'}})


SECTION_ORDER=('consent','history_imports','tracks','events','episode_snapshots','eligible_windows','native_candidates',
               'mappings','assignments','prompt_packets','submissions','locks','prompt_events')
VOLATILE={'record_id','record_hash','created_at','generated_at','actual_imported_at','received_at'}
REFERENCE_FIELDS={'import_id','track_id','episode_id','window_id','assignment_id','prompt_packet_id','submission_id','neutral_submission_id',
                  'event_ids','native_candidate_ids','frame_window_ids','winning_window_ids','prior_assignment_ids','lock_id'}


def scientific_hash(bundle):
    """Scientific identity v1: resolve source IDs to parent semantic keys, retain meaningful clocks.

    Top-level record sets are unordered. Ordered membership/question/answer arrays stay ordered.
    Actual import/receipt/creation audit clocks belong to exact integrity, not this projection.
    """
    identities={};parts={}
    def project(value,key=None):
        if isinstance(value,dict): return {k:project(v,k) for k,v in value.items() if k not in VOLATILE}
        if isinstance(value,list): return [project(v,key) for v in value]
        if key in REFERENCE_FIELDS and isinstance(value,str):
            if value not in identities: raise ValueError('Unknown or forward scientific reference: '+value)
            return identities[value]
        return value
    for section in SECTION_ORDER:
        records=[bundle['consent']] if section=='consent' else bundle.get(section,[])
        projected=[]
        for record in records:
            payload=project(record)
            key=sha256({'domain':'resonance-record-science-v1','type':section,'content':payload})
            identities[record['record_id']]=key;projected.append(payload)
        parts[section]=sorted(projected,key=lambda item:dumps(item))
    manifest=bundle['manifest']
    return sha256({'domain':'resonance-bundle-science-v1','schema_version':manifest['schema_version'],
        'study_id':manifest['study_id'],'participant_pseudonym':manifest['participant_pseudonym'],
        'protocol_version':manifest['protocol_version'],'trial_type':manifest['trial_type'],
        'question_bank_hash':manifest['question_bank_hash'],'sampling_config_hash':manifest['sampling_config_hash'],
        'records':parts,'provenance':bundle['provenance']})


def seal(bundle):
    """Producer utility; never called by the importer to 'repair' participant records."""
    for section in SECTION_ORDER:
        records=[bundle['consent']] if section=='consent' else bundle.get(section,[])
        for record in records: record['record_hash']=record_hash(record)
    bundle['manifest']['content_hash']=scientific_hash(bundle)
    bundle['manifest']['integrity_hash']=integrity_hash(bundle)
    return bundle
