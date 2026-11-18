import copy
import tempfile
import unittest
from pathlib import Path

from test_context_v4 import V4Client,patch_for
from test_context_v3 import check_response,interpretation
from test_context_state import ledger_fixture
from meeting_eval.context_content_qa import ContextQAPipeline,validate_answers
from meeting_eval.context_v3 import reduce_v3


class QAClient(V4Client):
    def call(self,prompt,p,stage,**kwargs):
        self.calls.append((stage,copy.deepcopy(p)))
        if stage=='source_requirements':
            return dict(case_id='M',requirements=[dict(work='工作',question='要解决什么问题？',expected_answer='必要目的',basis='explicit',evidence=['Q1'])])
        if stage.startswith('answer_requirements'):
            description=p['records'][0]['description'];ok=description=='必要目的'
            return dict(case_id='M',answers=[dict(question_id='K1',record_id='R1',answer='必要目的' if ok else None,quote='必要目的' if ok else None)])
        if stage in ('check_work','check_repair'):
            raw=check_response(p['records'],p['events']);raw.pop('coverage_findings')
            if stage=='check_work':raw.update(new_work_findings=[],uncertain_findings=[])
            else:raw['disposition_checks']=[]
            raw['requirement_checks']=[dict(question_id='K1',target_ref='record:R1',status='covered' if stage=='check_repair' else 'missing',reason='核对最终描述',evidence=['Q1'])]
            return raw
        if stage=='repair_work':
            raw=patch_for(p);raw['scope']=p['repair_scope'];raw['targets']['target_1']['record']['description']='必要目的'
            return raw
        return super().call(prompt,p,stage,**kwargs)


class ContentQATests(unittest.TestCase):
    def test_whole_omission_can_bind_finding_and_reach_addition(self):
        class Client(QAClient):
            def call(self,prompt,p,stage,**kwargs):
                if stage=='source_requirements':
                    return dict(case_id='M',requirements=[dict(work='第二项工作',question='第二项要解决什么？',expected_answer='必要目的',basis='explicit',evidence=['Q1'])])
                if stage.startswith('answer_requirements'):
                    rid='R_O1_1' if any(r['record_id']=='R_O1_1' for r in p['records']) else None
                    return dict(case_id='M',answers=[dict(question_id='K1',record_id=rid,answer='必要目的' if rid else None,quote='必要目的' if rid else None)])
                if stage in ('check_work','check_repair'):
                    raw=check_response(p['records'],p['events']);raw.pop('coverage_findings')
                    if stage=='check_work':
                        raw.update(new_work_findings=[dict(description='第二项工作，必要目的',evidence=['Q1'])],uncertain_findings=[])
                        raw['requirement_checks']=[dict(question_id='K1',target_ref='finding:1',status='missing',reason='整项缺失',evidence=['Q1'])]
                    else:
                        raw['disposition_checks']=[dict(**d,verdict='supported',reason='补回了第二项') for d in p['dispositions']]
                        raw['requirement_checks']=[dict(question_id='K1',target_ref='record:R_O1_1',status='covered',reason='已补回',evidence=['Q1'])]
                    return raw
                if stage=='repair_work':
                    from test_context_v4 import payload
                    bundle=patch_for(payload())['targets']['target_1'];bundle['record']['description']='必要目的';bundle['event']['candidate_ids']=[]
                    return dict(case_id='M',scope=p['repair_scope'],targets={},additions={'O1':[bundle]},
                        dispositions=[dict(finding_id='O1',disposition='added',record_ids=['R_O1_1'],evidence=['Q1'])])
                return super().call(prompt,p,stage,**kwargs)
        m,*_=ledger_fixture()
        with tempfile.TemporaryDirectory() as tmp:out=ContextQAPipeline(Client(),Path(tmp),{}).run(m,{'tasks':[]})
        self.assertEqual(out['errors'],[])
        self.assertEqual(out['trace']['repair']['status'],'checked')
        self.assertEqual(out['coverage_findings'],[])
        self.assertEqual(len(reduce_v3(out,m,{'tasks':[]})['items']),2)

    def test_readonly_questions_are_not_reopened_during_local_repair(self):
        class Client(QAClient):
            def call(self,prompt,p,stage,**kwargs):
                if stage=='track_context':
                    raw=super().call(prompt,p,stage,**kwargs);thread=copy.deepcopy(raw['threads'][0]);thread['thread_id']='T2';raw['threads'].append(thread);return raw
                if stage=='interpret_work':
                    raw=interpretation();r=copy.deepcopy(raw['records'][0]);r.update(record_id='R2',thread_ids=['T2'],description='另一任务目的')
                    e=copy.deepcopy(raw['events'][0]);e['record_id']='R2';raw['records'].append(r);raw['events'].append(e);return raw
                if stage=='source_requirements':
                    raw=super().call(prompt,p,stage,**kwargs);q=copy.deepcopy(raw['requirements'][0]);q.update(work='另一任务',question='另一任务的目的？',expected_answer='另一任务目的');raw['requirements'].append(q);return raw
                if stage.startswith('answer_requirements'):
                    self.calls.append((stage,copy.deepcopy(p)));rows=[]
                    for q in p['questions']:
                        rid='R1' if q['question_id']=='K1' else 'R2';desc=next(r['description'] for r in p['records'] if r['record_id']==rid)
                        ok=desc in ('必要目的','另一任务目的');rows.append(dict(question_id=q['question_id'],record_id=rid,answer=desc if ok else None,quote=desc if ok else None))
                    return dict(case_id='M',answers=rows)
                if stage in ('check_work','check_repair'):
                    raw=super().call(prompt,p,stage,**kwargs)
                    if any(q['question_id']=='K2' for q in p['source_requirements']):
                        raw['requirement_checks'].append(dict(question_id='K2',target_ref='record:R2',status='covered' if stage=='check_work' else 'missing',reason='第二项',evidence=['Q1']))
                    return raw
                return super().call(prompt,p,stage,**kwargs)
        m,*_=ledger_fixture();client=Client()
        with tempfile.TemporaryDirectory() as tmp:out=ContextQAPipeline(client,Path(tmp),{}).run(m,{'tasks':[]})
        self.assertEqual(out['errors'],[])
        self.assertEqual(out['trace']['repair']['status'],'checked')
        asked=next(p['questions'] for s,p in client.calls if s=='answer_requirements_check_repair')
        self.assertEqual([q['question_id'] for q in asked],['K1'])

    def test_background_cannot_supply_task_coverage_answer(self):
        class Client(QAClient):
            def call(self,prompt,p,stage,**kwargs):
                if stage=='interpret_work':
                    raw=interpretation();r=copy.deepcopy(raw['records'][0]);r.update(record_id='R2',thread_ids=[],kind='context_only',description='必要目的');raw['records'].append(r);return raw
                if stage.startswith('answer_requirements'):
                    self.calls.append((stage,copy.deepcopy(p)))
                    return dict(case_id='M',answers=[dict(question_id='K1',record_id='R2',answer='必要目的',quote='必要目的')])
                return super().call(prompt,p,stage,**kwargs)
        m,*_=ledger_fixture();client=Client()
        with tempfile.TemporaryDirectory() as tmp:out=ContextQAPipeline(client,Path(tmp),{}).run(m,{'tasks':[]})
        answer=next(p for s,p in client.calls if s.startswith('answer_requirements'))
        self.assertNotIn('R2',[r['record_id'] for r in answer['records']])
        self.assertTrue(out['errors'])

    def test_qa_routes_missing_content_to_repair_without_source_leakage(self):
        m,*_=ledger_fixture();client=QAClient()
        with tempfile.TemporaryDirectory() as tmp:
            pipe=ContextQAPipeline(client,Path(tmp),{});out=pipe.run(m,{'tasks':[]})
            before=len(client.calls);pipe.run(m,{'tasks':[]},resume=True)
            self.assertEqual(len(client.calls),before)
        self.assertEqual(out['errors'],[])
        self.assertEqual(out['trace']['repair']['status'],'checked')
        self.assertEqual(reduce_v3(out,m,{'tasks':[]})['items'][0]['description'],'必要目的')
        inputs=[p for s,p in client.calls if s.startswith('answer_requirements')]
        self.assertEqual(len(inputs),2)
        for p in inputs:
            self.assertEqual(set(p),{'case_id','questions','records'})
            self.assertEqual(set(p['questions'][0]),{'question_id','question'})
            self.assertEqual(set(p['records'][0]),{'record_id','description'})
        source=next(p for s,p in client.calls if s=='source_requirements')
        self.assertNotIn('records',source)

    def test_answer_requires_literal_support_and_complete_questions(self):
        questions=[dict(question_id='K1')];records=[dict(record_id='R1',description='联系对方')]
        raw=dict(case_id='M',answers=[dict(question_id='K1',record_id='R1',answer='核对',quote='核对未听清的问题')])
        with self.assertRaises(ValueError):validate_answers(raw,questions,records)
        raw['answers']=[]
        with self.assertRaises(ValueError):validate_answers(raw,questions,records)
