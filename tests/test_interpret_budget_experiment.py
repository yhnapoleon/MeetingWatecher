import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('interpret_budget_run',ROOT/'experiments/interpret-budget/run.py')
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class BudgetExperimentTests(unittest.TestCase):
    def test_waiting_retry_resumes_but_processed_result_is_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            pending={'status':'partial','recovery':[{'status':'waiting_retry'}]}
            runner.atomic_json(folder/'result.json',pending)
            with patch.object(runner,'execute_case',return_value={'status':'processed'}) as execute:
                self.assertEqual(runner.cached_or_resume({},folder)['status'],'processed')
                execute.assert_called_once()
            runner.atomic_json(folder/'result.json',{'status':'processed'})
            with patch.object(runner,'execute_case',side_effect=AssertionError('Repeated completed case')):
                self.assertEqual(runner.cached_or_resume({},folder)['status'],'processed')

    def test_changed_resume_identity_does_not_overwrite_any_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);case=out/'natural'/'GN29';case.mkdir(parents=True)
            original={'cases':['GN29'],'execution_hashes':{'run.py':'before'}}
            runner.atomic_json(out/'manifest.json',original)
            runner.atomic_json(case/'preflight.json',{'prompt':'before'})
            runner.atomic_json(case/'config.json',{'version':1})
            before={p.name:p.read_bytes() for p in (out/'manifest.json',case/'preflight.json',case/'config.json')}
            with self.assertRaisesRegex(ValueError,'identity'):
                runner.freeze_preflight(out,{**original,'execution_hashes':{'run.py':'after'}},
                    {'GN29':{'prompt':'after'}},{'GN29':{'version':2}})
            self.assertEqual(before,{p.name:p.read_bytes() for p in (out/'manifest.json',case/'preflight.json',case/'config.json')})

    def test_eighth_request_survives_restart_ninth_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'budget.json'
            for _ in range(8):runner.reserve_request(path)
            with self.assertRaisesRegex(ValueError,'limit'):runner.reserve_request(Path(str(path)))
            self.assertEqual(json.loads(path.read_text(encoding='utf8'))['used'],8)
            with self.assertRaises(ValueError):runner.reserve_request(path,9)

    def test_http_failure_charged_and_cache_not_charged(self):
        from meeting_eval.model_client import ModelClient
        with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')):
            path=Path(tmp);client=ModelClient(None,path/'model')
            reply={'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}
            error=urllib.error.HTTPError('https://example.invalid',400,'Unsupported low',{},io.BytesIO(b'unsupported low'))
            with patch('urllib.request.urlopen',side_effect=[error,io.BytesIO(json.dumps(reply).encode())]) as network:
                with runner.limited_http(path/'budget.json'):
                    with self.assertRaises(ValueError):client.call('JSON',{},'probe',inference={'thinking':'enabled','reasoning_effort':'low'})
                    client.call('JSON',{'new':True},'probe')
                    client.call('JSON',{'new':True},'probe')
            self.assertEqual(network.call_count,2)
            self.assertEqual(runner.read(path/'budget.json')['used'],2)

    def test_frozen_input_and_ledger_tampering_rejected(self):
        frozen=runner.load_frozen_case('GN29')
        for part in ('meeting','ledger'):
            row=copy.deepcopy(frozen)
            if part=='meeting':row['job']['meeting']['segments'][0]['text']+=' changed'
            else:row['trace']['ledger']['threads'][0]['updates'][0]['description']+=' changed'
            with self.subTest(part=part),self.assertRaises(ValueError):
                runner.validate_frozen_case(row['job'],row['trace'],row['prior_payload'])

    def test_stage_settings_only_change_interpretation(self):
        frozen=runner.load_frozen_case('GN25')
        with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')):
            ex=runner.TaskOnlyExtractor(None,Path(tmp)/'model',frozen)
            old=frozen['config']['task_pipeline']['inference']
            for stage in ('check_work','repair_work','check_repair','track_context'):
                self.assertEqual(ex.task_pipeline.inference[stage],old[stage])
            self.assertEqual(ex.task_pipeline.inference['interpret_work']['reasoning_effort'],'low')
            with patch.object(ex,'stage',side_effect=AssertionError('Independent stage called')),patch.object(ex.minutes_reviewer,'review',side_effect=AssertionError('Minutes called')):
                with patch.object(ex.task_pipeline,'run',return_value={'errors':[],'trace':{},'checked_records':[],'checked_events':[],'coverage_findings':[],'uncovered_spans':[]}):
                    result=ex.extract(frozen['meeting'],{'tasks':[],'decisions':[]})
            self.assertEqual(result['facts'],[])
            self.assertEqual(result['_experiment']['scope'],'task_branch_only')

    def test_preflight_payload_and_prompt_equal_prior_request_without_labels(self):
        frozen=runner.load_frozen_case('GN29')
        with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')):
            ex=runner.TaskOnlyExtractor(None,Path(tmp)/'model',frozen)
            preflight=runner.preflight(ex,frozen)
            self.assertTrue(preflight['prompt_equal'])
            self.assertTrue(preflight['payload_equal'])
            self.assertNotIn('gold',json.dumps(preflight['payload']).lower())

    def test_low_400_is_terminal_without_high_fallback(self):
        from meeting_eval.model_client import ModelClient
        from meeting_eval.stage_runner import run_stage
        with tempfile.TemporaryDirectory() as tmp,patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')):
            root=Path(tmp);client=ModelClient(None,root/'model')
            error=urllib.error.HTTPError(client.endpoint,400,'Unsupported low',{},io.BytesIO(b'unsupported low'))
            with patch('urllib.request.urlopen',side_effect=error) as network,runner.limited_http(root/'budget.json'):
                with self.assertRaises(ValueError):
                    run_stage(client,'JSON',{'case_id':'test'},'interpret_work',lambda x:x,root/'nodes',{'thinking':'enabled','reasoning_effort':'low','max_tokens':32768})
            self.assertEqual(network.call_count,1)
            self.assertEqual(json.loads(network.call_args[0][0].data)['reasoning_effort'],'low')


if __name__=='__main__':unittest.main()
