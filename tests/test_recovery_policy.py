import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meeting_eval.model_client import ModelResponseError
from meeting_eval.stage_runner import run_stage
from test_check_transport import FIXTURES


class Client:
    model='deepseek-flash';endpoint='https://example.invalid'
    def __init__(self,steps):self.steps=list(steps);self.calls=0
    def call(self,*args,**kwargs):
        self.calls+=1;step=self.steps.pop(0)
        if isinstance(step,BaseException):raise step
        return step


class RecoveryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.folder=Path(self.tmp.name)
    def call(self,c,**kwargs):return run_stage(c,'JSON',{},'probe',lambda x:x,self.folder,{},**kwargs)

    def test_network_failure_does_not_consume_content_recovery(self):
        c=Client([ModelResponseError('429','transport_failed'),ModelResponseError('bad JSON','syntax_invalid'),{'ok':True}])
        with patch('meeting_eval.stage_runner.time.sleep'):self.assertEqual(self.call(c),{'ok':True})
        self.assertEqual(c.calls,3)

    def test_interleaved_transport_and_format_failures_cap_at_four(self):
        c=Client([ModelResponseError('429','transport_failed'),ModelResponseError('bad','syntax_invalid'),ModelResponseError('503','transport_failed'),ModelResponseError('bad','syntax_invalid')])
        with patch('meeting_eval.stage_runner.time.sleep'):
            for _ in range(2):
                with self.assertRaises(ValueError):self.call(c)
        self.assertEqual(c.calls,4)
        state=json.loads(next(self.folder.rglob('state.json')).read_text(encoding='utf8'))
        self.assertEqual(state['status'],'recovery_required')

    def test_manual_grant_is_one_bounded_extension(self):
        c=Client([ModelResponseError('bad','syntax_invalid') for _ in range(3)]+[{'ok':True}])
        with self.assertRaises(ValueError) as failure:self.call(c)
        node=failure.exception.recovery['node_id']
        grant={node:'retry-1'}
        with self.assertRaises(ValueError):self.call(c,recovery_grant=grant)
        with self.assertRaises(ValueError):self.call(c,recovery_grant=grant)
        with self.assertRaises(ValueError):self.call(c,recovery_grant={node:'retry-2'})
        self.assertEqual(c.calls,3)

    def test_automatic_and_manual_transport_recovery_total_never_exceeds_six(self):
        kinds=['transport_failed','syntax_invalid','transport_failed','syntax_invalid','transport_failed','syntax_invalid']
        c=Client([ModelResponseError('injected failure',kind) for kind in kinds]+[{'unexpected':True}])
        with patch('meeting_eval.stage_runner.time.sleep'):
            with self.assertRaises(ValueError) as failure:self.call(c)
            node=failure.exception.recovery['node_id']
            for token in ('one','one','two'):
                with self.assertRaises(ValueError):self.call(c,recovery_grant={node:token})
        self.assertEqual(c.calls,6)

    def test_recorded_structure_is_accepted_without_second_model_call(self):
        for i,f in enumerate(FIXTURES):
            c=Client([ModelResponseError('JSON','syntax_invalid',dict(raw_text=f['text'],finish_reason=f['finish_reason']))])
            def validate(raw):
                from meeting_eval.context_protocol_v4 import closed_validate
                closed_validate(raw,f['contract']);return raw
            out=run_stage(c,'JSON',f['payload'],'check_work',validate,self.folder/str(i),{})
            self.assertEqual(out['case_id'],f['case_id']);self.assertEqual(c.calls,1)
            accepted=next((self.folder/str(i)).rglob('accepted.json'));accepted.write_text('{')
            again=run_stage(c,'JSON',f['payload'],'check_work',validate,self.folder/str(i),{})
            self.assertEqual(again,out);self.assertEqual(c.calls,1)
            state=json.loads(next((self.folder/str(i)).rglob('state.json')).read_text(encoding='utf8'))
            self.assertEqual(state['attempts'][0]['candidate_file'],'normalized.json')

    def test_unknown_interrupted_requests_spend_reserved_time(self):
        class Crash(Client):
            def call(self,*a,**k):self.calls+=1;raise KeyboardInterrupt()
        c=Crash([])
        with self.assertRaises(KeyboardInterrupt):self.call(c)
        with patch('meeting_eval.stage_runner.time.sleep'):
            with self.assertRaises(KeyboardInterrupt):self.call(c)
            with self.assertRaises(ValueError):self.call(c)
        self.assertEqual(c.calls,2)
        self.assertEqual(json.loads(next(self.folder.rglob('state.json')).read_text(encoding='utf8'))['charged_request_seconds'],600)

    def test_concurrent_node_call_cannot_reserve_a_second_request(self):
        import threading
        entered=threading.Event();release=threading.Event();result=[]
        class Blocking(Client):
            def call(self,*a,**k):
                self.calls+=1;entered.set();release.wait(5);return {'ok':True}
        c=Blocking([])
        thread=threading.Thread(target=lambda:result.append(self.call(c)))
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            with self.assertRaises(ValueError) as failure:self.call(c)
            self.assertEqual(failure.exception.recovery['reason'],'stage_busy')
            self.assertEqual(c.calls,1)
        finally:release.set();thread.join()
        self.assertEqual(result,[{'ok':True}])

    def test_local_normalization_never_accepts_truncation_or_wrong_scope(self):
        f=FIXTURES[0]
        for finish in ('length','stop'):
            with self.subTest(finish=finish):
                c=Client([ModelResponseError('bad','syntax_invalid',dict(raw_text=f['text'],finish_reason=finish)) for _ in range(2)])
                def reject(raw):raise ValueError('Stale scope')
                with self.assertRaises(ValueError):run_stage(c,'JSON',f['payload'],'check_work',reject,self.folder/finish,{})
                self.assertFalse(list((self.folder/finish).rglob('accepted.json')))

    def test_manual_grant_after_32k_length_allows_one_generation(self):
        c=Client([ModelResponseError('length','budget_exhausted'),{'ok':True}])
        with self.assertRaises(ValueError) as failure:run_stage(c,'JSON',{},'probe',lambda x:x,self.folder,{'max_tokens':32768})
        out=run_stage(c,'JSON',{},'probe',lambda x:x,self.folder,{'max_tokens':32768},recovery_grant={failure.exception.recovery['node_id']:'one'})
        self.assertEqual(out,{'ok':True});self.assertEqual(c.calls,2)


if __name__=='__main__':unittest.main()
