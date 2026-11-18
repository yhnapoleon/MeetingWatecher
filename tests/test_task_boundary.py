import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_context_state import ledger_fixture
from meeting_eval.context_state import canonical_ledger, canonical_records, reduce_context
from meeting_eval.inputs import normalize

ROOT = Path(__file__).resolve().parents[1]


def supported_record():
    m, e, ledger, r = ledger_fixture()
    r['check'] = dict(verdict='supported', issues=[], reason='原话支持', evidence=r['evidence'])
    e['time']['change'] = 'keep'
    e['other_changes'] = []
    return m, e, ledger, r


class TaskBoundaryTests(unittest.TestCase):
    def test_context_is_preserved_without_task_or_question(self):
        m, e, ledger, r = supported_record()
        r['kind'] = 'context_only'
        ledger['threads'][0]['updates'][0]['kind'] = 'context_only'
        ledger = canonical_ledger(ledger, m, None)
        records = canonical_records([r], ledger, [], m)
        result = reduce_context([], [], records, m, {'tasks': []})
        self.assertEqual(result['items'], [])
        self.assertEqual(result['review_records'], [])
        self.assertEqual(result['context_records'][0]['description'], '剪辑视频')
        with self.assertRaises(ValueError):
            canonical_records([r], ledger, [e], m)
        for changes in ({'question': '谁负责？'}, {'missing_fields': ['owner']}):
            with self.assertRaises(ValueError):
                canonical_records([{**r, **changes}], ledger, [], m)

    def test_context_can_later_become_current_work(self):
        m, e, ledger, r = supported_record()
        ledger['threads'][0]['updates'][0]['kind'] = 'context_only'
        old = canonical_ledger(ledger, m, None)
        m['segments'].append(dict(id='s2', speaker='A', person_ref='alice', text='这次我来剪辑视频。'))
        later = copy.deepcopy(old)
        later['threads'][0]['updates'].append(dict(after_segment='s2', kind='work',
            description='这次剪辑视频', evidence=[dict(segment_id='s2', quote='我来剪辑视频')]))
        current = canonical_ledger(later, m, old)
        records = canonical_records([r], current, [e], m)
        result = reduce_context([e], [], records, m, {'tasks': []})
        self.assertEqual(result['items'][0]['operation'], 'create')
        self.assertEqual(current['threads'][0]['updates'][0], old['threads'][0]['updates'][0])

    def test_disputed_context_classification_is_not_silently_hidden(self):
        m, e, ledger, r = supported_record()
        r.update(kind='context_only')
        r['check'].update(verdict='contradicted', issues=['classification'], reason='实际仍有工作待明确')
        result = reduce_context([], [], [r], m, {'tasks': []})
        self.assertEqual(len(result['review_records']), 1)
        self.assertEqual(result.get('context_records', []), [])

    def test_frozen_status_reports_do_not_ask_for_already_known_fields(self):
        base = ROOT/'runs/2026-11-15-full-validation'
        raw = next(json.loads(s) for s in (base/'corpus/input.jsonl').read_text(encoding='utf-8').splitlines()
                   if json.loads(s)['case_id'] == 'C17')
        trace = json.loads((base/'corpus/C17/result.json').read_text(encoding='utf-8'))['extraction']['_task_trace']
        result = reduce_context(trace['checked_events'], [], trace['checked_records'], normalize(raw, 'evaluator'), {'tasks': []})
        self.assertEqual(result['items'], [])
        self.assertEqual(result['updates'], [])
        self.assertEqual(result['review_records'], [])
        self.assertEqual(len(result['reports']), 2)
        self.assertEqual([r['state'] for r in result['reports']], ['completed', 'progress'])

    def test_report_with_real_uncertainty_keeps_review(self):
        m, e, ledger, r = supported_record()
        e['state']['kind'] = 'completed'
        for field in ('work', 'time', 'state', 'relation'):
            bad = copy.deepcopy(e)
            bad['checks'][field]['verdict'] = 'insufficient'
            result = reduce_context([bad], [], [r], m, {'tasks': []})
            self.assertEqual(result['reports'], [])
            self.assertEqual(len(result['review_records']), 1)
        r['missing_fields'] = ['scope']
        result = reduce_context([e], [], [r], m, {'tasks': []})
        self.assertEqual(result['reports'], [])
        self.assertEqual(len(result['review_records']), 1)

    def test_conditional_work_is_candidate_with_condition_and_never_creates(self):
        m, e, ledger, r = supported_record()
        m['segments'][0]['text'] = '如果拿到素材，我来剪辑视频。'
        span = dict(segment_id='s1', quote='如果拿到素材', start=0, end=6)
        e['commitment'].update(kind='conditional', evidence=[span])
        result = reduce_context([e], [], [r], m, {'tasks': []})
        self.assertEqual([i['operation'] for i in result['items']], ['candidate'])
        card = result['review_records'][0]
        self.assertEqual(card['commitment_kind'], 'conditional')
        self.assertEqual(card['commitment_quotes'], ['如果拿到素材'])
        self.assertIn('条件', card['question'])
        e['checks']['work']['verdict'] = 'contradicted'
        self.assertEqual(reduce_context([e], [], [r], m, {'tasks': []})['items'], [])

    def test_suggestion_asks_adoption_without_asserting_commitment(self):
        m, e, ledger, r = supported_record()
        e['commitment']['kind'] = 'suggested'
        result = reduce_context([e], [], [r], m, {'tasks': []})
        self.assertEqual(result['items'], [])
        self.assertEqual(result['review_records'][0]['category'], 'proposal')
        self.assertIn('采纳', result['review_records'][0]['question'])
        self.assertEqual(result['review_records'][0]['commitment_kind'], 'suggested')

    def test_local_time_issue_preserves_condition_or_proposal(self):
        for kind in ('conditional', 'suggested'):
            m, e, ledger, r = supported_record()
            e['commitment']['kind'] = kind
            e['time']['change'] = 'uncertain'
            r.update(question='以哪个期限为准？', missing_fields=['time'])
            r['check'].update(verdict='insufficient', issues=['time'])
            with self.subTest(kind=kind):
                result = reduce_context([e], [], [r], m, {'tasks': []})
                self.assertEqual([i['operation'] for i in result['items']], ['candidate'] if kind=='conditional' else [])
                self.assertEqual(result['review_records'][0]['commitment_kind'], kind)
                self.assertTrue(result['review_records'][0]['commitment_quotes'])
                self.assertEqual(result['review_records'][0]['question'], '以哪个期限为准？')
                self.assertTrue(all(i['due_date'] is None for i in result['items']))

    def test_pipeline_rejects_conditional_without_condition_evidence(self):
        from test_context_pipeline import ContextClient
        from meeting_eval.context_pipeline import ContextPipeline
        class Client(ContextClient):
            def call(self, prompt, payload, stage, **kwargs):
                value = super().call(prompt, payload, stage, **kwargs)
                if stage=='interpret_work':
                    value['events'][0]['commitment'].update(kind='conditional', evidence=[])
                return value
        m, *_ = ledger_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            result = ContextPipeline(Client(), Path(tmp), {}).run(m, {'tasks': []})
            self.assertEqual(result['errors'][0]['stage'], 'interpret_work')
            self.assertIn('Conditional work requires condition evidence', result['errors'][0]['detail'])
            self.assertEqual(result['checked_events'], [])

    def test_service_renders_context_and_condition_without_extra_writes(self):
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        m, e, ledger, r = supported_record()
        m.update(account_map={'alice': 'alice'}, audience=['host', 'alice'], writers=['host'])
        e['commitment']['kind'] = 'conditional'
        context = copy.deepcopy(r)
        context.update(record_id='R2', kind='context_only', description='会议现场有视频演示。')
        reduced = reduce_context([e], [], [r, context], m, {'tasks': []})
        class Fixed:
            def extract(self, meeting, history):
                return dict(items=reduced['items'], updates=[], facts=[], decisions=[], unresolved=[],
                    _task_trace={**reduced})
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'state.sqlite')
            try:
                service = Service(store, Fixed())
                out = service.process(m, 'host', '2026-11-15T00:00:00+08:00')
                minutes = service.minutes(out['source_id'], 'host')
                self.assertEqual(store.tasks(), [])
                self.assertIn('会议上下文', minutes)
                self.assertIn('会议现场有视频演示。', minutes)
                self.assertIn('条件', minutes)
                self.assertEqual(len(service.requirements(out['source_id'], 'host')), 1)
                with self.assertRaises(PermissionError):service.minutes(out['source_id'], 'outsider')
            finally:store.close()

    def test_repair_can_reclassify_work_as_context_without_rewriting_other_work(self):
        from test_context_pipeline import ContextClient
        from meeting_eval.context_pipeline import ContextPipeline
        class Client(ContextClient):
            def call(self, prompt, payload, stage, **kwargs):
                if stage == 'repair_work':
                    r = copy.deepcopy(payload['original_records'][0])
                    r.update(kind='context_only', missing_fields=[], question=None)
                    return dict(case_id='M', records=[r], events=[])
                if stage == 'check_repair':
                    return dict(case_id='M', checks=[], uncovered_spans=[], record_checks=[dict(record_id='R1',
                        verdict='supported', issues=[], reason='这是背景信息', evidence=['Q1'])])
                value = super().call(prompt, payload, stage, **kwargs)
                if stage == 'interpret_work':
                    value['records'].append({**copy.deepcopy(value['records'][0]), 'record_id': 'R2'})
                    value['events'].append({**copy.deepcopy(value['events'][0]), 'record_id': 'R2'})
                if stage == 'check_work':
                    value['record_checks'].append({**copy.deepcopy(value['record_checks'][0]), 'record_id': 'R2'})
                    value['checks'].append({**copy.deepcopy(value['checks'][0]), 'event_id': 'E2'})
                    value['record_checks'][0].update(verdict='contradicted', issues=['classification'], reason='背景被当工作')
                return value
        m, *_ = ledger_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            result = ContextPipeline(Client(), Path(tmp), {}).run(m, {'tasks': []})
            self.assertEqual(result['trace']['repair']['status'], 'checked')
            self.assertEqual(result['checked_events'], [result['trace']['repair']['before']['checked_events'][1]])
            self.assertEqual(result['checked_records'][0]['kind'], 'context_only')


if __name__ == '__main__':unittest.main()
