import copy
import tempfile
import unittest
from pathlib import Path

from meeting_eval.context_state import reduce_context
from meeting_eval.inputs import normalize
from meeting_eval.service import Service
from meeting_eval.store import Store
from test_context_updates import fixture, ReducedExtractor


def new_work():
    raw, meeting, event, record, _ = fixture('set', 'future_work')
    event['relation'].update(kind='new', target_guid=None)
    event['work']['description'] = record['description'] = '整理合同'
    event['time'].update(date=None, text='下次会前')
    raw['segments'][0]['text'] = '我来整理合同，下次会前完成。'
    for obj in [event[k] for k in ('work', 'owner', 'commitment', 'time', 'state', 'relation')] + [record]:
        obj['evidence'] = [dict(segment_id='s1', start=0, end=len(raw['segments'][0]['text']), quote=raw['segments'][0]['text'])]
    for check in list(event['checks'].values())+[record['check']]:
        check['evidence'] = copy.deepcopy(record['evidence'])
    return raw, normalize(raw, 'host'), event, record


class FieldPreservationTests(unittest.TestCase):
    def test_relative_deadline_missing_calendar_date_creates_task_without_date_question(self):
        raw, meeting, event, record = new_work()
        record.update(missing_fields=['time'], question='下次会议具体是哪一天？')
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp)/'state.sqlite')
            try:
                service = Service(store, ReducedExtractor(event, record))
                result = service.process(raw, 'host', '2026-11-16T10:00:00+08:00')
                self.assertEqual(len(store.tasks()), 1)
                self.assertEqual(store.tasks()[0]['summary'], '整理合同')
                self.assertEqual(store.tasks()[0]['due_text'], '下次会前')
                self.assertIsNone(store.tasks()[0]['due_date'])
                self.assertEqual(service.requirements(result['source_id'], 'host'), [])
            finally:
                store.close()

    def test_disputed_acceptance_retains_candidate_without_claiming_commitment(self):
        for verdict in ('insufficient', 'contradicted'):
            raw, meeting, event, record = new_work()
            event['checks']['commitment'].update(verdict=verdict, reason='回应的对象不清楚')
            before = copy.deepcopy(event)
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as tmp:
                store = Store(Path(tmp)/'state.sqlite')
                try:
                    service = Service(store, ReducedExtractor(event, record))
                    result = service.process(raw, 'host', '2026-11-16T10:00:00+08:00')
                    self.assertEqual(len(result['extraction']['items']), 1)
                    self.assertEqual(result['extraction']['items'][0]['operation'], 'candidate')
                    self.assertEqual(store.tasks(), [])
                    self.assertIn('commitment', service.requirements(result['source_id'], 'host')[0]['missing_fields'])
                    self.assertEqual(event, before)
                finally:
                    store.close()

    def test_uncertain_date_keeps_work_candidate_without_writing_date(self):
        raw, meeting, event, record = new_work()
        event['time'].update(change='uncertain', date='2026-11-20', text='可能11月20日')
        result = reduce_context([event], [], [record], meeting, {'tasks': []})
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['operation'], 'candidate')
        self.assertIsNone(result['items'][0]['due_date'])
        self.assertIsNone(result['items'][0]['due_text'])
        self.assertIn('time', result['review_records'][0]['missing_fields'])

    def test_unclassified_time_gap_keeps_question_and_candidate(self):
        raw, meeting, event, record = new_work()
        event['time'].update(kind='unspecified', change='keep', text=None, date=None, evidence=[])
        record.update(missing_fields=['time'], question='两个期限以哪个为准？')
        result = reduce_context([event], [], [record], meeting, {'tasks': []})
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['items'][0]['operation'], 'candidate')
        self.assertEqual(result['review_records'][0]['question'], '两个期限以哪个为准？')

    def test_real_time_issue_is_not_erased_by_relative_deadline(self):
        raw, meeting, event, record = new_work()
        record['check'].update(verdict='insufficient', issues=['time'], reason='存在两个竞争的下次会议')
        result = reduce_context([event], [], [record], meeting, {'tasks': []})
        self.assertEqual(len(result['items']), 1)
        self.assertFalse(any(item['operation']=='create' for item in result['items']))
        self.assertIn('time', result['review_records'][0]['missing_fields'])

    def test_record_field_issues_retain_candidates_and_do_not_erase_relative_time(self):
        for field, verdict in (('commitment', 'contradicted'), ('commitment', 'insufficient'), ('time', 'insufficient')):
            raw, meeting, event, record = new_work()
            record.update(missing_fields=['time'], question='下次会议具体是哪一天？')
            record['check'].update(verdict=verdict, issues=[field], reason='仅该字段未确认')
            if field == 'commitment':
                event['checks']['commitment']['verdict'] = verdict
            else:
                event['time']['change'] = 'uncertain'
            with self.subTest(field=field, verdict=verdict):
                result = reduce_context([event], [], [record], meeting, {'tasks': []})
                self.assertEqual(len(result['items']), 1)
                self.assertEqual(result['items'][0]['operation'], 'candidate')
                self.assertEqual(result['review_records'][0]['description_status'], 'supported_interpretation')
                if field == 'commitment':
                    self.assertEqual(result['items'][0]['due_text'], '下次会前')
                    self.assertNotIn('time', result['review_records'][0]['missing_fields'])
                else:
                    self.assertIsNone(result['items'][0]['due_text'])

    def test_removed_time_gap_does_not_leave_date_question_for_owner_and_commitment(self):
        raw, meeting, event, record = new_work()
        record.update(missing_fields=['time','owner','commitment'], question='下次会议具体是哪一天？')
        result = reduce_context([event], [], [record], meeting, {'tasks': []})
        question = result['review_records'][0]['question']
        self.assertNotIn('日期', question)
        self.assertNotIn('哪一天', question)
        self.assertIn('承接', question)

    def test_suggestions_and_bad_content_do_not_gain_executable_status(self):
        for mode in ('suggested', 'conditional', 'declined', 'unknown', 'bad_time', 'scope', 'inferred'):
            raw, meeting, event, record = new_work()
            if mode == 'bad_time':
                event['checks']['time']['verdict'] = 'contradicted'
                event['work']['description'] = '在错误日期之前整理合同'
            elif mode == 'scope':
                record.update(missing_fields=['scope'], question='整理哪一类合同？')
            elif mode == 'inferred':
                record.update(kind='implicit_need', content_basis='inferred', question='是否开展这项工作？')
            else:
                event['commitment']['kind'] = mode
            with self.subTest(mode=mode):
                result = reduce_context([event], [], [record], meeting, {'tasks': []})
                if mode == 'conditional':
                    self.assertEqual([i['operation'] for i in result['items']], ['candidate'])
                else:
                    self.assertEqual(result['items'], [])
                self.assertTrue(result['review_records'])


if __name__ == '__main__':
    unittest.main()
