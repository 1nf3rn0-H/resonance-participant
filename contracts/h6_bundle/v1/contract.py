"""Strict H6 supplement validation over an independently valid, unchanged M0 core."""
from copy import deepcopy
from pathlib import Path
from jsonschema import Draft202012Validator
from contracts.offline_bundle.v1.canonical import loads,dumps,sha256,record_hash
from contracts.offline_bundle.v1.validate import validate as validate_core,records as core_records,CHECKER
from .instrument import BANK,POLICY,select,audit,check
ROOT=Path(__file__).parent
PROTOCOL='offline-retro-h6-1.0.0-pilot'
CONSENT=loads((ROOT/'consent.json').read_bytes())
SECTIONS=('event_evidence','sessionization_runs','sessions','followup_selections','followup_exposures','followup_submissions','followup_completions')
NOTICE='H6 is an observational retrospective pilot, not preregistered. Only authorized sections are included. After transfer, local deletion cannot remove researcher-held copies or backups; contact the researcher for withdrawal.'
def schema_path():return ROOT/'schema.json'
VALIDATOR=Draft202012Validator(loads(schema_path().read_bytes()),format_checker=CHECKER)
def require(value,code):
    if not value:raise ValueError('H6:'+code)
def records(bundle):
    yield 'h6_consent',bundle['extension']['consent']
    for section in SECTIONS:
        for record in bundle['extension'][section]:yield 'h6_'+section,record

def integrity_hash(bundle):return sha256({**bundle,'manifest':{k:v for k,v in bundle['manifest'].items() if k!='integrity_hash'}})
def content_hash(bundle):
    core=bundle['core'];ext=bundle['extension'];identities={r['record_id']:r['event_key'] for r in core['events']}
    assignments={r['record_id']:r for r in core['assignments']};windows={r['record_id']:r for r in core['eligible_windows']}
    for p in core['prompt_packets']:
        a=assignments[p['assignment_id']];identities[p['record_id']]=sha256({'window':windows[a['window_id']]['window_key'],'day':a['collection_day'],'slot':a['slot_ordinal']})
    for lock in core['locks']:identities[lock['record_id']]=sha256([identities[lock['prompt_packet_id']],lock['answer_set_hash']])
    for r in ext['sessionization_runs']:identities[r['record_id']]=sha256([r['input_event_refs'],r['parameters']])
    for r in ext['followup_selections']:identities[r['record_id']]=sha256([identities[r['prompt_packet_id']],r['policy_version']])
    refs={'event_id','prompt_packet_id','neutral_lock_id','run_id','selection_id'}
    def project(value,key=None):
        if isinstance(value,dict):return {k:project(v,k) for k,v in value.items() if k not in {'record_id','record_hash','created_at','generated_at','artifact_generated_at','input_hash'}}
        if isinstance(value,list):return [project(v,key) for v in value]
        return identities.get(value,value) if key in refs and isinstance(value,str) else value
    sections={name:sorted((project(r) for r in ext[name]),key=sha256) for name in SECTIONS}
    return sha256({'domain':'resonance-h6-scientific-1.0.0','core_content_hash':core['manifest']['content_hash'],'consent':project(ext['consent']),'availability':ext['availability'],'sections':sections})
def seal(bundle):
    for _,r in records(bundle):r['record_hash']=record_hash(r)
    bundle['manifest']['core_integrity_hash']=bundle['core']['manifest']['integrity_hash']
    bundle['manifest']['content_hash']=content_hash(bundle);bundle['manifest']['integrity_hash']=integrity_hash(bundle)
    return bundle

def preview_sections(bundle):
    return [{'name':name,'count':1 if name=='consent' else len(bundle['extension'][name]),'records_hash':sha256(bundle['extension'][name])} for name in ('consent',*SECTIONS)]

def availability(grants):
    return {'event_evidence':'INCLUDED' if grants['share_event_evidence'] else 'WITHHELD','playlist_context':'INCLUDED' if grants['share_playlist_context'] else 'WITHHELD',
        'followup_evidence':'INCLUDED' if grants['share_followup_evidence'] else 'WITHHELD','unavailable_analyses':[
        *([] if grants['share_event_evidence'] else ['EXTENDED_EVENT_AND_SESSION_COMPARISONS']),
        *([] if grants['share_playlist_context'] else ['PLAYLIST_CONTEXT_COMPARISONS']),
        *([] if grants['share_followup_evidence'] else ['PARTICIPANT_CONTEXT_AND_MOMENT_REPORTS']),'PRECISE_LYRIC_EXPOSURE']}

def _validate(bundle):
    from .release import verify_release
    from .capture import sessions,normalized,PLAYLIST_FIELDS
    sha256(bundle);error=next(VALIDATOR.iter_errors(bundle),None)
    if error:raise ValueError('H6:SCHEMA:'+('/'.join(map(str,error.absolute_path)) or 'root'))
    core=bundle['core'];report=validate_core(core);ext=bundle['extension'];m=bundle['manifest'];consent=ext['consent'];grants=consent['grants']
    require(m['contract_release_hash']==verify_release(),'RELEASE');require(m['question_bank_hash']==sha256(BANK),'BANK')
    require(consent['form_hash']==sha256(CONSENT),'CONSENT_FORM');require(m['bundle_id']==core['manifest']['bundle_id'],'BUNDLE_ID')
    require(m['core_integrity_hash']==core['manifest']['integrity_hash'],'CORE_HASH');require(m['content_hash']==content_hash(bundle),'CONTENT_HASH');require(m['integrity_hash']==integrity_hash(bundle),'INTEGRITY')
    all_records=list(records(bundle));ids={r['record_id'] for _,r in all_records}
    require(len(ids)==len(all_records) and not ids&{r['record_id'] for _,r in core_records(core)} and m['bundle_id'] not in ids|{r['record_id'] for _,r in core_records(core)},'DUPLICATE_ID')
    require(all(record_hash(r)==r['record_hash'] for _,r in all_records),'RECORD_HASH')
    require(len(all_records)<=60000,'RECORD_BUDGET')
    require(ext['availability']==availability(grants),'AVAILABILITY')
    require(not grants['share_event_evidence'] or core['manifest']['export_scope']=='HISTORY_AND_RESPONSES','HISTORY_SCOPE')
    require(not grants['share_playlist_context'] or grants['share_event_evidence'],'PLAYLIST_SCOPE')
    require(consent['accepted_at']<=core['provenance']['sampling_cutoff_at'] and all(consent['accepted_at']<=i['actual_imported_at'] for i in core['history_imports']),'CONSENT_AFTER_CAPTURE')
    if not grants['share_event_evidence']:require(not any(ext[k] for k in ['event_evidence','sessionization_runs','sessions']),'WITHHELD_EVENTS_PRESENT')
    else:
        require(len(ext['event_evidence'])==len(core['events']),'EVENT_COVERAGE')
        events={e['record_id']:e for e in core['events']};imports={i['record_id']:i for i in core['history_imports']};seen=set()
        for r in ext['event_evidence']:
            require(r['event_id'] in events and r['event_id'] not in seen,'EVENT_REFERENCE');seen.add(r['event_id']);e=events[r['event_id']]
            require(r['event_key']==e['event_key'] and r['source_ordinal']==e['source_ordinal'] and r['source_file_sha256']==imports[e['import_id']]['source_file_sha256'],'SOURCE_IDENTITY')
            require(r['normalized']==normalized(r['native'],e),'NORMALIZATION')
            for field,key in [('skipped','skipped'),('shuffle','shuffle'),('reason_start','reason_start'),('reason_end','reason_end')]:
                require(r['native'].get(field)==e[key],'SOURCE_VALUE')
            require(any(field in r['native'] for field in ['ms_played','msPlayed']) and any(field in r['native'] for field in ['ts','endTime']),'MISSING_NATIVE_SOURCE_FIELDS')
            for field in ['ms_played','msPlayed']:
                if field in r['native']:require(r['native'][field]==e['played_ms'],'PLAYED_VALUE')
            for field in ['ts','endTime']:
                if field in r['native']:require(r['native'][field]==e['provider_timestamp_raw'],'TIMESTAMP_RAW')
            require(set(r['withheld_native_fields'])<=PLAYLIST_FIELDS,'REDACTION_FIELDS')
            if not grants['share_playlist_context']:require(not PLAYLIST_FIELDS&set(r['native']),'WITHHELD_PLAYLIST_PRESENT')
            else:require(not r['withheld_native_fields'],'UNDECLARED_REDACTION')
        require(len(ext['sessionization_runs'])==1,'SESSION_RUN')
        generated_at=ext['sessionization_runs'][0]['artifact_generated_at']
        require(core['provenance']['sampling_cutoff_at']<=generated_at<=core['manifest']['generated_at'],'SESSION_ARTIFACT_TIME')
        run,expected=sessions(core['events'],generated_at)
        require({k:v for k,v in ext['sessionization_runs'][0].items() if k!='record_hash'}==run,'SESSION_RUN_CONTENT')
        require([{k:v for k,v in r.items() if k!='record_hash'} for r in ext['sessions']]==expected,'SESSION_MEMBERSHIP_OR_TRANSITIONS')
    question_sections=['followup_selections','followup_exposures','followup_submissions','followup_completions']
    require(all(not p['allowed_followup_question_ids'] for p in core['prompt_packets']),'LEGACY_FOLLOWUPS_ENABLED')
    require(not any(e['event_type'].startswith('FOLLOWUP_') for e in core['prompt_events']) and not any(s['stage']=='FOLLOWUP' for s in core['submissions']),'LEGACY_FOLLOWUP_EVIDENCE')
    if not grants['share_followup_evidence']:require(not any(ext[k] for k in question_sections),'WITHHELD_FOLLOWUPS_PRESENT')
    else:
        prompts={p['record_id']:p for p in core['prompt_packets']};locks={r['prompt_packet_id']:r for r in core['locks']};submissions={r['record_id']:r for r in core['submissions']}
        selections={r['prompt_packet_id']:r for r in ext['followup_selections']};completions={r['prompt_packet_id']:r for r in ext['followup_completions']}
        require(len(selections)==len(ext['followup_selections']) and len(completions)==len(ext['followup_completions']),'DUPLICATE_STAGE')
        require(set(selections)==set(locks) and set(completions)==set(locks),'FOLLOWUP_AUDIT_COVERAGE')
        require(all(r['prompt_packet_id'] in locks for k in question_sections for r in ext[k]),'PROMPT_REFERENCE')
        episodes={e['record_id']:e for e in core['episode_snapshots']};questions={q['question_id']:q for q in BANK['questions']}
        for pid,lock in locks.items():
            p=prompts[pid];neutral=submissions[lock['neutral_submission_id']];selection=selections[pid]
            require(all(r['neutral_lock_id']==lock['record_id'] for k in question_sections for r in ext[k] if r['prompt_packet_id']==pid),'LOCK_REFERENCE')
            expected=select(neutral_locked=True,recognition=neutral['answers'][0]['value'],episode_key=episodes[p['episode_id']]['episode_key'],seed=core['provenance']['sampling_seed'])
            require({k:selection[k] for k in expected}==expected,'SELECTION_REPRODUCTION')
            require(selection['sequence']>lock['sequence'] and selection['selected_at']>=lock['locked_at'],'SELECTION_BEFORE_LOCK')
            exposures=[r for r in ext['followup_exposures'] if r['prompt_packet_id']==pid];answers=[r for r in ext['followup_submissions'] if r['prompt_packet_id']==pid]
            require(len(answers)<=1,'DUPLICATE_SUBMISSION');shown=[];seq=[selection['sequence']]
            for exposure in exposures:
                q=exposure['rendered_question'];require(q['question_id'] in questions and q==questions[q['question_id']],'QUESTION_WORDING')
                require(exposure['selection_id']==selection['record_id'] and exposure['shown_at']>=selection['selected_at'] and exposure['sequence']>selection['sequence'],'EXPOSURE_TIME')
                shown.append(q['question_id']);seq.append(exposure['sequence'])
            require(shown==[q for q in expected['selected_question_ids'] if q in shown],'EXPOSURE_ORDER')
            response=answers[0] if answers else None
            if response:
                require(bool(response['answers']) and response['submitted_at']<=response['locked_at'],'RESPONSE_TIME')
                require(all(r['sequence']<response['sequence'] and r['shown_at']<=response['submitted_at'] for r in exposures),'ANSWER_BEFORE_EXPOSURE')
                seq.append(response['sequence'])
            completion=completions[pid];summary=audit(expected,shown,response['answers'] if response else [])
            require({k:completion[k] for k in summary}==summary,'COMPLETION_AUDIT')
            seq.append(completion['sequence']);require(seq==sorted(set(seq)),'FOLLOWUP_SEQUENCE')
            require(completion['completed_at']>=selection['selected_at'] and (not response or completion['completed_at']>=response['locked_at']),'COMPLETION_TIME')
            terminal=next((e for e in core['prompt_events'] if e['prompt_packet_id']==pid and e['event_type']=='COMPLETED'),None)
            require(terminal and terminal['sequence']>=completion['sequence'] and terminal['occurred_at']>=completion['completed_at'],'AFTER_TERMINAL')
    preview=bundle['export_preview'];authority=bundle['export_authorization']
    require(preview['notice']==NOTICE and preview['sections']==preview_sections(bundle),'PREVIEW')
    require(preview['core_integrity_hash']==m['core_integrity_hash'] and preview['extension_hash']==sha256(ext),'PREVIEW_CONTENT')
    require(authority['preview_hash']==sha256(preview),'PREVIEW_AUTHORIZATION')
    require(authority['recipient_fingerprint']==core['export_authorization']['recipient_fingerprint'],'RECIPIENT')
    require(authority['confirmed_at']>=preview['presented_at'] and authority['confirmed_at']>=consent['accepted_at'],'EXPORT_CONSENT_TIME')
    return {**report,'format':m['format'],'h6_schema_version':'1.0.0','protocol_version':PROTOCOL,'h6_record_count':len(all_records),'h6_availability':ext['availability']}

def wrap(core,extension,stamp):
    from .release import verify_release
    bundle={'manifest':{'format':'resonance-h6-bundle','schema_version':'1.0.0','protocol_version':PROTOCOL,'temporal_mode':'RETROSPECTIVE_REPLAY','bundle_id':core['manifest']['bundle_id'],
        'generated_at':stamp,'core_integrity_hash':core['manifest']['integrity_hash'],'contract_release_hash':verify_release(),'question_bank_hash':sha256(BANK),'content_hash':'0'*64,'integrity_hash':'0'*64},
        'core':core,'extension':extension,'export_preview':{'presented_at':stamp,'notice':NOTICE,'core_integrity_hash':core['manifest']['integrity_hash'],'extension_hash':sha256(extension),'sections':[]},
        'export_authorization':{'explicitly_confirmed':core['export_authorization']['explicitly_confirmed'],'confirmed_at':core['export_authorization']['confirmed_at'],
            'preview_hash':'0'*64,'recipient_fingerprint':core['export_authorization']['recipient_fingerprint']}}
    return refresh(bundle)

def refresh(bundle):
    seal(bundle)
    bundle['export_preview'].update(core_integrity_hash=bundle['manifest']['core_integrity_hash'],extension_hash=sha256(bundle['extension']),sections=preview_sections(bundle))
    bundle['export_authorization']['preview_hash']=sha256(bundle['export_preview']);seal(bundle);return bundle


def validate(bundle):
    try:return _validate(bundle)
    except (KeyError,TypeError,IndexError,StopIteration,RecursionError) as error:raise ValueError('H6:INVALID_REFERENCE_OR_STRUCTURE') from error
