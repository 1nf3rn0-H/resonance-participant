"""Normative shared validator. Vendored unchanged by both applications; no private imports/network."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
from datetime import datetime,date
from jsonschema import Draft202012Validator, FormatChecker
from .canonical import loads,sha256,record_hash,integrity_hash,scientific_hash,SECTION_ORDER
from .sampling import eligible_universe,mapped_scores,allocate_slot,ARMS

ROOT=Path(__file__).resolve().parent
CONSENT_FORM=loads((ROOT/'consent.json').read_bytes())
QUESTIONS=loads((ROOT/'questions.json').read_bytes())
SAMPLING=loads((ROOT/'sampling.json').read_bytes())
SCHEMA=loads((ROOT/'schemas/bundle.schema.json').read_bytes())
CHECKER=FormatChecker()
@CHECKER.checks('date-time')
def utc_milliseconds(value):
    if not isinstance(value,str):return True
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).isoformat(timespec='milliseconds').replace('+00:00','Z')==value
    except ValueError:return False
@CHECKER.checks('date')
def calendar_date(value):
    if not isinstance(value,str):return True
    try:return date.fromisoformat(value).isoformat()==value
    except ValueError:return False
VALIDATOR=Draft202012Validator(SCHEMA,format_checker=CHECKER)
NOTICE='After transfer, deleting data on this device does not delete researcher-held bundles, exports or backups. Contact the study researcher to request withdrawal. Backup retention and already disseminated anonymous results may limit deletion.'


def fail(code): raise ValueError(code)
def require(condition,code):
    if not condition: fail(code)


def records(bundle):
    for section in SECTION_ORDER:
        for record in [bundle['consent']] if section=='consent' else bundle.get(section,[]): yield section,record


def preview_sections(bundle):
    return [{'name':section,'count':len(items),'records_hash':sha256(items)} for section,items in (
        [('consent',[bundle['consent']])]+[(name,bundle[name]) for name in SECTION_ORDER if name!='consent']+[('provenance',[bundle['provenance']])])]


def validate(bundle):
    # Validate JCS compatibility even when caller supplies an in-memory object.
    try: sha256(bundle)
    except Exception as error: raise ValueError('INVALID_I_JSON') from error
    error=next(VALIDATOR.iter_errors(bundle),None)
    if error: fail('SCHEMA:'+('/'.join(map(str,error.absolute_path)) or 'root'))
    pending=[bundle]
    prohibited={'ip_address','ip','email','account_email','username','access_token','refresh_token','device_id','gps','original_file_path','private_key'}
    while pending:
        value=pending.pop()
        if isinstance(value,dict):
            require(not(prohibited & {k.lower() for k in value}),'PROHIBITED_FIELD')
            pending.extend(value.values())
        elif isinstance(value,list):pending.extend(value)
    m=bundle['manifest'];consent=bundle['consent'];provenance=bundle['provenance']
    require(consent['form_hash']==sha256(CONSENT_FORM),'CONSENT_FORM_HASH')
    require(provenance['seed_commitment']==sha256(provenance['sampling_seed']),'SEED_COMMITMENT')
    require(m['question_bank_hash']==sha256(QUESTIONS),'QUESTION_BANK_HASH')
    require(m['sampling_config_hash']==sha256(SAMPLING),'SAMPLING_CONFIG_HASH')
    all_records=list(records(bundle))
    require(len(all_records)<=250000,'RECORD_BUDGET')
    require(sum(len(r.get('event_refs',[]))+len(r.get('frame_window_ids',[])) for _,r in all_records)<=500000,'MEMBERSHIP_BUDGET')
    by_id={r['record_id']:(kind,r) for kind,r in all_records}
    require(len(by_id)==len(all_records),'DUPLICATE_RECORD_ID')
    require(all(record_hash(r)==r['record_hash'] for _,r in all_records),'RECORD_HASH')
    require(integrity_hash(bundle)==m['integrity_hash'],'BUNDLE_INTEGRITY_HASH')
    require(scientific_hash(bundle)==m['content_hash'],'SCIENTIFIC_CONTENT_HASH')
    def ref(key,kind):
        require(key in by_id and by_id[key][0]==kind,'INVALID_REFERENCE:'+kind)
        return by_id[key][1]
    included=m['export_scope']=='HISTORY_AND_RESPONSES'
    require(consent['grants']['share_listening_history']==included,'CONSENT_HISTORY_SCOPE')
    require((provenance['source_data_status']=='INCLUDED')==included,'SOURCE_STATUS')
    require(included or not (bundle['events'] or bundle['tracks'] or bundle['history_imports']),'WITHHELD_HISTORY_PRESENT')
    require(not included or bool(bundle['events'] and bundle['history_imports'] and bundle['tracks']),'DECLARED_HISTORY_MISSING')
    require(provenance['source_coverage_start_at']<=provenance['source_coverage_end_at']<=provenance['sampling_cutoff_at'],'SOURCE_COVERAGE')
    import_ordinals=set();event_keys=set()
    for item in bundle['history_imports']:
        require(item['coverage_start_at']<=item['coverage_end_at'],'IMPORT_COVERAGE')
        require(item['actual_imported_at']<=provenance['sampling_cutoff_at'],'IMPORT_AFTER_SAMPLING')
    for event in bundle['events']:
        batch=ref(event['import_id'],'history_imports');ref(event['track_id'],'tracks')
        key=(event['import_id'],event['source_ordinal'])
        require(key not in import_ordinals and event['event_key'] not in event_keys,'DUPLICATE_SOURCE_EVENT');import_ordinals.add(key);event_keys.add(event['event_key'])
        require(event['event_key']==sha256({'source_file_sha256':batch['source_file_sha256'],'source_ordinal':event['source_ordinal']}),'EVENT_KEY')
        require(batch['coverage_start_at']<=event['occurred_at']<=batch['coverage_end_at'],'EVENT_COVERAGE')
        require(provenance['source_coverage_start_at']<=event['occurred_at']<=provenance['source_coverage_end_at'],'EVENT_OUTSIDE_FROZEN_INPUT')
        require(event['source_available_at']<=provenance['sampling_cutoff_at'],'SOURCE_UNAVAILABLE_AT_SELECTION')
        require(not(event['time_quality']=='OBSERVED' and not(event['observed_start_at'] or event['observed_end_at'])),'FABRICATED_OBSERVED_CLOCK')
        require(not(event['time_quality']=='ESTIMATED' and not(event['estimated_start_at'] or event['estimated_end_at'])),'MISSING_TIME_ESTIMATE')
        require(not(event['provider_timestamp_semantics']=='END' and event['observed_start_at'] and not event['observed_end_at']),'END_AS_START')
    episode_keys=set();window_keys=set()
    for episode in bundle['episode_snapshots']:
        require(episode['episode_key'] not in episode_keys,'DUPLICATE_EPISODE_KEY');episode_keys.add(episode['episode_key'])
        require(episode['historical_start_at']<=episode['historical_end_at']<=episode['episode_available_at'],'EPISODE_TIME')
        require(episode['historical_end_at']<=provenance['sampling_cutoff_at'],'FUTURE_EPISODE')
        require((episode['source_data_status']=='INCLUDED')==included,'EPISODE_SOURCE_STATUS')
        require(len(set(episode['event_refs']))==len(episode['event_refs']),'DUPLICATE_EVENT_MEMBERSHIP')
        if included: require(set(episode['event_refs'])<=event_keys,'UNKNOWN_EVENT_REFERENCE')
    for window in bundle['eligible_windows']:
        episode=ref(window['episode_id'],'episode_snapshots')
        require(window['window_key'] not in window_keys,'DUPLICATE_WINDOW_KEY');window_keys.add(window['window_key'])
        require(window['event_refs']==episode['event_refs'],'WINDOW_EPISODE_MEMBERSHIP')
        require(window['window_key']==sha256({'universe':'historical-disjoint-windows-1.0.0','event_refs':window['event_refs']}),'WINDOW_KEY')
    if included:
        expected=eligible_universe(bundle['events'],provenance['sampling_cutoff_at'])
        observed=[{k:w[k] for k in ('window_key','event_refs','eligibility','reasons')} for w in bundle['eligible_windows']]
        require(sorted(expected,key=lambda w:w['window_key'])==sorted(observed,key=lambda w:w['window_key']),'ELIGIBLE_UNIVERSE')
    for native in bundle['native_candidates']:
        require(native['algorithm_version']==SAMPLING['native_versions'][native['arm']],'NATIVE_VERSION')
        if native['prediction_as_of_at'] is not None:
            require(native['target_outcome_at'] is not None and native['prediction_as_of_at']<native['target_outcome_at'],'SELF_OUTCOME_LEAKAGE')
            require(native['training_coverage_end_at'] is None or native['training_coverage_end_at']<=native['prediction_as_of_at'],'FUTURE_TRAINING')
        require(native['training_coverage_end_at'] is None or native['prediction_as_of_at'] is not None,'TRAINING_WITHOUT_CUTOFF')
        if included: require(set(native['event_refs'])<=event_keys,'UNKNOWN_NATIVE_EVENT')
    scores=mapped_scores(bundle['eligible_windows'],bundle['native_candidates'])
    seen_mappings=set()
    for mapping in bundle['mappings']:
        ref(mapping['window_id'],'eligible_windows')
        key=(mapping['window_id'],mapping['arm']);require(key not in seen_mappings,'DUPLICATE_MAPPING');seen_mappings.add(key)
        require({k:mapping[k] for k in ('native_candidate_ids','mapped_score')}==scores[key[0]][key[1]],'NATIVE_MAPPING')
    require(len(seen_mappings)==len(bundle['eligible_windows'])*3,'MAPPING_DENOMINATOR')
    prior=[];occupied=set();slots=set()
    for assignment in bundle['assignments']:
        require(assignment['seed']==provenance['sampling_seed'],'SAMPLING_SEED_CHANGED')
        unit={'study_id':m['study_id'],'participant_pseudonym':m['participant_pseudonym'],'collection_day':assignment['collection_day'],'slot_ordinal':assignment['slot_ordinal']}
        slot=(assignment['collection_day'],assignment['slot_ordinal'])
        require(slot not in slots,'DUPLICATE_COLLECTION_SLOT');slots.add(slot)
        require(assignment['decision_at'][:10]==assignment['collection_day'],'COLLECTION_DATE_MISMATCH')
        require(assignment['decision_at']>=provenance['sampling_cutoff_at'],'ASSIGNMENT_BEFORE_INPUT_AVAILABLE')
        require(assignment['prior_assignment_ids']==[a['record_id'] for a in prior],'PRIOR_ASSIGNMENT_HISTORY')
        arms=assignment['available_arms'];require(arms==[a for a in ARMS if a in arms],'ARM_ORDER')
        require(len(arms)==3 or m['trial_type']=='FEASIBILITY_ONLY','UNAVAILABLE_ARM_COMPARATIVE_CLAIM')
        expected=allocate_slot(bundle['eligible_windows'],bundle['native_candidates'],assignment['seed'],unit,arms,occupied)
        require(all(assignment[k]==v for k,v in expected.items()),'ASSIGNMENT_REPRODUCTION')
        chosen=ref(assignment['window_id'],'eligible_windows');episode=ref(chosen['episode_id'],'episode_snapshots')
        require(episode['episode_available_at']<=assignment['decision_at'],'EPISODE_NOT_AVAILABLE')
        require(not occupied.intersection(chosen['event_refs']),'DUPLICATE_PROMPT_OVERLAP');occupied.update(chosen['event_refs']);prior.append(assignment)
    prompt_assignments=set();neutral_questions=QUESTIONS['neutral_questions'];followups={q['question_id']:q for q in QUESTIONS['followup_questions']}
    for packet in bundle['prompt_packets']:
        assignment=ref(packet['assignment_id'],'assignments');window=ref(assignment['window_id'],'eligible_windows');episode=ref(packet['episode_id'],'episode_snapshots')
        require(window['episode_id']==packet['episode_id'],'PROMPT_EPISODE')
        require(assignment['decision_at']<=packet['created_at']<=packet['available_at'],'PROMPT_AVAILABILITY')
        require(packet['assignment_id'] not in prompt_assignments,'DUPLICATE_ASSIGNMENT_PROMPT');prompt_assignments.add(packet['assignment_id'])
        require(packet['rendered_neutral_questions']==neutral_questions,'QUESTION_WORDING_OR_ORDER')
        require(set(packet['allowed_followup_question_ids'])<=set(followups),'UNKNOWN_FOLLOWUP_POLICY')
        context=packet['display_context']
        require(context=={'tracks':episode['display_tracks'],'historical_start_at':episode['historical_start_at'],'historical_end_at':episode['historical_end_at'],'time_quality':episode['time_quality']},'PROMPT_CONTEXT')
    submissions={};locks={};events={}
    for event in bundle['prompt_events']:
        ref(event['prompt_packet_id'],'prompt_packets');events.setdefault(event['prompt_packet_id'],[]).append(event)
    for submission in bundle['submissions']:
        packet=ref(submission['prompt_packet_id'],'prompt_packets');key=(packet['record_id'],submission['stage'])
        require(key not in submissions,'DUPLICATE_STAGE_SUBMISSION');submissions[key]=submission
        require(packet['available_at']<=submission['submitted_at']<=submission['locked_at'],'SUBMISSION_AVAILABILITY')
        questions=neutral_questions if submission['stage']=='NEUTRAL' else [followups[q] for q in packet['allowed_followup_question_ids'] if q in {a['question_id'] for a in submission['answers']}]
        require([a['question_id'] for a in submission['answers']]==[q['question_id'] for q in questions],'ANSWER_QUESTION_ORDER')
        for answer,question in zip(submission['answers'],questions):
            require(answer['question_version']==question['version'],'ANSWER_VERSION')
            require(Draft202012Validator(question['response_schema']).is_valid(answer['value']),'ANSWER_TYPE')
        if submission['stage']=='NEUTRAL':
            values={a['question_id']:a['value'] for a in submission['answers']}
            recognized=values['episode.recognition'];meaning=values['episode.meaningfulness']
            if recognized in {'NOT_RECALLED','UNSURE','NOT_APPLICABLE','DECLINED'}: require(meaning['status']==recognized and meaning['value'] is None,'UNKNOWN_IS_NOT_LOW_MEANINGFULNESS')
    for lock in bundle['locks']:
        packet=ref(lock['prompt_packet_id'],'prompt_packets');neutral=ref(lock['neutral_submission_id'],'submissions')
        require(neutral['stage']=='NEUTRAL' and neutral['prompt_packet_id']==packet['record_id'],'LOCK_OWNER')
        require(packet['record_id'] not in locks,'DUPLICATE_NEUTRAL_LOCK');locks[packet['record_id']]=lock
        require(lock['answer_set_hash']==sha256(neutral['answers']),'LOCK_HASH')
        require(lock['sequence']>=neutral['sequence'] and neutral['locked_at']==lock['locked_at'] and neutral['submitted_at']<=neutral['locked_at'],'LOCK_BEFORE_SUBMISSION')
    for packet in bundle['prompt_packets']:
        key=packet['record_id'];timeline=events.get(key,[])
        require([e['sequence'] for e in timeline]==sorted(set(e['sequence'] for e in timeline)),'AUDIT_SEQUENCE')
        require(timeline and timeline[0]['event_type']=='CREATED','MISSING_PROMPT_CREATION')
        lock=locks.get(key);neutral=submissions.get((key,'NEUTRAL'));followup=submissions.get((key,'FOLLOWUP'))
        require(bool(lock)==bool(neutral),'UNLOCKED_NEUTRAL_SUBMISSION')
        if neutral:
            require(any(e['event_type']=='OPENED' and e['sequence']<neutral['sequence'] for e in timeline),'MISSING_PRESENTATION')
            require(any(e['event_type']=='NEUTRAL_LOCKED' and e['lock_id']==lock['record_id'] and e['sequence']>=lock['sequence'] for e in timeline),'MISSING_LOCK_AUDIT')
        shown=[];state='NEW'
        for event in timeline:
            kind=event['event_type']
            require(state not in {'COMPLETED','DECLINED','EXPIRED'},'EVENT_AFTER_TERMINAL_STATE')
            if kind=='CREATED':require(state=='NEW','DUPLICATE_CREATION');state='CREATED'
            elif kind=='OPENED':require(state in {'CREATED','NEUTRAL_OPEN'},'INVALID_OPEN');state='NEUTRAL_OPEN'
            elif kind=='NEUTRAL_LOCKED':
                require(state=='NEUTRAL_OPEN' and lock is not None and event['sequence']==lock['sequence'] and event['lock_id']==lock['record_id'],'INVALID_LOCK_TRANSITION');state='NEUTRAL_LOCKED'
            elif kind=='FOLLOWUP_SHOWN':require(state in {'NEUTRAL_LOCKED','FOLLOWUP_OPEN'},'INVALID_FOLLOWUP_TRANSITION');state='FOLLOWUP_OPEN'
            elif kind=='FOLLOWUP_LOCKED':
                require(state=='FOLLOWUP_OPEN' and followup is not None and followup['sequence']<=event['sequence'],'INVALID_FOLLOWUP_LOCK');state='FOLLOWUP_LOCKED'
            elif kind=='COMPLETED':require(state in {'NEUTRAL_LOCKED','FOLLOWUP_OPEN','FOLLOWUP_LOCKED'},'INVALID_COMPLETION');state='COMPLETED'
            elif kind in {'DECLINED','EXPIRED'}:require(state in {'CREATED','NEUTRAL_OPEN'},'INVALID_DECLINE');state=kind
            if event['event_type']=='FOLLOWUP_SHOWN':
                require(lock is not None and event['sequence']>lock['sequence'],'FOLLOWUP_BEFORE_LOCK')
                require(event['lock_id']==lock['record_id'],'FOLLOWUP_LOCK_REFERENCE')
                require(event['question_id'] in packet['allowed_followup_question_ids'],'UNAUTHORIZED_FOLLOWUP')
                require(event['rendered_question']==followups[event['question_id']],'FOLLOWUP_WORDING')
                shown.append(event['question_id'])
            if event['lock_id'] is not None: ref(event['lock_id'],'locks')
        require(len(shown)<=2 and len(set(shown))==len(shown),'FOLLOWUP_CAP')
        if followup:
            require(any(e['event_type']=='FOLLOWUP_LOCKED' for e in timeline),'MISSING_FOLLOWUP_LOCK')
            require(followup['submitted_at']<=followup['locked_at'],'FOLLOWUP_LOCK_TIME')
            require(lock is not None and followup['sequence']>lock['sequence'],'FOLLOWUP_SUBMISSION_BEFORE_LOCK')
            require(all(a['question_id'] in shown for a in followup['answers']),'UNSHOWN_FOLLOWUP_ANSWER')
            require(all(e['sequence']<followup['sequence'] for e in timeline if e['event_type']=='FOLLOWUP_SHOWN'),'ANSWER_BEFORE_FOLLOWUP_PRESENTATION')
    preview=bundle['export_preview'];authorization=bundle['export_authorization']
    require(preview['sections']==preview_sections(bundle),'EXPORT_PREVIEW_MISMATCH')
    require(preview['notice']==NOTICE,'WITHDRAWAL_NOTICE')
    require(authorization['consent_record_id']==consent['record_id'],'EXPORT_CONSENT_REFERENCE')
    require(authorization['preview_hash']==sha256(preview),'EXPORT_PREVIEW_AUTHORIZATION')
    require(consent['accepted_at']<=authorization['confirmed_at'] and preview['presented_at']<=authorization['confirmed_at'],'EXPORT_BEFORE_CONSENT')
    return {'schema_version':'1.0.0','source_data_status':provenance['source_data_status'],'record_count':len(all_records),
        'independent_source_verification':'AVAILABLE_FOR_DIAGNOSTIC_REPLAY' if included else 'UNVERIFIABLE_HISTORY_WITHHELD',
        'participant_clock_verification':'DEVICE_REPORTED_NOT_INDEPENDENTLY_VERIFIED'}
