import copy
import unittest

from meeting_eval.inputs import normalize


def sample():
    meeting=normalize(dict(meeting_id='M',case_id='M',series='S',participants=[dict(speaker='A',person_ref='alice',speaker_name='Alice')],
        segments=[dict(id='s1',speaker='A',text='我会剪辑视频。我们可以细化方案。')]),'host')
    span=dict(segment_id='s1',start=0,end=6,quote='我会剪辑视频')
    event=dict(event_id='E1',candidate_ids=['C1'],work=dict(description='剪辑视频',evidence=[span]),
        owner=dict(kind='person',ref='alice',label='Alice',evidence=[span]),
        commitment=dict(kind='self_committed',evidence=[span]),
        time=dict(kind='unspecified',text=None,date=None,evidence=[]),
        state=dict(kind='future_work',evidence=[span]),
        relation=dict(kind='new',target_guid=None,evidence=[]))
    event['checks']={k:dict(verdict='supported',reason='原话支持',evidence=[span] if k!='relation' else [])
                     for k in ('work','owner','commitment','time','state','relation')}
    return meeting,event


class SpanTests(unittest.TestCase):
    def test_aligns_exact_quote_and_rejects_wrong_or_ambiguous_location(self):
        from meeting_eval.task_events import align_spans,validate_spans
        meeting,_=sample()
        spans=align_spans([dict(segment_id='s1',quote='剪辑视频')],meeting)
        self.assertEqual(spans,[dict(segment_id='s1',quote='剪辑视频',start=2,end=6)])
        bad=copy.deepcopy(spans);bad[0]['start']=1
        with self.assertRaises(ValueError): validate_spans(bad,meeting)
        meeting['segments'][0]['text']='好。好。'
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            align_spans([dict(segment_id='s1',quote='好')],meeting)
        self.assertEqual(align_spans([dict(segment_id='s1',quote='好',occurrence=2)],meeting)[0]['start'],2)

    def test_unknown_owner_or_task_target_is_invalid(self):
        from meeting_eval.task_events import validate_events
        meeting,event=sample();event.pop('checks')
        candidates=[dict(candidate_id='C1',spans=event['work']['evidence'])]
        event['owner']['ref']='stranger'
        with self.assertRaises(ValueError): validate_events([event],candidates,meeting,{'tasks':[]})
        event['owner']['ref']='alice';event['relation'].update(kind='existing',target_guid='hidden-task')
        with self.assertRaises(ValueError): validate_events([event],candidates,meeting,{'tasks':[]})


class ReducerTests(unittest.TestCase):
    def test_commitment_policy_distinguishes_assignment_suggestion_and_group(self):
        from meeting_eval.task_events import reduce_task_events
        for kind,expected in [('self_committed','create'),('accepted','create'),('assigned','candidate'),
                              ('suggested',None),('conditional',None),('unknown',None),('declined',None)]:
            with self.subTest(kind=kind):
                meeting,event=sample();event['commitment']['kind']=kind
                result=reduce_task_events([event],[],meeting,{'tasks':[]})
                self.assertEqual([i['operation'] for i in result['items']],[expected] if expected else [])
                if not expected:self.assertTrue(result['pending'])
        meeting,event=sample();event['owner'].update(kind='group',ref=None,label='我们')
        result=reduce_task_events([event],[],meeting,{'tasks':[]})
        self.assertEqual(result['items'][0]['operation'],'candidate')
        self.assertIsNone(result['items'][0]['owner_ref'])

    def test_bad_content_and_uncertain_relation_cannot_create(self):
        from meeting_eval.task_events import reduce_task_events
        for field in ('work','commitment','relation','state'):
            meeting,event=sample();event['checks'][field]['verdict']='insufficient'
            result=reduce_task_events([event],[],meeting,{'tasks':[]})
            self.assertEqual(result['items'],[])
            self.assertTrue(result['pending'])
        meeting,event=sample();event['relation']['kind']='ambiguous'
        self.assertEqual(reduce_task_events([event],[],meeting,{'tasks':[]})['items'],[])

    def test_pending_names_supported_work_without_asserting_acceptance(self):
        from meeting_eval.task_events import reduce_task_events
        meeting,event=sample();event['checks']['commitment']['verdict']='insufficient'
        result=reduce_task_events([event],[],meeting,{'tasks':[]})
        self.assertEqual(result['items'],[])
        self.assertEqual(result['pending'][0]['work_description'],'剪辑视频')
        event['checks']['work']['verdict']='insufficient'
        result=reduce_task_events([event],[],meeting,{'tasks':[]})
        self.assertNotIn('work_description',result['pending'][0])

    def test_rejected_deadline_in_description_cannot_be_written(self):
        from meeting_eval.task_events import reduce_task_events
        from meeting_eval.service import Service
        from meeting_eval.store import Store
        from pathlib import Path
        import tempfile
        meeting,event=sample();meeting.update(account_map={'alice':'alice'},audience=['host','alice'],writers=['host'])
        event['work']['description']='Finish editing the video by Friday'
        event['time'].update(kind='deadline',text='Friday',date='2026-11-20',evidence=event['work']['evidence'])
        event['checks']['time'].update(verdict='contradicted',reason='原话没有周五期限')
        proposed=reduce_task_events([event],[],meeting,{'tasks':[]})
        self.assertEqual(proposed['items'],[])
        self.assertNotIn('work_description',proposed['pending'][0])
        class Fixed:
            def extract(self,m,c):
                return dict(items=proposed['items'],updates=[],facts=[],unresolved=[],decisions=[],_task_trace={'pending':proposed['pending']})
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'state.sqlite')
            try:
                result=Service(store,Fixed()).process(meeting,'host','2026-11-14T00:00:00+08:00')
                self.assertEqual(store.tasks(),[])
                self.assertEqual(result['intent_ids'],[])
            finally:store.close()

    def test_work_window_is_not_a_deadline_and_unverified_owner_is_not_assigned(self):
        from meeting_eval.task_events import reduce_task_events
        meeting,event=sample();event['time'].update(kind='work_window',text='两会之间',date='2026-11-20')
        result=reduce_task_events([event],[],meeting,{'tasks':[]})
        self.assertIsNone(result['items'][0]['due_date'])
        self.assertIsNone(result['items'][0]['due_text'])
        event['checks']['owner']['verdict']='insufficient'
        result=reduce_task_events([event],[],meeting,{'tasks':[]})
        self.assertEqual(result['items'][0]['operation'],'candidate')
        self.assertIsNone(result['items'][0]['owner_ref'])

    def test_same_utterance_can_contain_two_tasks_and_old_completion(self):
        from meeting_eval.task_events import reduce_task_events
        meeting,first=sample();second=copy.deepcopy(first)
        second['event_id']='E2';second['work']['description']='检查字幕'
        result=reduce_task_events([first,second],[],meeting,{'tasks':[]})
        self.assertEqual(len(result['items']),2)
        first['state']['kind']='completed';first['relation'].update(kind='existing',target_guid='T1')
        result=reduce_task_events([first,second],[],meeting,{'tasks':[{'guid':'T1'}]})
        self.assertEqual(len(result['items']),1)
        self.assertEqual(result['updates'][0]['target_guid'],'T1')
        self.assertEqual(result['updates'][0]['status'],'done')

    def test_acceptance_by_someone_else_does_not_create_for_owner(self):
        from meeting_eval.task_events import reduce_task_events
        meeting,event=sample();meeting['segments'][0]['person_ref']='bob'
        result=reduce_task_events([event],[],meeting,{'tasks':[]})
        self.assertEqual(result['items'][0]['operation'],'candidate')

    def test_existing_state_report_does_not_require_a_new_promise(self):
        from meeting_eval.task_events import reduce_task_events
        for state,status in (('completed','done'),('reopened','open')):
            meeting,event=sample()
            event['state']['kind']=state
            event['relation'].update(kind='existing',target_guid='T1')
            event['checks']['commitment'].update(verdict='insufficient',reason='这是状态汇报，不是未来承诺')
            result=reduce_task_events([event],[],meeting,{'tasks':[{'guid':'T1'}]})
            self.assertEqual([(u['target_guid'],u['status']) for u in result['updates']],[('T1',status)])
            for field in ('work','time','state','relation','owner'):
                bad=copy.deepcopy(event);bad['checks'][field]['verdict']='insufficient'
                self.assertEqual(reduce_task_events([bad],[],meeting,{'tasks':[{'guid':'T1'}]})['updates'],[])
        event['state']['kind']='future_work';event['relation'].update(kind='new',target_guid=None)
        self.assertEqual(reduce_task_events([event],[],meeting,{'tasks':[]})['items'],[])


if __name__=='__main__':
    unittest.main()
