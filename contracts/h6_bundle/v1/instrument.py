"""Executable H6 instrument. Does not change M0 questions or invitations."""
from pathlib import Path
from jsonschema import Draft202012Validator
from contracts.offline_bundle.v1.canonical import loads,sha256
BANK=loads((Path(__file__).parent/'questions.json').read_bytes())
POLICY='h6-context-plus-balanced-domain-1.0.0'


def select(*,neutral_locked,recognition,episode_key,seed):
    if neutral_locked is not True:raise ValueError('Durable neutral lock required')
    if recognition not in {'CLEAR','VAGUE','NOT_RECALLED','UNSURE','NOT_APPLICABLE','DECLINED'}:raise ValueError('Unknown neutral recognition value')
    eligible=[] if recognition=='DECLINED' else ['h6.context']
    if recognition in {'CLEAR','VAGUE'}:eligible+=['h6.skipping','h6.moment']
    # No arm, predicted motives, meaningfulness score or inferred preference used.
    selected=eligible[:1]
    if len(eligible)>1:
        draw=int(sha256({'policy':POLICY,'episode_key':episode_key,'seed':seed}),16)%2
        selected.append(eligible[1+draw])
    return {'policy_version':POLICY,'bank_version':BANK['version'],'bank_hash':sha256(BANK),
            'eligible_question_ids':eligible,'selected_question_ids':selected,
            'not_selected_question_ids':[q for q in eligible if q not in selected],
            'ineligible_question_ids':[q['question_id'] for q in BANK['questions'] if q['question_id'] not in eligible]}


def check(question_id,value):
    q=next(q for q in BANK['questions'] if q['question_id']==question_id)
    if not Draft202012Validator(q['response_schema']).is_valid(value):raise ValueError('Invalid H6 answer')
    if value['status']!='ANSWERED' and set(value)!={'status'}:raise ValueError('Uncertainty/decline cannot contain scored or descriptive data')
    for field,exclusive in [('activities',{'UNSURE'}),('reasons',{'DONT_RECALL'}),('kinds',{'NOTHING','UNSURE'})]:
        values=value.get(field,[])
        if set(values)&exclusive and len(values)>1:raise ValueError('Exclusive uncertainty/nothing option')
    if value.get('recall') in {'NO','DONT_RECALL','UNSURE'} and value.get('reasons'):raise ValueError('Skip reasons require recalled skipping')
    start=value.get('approximate_start_seconds');end=value.get('approximate_end_seconds')
    if end is not None and (start is None or end<start):raise ValueError('Invalid approximate interval')
    return value


def audit(selection,shown_ids,answers):
    selected=selection['selected_question_ids']
    if len(shown_ids)>2 or len(set(shown_ids))!=len(shown_ids) or any(q not in selected for q in shown_ids):raise ValueError('Question exposure cap/policy mismatch')
    if len({a['question_id'] for a in answers})!=len(answers):raise ValueError('Duplicate answer')
    if [a['question_id'] for a in answers]!=[q for q in shown_ids if q in {a['question_id'] for a in answers}]:raise ValueError('Answer order mismatch')
    for a in answers:
        if a['question_id'] not in shown_ids or a['question_version']!='1.0.0':raise ValueError('Unshown or wrong-version answer')
        check(a['question_id'],a['value'])
    return {**selection,'shown_question_ids':shown_ids,
        'skipped_question_ids':[q for q in selected if q not in shown_ids or q not in {a['question_id'] for a in answers}],
        'answered_question_ids':[a['question_id'] for a in answers if a['value']['status']=='ANSWERED'],
        'declined_or_uncertain_question_ids':[a['question_id'] for a in answers if a['value']['status']!='ANSWERED']}
