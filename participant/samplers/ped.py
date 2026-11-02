"""Predictive Episode Discovery 0.5.1. Passive-only, chronological and content-addressed.

Identifiers in this module are content references, never persistence UUIDs. Database and
wall-clock identity are added by the service. Legacy data.ts is intentionally unchanged.
"""
from __future__ import annotations
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import hashlib
import json
import math
import random
from pathlib import Path
from .contracts import iso

VERSION = 'music-episode-surfacing-0.5.1'
HASH_VERSION = 'ped-canonical-json-1'
CLOCK_FIELDS = ('providerTimestampRaw','providerTimestampSemantics','observedStartAt','observedEndAt',
                'estimatedStartAt','estimatedEndAt','timeEstimationMethod','timeQuality')
PASSIVE_FIELDS = ('occurredAt','provider','providerTrackId','trackName','artistName','albumName',
                  'millisecondsPlayed','skipped','startReason','endReason','shuffle','playbackSource','deviceClass')


def canonical(value):
    if isinstance(value,dict): return {key:canonical(value[key]) for key in sorted(value)}
    if isinstance(value,(list,tuple)): return [canonical(item) for item in value]
    if isinstance(value,float):
        if not math.isfinite(value): raise ValueError('Non-finite scientific value')
        return int(value) if value.is_integer() else value
    if value is None or isinstance(value,(str,int,bool)): return value
    raise ValueError('Scientific content must be JSON')


def content_hash(value):
    text=json.dumps({'hashVersion':HASH_VERSION,'content':canonical(value)},ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    return hashlib.sha256(text.encode()).hexdigest()


def dt(value): return datetime.fromisoformat(iso(value).replace('Z','+00:00'))
def stamp(value): return iso(value.isoformat())
def seconds(a,b): return (dt(b)-dt(a)).total_seconds()
def track_key(event): return event.get('providerTrackId') or content_hash([event['provider'],event['artistName'],event['trackName'],event.get('albumName','')])
def artist_key(event): return event['artistName'].strip().casefold()
def known_rate(events,key='skipped'):
    values=[event[key] for event in events if event.get(key) is not None]
    return sum(values)/len(values) if values else None

def residual_and_surprisal(observed,p_skip,epsilon=1e-12):
    if observed is None: return None,None
    if type(observed) is not bool or not 0<=p_skip<=1: raise ValueError('Invalid binary skip forecast')
    y=int(observed)
    probability=p_skip if y else 1-p_skip
    return y-p_skip,-math.log(max(probability,epsilon))


@dataclass(frozen=True)
class PedConfig:
    version: str = VERSION
    execution_mode: str = 'RETROSPECTIVE_REPLAY'
    seed: str = 'ped-pilot-1'
    budget: int = 10
    min_history: int = 20
    shrinkage: float = 8.
    alpha: float = 1.
    beta: float = 1.
    pre_events: int = 5
    post_events: int = 3
    min_window_events: int = 3
    max_window_seconds: int = 1800
    session_gap_seconds: int = 1800
    return_gap_seconds: int = 7200
    surprise_threshold: float = 1.5
    pressure_min_skips: int = 2
    pressure_threshold: float = .6
    change_window: int = 4
    change_threshold: float = .5
    known_outcome_fraction: float = .5
    jaccard_threshold: float = .6
    per_day_cap: int = 3
    per_session_cap: int = 2
    fallback: str = 'REALLOCATE_TO_CONTROLS'

    def __post_init__(self):
        if self.execution_mode not in {'STRICT_ONLINE','RETROSPECTIVE_REPLAY'}: raise ValueError('Unknown execution mode')
        if self.version!=VERSION or self.fallback not in {'REALLOCATE_TO_CONTROLS','LEAVE_UNFILLED'}: raise ValueError('Unsupported policy version')
        for name in ['min_history','shrinkage','alpha','beta','min_window_events','max_window_seconds','session_gap_seconds','return_gap_seconds','change_window','per_day_cap','per_session_cap']:
            if getattr(self,name)<=0: raise ValueError(f'{name} must be positive')
        if not 1<=self.budget<=10 or self.pre_events<0 or self.post_events<0: raise ValueError('Invalid prompt/window budget')
        for name in ['known_outcome_fraction','jaccard_threshold','pressure_threshold']:
            if not 0<=getattr(self,name)<=1: raise ValueError('Invalid policy fraction')


def event_clock(event,available_at):
    """Old normalized rows have UNKNOWN semantics; never invent an observed start."""
    semantic=event.get('providerTimestampSemantics') or 'UNKNOWN'
    start=iso(event['observedStartAt']) if event.get('observedStartAt') else None
    end=iso(event['observedEndAt']) if event.get('observedEndAt') else None
    estimate_start=iso(event['estimatedStartAt']) if event.get('estimatedStartAt') else None
    estimate_end=iso(event['estimatedEndAt']) if event.get('estimatedEndAt') else None
    quality=event.get('timeQuality') or ('OBSERVED' if start and end else 'UNKNOWN')
    if start and end and start>end: raise ValueError('Observed start follows end')
    return {'provider_timestamp_raw':event.get('providerTimestampRaw'),'provider_timestamp_semantics':semantic,
            'observed_start_at':start,'observed_end_at':end,'estimated_start_at':estimate_start,'estimated_end_at':estimate_end,
            'time_estimation_method':event.get('timeEstimationMethod') or 'NONE','time_quality':quality,
            'actual_source_available_at':iso(available_at)}


def normalize_events(observations,available_at):
    normalized=[]
    for original in observations:
        missing=set(['id','occurredAt','provider','trackName','artistName','millisecondsPlayed','skipped'])-original.keys()
        if missing: raise ValueError('Incomplete normalized observation')
        if original['skipped'] is not None and type(original['skipped']) is not bool: raise ValueError('Unknown skip must remain null')
        event={key:original.get(key) for key in PASSIVE_FIELDS}
        event['occurredAt']=iso(event['occurredAt'])
        clock=event_clock(original,original.get('actualSourceAvailableAt') or available_at)
        # UNKNOWN timestamps are ordering proxies, not asserted physical playback ends.
        end=clock['observed_end_at'] or event['occurredAt']
        payload={**event,'clock':{k:v for k,v in clock.items() if k!='actual_source_available_at'}}
        normalized.append({'observation':event,'clock':clock,'outcome_at':end,'source_id':original['id'],'payload_hash':content_hash(payload)})
    normalized.sort(key=lambda item:(item['outcome_at'],item['payload_hash']))
    occurrences=Counter()
    for index,event in enumerate(normalized):
        occurrence=occurrences[event['payload_hash']];occurrences[event['payload_hash']]+=1
        event['key']=content_hash({'observation':event['payload_hash'],'occurrence':occurrence})
        event['ordinal']=index
    if len({event['source_id'] for event in normalized})!=len(normalized): raise ValueError('Duplicate source event identity')
    return normalized


class PastIndex:
    def __init__(self,events,mode):
        self.events=events;self.mode=mode
        self.ends=[event['outcome_at'] for event in events]
        self.counts=[0];self.skips=[0];self.prefix_hashes=[content_hash({'prefix':[]})]
        self.artist=defaultdict(list);self.track=defaultdict(list)
        for index,event in enumerate(events):
            observation=event['observation'];y=observation['skipped']
            self.counts.append(self.counts[-1]+int(y is not None));self.skips.append(self.skips[-1]+int(y is True))
            self.prefix_hashes.append(content_hash({'previous':self.prefix_hashes[-1],'event':event['key']}))
            if y is not None:
                for group,key in [(self.artist,artist_key(observation)),(self.track,track_key(observation))]:
                    series=group[key];series.append((index,(series[-1][1] if series else 0)+int(y)))

    def at(self,cutoff): return bisect_right(self.ends,cutoff)
    def group_counts(self,group,key,n):
        values=group.get(key,[]);count=bisect_left(values,(n,-1))
        return count,values[count-1][1] if count else 0


def validate_prediction(prediction,model,events,config):
    cutoff=prediction['prediction_as_of_at'];target=events[prediction['target_ordinal']]
    n=model['training_prefix_length']
    if n>prediction['target_ordinal'] or (n and events[n-1]['outcome_at']>cutoff): raise ValueError('Training crosses prediction cutoff')
    if n>target['ordinal']: raise ValueError('Target appears in its own training history')
    if cutoff>=target['outcome_at']: raise ValueError('Forecast cutoff must precede target outcome')
    if model['training_coverage_end_at'] and model['training_coverage_end_at']>cutoff: raise ValueError('Future model cannot score an earlier event')
    if config.execution_mode=='STRICT_ONLINE':
        if prediction['artifact_generated_at']>cutoff: raise ValueError('Historical reconstruction cannot be labeled STRICT_ONLINE')
        if model.get('actual_source_available_at') and model['actual_source_available_at']>cutoff: raise ValueError('Online history was not actually available')


def predictions_for(events,config,generated_at):
    index=PastIndex(events,config.execution_mode);predictions=[];models={};prefix_available=[]
    running=None
    for event in events:
        running=max(running,event['clock']['actual_source_available_at']) if running else event['clock']['actual_source_available_at']
        prefix_available.append(running)
    for i,event in enumerate(events):
        observation=event['observation'];end=event['outcome_at'];start=event['clock']['observed_start_at']
        earlier=bisect_left(index.ends,end)
        if start and start<end:
            cutoff=start;basis='OBSERVED_START';target_metadata_known=True
        else:
            cutoff=index.ends[earlier-1] if earlier else stamp(dt(end)-timedelta(milliseconds=1))
            basis='PRECEDING_COMPLETION_BOUNDARY';target_metadata_known=False
        if config.execution_mode=='STRICT_ONLINE' and event['clock']['actual_source_available_at']>cutoff:
            target_metadata_known=False
        n=index.at(cutoff)
        if n>i: raise ValueError('Target or later outcome entered training')
        count,total=index.counts[n],index.skips[n]
        person=(total+config.alpha)/(count+config.alpha+config.beta)
        p=person;tier='PERSON';track_n=0;artist_n=0
        if target_metadata_known:
            artist_n,artist_skips=index.group_counts(index.artist,artist_key(observation),n)
            artist=(artist_skips+config.shrinkage*person)/(artist_n+config.shrinkage)
            track_n,track_skips=index.group_counts(index.track,track_key(observation),n)
            p=(track_skips+config.shrinkage*artist)/(track_n+config.shrinkage)
            tier='SHRUNK_RECORDING' if track_n else 'SHRUNK_ARTIST' if artist_n else 'PERSON'
        if config.execution_mode=='STRICT_ONLINE' and n and prefix_available[n-1]>cutoff:
            raise ValueError('Online history contains backfilled observations')
        history=events[max(0,n-5):n]
        skip_values=[item['observation']['skipped'] for item in history]
        streak=0
        for item in reversed(events[max(0,n-256):n]):
            skipped=item['observation']['skipped']
            if skipped is None: streak=None;break
            if not skipped: break
            streak+=1
        reasons=[item['observation'].get('startReason') for item in history if item['observation'].get('startReason')]
        features={'person_prior':person,'person_support':count,'artist_support':artist_n,'recording_support':track_n,'tier':tier,
                  'preceding_consecutive_skips':streak,'recent_5_skip_rate':known_rate([item['observation'] for item in history]),
                  'recent_5_navigation_rate':sum(reason in {'clickrow','playbtn','backbtn','fwdbtn'} for reason in reasons)/len(reasons) if reasons else None,
                  'time_of_day':int(start[11:13]) if target_metadata_known else None,
                  'time_of_day_quality':'OBSERVED' if target_metadata_known else event['clock']['time_quality'],
                  'target_metadata_known':target_metadata_known,'decision_time_basis':basis}
        model_content={'version':VERSION,'model_family':'BETA_BINOMIAL','config':{'alpha':config.alpha,'beta':config.beta,'shrinkage':config.shrinkage},
                       'training_prefix_hash':index.prefix_hashes[n],'training_prefix_length':n,'person_count':count,'person_skips':total,
                       'training_coverage_start_at':events[0]['outcome_at'] if n else None,'training_coverage_end_at':events[n-1]['outcome_at'] if n else None,
                       'recording_key':track_key(observation) if target_metadata_known else None,'p_skip':p,'calibration_method':'NONE'}
        model_hash=content_hash(model_content)
        model={**model_content,'content_hash':model_hash,'artifact_generated_at':generated_at,
               'actual_source_available_at':prefix_available[n-1] if n else None,'execution_mode':config.execution_mode}
        models[model_hash]=model
        forecast={'version':VERSION,'target_reference':content_hash({'ordinal':i,'observed_start':start,'recording':track_key(observation) if target_metadata_known else None}),'model_content_hash':model_hash,'prediction_as_of_at':cutoff,
                  'execution_mode':config.execution_mode,'features':features,'p_skip':p,'p_non_skip':1-p,
                  'reliability_class':'SUFFICIENT' if count>=config.min_history else 'SPARSE_HISTORY','model_support_count':count}
        prediction={**forecast,'event_key':event['key'],'content_hash':content_hash(forecast),'target_ordinal':i,'artifact_generated_at':generated_at,
                    'training_coverage_end_at':model['training_coverage_end_at'],'actual_source_available_at':max(model['actual_source_available_at'] or event['clock']['actual_source_available_at'],event['clock']['actual_source_available_at']) if target_metadata_known else model['actual_source_available_at']}
        validate_prediction(prediction,model,events,config)
        # Only now inspect the target outcome. The forecast and its hash are already fixed.
        residual,surprise=residual_and_surprisal(observation['skipped'],p)
        prediction['score']={'observed_skip':observation['skipped'],'signed_residual':residual,'surprisal_nats':surprise,
                             'outcome_available_at':event['clock']['actual_source_available_at'],
                             'status':'SCORED' if observation['skipped'] is not None else 'UNSCORABLE'}
        predictions.append(prediction)
    return predictions,models


def percentile(value,reference):
    values=[item for item in reference if item is not None]
    if value is None or not values: return None
    return (sum(item<value for item in values)+.5*sum(item==value for item in values))/len(values)


def build_candidates(events,predictions,selected_keys,config):
    sessions=[];session_by_key={};session_items={};last=None
    for i,event in enumerate(events):
        if last is None or seconds(last,event['outcome_at'])>config.session_gap_seconds:
            sessions.append([])
        session=len(sessions)-1;sessions[-1].append(i);session_by_key[event['key']]=session
        last=event['outcome_at']
    session_items={i:items for i,items in enumerate(sessions)}
    candidates=[];results=[]
    def window(anchor,family,score,reason,members=None,prediction_keys=()):
        session=session_by_key[events[anchor]['key']];indices=session_items[session];position=indices.index(anchor)
        members=members or indices[max(0,position-config.pre_events):position+config.post_events+1]
        members=[i for i in members if events[i]['key'] in selected_keys and abs(seconds(events[anchor]['outcome_at'],events[i]['outcome_at']))<=config.max_window_seconds]
        members=sorted(members)
        while members and seconds(events[members[0]]['outcome_at'],events[members[-1]]['outcome_at'])>config.max_window_seconds:
            if anchor-members[0]>members[-1]-anchor: members.pop(0)
            else: members.pop()
        if not members or anchor not in members: return
        event_keys=[events[i]['key'] for i in members]
        detector={'family':family,'anchor_key':events[anchor]['key'],'score':score,'reason':reason,'prediction_keys':list(prediction_keys),
                  'boundary_mode':'RETROSPECTIVE_OFFLINE' if family=='BEHAVIORAL_CHANGE' else 'ANCHOR_WINDOW'}
        detector['content_hash']=content_hash(detector);results.append(detector)
        known=sum(events[i]['observation']['skipped'] is not None for i in members)/len(members)
        exclusions=[]
        if len(members)<config.min_window_events: exclusions.append('MIN_EVENT_SUPPORT')
        if family in {'HIGH_SURPRISAL','HIGH_SELECTION_PRESSURE','BEHAVIORAL_CHANGE'} and known<config.known_outcome_fraction: exclusions.append('LOW_OUTCOME_COVERAGE')
        if family=='HIGH_SURPRISAL' and predictions[anchor]['reliability_class']!='SUFFICIENT': exclusions.append('INSUFFICIENT_HISTORY')
        content={'members':event_keys,'anchor':events[anchor]['key'],'trigger':detector['content_hash'],
                 'builder':{'version':VERSION,'pre':config.pre_events,'post':config.post_events,'max_seconds':config.max_window_seconds}}
        candidate={'content_hash':content_hash(content),'event_keys':event_keys,'anchor_key':events[anchor]['key'],'session':session,
                   'started_at':events[members[0]]['outcome_at'],'ended_at':events[members[-1]]['outcome_at'],
                   'eligible_at':max(events[i]['clock']['actual_source_available_at'] for i in members),'family':family,'score':score,
                   'triggers':[detector['content_hash']],'eligible_strata':[family],'eligible':not exclusions,'exclusion_reasons':exclusions,
                   'quality':{'known_outcome_fraction':known,'history_support':predictions[anchor]['reliability_class'],
                              'time_quality':sorted({events[i]['clock']['time_quality'] for i in members}),'reviewability':'PASS' if not exclusions else 'FAIL'}}
        candidates.append(candidate)
    past_pressure=[]
    for i,(event,prediction) in enumerate(zip(events,predictions)):
        features=prediction['features'];cutoff=prediction['prediction_as_of_at']
        references=[record for record in past_pressure[-256:] if record['outcome_at']<=cutoff]
        values=[features['preceding_consecutive_skips'],features['recent_5_skip_rate'],features['recent_5_navigation_rate']]
        components=[(percentile(value,[record['values'][j] for record in references]),weight) for j,(value,weight) in enumerate(zip(values,[.5,.3,.2]))]
        known=[(value,weight) for value,weight in components if value is not None]
        pressure=sum(value*weight for value,weight in known)/sum(weight for _,weight in known) if known else None
        prediction['selection_pressure']={'value':pressure,'components':values,'baseline_support':len(references),'method':'prior-only-rolling-256-midrank'}
        if event['key'] in selected_keys:
            surprise=prediction['score']['surprisal_nats']
            if surprise is not None and surprise>=config.surprise_threshold:
                window(i,'HIGH_SURPRISAL',surprise,'UNEXPECTED_SKIP' if prediction['score']['observed_skip'] else 'UNEXPECTED_NON_SKIP',prediction_keys=[prediction['content_hash']])
            streak=features['preceding_consecutive_skips']
            explicit=features['target_metadata_known'] and event['observation'].get('startReason') in {'clickrow','playbtn','backbtn'}
            if (prediction['score']['observed_skip'] is False or explicit) and streak is not None and streak>=config.pressure_min_skips and pressure is not None and pressure>=config.pressure_threshold:
                window(i,'HIGH_SELECTION_PRESSURE',pressure,'NON_SKIP_AFTER_REJECTION_STREAK' if prediction['score']['observed_skip'] is False else 'EXPLICIT_SELECTION_AFTER_REJECTION_STREAK',prediction_keys=[prediction['content_hash']])
        past_pressure.append({'values':values,'outcome_at':event['outcome_at']})
    for session,indices in session_items.items():
        indices=[i for i in indices if events[i]['key'] in selected_keys]
        w=config.change_window
        if config.execution_mode=='RETROSPECTIVE_REPLAY':
            for j in range(w,len(indices)-w+1):
                before,after=indices[j-w:j],indices[j:j+w]
                def vector(items):
                    observations=[events[i]['observation'] for i in items]
                    counts=Counter(track_key(e) for e in observations)
                    reasons=[e['startReason'] for e in observations if e.get('startReason')]
                    return [known_rate(observations),sum(r in {'clickrow','playbtn','backbtn'} for r in reasons)/len(reasons) if reasons else None,max(counts.values())/len(items)]
                pre,post=vector(before),vector(after)
                magnitude=sum(abs(b-a) for a,b in zip(pre,post) if a is not None and b is not None)
                if magnitude>=config.change_threshold: window(after[0],'BEHAVIORAL_CHANGE',magnitude,'BEHAVIORAL_MODE_CHANGE',members=before+after)
        returns=defaultdict(list)
        for i in indices: returns[track_key(events[i]['observation'])].append(i)
        for occurrences in returns.values():
            clusters=[]
            for i in occurrences:
                if not clusters or seconds(events[clusters[-1][-1]]['outcome_at'],events[i]['outcome_at'])>min(config.return_gap_seconds,config.max_window_seconds): clusters.append([])
                clusters[-1].append(i)
            for cluster in clusters:
                if len(cluster)<2: continue
                anchor=cluster[-1];observations=[events[i]['observation'] for i in cluster]
                reasons=[e['startReason'] for e in observations if e.get('startReason')];skip=known_rate(observations)
                manual=sum(r in {'clickrow','playbtn','backbtn'} for r in reasons)/len(reasons) if reasons else None
                score=manual*(1-skip)*math.log1p(len(cluster)) if manual is not None and skip is not None else float(len(cluster))
                position=indices.index(cluster[0]);finish=indices.index(anchor)
                members=indices[max(0,position-config.pre_events):finish+config.post_events+1]
                window(anchor,'PERSISTENCE_RETURN',score,'HIGH_AGENCY_REPEAT' if manual is not None and manual>=.5 else 'CONCENTRATED_REPEAT',members=members)
        # Neutral windows define a control universe independently of anomaly eligibility.
        for j in range(0,len(indices),max(1,config.pre_events+config.post_events)):
            anchor=indices[min(j+config.pre_events,len(indices)-1)]
            members=indices[j:j+config.pre_events+config.post_events+1]
            observations=[events[i]['observation'] for i in members]
            q=known_rate(observations);prior=predictions[anchor]['features']['person_prior']
            distance=abs(q-prior) if q is not None else 1.
            window(anchor,'REPRESENTATIVE_ORDINARY',-distance,'REPRESENTATIVE_ORDINARY_CONTROL',members=members)
            if candidates and candidates[-1]['family']=='REPRESENTATIVE_ORDINARY': candidates[-1]['eligible_strata'].append('RANDOM_CONTROL')
    priorities={'HIGH_SURPRISAL':0,'HIGH_SELECTION_PRESSURE':1,'BEHAVIORAL_CHANGE':2,'PERSISTENCE_RETURN':3,'REPRESENTATIVE_ORDINARY':4}
    representatives=[];relations=[]
    for candidate in sorted(candidates,key=lambda c:(not c['eligible'],priorities[c['family']],-c['score'],c['content_hash'])):
        match=None
        if candidate['eligible']:
            current=set(candidate['event_keys'])
            for prior in representatives:
                other=set(prior['event_keys']);overlap=len(current&other)/len(current|other)
                if overlap>=config.jaccard_threshold and candidate['session']==prior['session'] and seconds(min(candidate['started_at'],prior['started_at']),max(candidate['ended_at'],prior['ended_at']))<=config.max_window_seconds:
                    match=prior;break
        if match:
            candidate['eligible']=False;candidate['exclusion_reasons'].append('DUPLICATE_WINDOW')
            match['triggers']=sorted(set(match['triggers']+candidate['triggers']))
            match['eligible_strata']=sorted(set(match['eligible_strata']+candidate['eligible_strata']))
            relations.append({'source':candidate['content_hash'],'target':match['content_hash'],'type':'SUPPRESSED_BY'})
        elif candidate['eligible']: representatives.append(candidate)
    # All surviving windows can be controls; low surprise is not required.
    for candidate in representatives: candidate['eligible_strata']=sorted(set(candidate['eligible_strata']+['RANDOM_CONTROL']))
    return candidates,results,relations


def sample_candidates(candidates,config):
    quotas={'HIGH_SURPRISAL':2,'HIGH_SELECTION_PRESSURE':2,'BEHAVIORAL_CHANGE':2,'PERSISTENCE_RETURN':1,'REPRESENTATIVE_ORDINARY':1,'RANDOM_CONTROL':2}
    selected=[];decisions={};strata=[];days=Counter();sessions=Counter();used=set()
    def compatible(candidate):
        return not used.intersection(candidate['event_keys']) and days[candidate['started_at'][:10]]<config.per_day_cap and sessions[candidate['session']]<config.per_session_cap
    def take(candidate,stratum,probability,method,rank):
        selected.append(candidate);used.update(candidate['event_keys']);days[candidate['started_at'][:10]]+=1;sessions[candidate['session']]+=1
        decisions[candidate['content_hash']]={'selected':True,'stratum':stratum,'rank':rank,'inclusion_probability':probability,'probability_method':method,'reason':'SELECTED'}
    for stratum,target in list(quotas.items())[:-1]:
        pool=sorted([c for c in candidates if c['eligible'] and stratum in c['eligible_strata']],key=lambda c:(-c['score'] if c['family']==stratum else 0,c['content_hash']))
        drawn=0
        for rank,candidate in enumerate(pool,1):
            if drawn>=target or len(selected)>=config.budget: break
            if candidate['content_hash'] in decisions or not compatible(candidate): continue
            take(candidate,stratum,1.,'DETERMINISTIC_CONDITIONAL_ON_FROZEN_POOL',rank);drawn+=1
        strata.append({'key':stratum,'target_count':target,'eligible_count':len(pool),'drawn_count':drawn,'draw_method':'DETERMINISTIC_TOPK'})
    # Freeze a diversity-compatible frame BEFORE randomization. Any subset of this
    # frame satisfies remaining caps, so uniform k/N is exact conditional on it.
    frame=[];frame_used=set(used);frame_days=Counter(days);frame_sessions=Counter(sessions)
    eligible=[c for c in candidates if c['eligible'] and c['content_hash'] not in decisions]
    for candidate in sorted(eligible,key=lambda c:c['content_hash']):
        day=candidate['started_at'][:10];session=candidate['session']
        if frame_used.intersection(candidate['event_keys']) or frame_days[day]>=config.per_day_cap or frame_sessions[session]>=config.per_session_cap: continue
        frame.append(candidate);frame_used.update(candidate['event_keys']);frame_days[day]+=1;frame_sessions[session]+=1
    remaining=config.budget-len(selected)
    target=remaining if config.fallback=='REALLOCATE_TO_CONTROLS' else min(quotas['RANDOM_CONTROL'],remaining)
    k=min(target,len(frame));rng=random.Random(config.seed)
    draw=rng.sample(frame,k)
    for rank,candidate in enumerate(draw,1): take(candidate,'RANDOM_CONTROL',k/len(frame),'UNIFORM_CONDITIONAL_ON_FROZEN_DIVERSITY_FRAME',rank)
    frame_keys={c['content_hash'] for c in frame}
    strata.append({'key':'RANDOM_CONTROL','target_count':target,'eligible_count':len(frame),'drawn_count':k,'draw_method':'SEEDED_UNIFORM','seed':config.seed,'frame_hash':content_hash(sorted(frame_keys))})
    for candidate in candidates:
        key=candidate['content_hash']
        if key not in decisions:
            decisions[key]={'selected':False,'stratum':'RANDOM_CONTROL' if key in frame_keys else None,'rank':None,
                            'inclusion_probability':k/len(frame) if key in frame_keys else None,
                            'probability_method':'UNIFORM_CONDITIONAL_ON_FROZEN_DIVERSITY_FRAME' if key in frame_keys else 'UNKNOWN_OR_EXCLUDED',
                            'reason':'NOT_DRAWN' if key in frame_keys else candidate['exclusion_reasons'][0] if candidate['exclusion_reasons'] else 'QUOTA_OR_DIVERSITY_LIMIT'}
    return selected,decisions,strata


def blind_packet(candidate,events_by_key,config):
    events=[events_by_key[key] for key in candidate['event_keys']]
    anchor=events_by_key[candidate['anchor_key']]['observation']
    return {'schemaVersion':'resonance-blind-window-1','episode':{'id':content_hash(candidate['event_keys']),
                'startedAt':candidate['started_at'],'endedAt':candidate['ended_at'],'referenceEventId':candidate['anchor_key'],
                'referenceTrack':{'trackName':anchor['trackName'],'artistName':anchor['artistName'],'albumName':anchor.get('albumName') or ''}},
            'events':[{'eventId':event['key'],**{k:event['observation'].get(k) for k in ['occurredAt','trackName','artistName','millisecondsPlayed','skipped']},
                       'timeQuality':event['clock']['time_quality'],'clock':{k:v for k,v in event['clock'].items() if k!='actual_source_available_at'}} for event in events],
            'behavior':{},'participantReport':None,'musicEvidence':[],
            'questions':['Do you recall this listening period?','Did this music feel unusually fitting?','Did your attention or feeling change?','Did anything from your own life come to mind?','I do not know / do not remember'],
            'limitations':['Timing may be approximate; reported clock uncertainty is retained.','This record does not establish a psychological explanation.'],
            'provenanceCommitment':content_hash({'inputs':candidate['event_keys'],'configuration':asdict(config)})}


def surface(observations,selected_source_ids,available_at,config=None,generated_at=None):
    config=config or PedConfig();generated_at=iso(generated_at or datetime.now().astimezone().isoformat())
    events=normalize_events(observations,available_at)
    selected_keys={event['key'] for event in events if event['source_id'] in selected_source_ids}
    if not selected_keys: raise ValueError('No selected observations')
    predictions,models=predictions_for(events,config,generated_at)
    candidates,detectors,relations=build_candidates(events,predictions,selected_keys,config)
    selected,decisions,strata=sample_candidates(candidates,config)
    by_key={event['key']:event for event in events}
    packets={candidate['content_hash']:blind_packet(candidate,by_key,config) for candidate in selected}
    eligible_predictions=[p for p in predictions if p['event_key'] in selected_keys and p['reliability_class']=='SUFFICIENT' and p['score']['observed_skip'] is not None]
    losses=[p['score']['surprisal_nats'] for p in eligible_predictions]
    brier=[(int(p['score']['observed_skip'])-p['p_skip'])**2 for p in eligible_predictions]
    validation={'split':'CHRONOLOGICAL_WALK_FORWARD_AFTER_WARMUP','n_events':len(losses),'log_loss':sum(losses)/len(losses) if losses else None,
                'brier_score':sum(brier)/len(brier) if brier else None,'calibration_method':'NONE','probabilities_validated_as_calibrated':False}
    baseline_losses=[residual_and_surprisal(p['score']['observed_skip'],p['features']['person_prior'])[1] for p in eligible_predictions]
    validation['constant_person_prior_log_loss']=sum(baseline_losses)/len(baseline_losses) if baseline_losses else None
    bins=[]
    for index in range(10):
        members=[p for p in eligible_predictions if min(int(p['p_skip']*10),9)==index]
        bins.append({'bin':index,'n':len(members),'mean_probability':sum(p['p_skip'] for p in members)/len(members) if members else None,'observed_skip_rate':sum(p['score']['observed_skip'] for p in members)/len(members) if members else None})
    validation['calibration_bins']=bins
    validation['ece']=sum(b['n']*abs(b['mean_probability']-b['observed_skip_rate']) for b in bins if b['n'])/len(eligible_predictions) if eligible_predictions else None
    semantic={'version':VERSION,'implementation_hash':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'config':asdict(config),'input_refs':[event['key'] for event in events],
              'selected_input_refs':sorted(selected_keys),'models':sorted(models),'predictions':[p['content_hash'] for p in predictions],
              'scores':[{'event':p['event_key'],'residual':p['score']['signed_residual'],'surprisal':p['score']['surprisal_nats']} for p in predictions],
              'candidate_pool':sorted(({'hash':c['content_hash'],'eligible':c['eligible'],'quality':c['quality'],'triggers':c['triggers'],'strata':c['eligible_strata'],'exclusions':c['exclusion_reasons']} for c in candidates),key=lambda c:c['hash']),
              'decisions':decisions,'strata':strata,'packets':{key:content_hash(value) for key,value in sorted(packets.items())},'validation':validation}
    return {'version':VERSION,'execution_mode':config.execution_mode,'simulation':config.execution_mode=='RETROSPECTIVE_REPLAY',
            'artifact_generated_at':generated_at,'content_hash':content_hash(semantic),'config':asdict(config),'events':events,'models':models,
            'predictions':predictions,'detectors':detectors,'candidates':candidates,'relations':relations,'decisions':decisions,'strata':strata,
            'packets':packets,'pool_hash':content_hash(semantic['candidate_pool']),'validation':validation}
