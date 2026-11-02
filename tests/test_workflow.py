import io
import json
import os
import socket
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
import pyrage
from contracts.offline_bundle.v1.canonical import sha256
from contracts.offline_bundle.v1.crypto import decrypt_bundle,recipient_fingerprint
from contracts.offline_bundle.v1.release import verify_release
from contracts.offline_bundle.v1.validate import validate,QUESTIONS
from contracts.offline_bundle.v1.sampling import allocate_slot
from participant.app import ParticipantApp
from participant.sampling import verify_native
from participant.ingest import parse


def history():
    rows=[]
    for day in range(4):
        for index in range(16):
            stamp=(datetime(2026,3,1+day,10,tzinfo=timezone.utc)+timedelta(minutes=index*2)).isoformat().replace('+00:00','Z')
            rows.append({'ts':stamp,'ms_played':60000,'master_metadata_track_name':'Track '+str(index%4),'master_metadata_album_artist_name':'Synthetic artist',
                'spotify_track_uri':'spotify:track:synthetic'+str(index%4),'skipped':index%4==0,'reason_start':'clickrow','reason_end':'trackdone','shuffle':False,
                'username':'DO_NOT_RETAIN_ACCOUNT','ip_addr':'192.0.2.10','platform':'DO_NOT_RETAIN_DEVICE'})
    return json.dumps(rows).encode()

class Clock:
    value='2026-11-02T12:00:00.000Z'
    def __call__(self):return self.value

class Workflow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.clock=Clock();self.directory=Path(self.temp.name)/'data'
        self.identity=pyrage.x25519.Identity.generate();recipient=str(self.identity.to_public());self.fingerprint=recipient_fingerprint(recipient)
        self.config={'version':'participant-study-1.0.0','study_id':'synthetic-pilot','participant_pseudonym':'P-SYNTHETIC','recipient':recipient,'recipient_fingerprint':self.fingerprint,
            'contract_release_hash':verify_release(),'researcher_contact':'Synthetic study contact — no real participant data'}
        self.app=ParticipantApp(self.directory,self.clock)
    def setup(self,share=True):self.app.configure(self.config,sha256(self.config),True,share)
    def ready(self,share=True):self.setup(share);return self.app.ingest(history())
    def answers(self,recognition='CLEAR',value=6):
        return [{'question_id':QUESTIONS['neutral_questions'][0]['question_id'],'question_version':'1.0.0','value':recognition},
            {'question_id':QUESTIONS['neutral_questions'][1]['question_id'],'question_version':'1.0.0','value':{'status':'KNOWN','value':value} if recognition=='CLEAR' else {'status':recognition,'value':None}}]
    def interview(self):
        prompt=self.app.allocate()['prompt_id'];self.app.prompt(prompt);self.app.neutral(prompt,self.answers());self.app.finish(prompt);return prompt
    def test_frozen_native_files_and_private_boundaries(self):
        verify_native();root=Path(__file__).resolve().parents[1]
        for forbidden in ['api','investigator','music','models','audio']:
            self.assertFalse((root/forbidden).exists())
    def test_config_requires_explicit_consent_and_pinned_recipient(self):
        with self.assertRaises(ValueError):self.app.configure(self.config,'0'*64,True,False)
        with self.assertRaises(ValueError):self.app.configure(self.config,sha256(self.config),False,False)
        self.setup();self.assertTrue(self.app.state()['configured'])
    def test_spotify_ingestion_sessions_reimport_and_privacy(self):
        result=self.ready();self.assertEqual(result['history']['music_events'],64);self.assertEqual(result['sessions'],4)
        self.assertTrue(self.app.ingest(history())['duplicate'])
        with self.app.store.connect() as c:
            payload='\n'.join(r[0] for r in c.execute('SELECT payload FROM records'))
            self.assertNotIn('DO_NOT_RETAIN_ACCOUNT',payload);self.assertNotIn('192.0.2.10',payload);self.assertNotIn('DO_NOT_RETAIN_DEVICE',payload)
            self.assertTrue(all(e['observed_start_at'] is None and e['time_quality']=='ESTIMATED' for e in self.app.store.records(c,'events')))
    def test_invalid_history_is_atomic_and_source_semantics_nullable(self):
        self.setup()
        for payload in [b'{}',b'[{"ts":"invalid"}]',b'[{"trackName":"A","artistName":"B","endTime":"nonsense","msPlayed":10}]']:
            with self.assertRaises(ValueError):self.app.ingest(payload)
        self.assertIsNone(self.app.state()['history'])
        legacy=json.dumps([{'endTime':f'2026-03-01 10:{i*2:02}','trackName':'Track','artistName':'Artist','msPlayed':60000} for i in range(4)]).encode()
        parsed=parse(legacy,False,self.clock());self.assertTrue(all(e['skipped'] is None for e in parsed['events']))
    def test_zip_traversal_and_duplicate_paths_are_rejected(self):
        self.setup();buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:z.writestr('../Streaming_History.json',history())
        with self.assertRaises(ValueError):self.app.ingest(buffer.getvalue(),True)
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:z.writestr('Spotify/Streaming_History_Audio_0.json',history())
        self.assertEqual(self.app.ingest(buffer.getvalue(),True)['history']['music_events'],64)
    def test_slot_reproducibility_daily_budget_and_no_duplicate_prompts(self):
        self.ready();a=self.app.allocate();self.assertEqual(self.app.allocate()['prompt_id'],a['prompt_id'])
        with self.app.store.connect() as c:
            record=self.app.store.records(c,'assignments')[0];config=self.app.store.get(c,'config')
            unit={'study_id':config['study_id'],'participant_pseudonym':config['participant_pseudonym'],'collection_day':self.clock()[:10],'slot_ordinal':1}
            expected=allocate_slot(self.app.store.records(c,'eligible_windows'),self.app.store.records(c,'native_candidates'),record['seed'],unit)
            self.assertTrue(all(record[k]==v for k,v in expected.items()))
        self.app.prompt(a['prompt_id']);self.app.neutral(a['prompt_id'],self.answers());self.app.finish(a['prompt_id'])
        self.clock.value='2026-11-03T12:00:00.000Z';b=self.app.allocate();self.assertNotEqual(a['prompt_id'],b['prompt_id'])
        with self.app.store.connect() as c:
            assignments=self.app.store.records(c,'assignments');refs=[set(self.app.store.record(c,x['window_id'])['event_refs']) for x in assignments]
            self.assertFalse(refs[0]&refs[1])
    def test_followups_denied_before_atomic_neutral_lock_and_retries_idempotent(self):
        self.ready();prompt=self.app.allocate()['prompt_id'];self.app.prompt(prompt)
        with self.assertRaises(ValueError):self.app.followups(prompt)
        answers=self.answers();self.app.neutral(prompt,answers);self.assertTrue(self.app.neutral(prompt,answers)['duplicate'])
        with self.assertRaises(ValueError):self.app.neutral(prompt,self.answers(value=1))
        self.assertEqual(len(self.app.followups(prompt)['questions']),2);self.assertEqual(len(self.app.followups(prompt)['questions']),2)
        with self.app.store.connect() as c:
            self.assertEqual(len([e for e in self.app.store.records(c,'prompt_events') if e['event_type']=='FOLLOWUP_SHOWN']),2)
            with self.assertRaises(sqlite3.IntegrityError):c.execute('UPDATE records SET payload=? WHERE kind=?',('{}','submissions'))
    def test_concurrent_neutral_submissions_commit_only_one(self):
        self.ready();prompt=self.app.allocate()['prompt_id'];self.app.prompt(prompt)
        def submit(value):
            try:self.app.neutral(prompt,self.answers(value=value));return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=2) as workers:results=list(workers.map(submit,[1,6]))
        self.assertEqual(sum(results),1)
        with self.app.store.connect() as c:self.assertEqual(len(self.app.store.records(c,'submissions')),1);self.assertEqual(len(self.app.store.records(c,'locks')),1)
    def test_progress_and_draft_survive_close_and_reopen(self):
        self.ready();prompt=self.app.allocate()['prompt_id'];self.app.prompt(prompt);self.app.save_draft(prompt,self.answers())
        reopened=ParticipantApp(self.directory,self.clock);self.assertEqual(reopened.prompt(prompt)['draft'],self.answers())
        reopened.neutral(prompt,self.answers());again=ParticipantApp(self.directory,self.clock);self.assertTrue(again.prompt(prompt)['neutral_locked'])
        with self.assertRaises(ValueError):again.save_draft(prompt,self.answers(value=1))
    def test_history_export_and_full_m0_validation_after_restart(self):
        self.ready();prompt=self.app.allocate()['prompt_id'];self.app.prompt(prompt);self.app.neutral(prompt,self.answers())
        questions=self.app.followups(prompt)['questions'];self.app.followup(prompt,[{'question_id':q['question_id'],'question_version':q['version'],'value':{'status':'UNSURE','value':None}} for q in questions])
        self.app=ParticipantApp(self.directory,self.clock);preview=self.app.preview(True)
        with self.assertRaises(ValueError):self.app.export(preview['preview_id'],preview['preview_hash'],False)
        exported=self.app.export(preview['preview_id'],preview['preview_hash'],True);filename,cipher=self.app.download(exported['export_id'])
        captured=decrypt_bundle(cipher,str(self.identity),self.fingerprint)
        self.assertEqual(validate(captured)['source_data_status'],'INCLUDED');self.assertEqual(len(captured['events']),64)
        self.assertEqual(captured['prompt_packets'][0]['rendered_neutral_questions'],QUESTIONS['neutral_questions']);self.assertTrue(filename.endswith('.resonance.age'))
        self.assertEqual(self.app.export(preview['preview_id'],preview['preview_hash'],True),exported)
    def test_responses_only_unknowns_remain_unknown(self):
        self.ready(False);prompt=self.app.allocate()['prompt_id'];self.app.prompt(prompt);self.app.neutral(prompt,self.answers('NOT_RECALLED'));self.app.finish(prompt)
        preview=self.app.preview(True);exported=self.app.export(preview['preview_id'],preview['preview_hash'],True)
        captured=decrypt_bundle(self.app.download(exported['export_id'])[1],str(self.identity),self.fingerprint)
        self.assertEqual(captured['events'],[]);self.assertEqual(captured['tracks'],[])
        self.assertEqual(validate(captured)['source_data_status'],'WITHHELD_UNVERIFIABLE')
        self.assertIsNone(captured['submissions'][0]['answers'][1]['value']['value'])
    def test_local_erasure_clears_raw_derived_answers_and_cached_exports(self):
        self.ready();self.interview();preview=self.app.preview(True);self.app.export(preview['preview_id'],preview['preview_hash'],True)
        self.app.store.erase();self.assertFalse(self.app.state()['configured'])
        with self.app.store.connect() as c:
            for table in ['records','sessions','runs','slots','locks','exports','previews','drafts']:self.assertEqual(c.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

if __name__=='__main__':unittest.main()
