import json,tempfile,unittest,sqlite3
from pathlib import Path
from copy import deepcopy
import pyrage
from participant.app import ParticipantApp
from contracts.offline_bundle.v1.canonical import sha256,dumps
from contracts.offline_bundle.v1.release import verify_release
from contracts.offline_bundle.v1.crypto import recipient_fingerprint
from contracts.offline_bundle.v1.validate import validate as validate_core,QUESTIONS
from contracts.h6_bundle.v1.release import verify_release as h6_release
from contracts.h6_bundle.v1.contract import PROTOCOL,validate
from contracts.h6_bundle.v1.transport import decrypt_any

STAMP='2026-11-03T12:00:00.000Z'

def history():
    rows=json.loads((Path(__file__).parent/'fixtures/h6-shuffled-history.json').read_bytes())
    for row in rows:row.update(duration_ms=180000,track_duration_ms=180000,trackDurationMs=180000,playback_source='PLAYLIST',manual_selection=False,
        context_uri='spotify:playlist:SYNTHETIC',playlist_uri='spotify:playlist:SYNTHETIC',playlist_name='H6_SENSITIVE_PLAYLIST',isrc='USAAA2600001',
        username='DO_NOT_EXPORT_ACCOUNT',ip_address='DO_NOT_EXPORT_IP',access_token='DO_NOT_EXPORT_TOKEN',psychological_classification='DO_NOT_CLASSIFY')
    return json.dumps(rows).encode()

def setup(directory,share_history=True,event=True,playlist=True,followups=True):
    identity=pyrage.x25519.Identity.generate();recipient=str(identity.to_public());fp=recipient_fingerprint(recipient)
    config={'version':'participant-study-h6-1.0.0','study_id':'h6-retrospective-pilot','participant_pseudonym':'P-SYNTHETIC','recipient':recipient,'recipient_fingerprint':fp,
        'contract_release_hash':verify_release(),'h6_contract_release_hash':h6_release(),'protocol_version':PROTOCOL,'researcher_contact':'Synthetic test contact'}
    options={'collect_h6':True,'share_event_evidence':event,'share_playlist_context':playlist,'share_followup_evidence':followups}
    app=ParticipantApp(Path(directory)/'data',lambda:STAMP);app.configure(config,sha256(config),True,share_history,options)
    with app.store.transaction() as c:app.store.set(c,'seed','h6-seed-fixed')
    return app,identity,fp,config,options

def interview(app,respond=True):
    pid=app.allocate()['prompt_id'];app.prompt(pid)
    answers=[{'question_id':'episode.recognition','question_version':'1.0.0','value':'CLEAR'},
        {'question_id':'episode.meaningfulness','question_version':'1.0.0','value':{'status':'KNOWN','value':6}}]
    app.neutral(pid,answers);questions=app.followups(pid)['questions']
    if respond:
        app.followup(pid,[{'question_id':q['question_id'],'question_version':q['version'],'value':{'status':'ANSWERED','activities':['WORK_STUDY'],'attention':'VARIED','manual_control':'UNSURE','description':'Synthetic task'} if q['domain']=='CONTEXT' else {'status':'UNSURE'}} for q in questions])
    else:app.finish(pid)
    return pid,answers

def export(app,identity,fp):
    preview=app.preview(True);result=app.export(preview['preview_id'],preview['preview_hash'],True)
    return decrypt_any(app.download(result['export_id'])[1],str(identity),fp)

class H6Extension(unittest.TestCase):
    def test_full_capture_preserves_authorized_fields_and_sessions_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            app,identity,fp,_,_=setup(directory);app.ingest(history());pid,answers=interview(app)
            reopened=ParticipantApp(Path(directory)/'data',lambda:STAMP);bundle=export(reopened,identity,fp)
            validate(bundle);validate_core(bundle['core']);ext=bundle['extension']
            self.assertEqual(bundle['manifest']['protocol_version'],PROTOCOL)
            self.assertEqual(bundle['core']['submissions'][0]['answers'],answers)
            self.assertEqual(bundle['core']['prompt_packets'][0]['rendered_neutral_questions'],QUESTIONS['neutral_questions'])
            self.assertEqual(bundle['core']['prompt_packets'][0]['allowed_followup_question_ids'],[])
            self.assertEqual(len(ext['sessions']),2);self.assertEqual(sum(len(s['event_refs']) for s in ext['sessions']),8)
            self.assertEqual(sum(len(s['transitions']) for s in ext['sessions']),6)
            self.assertEqual(len(ext['followup_exposures']),2)
            for e in ext['event_evidence']:
                self.assertEqual(e['native']['playlist_name'],'H6_SENSITIVE_PLAYLIST');self.assertEqual(e['native']['duration_ms'],180000)
                self.assertEqual(e['normalized']['recording_duration_ms'],180000);self.assertFalse(e['normalized']['manual_selection'])
            raw=dumps(bundle).decode()
            for forbidden in ['DO_NOT_EXPORT_ACCOUNT','DO_NOT_EXPORT_IP','DO_NOT_EXPORT_TOKEN','DO_NOT_CLASSIFY']:self.assertNotIn(forbidden,raw)
            self.assertTrue(reopened.prompt(pid)['neutral_locked'])
    def test_scope_redaction_and_responses_only_do_not_fabricate_events(self):
        for share,event,playlist,followups in [(True,True,False,True),(False,False,False,True),(True,False,False,False)]:
            with self.subTest(scope=(share,event,playlist,followups)),tempfile.TemporaryDirectory() as directory:
                app,identity,fp,_,_=setup(directory,share,event,playlist,followups);app.ingest(history());interview(app)
                bundle=export(app,identity,fp);validate(bundle);ext=bundle['extension']
                self.assertNotIn('H6_SENSITIVE_PLAYLIST',dumps(bundle).decode())
                self.assertEqual(bool(ext['event_evidence']),event);self.assertEqual(bool(ext['followup_submissions']),followups)
                if not event:self.assertEqual(ext['sessions'],[])
                if not share:self.assertEqual(bundle['core']['events'],[]);self.assertEqual(bundle['core']['tracks'],[])
                if not followups:
                    self.assertEqual(ext['followup_exposures'],[]);self.assertEqual(ext['followup_selections'],[])
    def test_neutral_and_h6_locking_cap_versions_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            app,identity,fp,_,_=setup(directory);app.ingest(history());pid=app.allocate()['prompt_id'];app.prompt(pid)
            with self.assertRaises(ValueError):app.followups(pid)
            answers=[{'question_id':'episode.recognition','question_version':'1.0.0','value':'CLEAR'},{'question_id':'episode.meaningfulness','question_version':'1.0.0','value':{'status':'KNOWN','value':4}}]
            app.neutral(pid,answers);questions=app.followups(pid)['questions'];self.assertEqual(questions,app.followups(pid)['questions']);self.assertLessEqual(len(questions),2)
            bad=deepcopy(answers);bad[1]['value']['value']=1
            with self.assertRaises(ValueError):app.neutral(pid,bad)
            response=[{'question_id':q['question_id'],'question_version':q['version'],'value':{'status':'UNSURE'}} for q in questions]
            wrong=deepcopy(response);wrong[0]['question_version']='0.1.0'
            with self.assertRaises(ValueError):app.followup(pid,wrong)
            app.followup(pid,response);self.assertTrue(app.followup(pid,response)['duplicate'])
            wrong=deepcopy(response);wrong[0]['value']={'status':'DECLINED'}
            with self.assertRaises(ValueError):app.followup(pid,wrong)
            with app.store.connect() as c:
                with self.assertRaises(sqlite3.IntegrityError):c.execute("UPDATE records SET payload='{}' WHERE kind='h6_followup_submissions'")
            validate(export(app,identity,fp))
    def test_new_consent_is_required_and_cannot_silently_expand(self):
        with tempfile.TemporaryDirectory() as directory:
            app,_,_,config,options=setup(directory,False,False,False,False)
            changed={**options,'share_followup_evidence':True}
            with self.assertRaises(ValueError):app.configure(config,sha256(config),True,False,changed)
            other=ParticipantApp(Path(directory)/'other',lambda:STAMP)
            with self.assertRaises(ValueError):other.configure(config,sha256(config),True,False)
            with self.assertRaises(ValueError):other.configure(config,sha256(config),True,False,{**options,'collect_h6':False})
    def test_finishing_without_followups_records_skipped_questions(self):
        with tempfile.TemporaryDirectory() as directory:
            app,identity,fp,_,_=setup(directory);app.ingest(history());interview(app,False)
            ext=export(app,identity,fp)['extension']
            self.assertEqual(ext['followup_completions'][0]['answered_question_ids'],[])
            self.assertEqual(len(ext['followup_completions'][0]['skipped_question_ids']),2)

if __name__=='__main__':unittest.main()
