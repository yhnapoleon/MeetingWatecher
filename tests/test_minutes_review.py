import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from meeting_eval.context_protocol import example
try:
    from meeting_eval.minutes_review import MinutesReviewer
except ImportError:
    MinutesReviewer=None


def assessment(payload,overrides=None,findings=None):
    raw=example(payload['output_schema'])
    for candidate in payload['candidates']:
        raw['checks'][candidate['claim_id']]=dict(content='supported',speech_scope='current',
            adoption_evidence=[],final_status='open' if candidate['kind']=='unresolved' else 'not_applicable',
            route=candidate['kind'],reason='原文支持此命题与会中状态',evidence=candidate['evidence'],deferred_record_ids=[])
    for identity,values in (overrides or {}).items():raw['checks'][identity].update(values)
    if 'coverage_findings' in raw:raw['coverage_findings']=findings or []
    return raw


class ScriptedClient:
    model='deepseek-flash';endpoint='https://example.invalid'
    def __init__(self,steps):self.steps=list(steps);self.stages=[]
    def call(self,prompt,payload,stage,**kwargs):
        self.stages.append(stage)
        if not self.steps:raise AssertionError('Unexpected extra model call')
        return self.steps.pop(0)(payload)


class MinutesReviewTests(unittest.TestCase):
    def service_combination(self,fail_minutes):
        import json
        from test_context_state import ledger_fixture
        from test_context_v3 import interpretation,check_response
        from meeting_eval.extract import Extractor
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        from meeting_eval.model_client import ModelResponseError
        m,_,_,_=ledger_fixture()
        m['account_map']={'alice':'alice'}
        m['segments'][0]['text']='我会调查录像支持能力。设备是否支持录像尚不确定。决定下周一召开评审会。'
        calls=[]
        def call(_client,prompt,payload,stage,**kwargs):
            calls.append(stage)
            if stage=='facts':return dict(facts=[],unresolved=[dict(statement='设备是否支持录像尚不确定',evidence_ids=['s1'])])
            if stage=='decisions':return dict(decisions=[dict(statement='下周一召开评审会',attribute='评审会时间',supersedes=None,final_status='effective',basis='newly_adopted',choice_ids=['s1'],adoption_ids=['s1'],later_ids=[])])
            if stage=='track_context':
                return dict(case_id='M',entities=[dict(label='设备',evidence_ids=['s1'])],
                    new_threads=[dict(entity_labels=['设备'],updates=[dict(kind='work',description='调查录像支持能力',evidence_ids=['s1'])])],thread_updates=[])
            if stage=='interpret_work':
                raw=interpretation();raw['events'][0].pop('event_id')
                return json.loads(json.dumps(raw,ensure_ascii=False).replace('剪辑视频','调查录像支持能力').replace('"Q1"','"s1"'))
            if stage=='check_work':
                old=check_response(payload['records'],payload['events']);raw=example(payload['output_schema'])
                raw['record_checks']={r['record_id']:{k:v for k,v in r.items() if k!='record_id'} for r in old['record_checks']}
                for r in raw['record_checks'].values():r['qualification']=dict(speech_scope='current',work_basis='action',evidence=['Q1'],adoption_evidence=[],reason='说话人明确承接调查')
                raw['checks']={r['event_id']+'.'+k:v for r in old['checks'] for k,v in r['fields'].items()};raw['coverage_findings']=[]
                return json.loads(json.dumps(raw,ensure_ascii=False).replace('"Q1"','"s1"'))
            if stage=='check_minutes':
                if fail_minutes:raise ModelResponseError('bad JSON','syntax_invalid')
                return assessment(payload)
            raise AssertionError(stage)
        with patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')),patch('meeting_eval.model_client.ModelClient.call',call):
            store=Store(Path(self.tmp.name)/'combined.sqlite')
            try:
                svc=Service(store,Extractor(None,Path(self.tmp.name)/'combined','context-v5'))
                out=svc.process(m,'host','2026-11-16T10:01:00+08:00')
                self.assertEqual(out['status'],'partial' if fail_minutes else 'processed',out['extraction'].get('_errors'))
                self.assertEqual(len(store.tasks()),1)
                self.assertEqual(store.db.execute('SELECT count(*) FROM decisions').fetchone()[0],1)
                self.assertEqual(len(out['extraction']['unresolved']),0 if fail_minutes else 1)
                self.assertEqual({e['field'] for e in out['extraction'].get('_errors',[])},{'facts','unresolved'} if fail_minutes else set())
                self.assertFalse(out['extraction']['_task_trace']['review_records'])
                before=list(calls);again=svc.process(m,'host','2026-11-16T10:02:00+08:00')
                self.assertEqual(again['source_id'],out['source_id']);self.assertEqual(again['status'],out['status'])
                self.assertEqual(calls,before);self.assertEqual(calls.count('check_minutes'),2 if fail_minutes else 1)
                self.assertEqual(len(store.tasks()),1)
                self.assertEqual(store.db.execute('SELECT count(*) FROM decisions').fetchone()[0],1)
            finally:store.close()

    def test_service_research_unknown_and_decision_are_independent(self):self.service_combination(False)

    def test_service_minutes_exhaustion_preserves_task_decision_and_attempt_limit(self):self.service_combination(True)

    def setUp(self):
        self.assertIsNotNone(MinutesReviewer,'Minutes semantic review is missing')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.meeting=dict(case_id='M',segments=[dict(id='s1',text='原话证据',speaker='小林'),dict(id='s2',text='后文答复',speaker='主持人')])

    def review(self,client,facts=None,unresolved=None,context=None):
        return MinutesReviewer(client,Path(self.tmp.name),{}).review(self.meeting,
            dict(facts=facts or [],unresolved=unresolved or []),context or {})

    def test_answered_choice_is_removed_without_removing_answer_fact(self):
        fact=dict(statement='已确定研究说明书',evidence_ids=['s2'])
        issue=dict(statement='研究对象尚未确定',evidence_ids=['s1'])
        c=ScriptedClient([lambda p:assessment(p,{'U1':dict(content='contradicted',final_status='answered',route='omit',evidence=['Q1','Q2'])})])
        out=self.review(c,[fact],[issue])
        self.assertEqual(out['facts'],[fact]);self.assertEqual(out['unresolved'],[]);self.assertEqual(out['errors'],[])

    def test_real_unknown_is_rewritten_and_independently_rechecked(self):
        issue=dict(statement='小林能否支持录像',evidence_ids=['s1'])
        def repair(p):
            raw=example(p['output_schema']);raw['replacements']['U1']=dict(kind='unresolved',statement='是否支持录像尚待了解',evidence=['Q1']);return raw
        c=ScriptedClient([lambda p:assessment(p,{'U1':dict(content='contradicted')}),repair,assessment])
        out=self.review(c,unresolved=[issue])
        self.assertEqual(out['unresolved'][0]['statement'],'是否支持录像尚待了解')
        self.assertEqual(c.stages,['check_minutes','repair_minutes','check_minutes_repair'])

    def test_quoted_question_moves_to_fact_not_current_issue(self):
        def repair(p):
            raw=example(p['output_schema']);raw['replacements']['U1']=dict(kind='fact',statement='培训中举了发群许可问题的例子',evidence=['Q1']);return raw
        c=ScriptedClient([lambda p:assessment(p,{'U1':dict(speech_scope='quoted',final_status='not_applicable',route='fact')}),repair,
            lambda p:assessment(p,{'U1':dict(speech_scope='quoted')})])
        out=self.review(c,unresolved=[dict(statement='发群许可未回答',evidence_ids=['s1'])])
        self.assertEqual(out['unresolved'],[]);self.assertIn('培训',out['facts'][0]['statement'])

    def test_current_unknown_survives_even_with_accepted_research_work(self):
        issue=dict(statement='设备能否支持录像尚待了解',evidence_ids=['s1'])
        c=ScriptedClient([assessment]);out=self.review(c,unresolved=[issue],context={'work_records':[{'kind':'work','description':'小林已经承接调查'}]})
        self.assertEqual(out['unresolved'],[issue])

    def test_missing_deferred_fact_is_added_when_work_branch_failed(self):
        finding=dict(kind='fact',description='保留议题已暂缓到下周的事实',evidence=['Q1'])
        def repair(p):
            raw=example(p['output_schema']);raw['replacements']['N1']=dict(kind='fact',statement='该议题暂缓到下周再议',evidence=['Q1']);return raw
        c=ScriptedClient([lambda p:assessment(p,findings=[finding]),repair,
            lambda p:assessment(p,{'N1':dict(final_status='deferred')})])
        out=self.review(c,context={'work_errors':['track failed']})
        self.assertEqual(out['unresolved'],[]);self.assertIn('下周',out['facts'][0]['statement'])

    def test_repair_disagreement_is_system_failure_not_user_question(self):
        def repair(p):
            raw=example(p['output_schema']);raw['replacements']['U1']=dict(kind='unresolved',statement='仍然无依据的说法',evidence=['Q1']);return raw
        c=ScriptedClient([lambda p:assessment(p,{'U1':dict(content='contradicted')}),repair,
            lambda p:assessment(p,{'U1':dict(content='insufficient',route='unverified')})])
        out=self.review(c,unresolved=[dict(statement='错误未决',evidence_ids=['s1'])])
        self.assertEqual(out['unresolved'],[]);self.assertEqual(out['facts'],[])
        self.assertTrue(out['errors']);self.assertNotIn('question',out)

    def test_unresolved_recheck_objection_cannot_be_hidden_by_omit(self):
        def repair(p):
            raw=example(p['output_schema']);raw['replacements']['U1']=dict(kind='unresolved',statement='某问题仍待解决',evidence=['Q1']);return raw
        def recheck(p):
            raw=assessment(p,{'U1':dict(route='omit')});raw['issue_checks']['U1']['status']='unresolved';return raw
        c=ScriptedClient([lambda p:assessment(p,{'U1':dict(content='insufficient')}),repair,recheck])
        out=self.review(c,unresolved=[dict(statement='某问题仍待解决',evidence_ids=['s1'])])
        self.assertTrue(out['errors'],'An unresolved original objection must remain a system failure')

    def test_service_keeps_deferred_fact_when_work_fails_and_reentry_reuses_minutes(self):
        from meeting_eval.extract import Extractor
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        meeting=dict(meeting_id='deferred',case_id='M',series='demo',started_at='2026-11-16T10:00:00+08:00',
            audience=['host'],writers=['host'],roster={'host':'主持人'},speaker_map={'主持人':'host'},
            account_map={'host':'host'},segments=[dict(id='s1',speaker='主持人',text='这个方案先放着，下周再议。')])
        finding=dict(kind='fact',description='方案已暂缓到下周',evidence=['Q1'])
        def repair(p):
            raw=example(p['output_schema']);raw['replacements']['N1']=dict(kind='fact',statement='方案暂缓到下周再议',evidence=['Q1']);return raw
        reviewer=ScriptedClient([lambda p:assessment(p,findings=[finding]),repair,lambda p:assessment(p,{'N1':dict(final_status='deferred')})])
        calls=[]
        def call(_client,prompt,payload,stage,**kwargs):
            calls.append(stage)
            if stage=='facts':return dict(facts=[],unresolved=[])
            if stage=='decisions':return dict(decisions=[])
            return reviewer.call(prompt,payload,stage,**kwargs)
        failed=dict(errors=[dict(stage='track_context',error='test_failure')],trace={},checked_events=[],checked_records=[])
        with patch('meeting_eval.model_client.credentials',return_value=('secret','deepseek-flash','https://example.invalid')),patch('meeting_eval.model_client.ModelClient.call',call),patch('meeting_eval.context_v5.ContextV5Pipeline.run',return_value=failed):
            store=Store(Path(self.tmp.name)/'state.sqlite')
            try:
                svc=Service(store,Extractor(None,Path(self.tmp.name)/'model','context-v5'))
                out=svc.process(meeting,'host','2026-11-16T10:01:00+08:00')
                self.assertEqual(out['status'],'partial')
                self.assertTrue(out['extraction']['facts'],'Deferred fact must survive work branch failure')
                self.assertEqual(out['extraction']['facts'][0]['statement'],'方案暂缓到下周再议')
                self.assertEqual(out['extraction']['unresolved'],[])
                self.assertIn('方案暂缓到下周再议',svc.minutes(out['source_id'],'host'))
                before=len(calls);again=svc.process(meeting,'host','2026-11-16T10:01:00+08:00')
                self.assertEqual(again['extraction']['facts'],out['extraction']['facts'])
                self.assertEqual(len(calls),before)
                self.assertEqual(store.tasks(),[])
            finally:store.close()


if __name__=='__main__':unittest.main()
