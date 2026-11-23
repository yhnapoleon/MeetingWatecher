import json
import unittest
import test_copilot as base


class WorkModel(base.ModelFixture):
    target = None
    existing = None
    owner = 'David'
    def call(self, messages, log_path, tools=None, tool_choice=None):
        msg = super().call(messages, log_path, tools, tool_choice)
        if tools:
            return msg
        ctx = json.loads(messages[-1]['content'])
        data = json.loads(msg['content'])
        data['work_changes'] = [{'target_guid': self.target, 'existing_proposal_id':self.existing, 'owner': self.owner, 'title': '准备组件概念',
             'object_text':'遥控器组件概念', 'deadline_text':None,
             'due_text': None, 'state': 'progress' if self.target else 'open',
             'detail': '汇报了组件约束' if self.target else '准备组件概念并在下一场汇报',
             'evidence_ids': [ctx['evidence'][-1]['id']]}]
        return {'role':'assistant','content':json.dumps(data)}


class MeetingWorkTests(unittest.TestCase):
    setUp = base.CopilotTests.setUp
    tearDown = base.CopilotTests.tearDown
    session = base.CopilotTests.session
    run_job = base.CopilotTests.run_job

    def use_work_model(self):
        model = WorkModel()
        self.app.state.runner.model = model
        return model

    def test_confirm_recap_progress_same_identity_and_rewind(self):
        model = self.use_work_model()
        first = self.session(260000)
        job, _ = self.run_job('work', sid=first)
        self.assertEqual(job['status'], 'completed', job.get('error'))
        pid = job['result']['work_proposal_ids'][0]
        endpoint = f'/api/copilot/work/{pid}/confirm?session_id={first}'
        body = {'note':'由主持人确认分工', 'due_text':'下次会议前'}
        task = self.client.post(endpoint, json=body)
        self.assertEqual(task.status_code, 200, task.text)
        task = task.json()
        self.assertEqual(task['state'], 'open')
        self.assertEqual(self.client.post(endpoint, json=body).json(), task)
        second = self.session(700000, 1, [{'meeting':0,'cursor_ms':389999}])
        view = self.client.get('/api/copilot/work',params={'session_id':second}).json()
        self.assertEqual(len(view['tasks']),1)
        model.target = task['guid']
        update, _ = self.run_job('work',sid=second)
        self.assertEqual(update['status'],'completed',update.get('error'))
        updated = self.client.post(f"/api/copilot/work/{update['result']['work_proposal_ids'][0]}/confirm?session_id={second}",json={'note':'阶段汇报，继续跟进'}).json()
        self.assertEqual(updated['guid'], task['guid'])
        self.assertEqual(updated['platform_status'],'open')
        self.assertEqual(updated['state'],'progress')
        self.assertEqual(updated['due_text'],'下次会议前')
        view = self.client.get('/api/copilot/work',params={'session_id':second}).json()
        self.assertEqual((len(view['tasks']),len(view['history'])),(1,2))
        old = self.client.get('/api/copilot/work',params={'session_id':first}).json()
        self.assertEqual(old['tasks'][0]['state'],'open')
        self.assertEqual(len(old['history']),1)
        before = self.session(200000)
        self.assertEqual(self.client.get('/api/copilot/work',params={'session_id':before}).json()['tasks'],[])
        self.assertEqual(self.client.post(endpoint.replace(first,before),json={}).status_code,403)

    def test_unknown_or_wrong_owner_cannot_update(self):
        model = self.use_work_model();model.target='SIM-unavailable'
        job,_=self.run_job('work')
        self.assertEqual(job['status'],'failed')
        model.target=None;model.owner='Unknown person'
        job,_=self.run_job('work')
        self.assertEqual(job['status'],'failed')
        self.assertEqual(self.client.get('/api/copilot/work',params={'session_id':self.sid}).json()['proposals'],[])

    def test_confirmation_after_cursor_cannot_leak_into_earlier_view(self):
        self.use_work_model();sid=self.session(260000)
        job,_=self.run_job('work',sid=sid);pid=job['result']['work_proposal_ids'][0]
        later=self.session(300000)
        self.assertEqual(self.client.post(f'/api/copilot/work/{pid}/confirm?session_id={later}',json={}).status_code,200)
        old=self.client.get('/api/copilot/work',params={'session_id':sid}).json()
        self.assertEqual(old['tasks'],[])
        self.assertEqual(len(old['proposals']),1)

    def test_automatic_discovery_details_and_text_reuse(self):
        model=self.use_work_model();sid=self.session(260000)
        auto,_=self.run_job('summary',sid=sid,extract_work=True)
        self.assertEqual(auto['status'],'completed',auto.get('error'))
        pid=auto['result']['work_proposal_ids'][0]
        view=self.client.get('/api/copilot/work',params={'session_id':sid}).json()
        self.assertEqual(view['tasks'],[])
        self.assertEqual(view['proposals'][0]['origin'],'automatic')
        self.assertEqual(view['proposals'][0]['change']['object_text'],'遥控器组件概念')
        self.assertIsNone(view['proposals'][0]['change']['deadline_text'])
        model.existing=pid
        manual,_=self.run_job('work',sid=sid)
        self.assertEqual(manual['result']['work_proposal_ids'],[pid])
        view=self.client.get('/api/copilot/work',params={'session_id':sid}).json()
        self.assertEqual(len(view['proposals']),1)
        saved=self.client.post(f'/api/copilot/work/{pid}/confirm?session_id={sid}',json={}).json()
        self.assertEqual(saved['created_origin'],'automatic')
        self.assertEqual(saved['object_text'],'遥控器组件概念')
        second=self.session(700000,1,[{'meeting':0,'cursor_ms':389999}])
        model.existing=None;model.target=saved['guid']
        update,_=self.run_job('work',sid=second)
        updated=self.client.post(f"/api/copilot/work/{update['result']['work_proposal_ids'][0]}/confirm?session_id={second}",json={}).json()
        self.assertEqual(updated['created_origin'],'automatic')
        self.assertEqual(updated['origin'],'text')
        self.assertEqual(updated['guid'],saved['guid'])

    def test_plain_summary_does_not_create_work(self):
        self.use_work_model()
        summary,_=self.run_job('summary',sid=self.session(260000))
        self.assertEqual(summary['status'],'completed')
        self.assertEqual(summary['result']['answer']['work_changes'],[])
        self.assertNotIn('work_proposal_ids',summary['result'])

    def test_invalid_pending_reference_rejected(self):
        model=self.use_work_model();model.existing='not-visible'
        job,_=self.run_job('work',sid=self.session(260000))
        self.assertEqual(job['status'],'failed')
        self.assertIn('待确认事项关联不匹配',job['error'])


if __name__=='__main__':unittest.main()
