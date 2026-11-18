import copy
import unittest

from meeting_eval.context_protocol import example
from meeting_eval.context_protocol_v5 import check_contract, expand_checks
from meeting_eval.context_state import reduce_context
from meeting_eval.inputs import dumps
from test_context_state import ledger_fixture
import test_requirement_review


class IntentRoutingTests(unittest.TestCase):
    def fixture(self, kind='ambiguous', basis='unclear_intent'):
        meeting, event, _, record = ledger_fixture()
        record.update(kind=kind, description='稍后补充，具体方式待澄清', missing_fields=['work'],
                      question='稍后口头补充，还是修改材料？')
        record['check'] = dict(verdict='supported', reason='原话动作有两种解释', evidence=record['evidence'])
        record['qualification'] = dict(speech_scope='current', work_basis=basis,
                                      evidence=record['evidence'], adoption_evidence=[], reason='问答依据')
        return meeting, event, record

    def test_unclear_intent_has_no_task_permission_but_keeps_evidence(self):
        meeting, _, record = self.fixture()
        out = reduce_context([],[],[record],meeting,{'tasks':[]})
        self.assertEqual(out['items'],[])
        card = out['review_records'][0]
        self.assertEqual(card['category'],'unclear_intent')
        self.assertFalse(card['can_add_task'])
        self.assertTrue(card['can_clarify_as_new_task'])
        self.assertEqual(card['question'],record['question'])
        self.assertEqual(card['evidence_ids'],['s1'])
        with_history = reduce_context([],[],[record],meeting,{'tasks':[dict(guid='old')]})
        self.assertFalse(with_history['review_records'][0]['can_clarify_as_new_task'])

    def test_qualified_content_gap_requires_clarification_even_with_event(self):
        meeting, event, record = self.fixture('work','action')
        for field in ('work','reference','scope'):
            record['missing_fields'] = [field]
            out = reduce_context([event],[],[record],meeting,{'tasks':[]})
            self.assertEqual(out['items'],[])
            self.assertFalse(out['review_records'][0]['can_add_task'])
            self.assertTrue(out['review_records'][0]['requires_clarification'])

    def test_clear_work_without_deadline_keeps_normal_entry(self):
        meeting, event, record = self.fixture('work','action')
        record.update(missing_fields=[],question=None,description='剪辑视频')
        self.assertEqual(reduce_context([event],[],[record],meeting,{'tasks':[]})['items'][0]['operation'],'create')
        record.update(missing_fields=['owner'],question='谁负责？')
        card=reduce_context([event],[],[record],meeting,{'tasks':[]})['review_records'][0]
        self.assertTrue(card['can_add_task'])
        self.assertNotIn('requires_clarification',card)

    def test_dialogue_classification_is_checked_against_basis(self):
        meeting, _, record = self.fixture()
        payload=dict(meeting=meeting,records=[record],events=[])
        for basis, kind, supported in [('unclear_intent','ambiguous',True),
                                       ('unclear_intent','work',False),
                                       ('meeting_discourse','context_only',True),
                                       ('meeting_discourse','work',False)]:
            with self.subTest(basis=basis,kind=kind):
                raw=example(check_contract(payload)[0])
                row=raw['record_checks']['R1']
                row.update(kind=kind)
                row['qualification'].update(work_basis=basis)
                if basis=='unclear_intent':
                    row['gap_checks']=[dict(field='work',status='needed',reason='两种动作仍未明确',
                                            evidence=['Q1'],question='口头补充还是修改材料？')]
                actual=expand_checks(raw,payload)['record_checks'][0]
                self.assertEqual(actual['content']['verdict']=='supported',supported)

    def test_unclear_qualification_requires_a_content_question(self):
        meeting, _, record = self.fixture()
        payload=dict(meeting=meeting,records=[record],events=[])
        raw=example(check_contract(payload)[0])
        row=raw['record_checks']['R1']
        row.update(kind='ambiguous')
        row['qualification'].update(work_basis='unclear_intent')
        row['gap_checks']=[dict(field='owner',status='needed',reason='缺负责人',
                                evidence=['Q1'],question='谁负责？')]
        self.assertEqual(expand_checks(raw,payload)['record_checks'][0]['content']['verdict'],'insufficient')

    def test_unresolved_relation_blocks_clarification_via_normal_reducer(self):
        from meeting_eval.context_v3 import reduce_v3
        meeting,event,record=self.fixture()
        record.update(missing_fields=['work','relation'],
            clarification=dict(status='needed',question='具体做什么，对应哪个已有任务？'),
            gap_checks=[dict(field='work',verdict='supported',blocking_for='content'),
                        dict(field='relation',verdict='supported',blocking_for='operation')])
        out=reduce_v3(dict(checked_records=[record],checked_events=[event],
                          coverage_findings=[],trace={}),meeting,{'tasks':[dict(guid='old')]})
        self.assertFalse(out['review_records'][0]['can_clarify_as_new_task'])


class ClarificationTests(unittest.TestCase):
    tearDown = test_requirement_review.ReviewTests.tearDown
    decide = test_requirement_review.ReviewTests.decide

    def setUp(self):
        test_requirement_review.ReviewTests.setUp(self)
        result=self.svc.result(self.sid)
        self.card=result['extraction']['_task_trace']['review_records'][0]
        self.card.update(category='unclear_intent',can_add_task=False,requires_clarification=True,
                         can_clarify_as_new_task=True,question='口头补充还是修改文稿？')
        self.save_card(result)

    def save_card(self,result):
        with self.store.db:
            self.store.db.execute('UPDATE sources SET result=? WHERE id=?',(dumps(result),self.sid))

    # Use a standalone suite while reusing the existing Service fixture.
    def test_clarification_creates_once_with_final_description(self):
        with self.assertRaises(ValueError):self.decide()
        clarified={**self.decision,'decision':'clarify_and_add_task'}
        for change in (dict(description=''),dict(owner_ref='unknown')):
            with self.assertRaises(ValueError):self.decide(dict(clarified,**change))
        with self.assertRaises(PermissionError):self.decide(clarified,actor='reader')
        self.assertEqual(self.store.tasks(),[])
        self.assertIn('待澄清意向',self.svc.minutes(self.sid,'host'))
        first=self.decide(clarified)
        from meeting_eval.service import Service
        self.svc=Service(self.store)
        self.assertEqual(first['intent_id'],self.decide(clarified)['intent_id'])
        self.assertEqual(len(self.store.tasks()),1)
        self.assertIn('已澄清，任务已创建',self.svc.minutes(self.sid,'host'))

    def test_clarification_cannot_bypass_unknown_relation_or_revision(self):
        result=self.svc.result(self.sid)
        result['extraction']['_task_trace']['review_records'][0]['can_clarify_as_new_task']=False
        self.save_card(result)
        with self.assertRaises(ValueError):
            self.decide({**self.decision,'decision':'clarify_and_add_task'})
        self.assertEqual(self.store.tasks(),[])

    def test_clarification_revision_and_lost_response_use_existing_guards(self):
        clarified={**self.decision,'decision':'clarify_and_add_task'}
        original=self.svc.sim.create
        def lost(*args,**kwargs):
            original(*args,**kwargs)
            raise OSError('response lost')
        self.svc.sim.create=lost
        first=self.decide(clarified)
        self.assertEqual(len(self.store.tasks()),1)
        from meeting_eval.service import Service
        self.svc=Service(self.store)
        self.assertEqual(self.decide(clarified)['intent_id'],first['intent_id'])
        self.assertEqual(len(self.store.tasks()),1)
        raw=copy.deepcopy(self.meeting)
        raw['segments'][0]['text']='刚才的意向取消。'
        raw.pop('version',None)
        self.svc.extractor=type('Fixed',(),{'extract':lambda _,m,c:dict(
            items=[],updates=[],facts=[],unresolved=[],decisions=[])})()
        self.svc.process(raw,'host','2026-11-14T02:00:00+08:00')
        with self.assertRaises(ValueError):self.decide(clarified)


