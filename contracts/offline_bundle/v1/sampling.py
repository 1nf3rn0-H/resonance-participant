"""Portable M0 policy reference, not a replacement for either native surfacer."""
from __future__ import annotations
from datetime import datetime
from .canonical import sha256

ARMS=('RANDOM','V0_3','PED')

def dt(value): return datetime.fromisoformat(value.replace('Z','+00:00'))

def draw(seed,unit,purpose,n):
    if n<=0: raise ValueError('Empty draw frame')
    limit=(1<<256)-((1<<256)%n);counter=0
    while True:
        value=int(sha256({'rng':'jcs-sha256-rejection-v1','seed':seed,'unit':unit,'purpose':purpose,'counter':counter}),16)
        if value<limit: return value%n
        counter+=1


def eligible_universe(events,cutoff):
    """Same historical window geometry for every arm, before scoring; keep exclusions."""
    ordered=sorted(events,key=lambda e:(e['occurred_at'],e['source_ordinal'],e['event_key']))
    sessions=[]
    for event in ordered:
        if not sessions or event['occurred_at'][:10]!=sessions[-1][-1]['occurred_at'][:10] or (dt(event['occurred_at'])-dt(sessions[-1][-1]['occurred_at'])).total_seconds()>1800:
            sessions.append([])
        sessions[-1].append(event)
    result=[]
    for session in sessions:
        for offset in range(0,len(session),4):
            span=session[offset:offset+4];members=[e['event_key'] for e in span]
            reasons=[]
            if len(span)<3: reasons.append('TOO_SHORT')
            if (dt(span[-1]['occurred_at'])-dt(span[0]['occurred_at'])).total_seconds()>1800: reasons.append('SPAN_TOO_LONG')
            if any((e['observed_end_at'] or e['estimated_end_at'] or e['occurred_at'])>cutoff for e in span): reasons.append('AFTER_CUTOFF')
            result.append({'window_key':sha256({'universe':'historical-disjoint-windows-1.0.0','event_refs':members}),
                'event_refs':members,'eligibility':'INELIGIBLE' if reasons else 'ELIGIBLE','reasons':reasons or ['COMMON_WINDOW']})
    return result


def mapped_scores(windows,natives):
    rankings={arm:sorted([n for n in natives if n['arm']==arm],key=lambda n:(-n['score'],n['candidate_key'])) for arm in ARMS[1:]}
    by_event={arm:{} for arm in ARMS[1:]}
    for arm,candidates in rankings.items():
        for rank,candidate in enumerate(candidates,1):
            for event in set(candidate['event_refs']):by_event[arm].setdefault(event,[]).append((rank,candidate['record_id']))
    result={}
    for window in windows:
        result[window['record_id']]={}
        for arm in ARMS:
            matches=sorted({match for event in window['event_refs'] for match in by_event.get(arm,{}).get(event,[])})
            result[window['record_id']][arm]={'native_candidate_ids':[source_id for rank,source_id in matches],
                'mapped_score':1/matches[0][0] if matches else 0.}
    return result


def allocate_slot(windows,natives,seed,unit,available_arms=ARMS,prior_event_refs=()):
    frame=sorted([w for w in windows if w['eligibility']=='ELIGIBLE' and not set(w['event_refs']).intersection(prior_event_refs)],key=lambda w:w['window_key'])
    if not frame: raise ValueError('No eligible historical windows remain')
    arms=[a for a in ARMS if a in available_arms]
    if not arms: raise ValueError('No available arms')
    scores=mapped_scores(frame,natives)
    winners={a:sorted(frame,key=lambda w:(-scores[w['record_id']][a]['mapped_score'],w['window_key']))[0] for a in arms if a!='RANDOM'}
    arm=arms[draw(seed,unit,'arm',len(arms))]
    chosen=frame[draw(seed,unit,'random-window',len(frame))] if arm=='RANDOM' else winners[arm]
    marginal=sum(1/len(frame) if a=='RANDOM' else float(winners[a]['window_key']==chosen['window_key']) for a in arms)/len(arms)
    return {'window_id':chosen['record_id'],'arm':arm,'frame_window_ids':[w['record_id'] for w in frame],
        'frame_hash':sha256([w['window_key'] for w in frame]),'arm_probability':1/len(arms),
        'conditional_window_probability':1/len(frame) if arm=='RANDOM' else 1.,'step_inclusion_probability':marginal}
