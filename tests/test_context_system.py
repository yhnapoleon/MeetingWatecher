import copy
import json
from pathlib import Path
import unittest

from meeting_eval.context_v3 import reduce_v3
from meeting_eval.context_protocol import example
from meeting_eval.context_protocol_v5 import check_contract, expand_checks


class SystemContractTests(unittest.TestCase):
    def test_work_qualification_is_required_and_must_support_work(self):
        payload=self.payload();schema,_=check_contract(payload);raw=example(schema)
        raw['record_checks']['R1'].update(kind='work',qualification=dict(speech_scope='current',
            work_basis='entity_mention',evidence=['Q1'],adoption_evidence=[],reason='仅提及文稿，没有安排动作。'))
        try:out=expand_checks(raw,payload)
        except ValueError as exc:self.fail('Qualification must be represented in the check contract: '+str(exc))
        self.assertEqual(out['record_checks'][0]['content']['verdict'],'insufficient')

    def test_quoted_action_requires_current_adoption_but_report_is_work(self):
        payload=self.payload();schema,_=check_contract(payload)
        for scope,basis,adoption,verdict in [('quoted','action',[],'insufficient'),
                ('quoted','action',['Q1'],'supported'),('current','work_report',[],'supported')]:
            with self.subTest(scope=scope,basis=basis):
                raw=example(schema);row=raw['record_checks']['R1'];row['kind']='work';row['content']['verdict']='supported'
                row['qualification']=dict(speech_scope=scope,work_basis=basis,evidence=['Q1'],adoption_evidence=adoption,reason='原文用途依据')
                try:out=expand_checks(raw,payload)
                except ValueError as exc:self.fail('Qualification contract is missing: '+str(exc))
                self.assertEqual(out['record_checks'][0]['content']['verdict'],verdict)

    def test_completed_report_asks_only_which_old_task(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/ht04_checked.json').read_text(encoding='utf8'))
        out=reduce_v3(fixture['pipeline'],fixture['meeting'],fixture['history'])
        self.assertEqual(out['items'],[])
        self.assertEqual(out['updates'],[])
        review=out['review_records'][0]
        self.assertEqual(review['missing_fields'],['relation'])
        self.assertNotIn('承接',review['question'])
        self.assertIn('已有任务',review['question'])
        self.assertEqual(len(review['relation_options']),2)

    def payload(self):
        return dict(meeting=dict(case_id='M',segments=[dict(id='s1',text='可以考虑哨子方案。')]),
            records=[dict(record_id='R1')],events=[],
            review_issues=[dict(issue_id='R1:classification',record_id='R1',field='classification',
                reason='只是产品备选方案，未建立执行工作。',evidence=['Q1'])])

    def test_recheck_must_address_original_objection(self):
        payload=self.payload();schema,_=check_contract(payload,True);raw=example(schema)
        raw.pop('issue_checks',None)
        with self.assertRaisesRegex(ValueError,'issue_checks'):
            expand_checks(raw,payload,True)

    def test_unresolved_objection_cannot_receive_supported_content(self):
        payload=self.payload();schema,_=check_contract(payload,True);raw=example(schema)
        raw['record_checks']['R1']['content']['verdict']='supported'
        raw['issue_checks']={'R1:classification':dict(status='unresolved',reason='仍无法确定工作资格',evidence=['Q1'])}
        try:out=expand_checks(raw,payload,True)
        except ValueError as exc:self.fail('A valid unresolved assessment must be retained, not rejected: '+str(exc))
        self.assertEqual(out['record_checks'][0]['content']['verdict'],'insufficient')

    def test_original_objection_may_be_overturned_with_evidence(self):
        payload=self.payload();schema,_=check_contract(payload,True);raw=example(schema)
        raw['record_checks']['R1']['content']['verdict']='supported'
        raw['issue_checks']={'R1:classification':dict(status='overturned',reason='原文的明确评估安排支持工作，首检遗漏了这个动作。',evidence=['Q1'])}
        try:out=expand_checks(raw,payload,True)
        except ValueError as exc:self.fail('Evidence-backed overturn must be representable: '+str(exc))
        self.assertEqual(out['record_checks'][0]['content']['verdict'],'supported')


if __name__=='__main__':unittest.main()
