import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meeting_eval.inputs import normalize
from meeting_eval.extract import validate

ROOT = Path(__file__).resolve().parents[1]


class RepairTests(unittest.TestCase):
    def setUp(self):
        cases = [json.loads(s) for s in (ROOT/'data/mvp-v1/input.jsonl').read_text(encoding='utf-8').splitlines()]
        self.raw = next(c for c in cases if c['case_id']=='C07')
        self.meeting = normalize(self.raw,'evaluator')
        rows = [json.loads(s) for s in (ROOT/'runs/2026-11-14-deepseek-flash-dev-v1/predictions.jsonl').read_text(encoding='utf-8').splitlines()]
        self.items = next(c['items'] for c in rows if c['case_id']=='C07')
        self.result = dict(items=self.items,facts=[],unresolved=[],decisions=[],updates=[])
        self.context = dict(tasks=[],decisions=[])

    def test_non_speaking_participants_remain_valid_owners(self):
        self.assertEqual(set(self.meeting['roster']),{'FEE005','MEE006','MEE007','MEE008'})
        self.assertEqual(len(validate(self.result,self.meeting,self.context)['items']),3)

    def test_execution_settings_do_not_change_model_input(self):
        from meeting_eval.extract import model_input
        altered = copy.deepcopy(self.raw)
        altered.update(account_map={'MEE006':'ou_6'},writers=[],audience=['evaluator','guest'])
        self.assertEqual(model_input(normalize(altered,'evaluator')),model_input(self.meeting))
        self.assertNotIn('account_map',model_input(self.meeting))

    def test_known_timestamp_supplies_local_calendar_date(self):
        from meeting_eval.extract import model_input
        raw = json.loads((ROOT/'examples/m1.json').read_text(encoding='utf-8'))
        raw['started_at'] = '2026-11-09T00:05:00+08:00'
        value = model_input(normalize(raw,'host'))
        self.assertEqual(value['meeting_date'],'2026-11-09')

    def test_explicit_weekday_uses_calendar_math_and_cited_phrase(self):
        from meeting_eval.extract import resolve_calendar_dates
        from tests.test_mvp import extraction,action
        raw = json.loads((ROOT/'examples/m1.json').read_text(encoding='utf-8'))
        value = extraction([action()])
        value['items'][0]['due_date'] = None
        resolve_calendar_dates(value,normalize(raw,'host'))
        self.assertEqual(value['items'][0]['due_date'],'2026-11-13')
        self.assertEqual(value['_date_resolutions'][0]['from'],None)
        raw['started_at']='2026-12-30T10:00:00+08:00'
        raw['segments'][1]['text']='我来，下周一下班前发群里。'
        value['items'][0].update(due_date=None,due_text='下周一下班前')
        resolve_calendar_dates(value,normalize(raw,'host'))
        self.assertEqual(value['items'][0]['due_date'],'2027-01-04')
        value['items'][0].update(due_date=None,due_text='下周五')
        resolve_calendar_dates(value,normalize(raw,'host'))
        self.assertIsNone(value['items'][0]['due_date'])  # Phrase absent from cited evidence.
        value['items'][0].update(due_text='尽快')
        resolve_calendar_dates(value,normalize(raw,'host'))
        self.assertIsNone(value['items'][0]['due_date'])

    def test_partial_validation_preserves_good_items_with_explicit_errors(self):
        from meeting_eval.extract import validate_partial
        result = copy.deepcopy(self.result)
        result['items'][1]['owner_ref'] = 'invented-person'
        valid = validate_partial(result,self.meeting,self.context)
        self.assertEqual(len(valid['items']),2)
        self.assertEqual(valid['_errors'][0]['field'],'items')
        self.assertEqual(valid['_errors'][0]['index'],1)
        self.assertEqual(valid['_errors'][0]['rejected']['owner_ref'],'invented-person')

    def test_stage_assembly_preserves_actions_and_exposes_failed_stage(self):
        from meeting_eval.extract import assemble
        a = {'items':self.items}
        result = assemble({'actions':a,'facts':{'facts':[], 'unresolved':[], 'items':[]},
                           'decisions':{'_errors':[{'stage':'decisions','error':'TimeoutError'}]}},self.meeting,self.context)
        self.assertEqual(result['items'],self.items)
        self.assertEqual(result['_errors'][0]['stage'],'decisions')

    def test_service_exposes_partial_status_and_keeps_valid_output(self):
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        class Extract:
            def extract(inner,m,c):
                return {**self.result,'_errors':[{'field':'facts','error':'invalid_evidence'}]}
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'state.sqlite')
            try:
                svc = Service(store,Extract())
                result = svc.process(self.raw,'evaluator','2026-11-14T00:00:00+08:00')
                self.assertEqual(result['status'],'partial')
                self.assertEqual(len(result['extraction']['items']),3)
                self.assertIn('未完整完成',svc.minutes(result['source_id'],'evaluator'))
            finally:
                store.close()

    def test_changed_extractor_cannot_silently_reuse_database(self):
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        class Configured:
            config = {'strategy':'one'}
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'state.sqlite')
            try:
                Service(store,Configured())
                other = Configured()
                other.config = {'strategy':'two'}
                with self.assertRaises(ValueError):
                    Service(store,other)
            finally:
                store.close()

    def test_extra_model_fields_cannot_override_internal_ids(self):
        from meeting_eval.extract import validate_partial
        raw = {**self.result, '_errors':None, 'decisions':[dict(attribute='范围', statement='电视',
            supersedes=None,evidence_ids=[self.meeting['segments'][0]['id']],id='model-id')]}
        clean = validate_partial(raw,self.meeting,self.context)
        self.assertNotIn('id',clean['decisions'][0])
        self.assertEqual(clean['_errors'],[])

    def test_baseline_missing_items_is_a_failure(self):
        from scripts.run_meeting_eval import BaselineExtractor
        model = object.__new__(BaselineExtractor)
        model.raw = self.raw
        model.stage = lambda *args,**kwargs: {'case_id':'C07'}
        result = model.extract(self.meeting,self.context)
        self.assertTrue(result['_errors'])
        self.assertTrue(model.retry(self.meeting,self.context,result)['_errors'])

    def test_retry_does_not_invalidate_successful_frozen_fields(self):
        from meeting_eval.extract import merge_retry
        first = {**self.result,'_errors':[{'field':'facts','error':'invalid'}]}
        retry = {**self.result,'items':[],'facts':[{'statement':'好','evidence_ids':[self.meeting['segments'][0]['id']]}],
                 '_errors':[{'field':'items','error':'invalid'}]}
        result = merge_retry(first,retry)
        self.assertEqual(result['items'],self.items)
        self.assertEqual(result['_errors'],[])

    def test_partial_retry_recovers_without_repeating_successful_writes(self):
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        from tests.test_mvp import extraction,action,T0,T2
        raw = json.loads((ROOT/'examples/m1.json').read_text(encoding='utf-8'))
        class Flaky:
            calls = 0
            contexts = []
            def extract(inner,m,c):
                inner.calls += 1
                inner.contexts.append(copy.deepcopy(c))
                value = extraction([action()])
                if inner.calls == 1:
                    value['_errors'] = [{'stage':'facts','error':'TimeoutError'}]
                else:
                    value['facts'] = [{'statement':'已经承接','evidence_ids':['M1.2']}]
                return value
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'state.sqlite')
            try:
                model = Flaky()
                svc = Service(store,model)
                first = svc.process(raw,'host',T0)
                second = svc.process(raw,'host',T2)
                self.assertEqual(second['status'],'processed')
                self.assertEqual(model.calls,2)
                self.assertEqual(model.contexts[0],model.contexts[1])
                self.assertEqual(first['bindings'],second['bindings'])
                self.assertEqual(len(store.tasks()),1)
            finally:
                store.close()

    def test_create_update_conflict_stays_pending(self):
        from meeting_eval.service import Service
        from meeting_eval.store import Store,Simulator
        from tests.test_mvp import extraction,action,FixedExtractor,T0,T2
        raw = json.loads((ROOT/'examples/m1.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'state.sqlite')
            try:
                sim = Simulator(store)
                sim.seed(dict(guid='X',summary='整理案例',status='open',readers=['host','chen'],
                    writers=['host'],assignee='chen',tenant='local',series=raw['series']),T0)
                value = extraction([action('整理案例。')])
                value['updates'] = [dict(target_guid='X',description='整理案例',owner_ref='chen',
                    status='done',effective_at=None,evidence_ids=['M1.2'])]
                result = Service(store,FixedExtractor(value)).process(raw,'host',T2)
                self.assertEqual(len(store.tasks()),1)
                self.assertEqual(sim.get('X','host')['status'],'open')
                self.assertTrue(any(p['reason']=='create_update_conflict' for p in result['pending']))
            finally:
                store.close()

    def test_invalid_optional_field_cannot_poison_decision_history(self):
        from meeting_eval.extract import validate_partial
        raw = {**self.result,'decisions':[dict(attribute='范围',statement='电视',supersedes=[],
            evidence_ids=[self.meeting['segments'][0]['id']])]}
        value = validate_partial(raw,self.meeting,self.context)
        self.assertEqual(value['decisions'],[])
        self.assertEqual(value['_errors'][0]['field'],'decisions')

    def test_split_retries_only_failed_branch(self):
        from meeting_eval.extract import Extractor
        with tempfile.TemporaryDirectory() as tmp:
            model = object.__new__(Extractor)
            model.strategy,model.config,model.out = 'split-v2',{},Path(tmp)
            calls = []
            def stage(name,payload,fresh=False):
                calls.append((name,fresh))
                if name=='actions':
                    return {'items':self.items}
                if name=='facts':
                    if not fresh:
                        return {'_errors':[{'stage':'facts','error':'TimeoutError'}]}
                    return {'facts':[],'unresolved':[]}
                return {'decisions':[]}
            model.stage = stage
            first = model.extract(self.meeting,self.context)
            second = model.retry(self.meeting,self.context,first)
            self.assertEqual(second['_errors'],[])
            self.assertEqual(first['items'],second['items'])
            self.assertEqual(sorted(calls),[('actions',False),('decisions',False),('facts',False),('facts',True)])

    def test_model_retry_preserves_first_raw_response(self):
        from meeting_eval.model_client import ModelClient
        import io
        first = {'choices':[{'finish_reason':'stop','message':{'content':'[]'}}]}
        second = {'choices':[{'finish_reason':'stop','message':{'content':'{"items":[]}'}}]}
        with tempfile.TemporaryDirectory() as tmp, patch('meeting_eval.model_client.credentials',return_value=('secret','test','https://example.invalid')):
            client = ModelClient(None,tmp)
            with patch('urllib.request.urlopen',side_effect=[io.BytesIO(json.dumps(first).encode()),io.BytesIO(json.dumps(second).encode())]):
                with self.assertRaises(ValueError):
                    client.call('prompt',{},'actions')
                self.assertEqual(client.call('prompt',{},'actions',fresh=True),{'items':[]})
            responses = list(Path(tmp).rglob('response.json'))
            self.assertEqual(len(responses),2)
            self.assertEqual(len(list(Path(tmp).rglob('meta.json'))),2)
            self.assertTrue(any(json.loads(p.read_text())==first for p in responses))

    def test_eval_resume_keeps_original_latency_and_rejects_changed_labels(self):
        from scripts.run_meeting_eval import evaluate
        class Model:
            config = {'strategy':'test'}
            def __init__(inner,env,out,strategy):
                Path(out).mkdir(parents=True,exist_ok=True)
            def extract(inner,m,c):
                return copy.deepcopy(self.result)
        with tempfile.TemporaryDirectory() as tmp, patch('scripts.run_meeting_eval.Extractor',Model):
            out = Path(tmp)
            with patch('scripts.run_meeting_eval.time.perf_counter',side_effect=[0,10]):
                evaluate(out,None,'actions',only=['C07'])
            with patch('scripts.run_meeting_eval.time.perf_counter',side_effect=[100,100.001]):
                evaluate(out,None,'actions',only=['C07'])
            timing = json.loads((out/'timings.json').read_text())[0]
            self.assertEqual(timing['seconds'],10)
            self.assertEqual(timing['last_resume_seconds'],.001)
            original = Path.read_text
            def changed(path,*args,**kwargs):
                text = original(path,*args,**kwargs)
                return text+'\n' if path==ROOT/'data/mvp-v1/labels.jsonl' else text
            with patch.object(Path,'read_text',changed),self.assertRaisesRegex(ValueError,'Changed input'):
                evaluate(out,None,'actions',only=['C07'])


if __name__ == '__main__':
    unittest.main()
