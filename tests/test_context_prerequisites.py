import copy
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from test_context_state import ledger_fixture
from meeting_eval.context_state import canonical_ledger, canonical_records, check_records, reduce_context


def supported(record, event):
    return {**record, 'check': dict(verdict='supported', reason='原话支持', evidence=event['work']['evidence'])}


class PrerequisiteTests(unittest.TestCase):
    def test_shared_evidence_does_not_let_ambiguous_material_block_other_work(self):
        m,e,ledger,r=ledger_fixture()
        other={**r,'record_id':'R2','kind':'ambiguous','content_basis':'unknown',
               'description':'另一个材料的处理动作未定','missing_fields':['work'],'question':'材料如何处理？'}
        result=reduce_context([e],[],[supported(r,e),supported(other,e)],m,{'tasks':[]})
        self.assertEqual([i['description'] for i in result['items']],['剪辑视频'])
        self.assertEqual(result['item_records'],['R1'])
        self.assertEqual([r['record_id'] for r in result['review_records']],['R2'])

    def test_local_commitment_issue_keeps_supported_meaning_but_blocks_creation(self):
        m,e,ledger,r=ledger_fixture()
        r['check']=dict(verdict='insufficient',issues=['commitment'],reason='承接尚未确认',evidence=e['work']['evidence'])
        result=reduce_context([e],[],[r],m,{'tasks':[]})
        self.assertEqual(result['items'][0]['operation'],'candidate')
        self.assertEqual(result['review_records'][0]['missing_fields'],['commitment'])
        self.assertEqual(result['review_records'][0]['description_status'],'supported_interpretation')

    def test_local_owner_issue_cannot_assign_unverified_person(self):
        m,e,ledger,r=ledger_fixture()
        r['check']=dict(verdict='insufficient',issues=['owner'],reason='负责人待确认',evidence=e['work']['evidence'])
        for commitment in ('self_committed','assigned'):
            with self.subTest(commitment=commitment):
                e['commitment']['kind']=commitment
                result=reduce_context([e],[],[r],m,{'tasks':[]})
                self.assertEqual(result['items'][0]['operation'],'candidate')
                self.assertIsNone(result['items'][0]['owner_ref'])
                self.assertEqual(result['review_records'][0]['missing_fields'],
                                 ['owner','commitment'] if commitment=='assigned' else ['owner'])

    def test_service_rejects_closed_record_event_conflict_but_preserves_separate_work(self):
        from test_context_pipeline import ContextClient
        from meeting_eval.extract import Extractor
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        for kind in ('resolved','withdrawn','entity_only'):
            for separate in (False,True):
                with self.subTest(kind=kind,separate=separate),tempfile.TemporaryDirectory() as tmp:
                    m,*_=ledger_fixture()
                    m.update(account_map={'alice':'alice'},audience=['host','alice'],writers=['host'])
                    client=ContextClient()
                    def call(_client,prompt,payload,stage,*args,**kwargs):
                        if stage=='facts':return dict(facts=[],unresolved=[])
                        if stage=='decisions':return dict(decisions=[])
                        value=client.call(prompt,payload,stage,**kwargs)
                        if stage=='interpret_work':
                            if separate:
                                other=copy.deepcopy(value['records'][0]);other.update(record_id='R2',kind=kind)
                                value['records'].append(other)
                            else:value['records'][0]['kind']=kind
                        if stage=='check_work' and separate:
                            value['record_checks'].append(dict(record_id='R2',verdict='supported',reason='原话支持',evidence=['Q1']))
                        return value
                    with patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')),patch('meeting_eval.model_client.ModelClient.call',call):
                        store=Store(Path(tmp)/'state.sqlite')
                        try:
                            svc=Service(store,Extractor(None,Path(tmp)/'model','context-v1'))
                            result=svc.process(m,'host','2026-11-14T00:00:00+08:00')
                            self.assertEqual(result['status'],'processed' if separate else 'partial')
                            self.assertEqual(len(store.tasks()),1 if separate else 0)
                            if not separate:self.assertIn('Closed record cannot carry an event',str(result['extraction']['_errors']))
                        finally:store.close()

    def test_content_scope_relation_block_but_local_time_issue_keeps_candidate(self):
        m,e,ledger,r=ledger_fixture()
        for issue in ('work','time','scope','classification','relation'):
            with self.subTest(issue=issue):
                r['check']=dict(verdict='insufficient',issues=[issue],reason='此字段不受支持',evidence=e['work']['evidence'])
                result=reduce_context([e],[],[r],m,{'tasks':[]})
                if issue=='time':
                    self.assertEqual(result['items'][0]['operation'],'candidate')
                    self.assertIsNone(result['items'][0]['due_date'])
                else:
                    self.assertEqual(result['items'],[])
                self.assertEqual(result['updates'],[])

    def test_checker_must_identify_failure_field_and_reject_unknown_issue(self):
        m,e,ledger,r=ledger_fixture()
        base=dict(record_id='R1',verdict='insufficient',reason='有缺口',evidence=e['work']['evidence'])
        for issues in (None,[],['typo']):
            raw={**base,**({} if issues is None else {'issues':issues})}
            with self.subTest(issues=issues),self.assertRaises(ValueError):check_records([raw],[r],m)
        checked=check_records([{**base,'issues':['commitment']}],[r],m)
        self.assertEqual(checked[0]['check']['issues'],['commitment'])

    def test_answered_question_is_preserved_as_resolved_without_new_task_or_question(self):
        m,e,ledger,r=ledger_fixture()
        m['segments'].append(dict(id='s2',speaker='A',person_ref='alice',text='这个问题已确认，不需要再核对。'))
        ledger['threads'][0]['updates'].append(dict(after_segment='s2',kind='resolved',description='核对已解决',
            evidence=[dict(segment_id='s2',quote='这个问题已确认，不需要再核对。')]))
        ledger=canonical_ledger(ledger,m,None)
        r.update(kind='resolved',description='核对已解决',evidence=ledger['threads'][0]['updates'][-1]['evidence'])
        record=canonical_records([r],ledger,[],m)[0]
        result=reduce_context([],[],[supported(record,e)],m,{'tasks':[]})
        self.assertEqual(result['items'],[])
        self.assertEqual(result['review_records'],[])
        record['check']=dict(verdict='insufficient',issues=['state'],reason='答案不明确',evidence=[])
        self.assertEqual(len(reduce_context([],[],[record],m,{'tasks':[]})['review_records']),1)


if __name__=='__main__':unittest.main()
