"""Offline observational H6 collection. No media/network/model investigator."""
from copy import deepcopy
import uuid
from contracts.offline_bundle.v1.canonical import sha256,dumps,record_hash
from contracts.h6_bundle.v1.instrument import BANK,select,audit
from contracts.h6_bundle.v1.contract import wrap,availability,SECTIONS
from contracts.h6_bundle.v1.capture import PLAYLIST_FIELDS

def rid(prefix):return prefix+'-'+str(uuid.uuid4())
def require(value,message):
    if not value:raise ValueError(message)

class H6Mixin:
    def h6_select(self,c,prompt,lock,answers):
        packet=self.store.record(c,prompt);episode=self.store.record(c,packet['episode_id'])
        chosen=select(neutral_locked=True,recognition=answers[0]['value'],episode_key=episode['episode_key'],seed=self.store.get(c,'seed'))
        return self.store.add(c,'h6_followup_selections',{'record_id':rid('h6selection'),'prompt_packet_id':prompt,'neutral_lock_id':lock['record_id'],
            'selected_at':self.clock(),'sequence':self.sequence(c),**chosen})
    def h6_shown(self,c,prompt):return [r['rendered_question'] for r in self.store.records(c,'h6_followup_exposures') if r['prompt_packet_id']==prompt]
    def h6_followups(self,prompt):
        with self.store.transaction() as c:
            lock=c.execute('SELECT * FROM locks WHERE prompt_id=?',(prompt,)).fetchone();require(lock is not None,'Lock neutral responses first')
            shown=self.h6_shown(c,prompt)
            if shown:return {'questions':shown}
            require(not any(e['event_type'] in {'COMPLETED','DECLINED','EXPIRED'} for e in self.events(c,prompt)),'Reflection is finished')
            selection=next(r for r in self.store.records(c,'h6_followup_selections') if r['prompt_packet_id']==prompt)
            questions=[next(q for q in BANK['questions'] if q['question_id']==key) for key in selection['selected_question_ids']]
            for q in questions:self.store.add(c,'h6_followup_exposures',{'record_id':rid('h6shown'),'prompt_packet_id':prompt,'neutral_lock_id':lock['lock_id'],
                'selection_id':selection['record_id'],'shown_at':self.clock(),'sequence':self.sequence(c),'rendered_question':q})
            self.store.changed(c);return {'questions':questions}
    def h6_complete(self,c,prompt,lock):
        existing=next((r for r in self.store.records(c,'h6_followup_completions') if r['prompt_packet_id']==prompt),None)
        if existing:return existing
        selected=next(r for r in self.store.records(c,'h6_followup_selections') if r['prompt_packet_id']==prompt)
        fields={k:selected[k] for k in ['policy_version','bank_version','bank_hash','eligible_question_ids','selected_question_ids','not_selected_question_ids','ineligible_question_ids']}
        answers=next((r['answers'] for r in self.store.records(c,'h6_followup_submissions') if r['prompt_packet_id']==prompt),[])
        summary=audit(fields,[q['question_id'] for q in self.h6_shown(c,prompt)],answers)
        return self.store.add(c,'h6_followup_completions',{'record_id':rid('h6complete'),'prompt_packet_id':prompt,'neutral_lock_id':lock['lock_id'],
            'completed_at':self.clock(),'sequence':self.sequence(c),**summary})
    def h6_answer(self,prompt,answers):
        require(isinstance(answers,list) and 1<=len(answers)<=2 and all(isinstance(a,dict) and set(a)=={'question_id','question_version','value'} for a in answers),'Invalid H6 response')
        with self.store.transaction() as c:
            lock=c.execute('SELECT * FROM locks WHERE prompt_id=?',(prompt,)).fetchone();require(lock is not None,'Lock neutral responses first')
            shown=[q['question_id'] for q in self.h6_shown(c,prompt)];require(bool(shown),'Open the optional questions first')
            selection=next(r for r in self.store.records(c,'h6_followup_selections') if r['prompt_packet_id']==prompt)
            audit(selection,shown,answers)
            existing=next((r for r in self.store.records(c,'h6_followup_submissions') if r['prompt_packet_id']==prompt),None)
            if existing:
                require(existing['answers']==answers,'H6 response is already locked with different answers');return {'saved':True,'duplicate':True}
            require(not any(e['event_type']=='COMPLETED' for e in self.events(c,prompt)),'Reflection is finished')
            stamp=self.clock();self.store.add(c,'h6_followup_submissions',{'record_id':rid('h6response'),'prompt_packet_id':prompt,'neutral_lock_id':lock['lock_id'],
                'submitted_at':stamp,'locked_at':stamp,'sequence':self.sequence(c),'answers':answers})
            self.h6_complete(c,prompt,lock);self.audit(c,prompt,'COMPLETED',lock=lock['lock_id']);c.execute('DELETE FROM followup_drafts WHERE prompt_id=?',(prompt,));self.store.changed(c)
            return {'saved':True,'duplicate':False}
    def h6_wrap(self,c,core):
        consent=self.store.records(c,'h6_consent')[0];grants=consent['grants']
        extension={'version':'h6-evidence-1.0.0','consent':consent,'availability':availability(grants),**{name:[] for name in SECTIONS}}
        if grants['share_event_evidence']:
            for name in ['event_evidence','sessionization_runs','sessions']:extension[name]=deepcopy(self.store.records(c,'h6_'+name))
            if not grants['share_playlist_context']:
                for r in extension['event_evidence']:
                    r['withheld_native_fields']=sorted(PLAYLIST_FIELDS&set(r['native']))
                    r['native']={k:v for k,v in r['native'].items() if k not in PLAYLIST_FIELDS};r['record_hash']=record_hash(r)
        if grants['share_followup_evidence']:
            for name in ['followup_selections','followup_exposures','followup_submissions','followup_completions']:extension[name]=self.store.records(c,'h6_'+name)
        return wrap(core,extension,self.clock())
