"""Local participant service: immutable captures, durable interview state, explicit encrypted export."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
from copy import deepcopy
import hashlib
import json
import re
import secrets
import uuid
from jsonschema import Draft202012Validator
from contracts.offline_bundle.v1.canonical import sha256,dumps,loads,seal
from contracts.offline_bundle.v1.release import verify_release
from contracts.offline_bundle.v1.validate import QUESTIONS,SAMPLING,CONSENT_FORM,NOTICE,preview_sections,validate,SECTION_ORDER
from contracts.offline_bundle.v1.sampling import eligible_universe,mapped_scores,allocate_slot
from contracts.offline_bundle.v1.crypto import encrypt_bundle,recipient_fingerprint
from .store import Store
from .h6 import H6Mixin
from .ingest import parse
from .sampling import native_results

VERSION='participant-1.1.0'
def now():return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
def identifier(prefix):return prefix+'-'+str(uuid.uuid4())

def required(condition,message):
    if not condition:raise ValueError(message)

class ParticipantApp(H6Mixin):
    def __init__(self,directory,clock=now):
        self.store=Store(directory);self.clock=clock;self.release_hash=verify_release()
    def configure(self,config,expected_hash,processing_consent,share_history,h6_options=None):
        allowed={'version','study_id','participant_pseudonym','recipient','recipient_fingerprint','contract_release_hash','researcher_contact'}
        h6_config=isinstance(config,dict) and config.get('version')=='participant-study-h6-1.0.0'
        if h6_config:allowed|={'h6_contract_release_hash','protocol_version'}
        required(isinstance(config,dict) and set(config)==allowed,'Study configuration has missing or unexpected fields')
        required(all(isinstance(v,str) and len(v)<=2000 for v in config.values()),'Study configuration fields must be bounded strings')
        required(config['version'] in {'participant-study-1.0.0','participant-study-h6-1.0.0'},'Unsupported study configuration')
        required(sha256(config)==expected_hash,'Study configuration does not match the fingerprint provided by your researcher')
        required(config['contract_release_hash']==self.release_hash,'Study uses a different contract release')
        for field in ['study_id','participant_pseudonym']:required(isinstance(config[field],str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}',config[field]),'Invalid study alias')
        required(isinstance(config['researcher_contact'],str) and 1<=len(config['researcher_contact'])<=1000,'Researcher contact is required')
        required(recipient_fingerprint(config['recipient'])==config['recipient_fingerprint'],'Study recipient fingerprint does not match')
        import pyrage
        try:pyrage.x25519.Recipient.from_str(config['recipient'])
        except Exception as error:raise ValueError('Invalid public study recipient') from error
        public_fixture=loads((Path(__file__).resolve().parent.parent/'contracts/offline_bundle/v1/fixtures/PUBLIC_TEST_KEYS.json').read_bytes())
        required(config['recipient']!=public_fixture['recipient'],'The publicly disclosed contract fixture key cannot be used for participant data')
        required(processing_consent is True and type(share_history) is bool,'Explicit local-processing consent and sharing choice are required')
        if h6_config:
            from contracts.h6_bundle.v1.contract import PROTOCOL
            from contracts.h6_bundle.v1.release import verify_release as h6_release
            required(config['protocol_version']==PROTOCOL and config['h6_contract_release_hash']==h6_release(),'H6 protocol or contract mismatch')
            required(isinstance(h6_options,dict) and set(h6_options)=={'collect_h6','share_event_evidence','share_playlist_context','share_followup_evidence'} and all(type(v) is bool for v in h6_options.values()) and h6_options['collect_h6'],'Explicit H6 collection consent and sharing choices are required')
            required(not h6_options['share_event_evidence'] or share_history is True,'Extended H6 events require listening-history sharing')
            required(not h6_options['share_playlist_context'] or h6_options['share_event_evidence'],'Playlist sharing requires extended H6 event sharing')
        else:required(h6_options is None,'H6 cannot be added to an M0 study')
        with self.store.transaction() as c:
            old=self.store.get(c,'config')
            if old:
                required(old==config and self.store.get(c,'share_history')==share_history and self.store.get(c,'h6_options')==h6_options,'This local study is already configured. Delete local data before changing it.')
                return self.summary(c)
            self.store.set(c,'config',config);self.store.set(c,'config_hash',expected_hash);self.store.set(c,'share_history',share_history)
            if h6_config:
                from contracts.h6_bundle.v1.contract import CONSENT as H6_CONSENT
                c.execute('PRAGMA user_version=2')  # Old participant releases must reject H6 stores.
                self.store.set(c,'h6_options',h6_options)
                self.store.add(c,'h6_consent',{'record_id':identifier('h6consent'),'version':'h6-consent-1.0.0','form_hash':sha256(H6_CONSENT),'accepted_at':self.clock(),'collect_h6':True,'grants':{k:v for k,v in h6_options.items() if k!='collect_h6'}})
            self.store.set(c,'processing_consented_at',self.clock());self.store.set(c,'seed',secrets.token_hex(32));self.store.set(c,'sequence',0);self.store.changed(c)
            return self.summary(c)
    def sequence(self,c):
        value=self.store.get(c,'sequence',0)+1;self.store.set(c,'sequence',value);return value
    def audit(self,c,packet,kind,sequence=None,question=None,lock=None):
        return self.store.add(c,'prompt_events',{'record_id':identifier('audit'),'prompt_packet_id':packet,'event_type':kind,'occurred_at':self.clock(),
            'sequence':sequence if sequence is not None else self.sequence(c),'question_id':question['question_id'] if question else None,
            'rendered_question':question,'lock_id':lock})
    def ingest(self,payload,is_zip=False,start=None,end=None):
        stamp=self.clock();incoming_hash=hashlib.sha256(payload).hexdigest()
        with self.store.connect() as c:
            required(self.store.get(c,'config') is not None,'Configure your study first')
            if self.store.get(c,'upload_hash')==incoming_hash:return {**self.summary(c),'duplicate':True}
        with self.store.connect() as c:h6=bool(self.store.get(c,'h6_options'))
        parsed=parse(payload,is_zip,stamp,start,end,capture_h6=h6)
        with self.store.transaction() as c:
            if self.store.records(c,'events'):
                current={r['source_file_sha256'] for r in self.store.records(c,'history_imports')}
                incoming={r['source_file_sha256'] for r in parsed['history_imports']}
                required(current==incoming and [e['event_key'] for e in self.store.records(c,'events')]==[e['event_key'] for e in parsed['events']],
                    'History is frozen for this local study. Delete local data to start again with different history.')
                return {**self.summary(c),'duplicate':True}
            for kind in ['history_imports','tracks','events']:
                for record in parsed[kind]:self.store.add(c,kind,record)
            events=self.store.records(c,'events');tracks=self.store.records(c,'tracks')
            if h6:
                from contracts.h6_bundle.v1.capture import sessions as h6_sessions
                for r in parsed['h6_event_evidence']:self.store.add(c,'h6_event_evidence',r)
                run,session_records=h6_sessions(events,self.clock());self.store.add(c,'h6_sessionization_runs',run)
                for r in session_records:self.store.add(c,'h6_sessions',r)
                from contracts.h6_bundle.v1.transport import MAX_COMPONENT
                required(len(dumps(self.h6_extension(c)))<MAX_COMPONENT-2*1024*1024,'This historical range exceeds the H6 evidence budget. Choose a smaller date range before interviewing.')
            seed=self.store.get(c,'seed');natives,audit=native_results(events,tracks,seed,stamp,self.store.get(c,'share_history'))
            for native in natives:self.store.add(c,'native_candidates',native)
            completed_at=self.clock()
            audit['runtime_started_at']=stamp;audit['runtime_completed_at']=completed_at
            event_index={e['event_key']:e for e in events};track_index={t['record_id']:t for t in tracks}
            windows=[]
            for raw in eligible_universe(events,stamp):
                members=[event_index[key] for key in raw['event_refs']]
                episode_key=sha256({'episode':raw['event_refs']});seen=set();display=[]
                for event in members:
                    if event['track_id'] in seen:continue
                    seen.add(event['track_id']);track=track_index[event['track_id']];display.append({'title':track['title'],'artist':track['artist']})
                ep=self.store.add(c,'episode_snapshots',{'record_id':'episode-'+episode_key,'episode_key':episode_key,
                    'historical_start_at':members[0]['occurred_at'],'historical_end_at':members[-1]['occurred_at'],'episode_available_at':completed_at,
                    'time_quality':'ESTIMATED','event_refs':raw['event_refs'],'display_tracks':display,
                    'source_data_status':'INCLUDED' if self.store.get(c,'share_history') else 'WITHHELD_UNVERIFIABLE'})
                windows.append(self.store.add(c,'eligible_windows',{'record_id':'window-'+raw['window_key'],'episode_id':ep['record_id'],**raw}))
            required(any(w['eligibility']=='ELIGIBLE' for w in windows),'No eligible historical periods. At least three consecutive plays within 30 minutes are needed.')
            scores=mapped_scores(windows,natives)
            for window in windows:
                for arm in ['RANDOM','V0_3','PED']:
                    self.store.add(c,'mappings',{'record_id':'map-'+sha256([window['record_id'],arm]),'window_id':window['record_id'],'arm':arm,**scores[window['record_id']][arm]})
            # Operational sessions can cross midnight; eligible windows additionally split historical UTC days per M0.
            sessions=[]
            for event in events:
                if not sessions or (datetime.fromisoformat(event['occurred_at'].replace('Z','+00:00'))-datetime.fromisoformat(sessions[-1][-1]['occurred_at'].replace('Z','+00:00'))).total_seconds()>1800:sessions.append([])
                sessions[-1].append(event)
            for session in sessions:
                refs=[e['event_key'] for e in session];c.execute('INSERT INTO sessions VALUES(?,?,?,?)',('session-'+sha256(refs),'gap-30m-1',dumps(refs).decode(),'ESTIMATED'))
            # Reject an oversized cohort before anyone spends time answering. The frozen receiver limits apply unchanged.
            from contracts.offline_bundle.v1.archive import MAX_FILE,MAX_EXPANDED
            total=0
            for kind in SECTION_ORDER:
                if kind=='consent' or (not self.store.get(c,'share_history') and kind in {'history_imports','tracks','events'}):continue
                size=sum(len(dumps(record))+1 for record in self.store.records(c,kind));total+=size
                required(size<MAX_FILE-1024*1024,'This date range produces more audit data than the frozen export permits. Choose a smaller historical range.')
            required(total<MAX_EXPANDED-4*1024*1024,'Choose a smaller historical range to stay within the frozen export budget.')
            input_hash=sha256({'event_keys':[e['event_key'] for e in events],'study_config_hash':self.store.get(c,'config_hash'),'sampling_config_hash':sha256(SAMPLING)})
            c.execute('INSERT INTO runs VALUES(?,?,?,?)',('frozen-behavior-1','V03_AND_PED',dumps(audit).decode(),input_hash))
            self.store.set(c,'input_manifest_hash',input_hash);self.store.set(c,'sampling_cutoff_at',stamp);self.store.set(c,'upload_hash',incoming_hash)
            self.store.set(c,'ingest_summary',parsed['summary']);self.store.changed(c)
            return {**self.summary(c),'duplicate':False}
    def summary(self,c):
        config=self.store.get(c,'config');summary=self.store.get(c,'ingest_summary')
        return {'version':VERSION,'configured':config is not None,'study_id':config['study_id'] if config else None,
            'participant_pseudonym':config['participant_pseudonym'] if config else None,'researcher_contact':config['researcher_contact'] if config else None,
            'share_history':self.store.get(c,'share_history',False),'history':summary,
            'sessions':c.execute('SELECT count(*) FROM sessions').fetchone()[0],
            'prompts':[{'prompt_id':p['record_id'],'historical_start_at':p['display_context']['historical_start_at'],
                       'neutral_locked':c.execute('SELECT 1 FROM locks WHERE prompt_id=?',(p['record_id'],)).fetchone() is not None,
                       'completed':any(e['event_type'] in {'COMPLETED','DECLINED','EXPIRED'} for e in self.events(c,p['record_id']))} for p in self.store.records(c,'prompt_packets')],
            'collection_day':self.clock()[:10],'collection_timezone':'UTC','contract_release_hash':self.release_hash,'withdrawal_notice':NOTICE,
            'h6_enabled':bool(self.store.get(c,'h6_options')),'h6_consent_form':__import__('contracts.h6_bundle.v1.contract',fromlist=['CONSENT']).CONSENT,'h6_grants':self.store.get(c,'h6_options'),'consent_form':CONSENT_FORM,'export_count':c.execute('SELECT count(*) FROM exports').fetchone()[0]}
    def state(self):
        with self.store.connect() as c:return self.summary(c)
    def events(self,c,prompt):return [e for e in self.store.records(c,'prompt_events') if e['prompt_packet_id']==prompt]
    def allocate(self):
        with self.store.transaction() as c:
            config=self.store.get(c,'config');required(config and self.store.records(c,'events'),'Import your history first')
            day=self.clock()[:10];existing=c.execute('SELECT assignment_id FROM slots WHERE collection_day=? AND slot=1',(day,)).fetchone()
            if existing:
                packet=next(p for p in self.store.records(c,'prompt_packets') if p['assignment_id']==existing[0]);return {'prompt_id':packet['record_id'],'reused':True}
            required(all(any(e['event_type'] in {'COMPLETED','DECLINED','EXPIRED'} for e in self.events(c,p['record_id'])) for p in self.store.records(c,'prompt_packets')),'Finish or decline your existing reflection first')
            prior=self.store.records(c,'assignments');windows=self.store.records(c,'eligible_windows');natives=self.store.records(c,'native_candidates')
            chosen_refs=set()
            for a in prior:chosen_refs.update(self.store.record(c,a['window_id'])['event_refs'])
            unit={'study_id':config['study_id'],'participant_pseudonym':config['participant_pseudonym'],'collection_day':day,'slot_ordinal':1}
            choice=allocate_slot(windows,natives,self.store.get(c,'seed'),unit,prior_event_refs=chosen_refs)
            stamp=self.clock();assignment=self.store.add(c,'assignments',{'record_id':identifier('assignment'),**choice,'collection_day':day,'collection_timezone':'UTC','slot_ordinal':1,
                'decision_at':stamp,'available_arms':['RANDOM','V0_3','PED'],'seed':self.store.get(c,'seed'),'prior_assignment_ids':[a['record_id'] for a in prior],
                'cumulative_inclusion_probability':None,'probability_basis':SAMPLING['probability_basis']})
            episode=self.store.record(c,self.store.record(c,choice['window_id'])['episode_id'])
            packet=self.store.add(c,'prompt_packets',{'record_id':identifier('prompt'),'assignment_id':assignment['record_id'],'episode_id':episode['record_id'],
                'rendered_neutral_questions':QUESTIONS['neutral_questions'],'allowed_followup_question_ids':[] if self.store.get(c,'h6_options') else [q['question_id'] for q in QUESTIONS['followup_questions']],
                'display_context':{'tracks':episode['display_tracks'],'historical_start_at':episode['historical_start_at'],'historical_end_at':episode['historical_end_at'],'time_quality':episode['time_quality']},
                'created_at':stamp,'available_at':stamp})
            c.execute('INSERT INTO slots VALUES(?,?,?)',(day,1,assignment['record_id']));self.audit(c,packet['record_id'],'CREATED');self.store.changed(c)
            return {'prompt_id':packet['record_id'],'reused':False}
    def prompt(self,prompt_id):
        with self.store.transaction() as c:
            packet=self.store.record(c,prompt_id);timeline=self.events(c,prompt_id);lock=c.execute('SELECT * FROM locks WHERE prompt_id=?',(prompt_id,)).fetchone()
            completed=any(e['event_type'] in {'COMPLETED','DECLINED','EXPIRED'} for e in timeline)
            if not lock and not completed and not any(e['event_type']=='OPENED' for e in timeline):self.audit(c,prompt_id,'OPENED');self.store.changed(c)
            draft=c.execute('SELECT payload FROM drafts WHERE prompt_id=?',(prompt_id,)).fetchone()
            optional_draft=c.execute('SELECT payload FROM followup_drafts WHERE prompt_id=?',(prompt_id,)).fetchone()
            neutral=next((s for s in self.store.records(c,'submissions') if s['prompt_packet_id']==prompt_id and s['stage']=='NEUTRAL'),None)
            return {'prompt_id':prompt_id,'display_context':packet['display_context'],'neutral_questions':packet['rendered_neutral_questions'],
                'neutral_locked':bool(lock),'completed':completed,'draft':json.loads(draft[0]) if draft else None,
                'neutral_answers':neutral['answers'] if neutral else None,'followup_draft':json.loads(optional_draft[0]) if optional_draft else None,'followups':self.h6_shown(c,prompt_id) if self.store.get(c,'h6_options') else [e['rendered_question'] for e in timeline if e['event_type']=='FOLLOWUP_SHOWN']}
    def save_draft(self,prompt_id,answers):
        required(isinstance(answers,list) and len(dumps(answers))<=12000,'Invalid draft')
        with self.store.transaction() as c:
            self.store.record(c,prompt_id)
            required(not c.execute('SELECT 1 FROM locks WHERE prompt_id=?',(prompt_id,)).fetchone(),'Your neutral response is locked')
            required(not any(e['event_type'] in {'COMPLETED','DECLINED','EXPIRED'} for e in self.events(c,prompt_id)),'Reflection is finished')
            c.execute('INSERT INTO drafts VALUES(?,?) ON CONFLICT(prompt_id) DO UPDATE SET payload=excluded.payload',(prompt_id,dumps(answers).decode()))
        return {'saved':True}
    def save_followup_draft(self,prompt_id,answers):
        required(isinstance(answers,list) and len(dumps(answers))<=12000,'Invalid optional draft')
        with self.store.transaction() as c:
            required(c.execute('SELECT 1 FROM locks WHERE prompt_id=?',(prompt_id,)).fetchone() is not None,'Neutral responses must be locked first')
            required(not any(e['event_type'] in {'COMPLETED','DECLINED','EXPIRED','FOLLOWUP_LOCKED'} for e in self.events(c,prompt_id)),'Reflection is finished')
            required(bool(self.h6_shown(c,prompt_id)) if self.store.get(c,'h6_options') else any(e['event_type']=='FOLLOWUP_SHOWN' for e in self.events(c,prompt_id)),'Open the optional questions first')
            c.execute('INSERT INTO followup_drafts VALUES(?,?) ON CONFLICT(prompt_id) DO UPDATE SET payload=excluded.payload',(prompt_id,dumps(answers).decode()))
        return {'saved':True}
    def check_answers(self,answers,questions):
        required(isinstance(answers,list) and len(answers)==len(questions),'Answer both required questions or choose an uncertainty option')
        for a,q in zip(answers,questions):
            required(isinstance(a,dict) and set(a)=={'question_id','question_version','value'} and a['question_id']==q['question_id'] and a['question_version']==q['version'],'Question version/order mismatch')
            required(Draft202012Validator(q['response_schema']).is_valid(a['value']),'Choose a valid answer or uncertainty option')
    def neutral(self,prompt_id,answers):
        self.check_answers(answers,QUESTIONS['neutral_questions'])
        recognition=answers[0]['value'];meaning=answers[1]['value']
        if recognition in {'NOT_RECALLED','UNSURE','NOT_APPLICABLE','DECLINED'}:required(meaning['status']==recognition and meaning['value'] is None,'Non-recalled/unknown meaningfulness cannot be scored numerically')
        with self.store.transaction() as c:
            self.store.record(c,prompt_id);existing=c.execute('SELECT * FROM locks WHERE prompt_id=?',(prompt_id,)).fetchone()
            if existing:
                previous=self.store.record(c,existing['submission_id']);required(previous['answers']==answers,'Your neutral response is already locked with different answers')
                return {'locked':True,'submission_id':existing['submission_id'],'duplicate':True}
            timeline=self.events(c,prompt_id)
            required(any(e['event_type']=='OPENED' for e in timeline) and not any(e['event_type'] in {'COMPLETED','DECLINED','EXPIRED'} for e in timeline),'Open an active reflection before answering')
            stamp=self.clock();sequence=self.sequence(c)
            submission=self.store.add(c,'submissions',{'record_id':identifier('submission'),'prompt_packet_id':prompt_id,'stage':'NEUTRAL','submitted_at':stamp,'locked_at':stamp,'sequence':sequence,'answers':answers})
            lock=self.store.add(c,'locks',{'record_id':identifier('lock'),'neutral_submission_id':submission['record_id'],'prompt_packet_id':prompt_id,'locked_at':stamp,'sequence':sequence,'answer_set_hash':sha256(answers),'policy_version':'durable-neutral-lock-1.0.0'})
            c.execute('DELETE FROM drafts WHERE prompt_id=?',(prompt_id,));c.execute('INSERT INTO locks VALUES(?,?,?)',(prompt_id,submission['record_id'],lock['record_id']))
            self.audit(c,prompt_id,'NEUTRAL_LOCKED',sequence=sequence,lock=lock['record_id']);self.store.changed(c)
            if self.store.get(c,'h6_options'):self.h6_select(c,prompt_id,lock,answers)
            return {'locked':True,'submission_id':submission['record_id'],'duplicate':False}
    def followups(self,prompt_id):
        with self.store.connect() as c:h6=bool(self.store.get(c,'h6_options'))
        if h6:return self.h6_followups(prompt_id)
        with self.store.transaction() as c:
            packet=self.store.record(c,prompt_id);lock=c.execute('SELECT * FROM locks WHERE prompt_id=?',(prompt_id,)).fetchone()
            required(lock is not None,'Save and lock the neutral response first')
            timeline=self.events(c,prompt_id);shown=[e['rendered_question'] for e in timeline if e['event_type']=='FOLLOWUP_SHOWN']
            if shown:return {'questions':shown}
            required(not any(e['event_type'] in {'COMPLETED','DECLINED','EXPIRED'} for e in timeline),'Reflection is finished')
            # Same versioned two-question cap for every arm; the sequence question is relevant to multi-track windows.
            questions=QUESTIONS['followup_questions'][:2]
            for q in questions:self.audit(c,prompt_id,'FOLLOWUP_SHOWN',question=q,lock=lock['lock_id'])
            self.store.changed(c);return {'questions':questions}
    def followup(self,prompt_id,answers):
        with self.store.connect() as c:h6=bool(self.store.get(c,'h6_options'))
        if h6:return self.h6_answer(prompt_id,answers)
        with self.store.transaction() as c:
            lock=c.execute('SELECT * FROM locks WHERE prompt_id=?',(prompt_id,)).fetchone();required(lock is not None,'Neutral response must be locked first')
            timeline=self.events(c,prompt_id);shown=[e['rendered_question'] for e in timeline if e['event_type']=='FOLLOWUP_SHOWN']
            required(shown,'Open the optional questions first');self.check_answers(answers,shown)
            existing=next((s for s in self.store.records(c,'submissions') if s['prompt_packet_id']==prompt_id and s['stage']=='FOLLOWUP'),None)
            if existing:required(existing['answers']==answers,'Follow-up already saved with different answers');return {'saved':True,'duplicate':True}
            required(not any(e['event_type']=='COMPLETED' for e in timeline),'Reflection is finished')
            stamp=self.clock();sequence=self.sequence(c)
            self.store.add(c,'submissions',{'record_id':identifier('submission'),'prompt_packet_id':prompt_id,'stage':'FOLLOWUP','submitted_at':stamp,'locked_at':stamp,'sequence':sequence,'answers':answers})
            c.execute('DELETE FROM followup_drafts WHERE prompt_id=?',(prompt_id,))
            self.audit(c,prompt_id,'FOLLOWUP_LOCKED',sequence=sequence,lock=lock['lock_id']);self.audit(c,prompt_id,'COMPLETED',lock=lock['lock_id']);self.store.changed(c)
            return {'saved':True,'duplicate':False}
    def finish(self,prompt_id):
        with self.store.transaction() as c:
            self.store.record(c,prompt_id);timeline=self.events(c,prompt_id)
            if any(e['event_type'] in {'COMPLETED','DECLINED','EXPIRED'} for e in timeline):return {'finished':True}
            lock=c.execute('SELECT * FROM locks WHERE prompt_id=?',(prompt_id,)).fetchone()
            if lock and self.store.get(c,'h6_options'):self.h6_complete(c,prompt_id,lock)
            self.audit(c,prompt_id,'COMPLETED' if lock else 'DECLINED',lock=lock['lock_id'] if lock else None);self.store.changed(c)
            return {'finished':True}
    def assemble(self,c,consent):
        config=self.store.get(c,'config');share=self.store.get(c,'share_history');seed=self.store.get(c,'seed');events=self.store.records(c,'events');stamp=self.clock()
        data={kind:self.store.records(c,kind) for kind in SECTION_ORDER if kind!='consent'}
        if not share:
            for kind in ['history_imports','tracks','events']:data[kind]=[]
        return {'manifest':{'format':'resonance-bundle','schema_version':'1.0.0','bundle_id':identifier('bundle'),'study_id':config['study_id'],
            'participant_pseudonym':config['participant_pseudonym'],'protocol_version':'offline-retro-mvp-1.0.0-draft','temporal_mode':'RETROSPECTIVE_REPLAY',
            'trial_type':'THREE_ARM_PILOT','app_release':VERSION,'generated_at':stamp,'previous_bundle_id':self.store.get(c,'last_bundle_id'),
            'export_scope':'HISTORY_AND_RESPONSES' if share else 'RESPONSES_ONLY','question_bank_hash':sha256(QUESTIONS),'sampling_config_hash':sha256(SAMPLING),
            'content_hash':'0'*64,'integrity_hash':'0'*64,'test_only':False},'consent':consent,
            'provenance':{'source_data_status':'INCLUDED' if share else 'WITHHELD_UNVERIFIABLE','input_manifest_hash':self.store.get(c,'input_manifest_hash'),
                'source_coverage_start_at':min(e['occurred_at'] for e in events),'source_coverage_end_at':max(e['occurred_at'] for e in events),
                'sampling_cutoff_at':self.store.get(c,'sampling_cutoff_at'),'participant_clock_status':'DEVICE_REPORTED_NOT_INDEPENDENTLY_VERIFIED',
                'sampling_seed':seed,'seed_commitment':sha256(seed)},**data,
            'export_preview':{'sections':[],'presented_at':stamp,'notice_version':'offline-withdrawal-1.0.0','notice':NOTICE},
            'export_authorization':{'consent_record_id':consent['record_id'],'preview_hash':'0'*64,'explicitly_confirmed':False,'confirmed_at':stamp,
                'encryption':'age-v1','recipient_fingerprint':config['recipient_fingerprint']}}
    def preview(self,share_responses):
        required(share_responses is True,'Explicit consent to sharing your responses is required')
        with self.store.transaction() as c:
            required(self.store.records(c,'events') and self.store.records(c,'prompt_packets'),'Import history and complete or decline a reflection first')
            required(all(any(e['event_type'] in {'COMPLETED','DECLINED','EXPIRED'} for e in self.events(c,p['record_id'])) for p in self.store.records(c,'prompt_packets')),'Finish your reflection before viewing the full research export')
            consents=self.store.records(c,'consent')
            consent=consents[0] if consents else self.store.add(c,'consent',{'record_id':identifier('consent'),'version':'offline-consent-1.0.0',
                'form_hash':sha256(CONSENT_FORM),'accepted_at':self.clock(),'grants':{'share_responses':True,'share_listening_history':self.store.get(c,'share_history')},'withdrawal_notice_version':'offline-withdrawal-1.0.0'})
            document=self.assemble(c,consent);seal(document);document['export_preview']['sections']=preview_sections(document)
            document['export_authorization']['preview_hash']=sha256(document['export_preview']);seal(document)
            # Validate every field before asking for the final confirmation; the temporary check is never stored/exported as consent.
            if self.store.get(c,'h6_options'):document=self.h6_wrap(c,document)
            checked=deepcopy(document)
            if self.store.get(c,'h6_options'):
                from contracts.h6_bundle.v1.contract import refresh,validate as validate_h6
                checked['core']['export_authorization'].update(explicitly_confirmed=True,confirmed_at=self.clock());seal(checked['core'])
                checked['export_authorization'].update(explicitly_confirmed=True,confirmed_at=self.clock());refresh(checked);validate_h6(checked)
            else:checked['export_authorization']['explicitly_confirmed']=True;seal(checked);validate(checked)
            from contracts.h6_bundle.v1.transport import encode_any,decode_any
            decode_any(encode_any(checked))
            preview_id=identifier('preview');c.execute('INSERT INTO previews VALUES(?,?,?,?)',(preview_id,self.store.revision(c),dumps(document).decode(),document['export_authorization']['preview_hash']))
            return {'preview_id':preview_id,'preview_hash':document['export_authorization']['preview_hash'],'document':document}
    def export(self,preview_id,preview_hash,confirmed):
        required(confirmed is True,'Confirm the preview before saving an encrypted package')
        with self.store.transaction() as c:
            pending=c.execute('SELECT * FROM previews WHERE id=?',(preview_id,)).fetchone();required(pending is not None,'Preview not found')
            required(pending['preview_hash']==preview_hash,'Export preview fingerprint differs')
            prior=c.execute('SELECT * FROM exports WHERE preview_id=?',(preview_id,)).fetchone()
            if prior:return {'export_id':prior['id'],'bundle_id':prior['bundle_id'],'download_url':'/api/exports/'+prior['id']}
            required(pending['revision']==self.store.revision(c) and pending['preview_hash']==preview_hash,'Your study changed. Review a fresh export preview.')
            document=loads(pending['payload'])
            if document['manifest']['format']=='resonance-h6-bundle':
                from contracts.h6_bundle.v1.contract import refresh,validate as validate_h6
                document['core']['export_authorization'].update(explicitly_confirmed=True,confirmed_at=self.clock());document['core']['manifest']['generated_at']=self.clock();seal(document['core'])
                document['export_authorization'].update(explicitly_confirmed=True,confirmed_at=self.clock());document['manifest']['generated_at']=self.clock();refresh(document);validate_h6(document)
            else:
                document['export_authorization'].update(explicitly_confirmed=True,confirmed_at=self.clock());document['manifest']['generated_at']=self.clock();seal(document);validate(document)
            from contracts.h6_bundle.v1.transport import encrypt
            config=self.store.get(c,'config');cipher=encrypt(document,config['recipient'],config['recipient_fingerprint'])
            export_id=identifier('export');c.execute('INSERT INTO exports VALUES(?,?,?,?,?)',(export_id,preview_id,document['manifest']['bundle_id'],dumps(document).decode(),cipher))
            self.store.set(c,'last_bundle_id',document['manifest']['bundle_id']);self.store.changed(c)
            return {'export_id':export_id,'bundle_id':document['manifest']['bundle_id'],'download_url':'/api/exports/'+export_id}
    def download(self,export_id):
        with self.store.connect() as c:
            row=c.execute('SELECT bundle_id,cipher FROM exports WHERE id=?',(export_id,)).fetchone();required(row is not None,'Export not found')
            return row['bundle_id']+'.resonance.age',row['cipher']
