import copy
import tempfile
import unittest
from pathlib import Path

from meeting_eval.context_state import reduce_context
from meeting_eval.extract import validate, validate_partial
from meeting_eval.inputs import normalize
from meeting_eval.service import Service
from meeting_eval.store import Store


def fixture(change='keep',state='progress'):
    raw=dict(meeting_id='U',series='S',meeting_date='2026-11-16',audience=['host','alice'],writers=['host'],
        speaker_map={'甲':'alice','主持':'host'},segments=[dict(id='s1',speaker='甲',
        text='合同已经整理了一半，期限改到2026年11月20日，我会按时完成。')])
    m=normalize(raw,'host');span=dict(segment_id='s1',start=0,end=len(raw['segments'][0]['text']),quote=raw['segments'][0]['text'])
    e=dict(event_id='E1',record_id='R1',candidate_ids=['C1'],
        work=dict(description='整理合同，期限改为2026年11月20日。',evidence=[span]),
        owner=dict(kind='person',ref='alice',label='甲',evidence=[span]),
        commitment=dict(kind='self_committed',evidence=[span]),
        time=dict(kind='deadline' if change in ('set','uncertain') else 'unspecified',change=change,
            text='2026年11月20日' if change in ('set','uncertain') else '取消截止期限' if change=='clear' else None,
            date='2026-11-20' if change in ('set','uncertain') else None,evidence=[span] if change!='keep' else []),
        state=dict(kind=state,evidence=[span]),relation=dict(kind='existing',target_guid='T',evidence=[span]))
    e['checks']={k:dict(verdict='supported',reason='原话支持',evidence=[span]) for k in ('work','owner','commitment','time','state','relation')}
    r=dict(record_id='R1',kind='work',content_basis='explicit',description=e['work']['description'],
        missing_fields=[],question=None,issuer_ref='alice',evidence=[span],
        check=dict(verdict='supported',reason='原话支持',evidence=[span],issues=[]))
    task=dict(guid='T',summary='整理合同，11月13日前完成',assignee='alice',status='open',
        due_date='2026-11-13',due_text='11月13日前',readers=['host','alice'],writers=['host','alice'],series='S',tenant='local')
    return raw,m,e,r,task


class ReducedExtractor:
    strategy='context-v1'
    def __init__(self,event,record):self.event=event;self.record=record
    def extract(self,m,ctx):
        p=reduce_context([self.event],[],[self.record],m,{'tasks':ctx['tasks']})
        result=dict(items=p['items'],updates=p['updates'],facts=[],unresolved=[],decisions=[],
                    _task_trace=dict(pending=p['pending'],review_records=p['review_records'],checked_events=[self.event]))
        return result


class ContextUpdateTests(unittest.TestCase):
    def test_progress_does_not_request_a_fresh_commitment(self):
        raw,m,e,r,t=fixture();e['commitment']['kind']='unknown'
        p=reduce_context([e],[],[r],m,{'tasks':[t]})
        self.assertEqual(p['review_records'],[])
        self.assertEqual(p['pending'],[])
        self.assertEqual(p['updates'],[])

    def test_service_applies_date_patch_and_clear_once(self):
        for change in ('set','clear'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                raw,m,e,r,t=fixture(change,'revised')
                store=Store(Path(tmp)/'db');svc=Service(store,ReducedExtractor(e,r))
                try:
                    svc.sim.seed(t,'2026-11-15T00:00:00+08:00')
                    out=svc.process(raw,'host','2026-11-16T10:00:00+08:00')
                    current=store.task('T')
                    self.assertEqual(current['due_date'],'2026-11-20' if change=='set' else None)
                    self.assertEqual(current['due_text'],'2026年11月20日' if change=='set' else None)
                    self.assertEqual(current['summary'],t['summary'])
                    self.assertEqual(current['status'],'open')
                    self.assertEqual(out['extraction']['_task_trace']['review_records'],[])
                    self.assertIn('任务更新',svc.minutes(out['source_id'],'host'))
                    svc.process(raw,'host','2026-11-16T10:01:00+08:00')
                    self.assertEqual(store.db.execute("SELECT count(*) FROM audit WHERE kind='platform_update'").fetchone()[0],1)
                finally:store.close()

    def test_complete_preserves_date_and_combined_update_works(self):
        for change in ('keep','set'):
            raw,m,e,r,t=fixture(change,'completed')
            p=reduce_context([e],[],[r],m,{'tasks':[t]})
            self.assertEqual(p['updates'][0]['changes']['status'],'done')
            self.assertEqual('due_date' in p['updates'][0]['changes'],change=='set')

    def test_uncertain_or_unresolved_date_is_specific_and_not_executable(self):
        for change in ('uncertain','set'):
            raw,m,e,r,t=fixture(change,'revised')
            if change=='set':e['time']['date']=None
            p=reduce_context([e],[],[r],m,{'tasks':[t]})
            self.assertEqual(p['updates'],[])
            self.assertEqual(p['review_records'][0]['missing_fields'],['time'])
            self.assertIn('截止',p['review_records'][0]['question'])

    def test_unsupported_change_explains_capability_instead_of_asking(self):
        raw,m,e,r,t=fixture('keep','revised')
        p=reduce_context([e],[],[r],m,{'tasks':[t]})
        review=p['review_records'][0]
        self.assertEqual(review['category'],'execution_blocked')
        self.assertIsNone(review['question'])
        self.assertFalse(review['can_add_task'])
        self.assertIn('不支持',review['execution_reason'])

    def test_new_patch_validation_rejects_unknown_fields_and_missing_evidence(self):
        raw,m,e,r,t=fixture('set','revised')
        base=dict(target_guid='T',description='改期',owner_ref='alice',effective_at=None,evidence_ids=['s1'],
            changes=dict(due_date='2026-11-20',due_text='11月20日'),field_evidence_ids={'time':['s1']})
        result=dict(items=[],updates=[base],facts=[],unresolved=[],decisions=[])
        validate(result,m,{'tasks':[t],'decisions':[]})
        for bad in [dict(changes={'assignee':'host'}),dict(field_evidence_ids={}),
                    dict(changes={'due_date':None,'due_text':'某天'}),dict(changes={'due_date':'2026-11-20'})]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                validate({**result,'updates':[{**base,**bad}]},m,{'tasks':[t],'decisions':[]})

    def test_date_change_uses_its_own_speaker_evidence(self):
        raw,m,e,r,t=fixture('set','revised')
        raw['segments'].append(dict(id='s2',speaker='主持',text='改到11月20日。'))
        e['time']['evidence']=[dict(segment_id='s2',start=0,end=9,quote='改到11月20日。')]
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db');svc=Service(store,ReducedExtractor(e,r))
            try:
                svc.sim.seed(t,'2026-11-15T00:00:00+08:00')
                out=svc.process(raw,'host','2026-11-16T10:00:00+08:00')
                self.assertEqual(store.task('T')['due_date'],'2026-11-13')
                self.assertEqual(svc.requirements(out['source_id'],'host')[0]['missing_fields'],['time'])
                self.assertIn('2026-11-20',svc.requirements(out['source_id'],'host')[0]['question'])
            finally:store.close()

    def test_failed_write_does_not_overwrite_later_user_date(self):
        raw,m,e,r,t=fixture('set','revised')
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db');svc=Service(store,ReducedExtractor(e,r))
            try:
                svc.sim.seed(t,'2026-11-15T00:00:00+08:00');real=svc.sim.update
                def fail(*args,**kwargs):raise OSError('network')
                svc.sim.update=fail
                out=svc.process(raw,'host','2026-11-16T10:00:00+08:00')
                self.assertEqual(len(out['intent_ids']),1)
                real('T',{'due_date':'2026-11-25'},'host','2026-11-16T10:01:00+08:00')
                svc.sim.update=real;svc.recover(actor='host',observed_at='2026-11-16T10:02:00+08:00')
                self.assertEqual(store.task('T')['due_date'],'2026-11-25')
                self.assertIsNone(store.binding(out['intent_ids'][0]))
            finally:store.close()

    def test_mixed_content_and_date_only_updates_date_and_explains_remaining_change(self):
        raw,m,e,r,t=fixture('set','revised')
        e['work']['description']='把整理合同改成审核合同，期限改为11月20日。'
        e['other_changes']=['content'];r['description']=e['work']['description']
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db');svc=Service(store,ReducedExtractor(e,r))
            try:
                svc.sim.seed(t,'2026-11-15T00:00:00+08:00')
                out=svc.process(raw,'host','2026-11-16T10:00:00+08:00')
                self.assertEqual(store.task('T')['due_date'],'2026-11-20')
                self.assertEqual(store.task('T')['summary'],t['summary'])
                self.assertEqual(svc.requirements(out['source_id'],'host')[0]['category'],'execution_blocked')
                self.assertIn('未执行',svc.minutes(out['source_id'],'host'))
                with self.assertRaises(ValueError):svc.resolve_requirement(out['source_id'],'R1','host',{'decision':'ask_issuer'},'2026-11-16T10:01:00+08:00')
            finally:store.close()

    def test_tentative_new_task_deadline_is_not_written_as_agreed(self):
        raw,m,e,r,t=fixture('uncertain','future_work');e['relation'].update(kind='new',target_guid=None)
        p=reduce_context([e],[],[r],m,{'tasks':[]})
        self.assertFalse(any(i['operation']=='create' for i in p['items']))
        self.assertIn('2026-11-20',p['review_records'][0]['question'])

if __name__=='__main__':unittest.main()
