import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from meeting_eval.decision_review import DecisionReview, project_claims, review_input


class DecisionReviewTests(unittest.TestCase):
    def setUp(self):
        self.meeting = dict(segments=[dict(id='s1',speaker='甲',text='从本周起仅会员可参加。'),
                                      dict(id='s2',speaker='乙',text='访客周三可以参加。')])
        self.turns, _ = review_input(self.meeting, [])
        self.review = DecisionReview(SimpleNamespace(model='test'), None, {})
        self.row = dict(topic=1,attribute='资格',statement='限会员参加',basis='communicated_rule',
                        refs=[1],anchor=1,quote='仅会员可参加',supersedes=None)

    def respond(self, raw):
        self.review.call = lambda stage,payload,check: check(raw)

    def reconcile(self, row, history=()):
        self.respond(dict(decisions=[row]))
        return self.review.reconcile(self.turns,[dict(topic='资格',refs=[1])],[],[],history)

    def test_evidence_and_historical_target_must_be_authorized(self):
        actual = project_claims(self.meeting,self.reconcile(self.row))
        self.assertEqual(actual[0]['evidence_ids'], ['s1'])
        for change in (dict(refs=[3]),dict(anchor=2),dict(quote='全员参加'),dict(topic=2),
                       dict(supersedes='another')):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.reconcile(dict(self.row,**change))
        self.assertEqual(self.reconcile(dict(self.row,supersedes='old'),[dict(id='old',attribute='资格')])[0]['supersedes'],'old')

    def test_unresolved_topics_and_late_state_have_no_published_claim(self):
        topics = [dict(topic='资格',refs=[1])]
        row = dict(state='reopened',refs=[1],adopted=[1],later=[2],reason='团队将现行安排重新交给大家选择')
        self.respond({'1':[row]})
        self.assertEqual(self.review.verify(self.turns, topics, []), [])
        self.respond({'1':[dict(row,later=[])]})
        with self.assertRaises(ValueError):
            self.review.verify(self.turns, topics, [])

    def test_reaffirmation_requires_one_authorized_same_attribute_target(self):
        history = [dict(id='old',attribute='资格')]
        rows = self.reconcile(dict(self.row,reaffirms='old'),history)
        self.assertEqual(project_claims(self.meeting,rows)[0]['reaffirms'],'old')
        for change in (dict(reaffirms='unknown'),dict(reaffirms='old',attribute='年费'),
                       dict(reaffirms='old',supersedes='old')):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.reconcile(dict(self.row,**change), history)
        self.respond(dict(groups=[[1,2]]))
        with self.assertRaises(ValueError):
            self.review.merge([rows[0],dict(rows[0],reaffirms=None)])

    def test_merge_keeps_independent_exception_and_source_ids(self):
        a,b,c = [dict(attribute='资格',statement=s,refs=r,supersedes=None) for s,r in
                 [('会员可参加，访客周三例外',[1,2]),('会员可参加',[1]),('志愿者限周五参加',[2])]]
        self.respond(dict(groups=[[1,2],[3]]))
        out = self.review.merge([a,b,c])
        self.assertEqual(out,[a,c])
        for groups in ([[1,2]], [[1,2],[2,3]], [[0],[2,3]]):
            self.respond(dict(groups=groups))
            with self.assertRaises(ValueError):
                self.review.merge([a,b,c])

    def test_scans_all_turns_including_boundary_even_without_draft(self):
        seen = []
        def call(stage,payload,check):
            self.assertEqual(stage,'decision_scan')
            seen.append([n for n,_,_ in payload['turns']])
            return check({'topics':[]})
        self.review.call = call
        meeting = dict(segments=[dict(id=str(i),speaker='甲',text='收到') for i in range(321)])
        self.assertEqual(self.review.review(meeting,[],[]),[])
        self.assertEqual(set.union(*map(set,seen)),set(range(1,322)))
        self.assertTrue(set(seen[0]) & set(seen[1]))

    def test_later_reopening_overrides_an_earlier_effective_judgment(self):
        claims=[dict(topic=1,statement='所有访客都可参加',anchor=1,refs=[1]),
                dict(topic=2,statement='会费不变',anchor=2,refs=[2])]
        findings=[dict(topic=1,state='effective',later=[2])]
        self.respond({'states':{'0':'open'}})
        self.assertEqual(self.review.closing_status(self.turns,claims,findings),[claims[1]])

    def test_complete_list_uses_only_a_reported_group_and_draft(self):
        claims=[dict(attribute='必备项',statement=x,refs=[i],supersedes=None)
                for i,x in enumerate(('频道','音量'),1)]
        draft=dict(topic='必备项',statement='频道和音量为必备项',supersedes=None)
        self.respond(dict(groups=[[1,2]],complete_lists={'1':1}))
        self.assertEqual(self.review.merge(claims,[draft]),[
            dict(attribute='必备项',statement=draft['statement'],refs=[1,2],supersedes=None)])
        self.respond(dict(groups=[[1],[2]],complete_lists={'1':1}))
        with self.assertRaises(ValueError):
            self.review.merge(claims,[draft])

    def test_failed_review_cannot_publish_the_original_proposal(self):
        from meeting_eval.extract import Extractor
        with tempfile.TemporaryDirectory() as temp, patch('meeting_eval.model_client.credentials',
                return_value=('test','deepseek-flash','https://example.invalid')):
            model=Extractor(None,Path(temp),'context-v5',review_decisions=True)
            draft={'decisions':[dict(attribute='资格',statement='全部通过',evidence_ids=['s1'],supersedes=None)]}
            with patch('meeting_eval.stage_runner.run_stage',return_value=draft), patch.object(
                    model.decision_reviewer,'review',side_effect=ValueError('invalid source quote')):
                result=model.stage('decisions',dict(meeting=self.meeting,decisions=[]))
            self.assertNotIn('decisions',result)
            self.assertEqual(result['_errors'][0]['stage'],'decisions')

