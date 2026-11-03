import json
from pathlib import Path
import unittest
from participant.ingest import parse,opportunity
from participant.sampling import observations,verify_native

PATH=Path(__file__).parent/'fixtures/h6-shuffled-history.json'
STAMP='2026-11-03T10:00:00.000Z'

class Capture(unittest.TestCase):
    def test_known_unknown_reversal_native_reasons_and_played_ms(self):
        result=parse(PATH.read_bytes(),False,STAMP);events=result['events']
        self.assertEqual([e['skipped'] for e in events[:3]],[True,False,None])
        self.assertEqual(events[0]['track_id'],events[4]['track_id'])
        self.assertNotEqual(events[0]['event_key'],events[4]['event_key'])
        self.assertEqual(events[4]['skipped'],False)
        self.assertEqual(events[0]['reason_end'],'fwdbtn')
        self.assertEqual(events[4]['reason_end'],'trackdone')
        self.assertTrue(all(e['shuffle'] is True for e in events))
        self.assertEqual(events[0]['played_ms'],2000)
        self.assertIsNone(events[0]['observed_start_at'])
        self.assertEqual(events[0]['time_quality'],'ESTIMATED')
        self.assertEqual(events[0]['estimated_start_at'],'2026-03-01T09:59:58.000Z')
        self.assertNotIn('listening_position',events[0])
        self.assertEqual([e['opportunity'] for e in events[:2]],['MANUAL','SHUFFLE'])
        self.assertEqual(events,parse(PATH.read_bytes(),False,STAMP)['events'])
        self.assertEqual([e['source_ordinal'] for e in events],list(range(8)))

    def test_skip_absence_stays_unknown_even_when_reason_looks_manual(self):
        rows=json.loads(PATH.read_bytes())
        for row in rows:row.pop('skipped',None)
        events=parse(json.dumps(rows).encode(),False,STAMP)['events']
        self.assertTrue(all(e['skipped'] is None for e in events))
        self.assertEqual(events[0]['reason_end'],'fwdbtn')

    def test_opportunity_capture_does_not_change_frozen_sampler_input(self):
        result=parse(PATH.read_bytes(),False,STAMP)
        before=observations(result['events'],result['tracks'])
        for event in result['events']:event['opportunity']='UNKNOWN'
        self.assertEqual(before,observations(result['events'],result['tracks']))
        self.assertEqual(opportunity(None,None),'UNKNOWN')
        self.assertEqual(opportunity('trackdone',False),'UNKNOWN')
        verify_native()

    def test_unrepresentable_source_evidence_is_rejected_instead_of_discarded(self):
        for field,value in [('duration_ms',180000),('track_duration_ms',180000),('trackDurationMs',180000),('context_uri','spotify:playlist:synthetic'),('playlist_uri','spotify:playlist:synthetic'),('playlist_name','Synthetic'),('playback_source','PLAYLIST'),('manual_selection',False)]:
            rows=json.loads(PATH.read_bytes());rows[0][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'cannot preserve'):
                parse(json.dumps(rows).encode(),False,STAMP)

    def test_synthetic_history_survives_atomic_ingest_lock_and_encrypted_m0_export(self):
        import tempfile
        import pyrage
        from participant.app import ParticipantApp
        from contracts.offline_bundle.v1.canonical import sha256
        from contracts.offline_bundle.v1.release import verify_release
        from contracts.offline_bundle.v1.crypto import recipient_fingerprint,decrypt_bundle
        from contracts.offline_bundle.v1.validate import QUESTIONS,validate
        with tempfile.TemporaryDirectory() as directory:
            identity=pyrage.x25519.Identity.generate();recipient=str(identity.to_public());fingerprint=recipient_fingerprint(recipient)
            config={'version':'participant-study-1.0.0','study_id':'synthetic-h6','participant_pseudonym':'P-SYNTHETIC',
                'recipient':recipient,'recipient_fingerprint':fingerprint,'contract_release_hash':verify_release(),'researcher_contact':'Synthetic fixture only'}
            app=ParticipantApp(Path(directory)/'data',lambda:STAMP);app.configure(config,sha256(config),True,True)
            enriched=json.loads(PATH.read_bytes());enriched[0]['duration_ms']=180000
            with self.assertRaises(ValueError):app.ingest(json.dumps(enriched).encode())
            self.assertIsNone(app.state()['history'])
            state=app.ingest(PATH.read_bytes());self.assertEqual(state['sessions'],2)
            prompt=app.allocate()['prompt_id'];app.prompt(prompt)
            answers=[{'question_id':'episode.recognition','question_version':'1.0.0','value':'CLEAR'},
                {'question_id':'episode.meaningfulness','question_version':'1.0.0','value':{'status':'KNOWN','value':4}}]
            app.neutral(prompt,answers)
            self.assertEqual(app.followups(prompt)['questions'],QUESTIONS['followup_questions'])
            changed=[dict(a) for a in answers];changed[0]['value']='VAGUE'
            with self.assertRaises(ValueError):app.neutral(prompt,changed)
            app.finish(prompt);preview=app.preview(True);export=app.export(preview['preview_id'],preview['preview_hash'],True)
            bundle=decrypt_bundle(app.download(export['export_id'])[1],str(identity),fingerprint);validate(bundle)
            actual=[{k:v for k,v in e.items() if k!='record_hash'} for e in bundle['events']]
            self.assertEqual(actual,parse(PATH.read_bytes(),False,STAMP)['events'])
            self.assertEqual(bundle['submissions'][0]['answers'],answers)
            self.assertEqual(len([e for e in bundle['prompt_events'] if e['event_type']=='FOLLOWUP_SHOWN']),2)
            self.assertEqual(bundle['manifest']['temporal_mode'],'RETROSPECTIVE_REPLAY')
            self.assertGreater(bundle['submissions'][0]['submitted_at'],bundle['events'][-1]['occurred_at'])

if __name__=='__main__':unittest.main()
