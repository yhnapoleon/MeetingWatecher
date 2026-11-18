import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'runs/2026-11-17-full-meeting-ES2002a'


def module():
    spec=importlib.util.spec_from_file_location('recover_protocol',ROOT/'experiments/full-meeting/recover_protocol.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod


class FullMeetingRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.out=Path(self.tmp.name)

    def compatible_preflight(self, mod):
        # Exercise the positive import against the dependency and prompt versions
        # that actually generated the frozen tracking responses.
        snapshot = self.out / 'snapshot'
        with zipfile.ZipFile(SOURCE / 'source.zip') as archive:
            for name in archive.namelist():
                if name.startswith(('prompts/', 'meeting_eval/')):
                    archive.extract(name, snapshot)
        with patch.object(mod, 'ROOT', snapshot), patch('meeting_eval.context_v5.ROOT', snapshot):
            return mod.preflight(SOURCE)

    def test_new_tracking_policy_rejects_legacy_checkpoint(self):
        with self.assertRaisesRegex(ValueError, 'Tracking (dependency|prompt) changed'):
            module().preflight(SOURCE)

    def test_revalidates_complete_tracking_before_import(self):
        mod=module();result=self.compatible_preflight(mod)
        self.assertEqual(result['tracking_segments'],434)
        self.assertEqual(len(result['tracking_nodes']),4)
        self.assertEqual(result['context'],{'tasks':[],'decisions':[]})

    def test_changed_input_cannot_reuse_tracking(self):
        mod=module();source=self.out/'source';source.mkdir()
        for name in ('input.json','result.json','config.json','inference.json','source.zip','state.sqlite'):
            shutil.copy2(SOURCE/name,source/name)
        value=json.loads((source/'input.json').read_text(encoding='utf8'));value['segments'][-1]['text']='Changed'
        (source/'input.json').write_text(json.dumps(value),encoding='utf8')
        with self.assertRaises(ValueError):mod.preflight(source)

    def test_changed_account_mapping_is_not_hidden_by_model_projection(self):
        mod=module();source=self.out/'source';shutil.copytree(SOURCE,source)
        value=json.loads((source/'input.json').read_text(encoding='utf8'))
        value['account_map']={'MEE006':'unapproved-account'}
        (source/'input.json').write_text(json.dumps(value),encoding='utf8')
        with self.assertRaisesRegex(ValueError,'Stored source differs'):mod.preflight(source)

    def test_concurrent_requests_and_new_output_cannot_reset_budget(self):
        mod=module();state=self.out/'budget.json';destination=self.out/'result'
        def reserve(_):
            try:mod.reserve_request(state,8,destination);return True
            except mod.ModelResponseError:return False
        with ThreadPoolExecutor(max_workers=10) as pool:results=list(pool.map(reserve,range(12)))
        self.assertEqual(sum(results),8)
        self.assertEqual(json.loads(state.read_text())['used'],8)
        with self.assertRaises(ValueError):mod.reserve_request(state,8,self.out/'another-result')
        with self.assertRaises(mod.ModelResponseError):mod.reserve_request(state,8,destination)

    def test_full_service_refreshes_minutes_with_new_work_context(self):
        mod=module();frozen=self.compatible_preflight(mod)
        from meeting_eval.extract import Extractor
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        from meeting_eval.inputs import digest
        calls=[]
        def model_call(client,prompt,payload,stage,**kwargs):
            calls.append(stage)
            self.assertEqual(stage,'check_minutes')
            self.assertEqual(payload['read_only_context']['work_records'],[{'record_id':'fresh-work'}])
            from test_minutes_review import assessment
            return assessment(payload)
        # Work extraction is already tested separately. This integration checks
        # that the recovery entry uses normal full Extractor/Service minutes flow.
        extracted={**json.loads((SOURCE/'result.json').read_text(encoding='utf8'))['extraction'],
            '_errors':[],'_task_trace':dict(checked_records=[{'record_id':'fresh-work'}],review_records=[],item_records=[],pending=[],deferred_topics=[]),
            'items':[],'updates':[]}
        with (patch('meeting_eval.model_client.credentials',return_value=('fake','deepseek-flash','https://api.deepseek.com/chat/completions')),
             patch('meeting_eval.model_client.ModelClient.call',model_call),
             patch.object(Extractor,'evidence_extract',return_value=extracted)):
            ex=mod.RecoveryExtractor(None,self.out/'model',frozen)
            store=Store(self.out/'state.sqlite')
            try:
                svc=Service(store,ex);result=svc.process(frozen['meeting'],'evaluator','2026-11-17T13:00:00+08:00')
                self.assertEqual(result['status'],'processed')
                self.assertEqual(calls,['check_minutes'])
                self.assertEqual(result['extraction']['_minutes_review']['status'],'accepted')
                before=digest(result);self.assertEqual(digest(svc.process(frozen['meeting'],'evaluator','2026-11-17T13:00:00+08:00')),before)
                self.assertEqual(calls,['check_minutes'])
            finally:store.close()


if __name__=='__main__':unittest.main()
