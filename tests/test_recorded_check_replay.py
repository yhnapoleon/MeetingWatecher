import copy
from pathlib import Path
import tempfile
import unittest

from meeting_eval.context_protocol_v5 import expand_checks
from meeting_eval.context_v5 import ContextV5Pipeline
from meeting_eval.context_v3 import reduce_v3
from meeting_eval.stage_runner import run_stage
from meeting_eval.model_client import ModelResponseError
from meeting_eval.service import Service
from meeting_eval.store import Store
from test_check_transport import FIXTURES
from test_recovery_policy import Client


class RecordedCheckReplayTests(unittest.TestCase):
    def test_all_historical_failures_pass_original_scope_evidence_reducer_and_persistence(self):
        for f in FIXTURES:
            with self.subTest(case=f['case_id'],attempt=f['attempt']),tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp)
                c=Client([ModelResponseError('bad structure','syntax_invalid',dict(raw_text=f['text'],finish_reason=f['finish_reason']))])
                p={k:copy.deepcopy(f['payload'][k]) for k in ('meeting','ledger','candidates','records','events','history','evidence_catalog')}
                pipe=ContextV5Pipeline(c,folder,{})
                def checked(raw):return pipe.check(expand_checks(raw,p),p,p['meeting'],p['evidence_catalog'])
                out=run_stage(c,'JSON',f['payload'],'check_work',checked,folder,{})
                reduced=reduce_v3(dict(**out,coverage_findings=[],trace={}),p['meeting'],p['history'])
                trace={k:reduced[k] for k in ('pending','review_records','item_records','reports','context_records','deferred_topics')}
                extracted=dict(items=reduced['items'],updates=reduced['updates'],facts=[],decisions=[],unresolved=[],_errors=[],_task_trace=trace)
                class Replay:
                    strategy='context-v5'
                    def extract(self,*a):return copy.deepcopy(extracted)
                store=Store(folder/'state.sqlite')
                try:
                    svc=Service(store,Replay());source=f['source_input'];actor=source['actor']
                    result=svc.process(source['meeting'],actor,'2026-11-17T10:00:00+08:00')
                    self.assertEqual(result['status'],'processed');self.assertEqual(store.tasks(),[])
                    if f['case_id']=='C14':
                        self.assertEqual(len(result['extraction']['items']),1)
                        self.assertEqual(result['extraction']['items'][0]['operation'],'candidate')
                        review=svc.requirements(result['source_id'],actor)[0]
                        self.assertEqual(review['commitment_kind'],'conditional');self.assertTrue(review['commitment_quotes'])
                    else:
                        self.assertEqual(result['extraction']['items'],[])
                        self.assertIn('下周',svc.minutes(result['source_id'],actor))
                    self.assertEqual(c.calls,1)
                    again=svc.process(source['meeting'],actor,'2026-11-17T10:01:00+08:00')
                    self.assertEqual(again,result);self.assertEqual(store.tasks(),[])
                finally:store.close()


if __name__=='__main__':unittest.main()
