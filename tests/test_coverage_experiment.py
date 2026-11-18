import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('coverage_experiment',ROOT/'experiments/task-boundary-diagnosis/check_coverage.py')
experiment=importlib.util.module_from_spec(spec);spec.loader.exec_module(experiment)
from meeting_eval.model_client import ModelResponseError
from meeting_eval.service import Service
from meeting_eval.store import Store


class CoverageExperimentTests(unittest.TestCase):
    def test_cached_stop_result_does_not_send_next_case_on_reentry(self):
        for status in ('terminal_error','waiting_retry','recovery_required'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp);(out/'GN25').mkdir()
                experiment.atomic_json(out/'GN25/result.json',dict(extraction=dict(
                    _errors=[dict(recovery=dict(status=status))])))
                with patch.object(experiment,'ModelClient',side_effect=AssertionError('Must not request BG01')):
                    experiment.execute(out,True)
                self.assertFalse((out/'http-budget.json').exists())

    def test_only_check_runs_when_replaying_supported_frozen_gn25(self):
        frozen=experiment.frozen_gn25();stages=[]
        normalized=experiment.read(next(experiment.BASE.glob('model/context_v2/*/check_work/*/attempt-1/normalized.json')))
        class Client:
            model='deepseek-flash';endpoint='https://example.invalid'
            def call(self,prompt,payload,stage,**kwargs):
                stages.append(stage)
                if stage!='check_work':raise AssertionError('Unexpected model stage')
                response=copy.deepcopy(normalized);response['scope']=payload['scope']
                return response
        with tempfile.TemporaryDirectory() as tmp:
            pipe=experiment.FrozenPipeline(Client(),Path(tmp),{},frozen)
            out=pipe.run(frozen['meeting'],{'tasks':[]})
        self.assertEqual(stages,['check_work'])
        self.assertEqual(out['errors'],[])
        self.assertFalse(out['trace']['coverage_plan']['needs_repair'])
        self.assertEqual(out['events'],frozen['interpret']['events'])

    def test_terminal_failure_is_saved_with_only_task_fields_blocked(self):
        frozen=experiment.background()
        class Client:
            model='deepseek-flash';endpoint='https://example.invalid'
            def call(self,*args,**kwargs):raise ModelResponseError('payment required','terminal_error')
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'state.sqlite')
            try:
                pipe=experiment.FrozenPipeline(Client(),Path(tmp),{},frozen)
                svc=Service(store,experiment.TaskBranch(pipe))
                out=svc.process(frozen['job']['meeting'],'host','2026-11-17T21:00:00+08:00')
                self.assertEqual(out['status'],'partial')
                self.assertEqual({e.get('field') for e in out['extraction']['_errors']},{'items','updates'})
                self.assertEqual(out['extraction']['items'],[])
                self.assertEqual(out['recovery'][0]['status'],'terminal_error')
            finally:store.close()


if __name__=='__main__':unittest.main()
