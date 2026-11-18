"""Reports cannot acquire new-task permission by falling through an update path."""
import copy
import unittest

from meeting_eval.context_state import reduce_context
from test_context_updates import fixture


class ReportRoutingTests(unittest.TestCase):
    def report(self, state='progress', change='set'):
        _, meeting, event, record, task = fixture(change, state)
        event['relation'].update(kind='new', target_guid=None)
        event['commitment']['kind'] = 'unknown'
        return meeting, event, record, task

    def test_report_with_time_is_retained_without_creating_or_asking(self):
        for state in ('progress', 'completed'):
            for change in ('keep', 'set', 'clear'):
                with self.subTest(state=state, change=change):
                    m, e, r, _ = self.report(state, change)
                    before = copy.deepcopy(e)
                    out = reduce_context([e], [], [r], m, {'tasks': []})
                    self.assertEqual(out['items'], [])
                    self.assertEqual(out['updates'], [])
                    self.assertEqual(out['pending'], [])
                    self.assertEqual(out['review_records'], [])
                    self.assertEqual(len(out['reports']), 1)
                    self.assertEqual(out['reports'][0]['state'], state)
                    self.assertEqual(out['reports'][0]['time'], before['time'])
                    self.assertEqual(e, before)

    def test_other_change_retains_report_and_explains_unavailable_update(self):
        m, e, r, _ = self.report()
        e['other_changes'] = ['content']
        out = reduce_context([e], [], [r], m, {'tasks': []})
        self.assertEqual(len(out['reports']), 1)
        self.assertEqual(out['items'], [])
        review = out['review_records'][0]
        self.assertFalse(review['can_add_task'])
        self.assertEqual(review['category'], 'execution_blocked')
        self.assertIsNone(review['question'])
        self.assertTrue(review['execution_reason'])

    def test_nonfuture_or_unverified_state_cannot_be_confirmed_as_new_task(self):
        for state, verdict in [('unknown', 'supported'), ('revised', 'supported'),
                               ('reopened', 'supported'), ('future_work', 'insufficient'),
                               ('progress', 'insufficient')]:
            with self.subTest(state=state, verdict=verdict):
                m, e, r, _ = self.report(state)
                e['checks']['state']['verdict'] = verdict
                out = reduce_context([e], [], [r], m, {'tasks': []})
                self.assertEqual(out['items'], [])
                review = out['review_records'][0]
                self.assertFalse(review['can_add_task'])
                self.assertTrue(review.get('question') or review.get('execution_reason'))

    def test_future_and_conditional_work_still_have_confirmation_path(self):
        for commitment in ('self_committed', 'conditional'):
            m, e, r, _ = self.report('future_work')
            e['commitment']['kind'] = commitment
            if commitment == 'self_committed':
                r.update(missing_fields=['owner'], question='由谁负责？')
            out = reduce_context([e], [], [r], m, {'tasks': []})
            self.assertEqual(len(out['items']), 1)
            self.assertEqual(out['items'][0]['operation'], 'candidate')
            self.assertTrue(out['review_records'][0]['can_add_task'])
            if commitment == 'conditional':
                self.assertEqual(out['review_records'][0]['category'], 'conditional_work')

    def test_existing_progress_date_update_keeps_its_operation(self):
        _, m, e, r, task = fixture('set', 'progress')
        out = reduce_context([e], [], [r], m, {'tasks': [task]})
        self.assertEqual(out['items'], [])
        self.assertEqual(out['updates'][0]['changes']['due_date'], '2026-11-20')
        self.assertEqual(out['review_records'], [])


if __name__ == '__main__':
    unittest.main()
