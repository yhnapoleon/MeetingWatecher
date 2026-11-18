import copy
import json
import unittest
import sys
from pathlib import Path

from test_context_state import ledger_fixture
from meeting_eval.context_state import canonical_records, reduce_context
from meeting_eval.context_v3 import reduce_v3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'experiments/task-boundary'))


def checked_fixture():
    m,e,ledger,r = ledger_fixture()
    r['check'] = dict(verdict='supported', reason='原文明确', evidence=r['evidence'], issues=[])
    return m,e,ledger,r


class UserSolutions(unittest.TestCase):
    def test_bound_repair_supplies_missing_identity_and_rejects_foreign_slot(self):
        from diagnose_review_feedback import recorded
        from meeting_eval.context_protocol_v4 import repair_contract, expand_patch
        from meeting_eval.context_protocol import example
        _, _, payload, old = recorded(ROOT/'runs/2026-11-16-baseline-reassessment/small-v1/A-r1/G-omitted', 'repair_work')
        schema, binding = repair_contract(payload)
        raw = example(schema)
        raw.update(case_id=payload['meeting']['case_id'], scope=binding['scope'], targets={},
                   dispositions=old['dispositions'])
        record = {k:v for k,v in old['records'][0].items() if k not in ('record_id','thread_ids','introduced_by')}
        event = {k:v for k,v in old['events'][0].items() if k not in ('record_id','event_id')}
        raw['additions']={'O1':[dict(record=record,event=event)]}
        fixed=expand_patch(raw,payload)
        self.assertEqual(fixed['records'][0]['introduced_by'], 'O1')
        self.assertEqual(fixed['records'][0]['record_id'], 'R_O1_1')
        self.assertEqual(fixed['records'][0]['description'], old['records'][0]['description'])
        bad=copy.deepcopy(raw);bad['additions']['O999']=[]
        with self.assertRaises(ValueError):expand_patch(bad,payload)
        bad=copy.deepcopy(raw);bad['scope']='stale'
        with self.assertRaises(ValueError):expand_patch(bad,payload)

    def test_bound_checks_reject_extra_event_but_preserve_discovery(self):
        from diagnose_review_feedback import recorded
        from meeting_eval.context_protocol_v5 import check_contract, expand_checks
        _, _, payload, old = recorded(ROOT/'runs/2026-11-16-baseline-reassessment/small-v1/D-r2/G-omitted', 'check_work')
        schema, binding = check_contract(payload)
        raw = dict(case_id=payload['meeting']['case_id'], scope=binding['scope'],
            record_checks={r['record_id']:{k:v for k,v in r.items() if k!='record_id'} for r in old['record_checks']},
            checks={e['event_id']+'.'+field:value for e in old['checks'] for field,value in e['fields'].items()},coverage_findings=old['coverage_findings'])
        for row in raw['record_checks'].values():
            row['qualification']=dict(speech_scope='current',work_basis='action' if row['kind']=='work' else 'none',
                evidence=row['evidence'],adoption_evidence=[],reason='此测试保持旧记录语义，仅将输入迁到新资格契约。')
        with self.assertRaisesRegex(ValueError, 'E2'):expand_checks(raw,payload)
        raw['checks']={k:v for k,v in raw['checks'].items() if not k.startswith('E2.')}
        expanded=expand_checks(raw,payload)
        self.assertEqual([c['event_id'] for c in expanded['checks']], ['E1'])
        self.assertEqual(expanded['coverage_findings'], old['coverage_findings'])
        del raw['checks']['E1.time']
        with self.assertRaises(ValueError):expand_checks(raw,payload)

    def test_closed_gap_is_not_reopened_by_historical_issue(self):
        folder = ROOT/'runs/2026-11-15-context-v4/small-v2/B-r2/M2'
        case = json.loads((folder/'input.json').read_text(encoding='utf8'))
        pipeline = json.loads((folder/'pipeline.json').read_text(encoding='utf8'))
        # The original event says unknown intent: it must remain reviewable,
        # but the checker explicitly closed the owner gap.
        result = reduce_v3(pipeline, case['meeting'], case['history'])
        self.assertNotIn('owner', result['review_records'][0]['missing_fields'])
        self.assertNotIn('具体内容', result['review_records'][0]['question'])

    def test_decided_work_is_retained_without_inventing_acceptance(self):
        m, e, ledger, r = checked_fixture()
        e['commitment'].update(kind='decided', evidence=e['work']['evidence'])
        e['owner'].update(kind='unknown', ref=None, label=None, evidence=[])
        e['time'].update(kind='deadline', text='今天', date=None, change='set')
        out = reduce_context([e], [], [r], m, {'tasks':[]})
        self.assertEqual(len(out['items']), 1)
        self.assertEqual(out['items'][0]['operation'], 'candidate')
        self.assertIsNone(out['items'][0]['owner_ref'])
        self.assertEqual(out['items'][0]['due_text'], '今天')
        self.assertEqual(out['review_records'][0]['missing_fields'], ['owner'])
        self.assertNotIn('是否', out['review_records'][0]['question'])

    def test_explicit_deferral_is_collect_only(self):
        m, e, ledger, r = checked_fixture()
        r.update(kind='deferred_topic', description='上线后监控面板先放着，今天不定。')
        canonical_records([r], ledger, [], m)
        out = reduce_context([], [], [r], m, {'tasks':[]})
        self.assertEqual(out['items'], [])
        self.assertEqual(out['review_records'], [])
        self.assertEqual(out['deferred_topics'][0]['description'], r['description'])
        with self.assertRaises(ValueError):
            canonical_records([r], ledger, [e], m)
        r['question']='谁做？'
        with self.assertRaises(ValueError):
            canonical_records([r], ledger, [], m)

    def test_no_deadline_does_not_mean_deferred(self):
        m, e, ledger, r = checked_fixture()
        e['time'].update(kind='unspecified', text=None, date=None, change='keep')
        out = reduce_context([e], [], [r], m, {'tasks':[]})
        self.assertEqual(len(out['items']), 1)
        self.assertEqual(out['deferred_topics'], [])

    def test_checked_work_window_survives_without_becoming_deadline(self):
        m,e,ledger,r=checked_fixture()
        e['time'].update(kind='work_window',text='今天',date='2026-11-16',change='keep')
        out=reduce_context([e],[],[r],m,{'tasks':[]})
        self.assertIn('今天',out['items'][0]['description'])
        self.assertIsNone(out['items'][0]['due_date'])
        self.assertIsNone(out['items'][0]['due_text'])
        e['checks']['time']['verdict']='contradicted'
        rejected=reduce_context([e],[],[r],m,{'tasks':[]})
        self.assertEqual(rejected['items'],[])


if __name__ == '__main__':
    unittest.main()
