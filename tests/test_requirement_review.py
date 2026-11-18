import copy
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from meeting_eval.service import Service
from meeting_eval.store import Store
from meeting_eval.inputs import dumps
from test_context_state import ledger_fixture


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'state.sqlite')
        self.meeting,*_=ledger_fixture()
        self.meeting.update(account_map={'alice':'alice'},audience=['host','alice','reader'],writers=['host'])
        record=dict(record_id='R1',category='implicit_need',description='研究视频使用问题',content_basis='inferred',
                    description_status='supported_interpretation',missing_fields=['work'],question='是否研究视频使用问题？',
                    issuer_ref='alice',evidence_ids=['s1'],check_reason='推测待确认',can_add_task=True)
        class Fixed:
            def extract(self,m,c):return dict(items=[],updates=[],facts=[],unresolved=[],decisions=[],_task_trace={'review_records':[record],'pending':[]})
        self.svc=Service(self.store,Fixed())
        self.result=self.svc.process(self.meeting,'host','2026-11-14T00:00:00+08:00')
        self.sid=self.result['source_id']
        self.decision=dict(decision='add_task',description='访谈用户，了解视频使用问题',owner_ref='alice',due_date=None,due_text=None)

    def tearDown(self):self.store.close();self.tmp.cleanup()

    def decide(self,decision=None,actor='host'):
        return self.svc.resolve_requirement(self.sid,'R1',actor,decision or self.decision,'2026-11-14T01:00:00+08:00')

    def test_manual_confirmation_creates_once_with_separate_audit(self):
        self.assertEqual(self.store.tasks(),[])
        first=self.decide();second=self.decide()
        self.assertEqual(first['intent_id'],second['intent_id'])
        self.assertEqual(len(self.store.tasks()),1)
        self.assertEqual(self.store.tasks()[0]['summary'],'访谈用户，了解视频使用问题')
        self.assertEqual(self.store.tasks()[0]['manual_decision']['actor'],'host')
        self.assertEqual(self.svc.requirements(self.sid,'reader')[0]['resolution']['decision'],'add_task')
        with self.assertRaises(ValueError):self.decide({**self.decision,'description':'不同任务'})

    def test_ask_is_nonterminal_dismiss_is_terminal(self):
        asked=self.decide(dict(decision='ask_issuer'))
        self.assertEqual(asked['decision'],'ask_issuer')
        self.assertEqual(self.store.tasks(),[])
        self.decide(dict(decision='dismiss'))
        self.assertEqual(self.store.tasks(),[])
        with self.assertRaises(ValueError):self.decide()

    def test_permission_and_owner_boundaries(self):
        for actor in ('reader','outsider'):
            with self.assertRaises(PermissionError):self.decide(actor=actor)
        with self.assertRaises(PermissionError):self.svc.requirements(self.sid,'outsider')
        with self.assertRaises(ValueError):self.decide({**self.decision,'owner_ref':'unknown'})
        with self.assertRaises(ValueError):self.decide({**self.decision,'description':''})
        self.assertEqual(self.store.tasks(),[])

    def test_source_revision_invalidates_confirmation(self):
        raw=copy.deepcopy(self.meeting);raw['segments'][0]['text']='我们不研究视频了。'
        raw.pop('version',None)
        self.svc.process(raw,'host','2026-11-14T00:30:00+08:00')
        with self.assertRaises(ValueError):self.decide()
        self.assertEqual(self.store.tasks(),[])

    def test_relation_uncertainty_cannot_be_manually_bypassed_as_new_task(self):
        out=self.svc.result(self.sid)
        out['extraction']['_task_trace']['review_records'][0]['can_add_task']=False
        with self.store.db:self.store.db.execute('UPDATE sources SET result=? WHERE id=?',(dumps(out),self.sid))
        with self.assertRaises(ValueError):self.decide()
        self.assertEqual(self.store.tasks(),[])

    def test_explicit_adoption_creates_once_and_preserves_audit(self):
        result = self.svc.result(self.sid)
        card = result['extraction']['_task_trace']['review_records'][0]
        card.update(can_add_task=False, requires_adoption=True)
        with self.store.db:
            self.store.db.execute('UPDATE sources SET result=? WHERE id=?', (dumps(result), self.sid))
        self.assertIn('## 待澄清需求', self.svc.minutes(self.sid, 'host'))
        with self.assertRaises(ValueError):
            self.decide()
        adopted = {**self.decision, 'decision': 'adopt_and_add_task'}
        with self.assertRaises(ValueError):
            self.decide({**adopted, 'owner_ref': 'unknown'})
        self.assertEqual(self.store.tasks(), [])
        first = self.decide(adopted)
        self.assertEqual(first['decision'], 'adopt_and_add_task')
        self.assertEqual(first['intent_id'], self.decide(adopted)['intent_id'])
        self.assertEqual(len(self.store.tasks()), 1)
        self.assertIn('已采纳，任务已创建', self.svc.minutes(self.sid, 'host'))

    def test_lost_response_reuses_intent_after_restart(self):
        original=self.svc.sim.create
        def lost(*args,**kwargs):
            original(*args,**kwargs)
            raise OSError('response lost')
        self.svc.sim.create=lost
        first=self.decide()
        self.assertEqual(len(self.store.tasks()),1)
        self.svc=Service(self.store)
        final=self.decide()
        self.assertEqual(first['intent_id'],final['intent_id'])
        self.assertEqual(len(self.store.tasks()),1)
        self.assertIsNotNone(final['task_guid'])

    def test_cli_lists_and_confirms_review_record(self):
        root=Path(__file__).resolve().parents[1]
        base=[sys.executable,'-m','meeting_eval','--db',str(Path(self.tmp.name)/'state.sqlite')]
        listed=subprocess.run(base+['requirements',self.sid,'--viewer','host'],cwd=root,capture_output=True,encoding='utf-8',check=True)
        self.assertEqual(json.loads(listed.stdout)[0]['record_id'],'R1')
        path=Path(self.tmp.name)/'decision.json';path.write_text(dumps(self.decision),encoding='utf-8')
        confirmed=subprocess.run(base+['resolve-requirement',self.sid,'R1','--actor','host','--input',str(path)],cwd=root,capture_output=True,encoding='utf-8',check=True)
        self.assertIsNotNone(json.loads(confirmed.stdout)['task_guid'])
        self.assertEqual(len(self.store.tasks()),1)

    def test_failed_write_is_not_displayed_as_created_and_can_recover(self):
        def unavailable(*args,**kwargs):raise OSError('network unavailable')
        self.svc.sim.create=unavailable
        result=self.decide()
        self.assertEqual(result['intent_status'],'unknown')
        self.assertEqual(self.store.tasks(),[])
        text=self.svc.minutes(self.sid,'host')
        self.assertIn('写入尚未确认',text)
        self.assertNotIn('确认问题：',text)
        self.svc=Service(self.store)
        result=self.decide()
        self.assertEqual(result['intent_status'],'confirmed')
        self.assertIn('任务已创建',self.svc.minutes(self.sid,'host'))

    def test_pending_manual_intent_cannot_send_after_source_revision(self):
        original=self.svc.sim.create
        def unavailable(*args,**kwargs):raise OSError('network unavailable')
        self.svc.sim.create=unavailable
        self.decide()
        self.svc.sim.create=original
        raw=copy.deepcopy(self.meeting);raw['segments'][0]['text']='这项工作已经取消。';raw.pop('version',None)
        self.svc.process(raw,'host','2026-11-14T02:00:00+08:00')
        self.assertEqual(self.store.tasks(),[])


if __name__=='__main__':unittest.main()
