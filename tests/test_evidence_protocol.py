import copy
import json
from pathlib import Path
import tempfile
import unittest

from meeting_eval.context_protocol import example
from meeting_eval.context_protocol_v3 import INTERPRET
from meeting_eval.context_v5 import ContextV5Pipeline
from meeting_eval.context_wire import decode_output,wire_prompt
from meeting_eval.model_client import ModelResponseError
from meeting_eval.reference_repair import ReferenceRepair
from meeting_eval.stage_runner import run_stage


def meeting():
    return dict(case_id='M',segments=[dict(id='source.19',text='我会整理资料。')])


def draft(objects=False):
    value=example(INTERPRET);value['case_id']='M'
    value['records'][0]['evidence']=['source.19']
    value['events'][0]['work']['evidence']=['source.19']
    if objects:value['records'][0]['evidence']=[dict(segment_id='source.19',start=0,end=999)]
    return value


class Client:
    model='deepseek-flash'
    endpoint='https://api.deepseek.com/chat/completions'
    def __init__(self,fn):self.fn=fn;self.calls=[]
    def call(self,prompt,payload,stage,**kwargs):
        self.calls.append((prompt,copy.deepcopy(payload),copy.deepcopy(kwargs)))
        return self.fn(payload,len(self.calls))


class EvidenceProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.out=Path(self.tmp.name)

    def test_interpret_request_has_closed_schema_and_nonempty_source_example(self):
        client=Client(lambda p,n:draft());pipe=ContextV5Pipeline(client,self.out,{})
        value=pipe._stage('interpret_work',dict(meeting=meeting(),ledger={},candidates=[],history={'tasks':[]}),
            lambda raw:raw,self.out,False)
        self.assertEqual(value['records'][0]['evidence'],['Q1'])
        prompt,payload,_=client.calls[0]
        self.assertIn('output_schema',payload)
        schema=payload['output_schema'];self.assertFalse(schema['additionalProperties'])
        record=schema['properties']['records']['items'];event=schema['properties']['events']['items']
        for ref in [record['properties']['evidence']]+[event['properties'][f]['properties']['evidence'] for f in ('work','owner','commitment','time','state','relation')]:
            self.assertEqual(ref['items']['type'],'string')
        self.assertIn('"evidence": ["source.19"]',prompt)
        self.assertIn('输入',prompt);self.assertIn('输出',prompt)

    def test_interpret_rejects_extra_fields_before_adapter(self):
        raw=draft();raw['events'][0]['surprise']='ignored by old validator'
        pipe=ContextV5Pipeline(Client(lambda p,n:raw),self.out,{})
        with self.assertRaises(ModelResponseError):
            pipe._stage('interpret_work',dict(meeting=meeting(),ledger={},candidates=[],history={'tasks':[]}),lambda r:r,self.out,False)

    def test_reference_error_reports_type_without_dumping_values(self):
        raw=draft(True)
        with self.assertRaises(ValueError) as failure:decode_output(raw,meeting())
        err=failure.exception
        self.assertEqual(type(err).__name__,'ReferenceValidationError')
        self.assertEqual(err.issues[0]['code'],'reference_type')
        self.assertEqual(err.issues[0]['actual_type'],'array[object]')
        self.assertEqual(err.issues[0]['expected'],'array[string: original segment_id]')
        self.assertNotIn('999',str(err))

    def test_complete_object_draft_patches_only_references(self):
        raw=draft(True);before=copy.deepcopy(raw);policy=ReferenceRepair()
        request=policy.prepare(raw,dict(meeting=meeting()))
        self.assertIsNotNone(request)
        patched=policy.merge(dict(case_id='M',scope=request['reference_repair']['scope'],patches={'fix_1':['source.19']}),request)
        self.assertEqual(patched,draft());self.assertEqual(raw,before)
        for bad in ([],['missing']):
            with self.assertRaises(ValueError):
                policy.merge(dict(case_id='M',scope=request['reference_repair']['scope'],patches={'fix_1':bad}),request)

    def test_incomplete_or_extra_structure_is_not_reference_repair(self):
        variants=[]
        for field in ('case_id','records','events'):
            value=draft(True);del value[field];variants.append(value)
        for field in ('owner','work'):
            value=draft(True);del value['events'][0][field];variants.append(value)
        value=draft(True);del value['records'][0]['evidence'];variants.append(value)
        value=draft(True);value['records'].append(copy.deepcopy(value['records'][0]));variants.append(value)
        value=draft(True);value['events'][0]['record_id']='missing';variants.append(value)
        value=draft(True);value['records'][0]['rogue_evidence']={};variants.append(value)
        for value in variants:
            with self.subTest(value=value):self.assertIsNone(ReferenceRepair().prepare(value,dict(meeting=meeting())))

    def test_official_reference_patch_is_strict_bounded_and_cached(self):
        def response(payload,n):
            if n==1:return draft(True)
            self.assertIn('reference_repair',payload)
            return dict(case_id='M',scope=payload['reference_repair']['scope'],patches={'fix_1':['source.19']})
        client=Client(response)
        def run():return run_stage(client,'JSON',dict(meeting=meeting()),'interpret_work',lambda r:decode_output(r,meeting()),self.out,
            dict(thinking='enabled',reasoning_effort='low',max_tokens=32768),reference_repair=ReferenceRepair())
        result=run();self.assertEqual(result['records'][0]['evidence'],['Q1'])
        self.assertEqual(len(client.calls),2)
        kwargs=client.calls[1][2];self.assertIn('strict_schema',kwargs)
        self.assertEqual(kwargs['inference'],dict(thinking='disabled',temperature=0,max_tokens=8192))
        self.assertEqual(run(),result);self.assertEqual(len(client.calls),2)

    def test_feedback_keeps_all_issues_on_disk_but_caps_model_examples(self):
        raw=draft(True)
        raw['records']=[{**copy.deepcopy(raw['records'][0]),'record_id':f'R{i}'} for i in range(12)]
        client=Client(lambda p,n:raw if n==1 else draft())
        run_stage(client,'JSON',dict(meeting=meeting()),'interpret_work',lambda r:decode_output(r,meeting()),self.out,dict(thinking='disabled',max_tokens=6000))
        feedback=client.calls[1][1]['validation_feedback']
        self.assertIn('total_issues',feedback)
        self.assertEqual(feedback['total_issues'],12)
        self.assertLessEqual(len(feedback['issues']),8)
        self.assertNotIn('invalid',feedback['issues'][0])
        issues=json.loads(next(self.out.rglob('reference-issues.json')).read_text())
        self.assertEqual(len(issues),12)


if __name__=='__main__':unittest.main()
