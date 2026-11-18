import copy
import importlib
from pathlib import Path
import tempfile
import unittest
from meeting_eval.context_protocol import example
from meeting_eval.context_protocol_v3 import INTERPRET
from meeting_eval.model_client import ModelResponseError
from meeting_eval.stage_runner import run_stage


def source():return dict(case_id='M',segments=[dict(id='qm.X.587',text='我会整理资料。')])
def draft(bad=True):
    raw=example(INTERPRET);raw['case_id']='M'
    raw['records'][0]['evidence']=['Q587' if bad else 'qm.X.587']
    raw['events'][0]['work']['evidence']=['qm.X.587']
    return raw


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)
    def policy(self):return importlib.import_module('meeting_eval.reference_repair').ReferenceRepair()

    def test_patch_preserves_every_other_field_and_rejects_scope_extra_or_unknown(self):
        policy=self.policy();raw=draft();req=policy.prepare(raw,dict(meeting=source()))
        patch=dict(case_id='M',scope=req['reference_repair']['scope'],patches={'fix_1':['qm.X.587']})
        fixed=policy.merge(patch,req);self.assertEqual(fixed,draft(False));self.assertEqual(raw,draft())
        for alter in [dict(scope='stale'),dict(patches={'fix_1':['Q587']}),dict(patches={'fix_1':['qm.X.587'],'fix_2':[]}),dict(records=[])]:
            with self.subTest(alter=alter),self.assertRaises(ValueError):policy.merge({**patch,**alter},req)

    def test_partial_schema_and_duplicate_record_identity_cannot_patch(self):
        policy=self.policy();p=dict(meeting=source())
        self.assertIsNone(policy.prepare(dict(case_id='M',records=[]),p))
        raw=draft();raw['records'].append(copy.deepcopy(raw['records'][0]))
        self.assertIsNone(policy.prepare(raw,p))
        self.assertIsNone(policy.prepare(draft(False),p))

    def test_empty_patch_for_optional_state_evidence_must_remain_failed(self):
        policy=self.policy();raw=draft(False);raw['events'][0]['state']['evidence']=['missing']
        req=policy.prepare(raw,dict(meeting=source()))
        patch=dict(case_id='M',scope=req['reference_repair']['scope'],patches={'fix_1':[]})
        with self.assertRaises(ValueError):policy.merge(patch,req)

    def invoke(self,client):
        from meeting_eval.context_wire import decode_output
        return run_stage(client,'interpret',dict(meeting=source()),'interpret_work',
            lambda r:decode_output(r,source()),self.path,dict(thinking='enabled',reasoning_effort='high',max_tokens=16384),
            reference_repair=self.policy())

    def test_length_then_bad_reference_gets_one_small_patch_and_restarts_cached(self):
        class Client:
            model='deepseek-flash';endpoint='https://example.invalid'
            def __init__(self):self.calls=[]
            def call(self,prompt,payload,stage,**kwargs):
                self.calls.append((payload,kwargs))
                if len(self.calls)==1:raise ModelResponseError('length','budget_exhausted')
                if len(self.calls)==2:return draft()
                return dict(case_id='M',scope=payload['reference_repair']['scope'],patches={'fix_1':['qm.X.587']})
        client=Client();result=self.invoke(client)
        self.assertEqual(result['records'][0]['evidence'],['Q1'])
        self.assertEqual([k['inference']['max_tokens'] for p,k in client.calls],[16384,32768,8192])
        self.assertEqual(self.invoke(client),result);self.assertEqual(len(client.calls),3)

    def test_invalid_patch_is_not_retried_on_reentry(self):
        class Client:
            model='deepseek-flash';endpoint='https://example.invalid'
            def __init__(self):self.calls=0
            def call(self,prompt,payload,stage,**kwargs):
                self.calls+=1
                if self.calls==1:return draft()
                return dict(case_id='M',scope=payload['reference_repair']['scope'],patches={'fix_1':['missing']})
        client=Client()
        for _ in range(2):
            with self.assertRaises(ModelResponseError):self.invoke(client)
        self.assertEqual(client.calls,2)

    def test_terminal_error_never_opens_patch_budget(self):
        class Client:
            model='deepseek-flash';endpoint='https://example.invalid'
            calls=0
            def call(self,*a,**k):self.calls+=1;raise ModelResponseError('402','terminal_error')
        c=Client()
        for _ in range(2):
            with self.assertRaises(ModelResponseError):self.invoke(c)
        self.assertEqual(c.calls,1)

    def test_patch_transport_retry_keeps_same_request_and_budget(self):
        class Client:
            model='deepseek-flash';endpoint='https://example.invalid'
            def __init__(self):self.requests=[]
            def call(self,prompt,payload,stage,**kwargs):
                self.requests.append((prompt,copy.deepcopy(payload),kwargs['inference']))
                if len(self.requests)==1:return draft()
                if len(self.requests)==2:
                    err=ModelResponseError('429','transport_failed');err.retry_at=0;raise err
                return dict(case_id='M',scope=payload['reference_repair']['scope'],patches={'fix_1':['qm.X.587']})
        c=Client();self.invoke(c)
        self.assertEqual(len(c.requests),3);self.assertEqual(c.requests[1],c.requests[2])

    def test_cached_merged_candidate_restores_acceptance_without_model(self):
        class Client:
            model='deepseek-flash';endpoint='https://example.invalid'
            calls=0
            def call(self,prompt,payload,stage,**kwargs):
                self.calls+=1
                if self.calls==1:return draft()
                return dict(case_id='M',scope=payload['reference_repair']['scope'],patches={'fix_1':['qm.X.587']})
        c=Client();before=self.invoke(c)
        next(self.path.rglob('accepted.json')).unlink()
        self.assertEqual(self.invoke(c),before);self.assertEqual(c.calls,2)


if __name__=='__main__':unittest.main()
