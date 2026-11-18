import copy
import json
from pathlib import Path
import tempfile
import unittest

from meeting_eval.context_v5 import ContextV5Pipeline
from meeting_eval.model_client import ModelResponseError
from meeting_eval.stage_runner import recovery_scope


def meeting(n=4, text='请跟进项目。'):
    return dict(case_id='M', source_key='test:M', segments=[dict(id=f'qm.Bed.600{i}', text=text,
        speaker='Alice', person_ref='alice') for i in range(n)])


def output(payload, kind='work'):
    sid=payload['new_segment_ids'][-1]
    update=dict(kind=kind, description='整理项目资料', evidence_ids=[sid])
    return dict(case_id='M', entities=[], thread_updates=[],
        new_threads=[dict(entity_labels=['资料'], updates=[update])])


class Client:
    model='deepseek-flash'
    endpoint='https://example.invalid'
    def __init__(self, fail=None):self.calls=[];self.fail=fail
    def call(self,prompt,payload,stage,**kwargs):
        self.calls.append((copy.deepcopy(payload),stage))
        if self.fail:self.fail(payload)
        return output(payload)


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.client=Client()
        self.pipe=ContextV5Pipeline(self.client,self.folder,{})

    def stage(self,payload):
        try:return self.pipe._stage('track_context',payload,lambda x:x,self.folder,False)
        except ModelResponseError as e:self.fail('Valid source-ID tracking must be accepted: '+str(e))

    def payload(self,m=None,previous=None):
        m=m or meeting();return dict(meeting=m,previous=previous,new_segment_ids=[s['id'] for s in m['segments']])

    def test_program_allocates_identity_and_uses_original_evidence_ids(self):
        m=meeting();ledger=self.stage(self.payload(m))
        self.assertEqual(ledger['threads'][0]['thread_id'],'T1')
        self.assertEqual(ledger['entities'][0]['entity_id'],'N1')
        self.assertEqual(ledger['threads'][0]['updates'][0]['after_segment'],m['segments'][-1]['id'])
        self.assertEqual(ledger['threads'][0]['updates'][0]['evidence'][0]['quote'],'请跟进项目。')
        sent=self.client.calls[0][0]
        self.assertEqual(set(sent['evidence_catalog']),{s['id'] for s in m['segments']})
        self.assertNotIn('after_segment',sent['output_schema']['properties']['new_threads']['items']['properties']['updates']['items']['properties'])

    def module(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('meeting_eval.context_tracking_reliable'),
            'source-grounded tracking protocol is missing')
        from meeting_eval import context_tracking_reliable
        return context_tracking_reliable

    def test_update_cancellation_preserves_history_and_program_orders_evidence(self):
        mod=self.module();m=meeting();p=self.payload(dict(m,segments=m['segments'][:2]))
        old=mod.expand_tracking(output(p),p);before=copy.deepcopy(old)
        p=dict(meeting=m,previous=old,new_segment_ids=[s['id'] for s in m['segments'][2:]])
        raw=dict(case_id='M',entities=[],new_threads=[],thread_updates=[dict(thread_id='T1',entity_labels=[],
            updates=[dict(kind='withdrawn',description='后文取消资料整理',evidence_ids=[m['segments'][3]['id'],m['segments'][1]['id']])])])
        new=mod.expand_tracking(raw,p)
        self.assertEqual(old,before)
        self.assertEqual(new['threads'][0]['updates'][:-1],old['threads'][0]['updates'])
        self.assertEqual(new['threads'][0]['updates'][-1]['kind'],'withdrawn')
        self.assertEqual(new['threads'][0]['updates'][-1]['after_segment'],m['segments'][3]['id'])

    def test_invalid_alias_unknown_thread_empty_updates_and_old_only_update_rejected(self):
        mod=self.module();m=meeting();p=self.payload(m)
        variants=[]
        raw=output(p);raw['new_threads'][0]['updates'][0]['evidence_ids']=['Q6003'];variants.append(raw)
        raw=output(p);raw['new_threads'][0]['updates']=[];variants.append(raw)
        raw=output(p);raw['new_threads'][0]['thread_id']='T99';variants.append(raw)
        raw=output(p);raw['thread_updates']=[dict(thread_id='T99',entity_labels=[],updates=raw['new_threads'][0]['updates'])];variants.append(raw)
        for raw in variants:
            with self.subTest(raw=raw),self.assertRaises(ValueError):mod.expand_tracking(raw,p)
        prior=self.payload(dict(m,segments=m['segments'][:2]));old=mod.expand_tracking(output(prior),prior)
        p=dict(meeting=m,previous=old,new_segment_ids=[s['id'] for s in m['segments'][2:]])
        raw=output(p);raw['new_threads'][0]['updates'][0]['evidence_ids']=[m['segments'][0]['id']]
        with self.assertRaises(ValueError):mod.expand_tracking(raw,p)

    def runtime(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('meeting_eval.context_checkpoints'),'durable tracker is missing')
        from meeting_eval import context_checkpoints
        return context_checkpoints

    def track(self,m):
        self.assertTrue(callable(getattr(self.pipe,'_track_ledger',None)),'tracking hook missing')
        trace={'checkpoints':[]}
        ledger=self.pipe._track_ledger(m,self.folder,trace,False)
        return ledger,trace

    def test_dense_turns_and_oversize_single_turn_have_exact_coverage(self):
        mod=self.runtime();m=meeting(100,'Yes.')
        self.assertEqual(mod.plan_ranges(m['segments']),[(0,100)])
        segs=meeting(3)['segments'];segs[1]['text']='很长'*4000
        ranges=mod.plan_ranges(segs)
        self.assertEqual(ranges,[(0,1),(1,2),(2,3)])
        self.assertEqual([i for a,b in ranges for i in range(a,b)],[0,1,2])
        self.assertEqual(mod.plan_ranges([]),[])

    def test_content_exhaustion_splits_then_reuses_success_after_restart(self):
        def fail(p):
            if len(p['new_segment_ids'])==4:raise ModelResponseError('bad JSON','syntax_invalid')
        self.client.fail=fail
        ledger,trace=self.track(meeting())
        self.assertEqual(len(self.client.calls),4) # two root attempts, two successful children
        self.assertEqual(trace['tracking']['completed_segments'],4)
        self.assertEqual(trace['tracking']['status'],'complete')
        self.assertEqual(len(trace['tracking']['splits']),1)
        self.assertEqual(len(ledger['threads']),2)
        self.pipe=ContextV5Pipeline(self.client,self.folder,{})
        again,_=self.track(meeting())
        self.assertEqual(again,ledger);self.assertEqual(len(self.client.calls),4)

    def test_leaf_failure_keeps_prefix_and_explicit_grant_only_retries_leaf(self):
        m=meeting()
        def fail(p):
            if len(p['new_segment_ids'])==4 or p['new_segment_ids'][0]==m['segments'][2]['id']:
                raise ModelResponseError('bad JSON','syntax_invalid')
        self.client.fail=fail
        self.assertTrue(callable(getattr(self.pipe,'_track_ledger',None)),'tracking hook missing')
        trace={'checkpoints':[]}
        with self.assertRaises(ModelResponseError) as failure:self.pipe._track_ledger(m,self.folder,trace,False)
        self.assertEqual(len(self.client.calls),5)
        saved=json.loads((self.folder/'tracking-state.json').read_text(encoding='utf8'))
        self.assertEqual(saved['completed_segments'],2)
        self.assertEqual(saved['pending_segment_ids'],[s['id'] for s in m['segments'][2:]])
        self.assertEqual(len(saved['last_ledger']['threads']),1)
        self.assertEqual(saved['status'],'recovery_required')
        self.client.fail=None
        with recovery_scope({failure.exception.recovery['node_id']:'explicit-user-retry'}):
            ledger,trace=self.track(m)
        self.assertEqual(len(self.client.calls),6)
        self.assertEqual(len(ledger['threads']),2)
        self.assertEqual(trace['tracking']['status'],'complete')

    def test_terminal_and_transport_errors_never_split_or_skip(self):
        for kind in ['terminal_error','transport_failed']:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                from unittest.mock import patch
                self.pipe=ContextV5Pipeline(Client(),Path(folder),{})
                err=ModelResponseError('provider failed',kind)
                err.recovery=dict(status='recovery_required',reason=kind,node_id='blocked')
                self.assertTrue(callable(getattr(self.pipe,'_track_ledger',None)),'tracking hook missing')
                trace={'checkpoints':[]}
                with patch.object(self.pipe,'_stage',side_effect=err) as stage,self.assertRaises(ModelResponseError):
                    self.pipe._track_ledger(meeting(),Path(folder),trace,False)
                self.assertEqual(stage.call_count,1)
                self.assertEqual(trace['tracking']['completed_segments'],0)
                self.assertEqual(trace['tracking']['splits'],[])

    def test_pipeline_never_interprets_incomplete_tracking(self):
        self.client.fail=lambda p: (_ for _ in ()).throw(ModelResponseError('bad JSON','syntax_invalid'))
        result=self.pipe.run(meeting(),[])
        self.assertTrue(result['errors'])
        self.assertEqual({stage for _,stage in self.client.calls},{'track_context'})
        self.assertEqual(result['events'],[])
        self.assertEqual(result['trace'].get('tracking',{}).get('status'),'recovery_required')


if __name__=='__main__':unittest.main()
