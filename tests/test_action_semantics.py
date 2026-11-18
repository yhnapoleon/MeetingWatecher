import copy
import json
from pathlib import Path
import tempfile
import unittest


class SemanticTests(unittest.TestCase):
    def data(self, description='剪辑视频交大家确认', failed=False):
        inputs = [dict(case_id='X', segments=[dict(id='s1', text='我们会剪辑视频给大家确认。还有文稿可以吧。')])]
        labels = [dict(case_id='X', event_id='X.1', operation='candidate', description='剪辑视频并确认', evidence_ids=['s1'], uncertainty=[])]
        predictions = [dict(case_id='X', items=[] if failed else [dict(description=description, operation='candidate', evidence_ids=['s1'])], status='failed' if failed else 'processed')]
        return inputs, labels, predictions

    def reviewed(self, inputs, labels, predictions, supported=True, complete=True):
        from scripts.review_action_semantics import export_review
        value = export_review(inputs, labels, predictions)
        value.update(status='agent_reviewed', reviewer='test-reviewer')
        for case in value['cases']:
            case['reviewed'] = True
            for row in case['judgments']:
                row.update(gold_event_id='X.1', content_supported=supported, content_complete=complete,
                           owner_correct=True, commitment_correct=True, time_correct=True,
                           operation_correct=True, reason='原话只承诺视频剪辑并确认。', evidence_ids=['s1'])
        return value

    def test_reviewed_false_description_cannot_score_like_valid_task(self):
        from scripts.score_action_semantics import score_semantics
        for desc, supported in [('采购二百台服务器并立即付款', False), ('剪视频并整理文稿', False), ('将视频剪辑好后请大家核对', True)]:
            with self.subTest(description=desc):
                inputs, labels, predictions = self.data(desc)
                review = self.reviewed(inputs, labels, predictions, supported)
                score = score_semantics(predictions, labels, review)
                self.assertEqual(score['content']['hits'], int(supported))
                self.assertEqual(score['unsupported_predictions'], int(not supported))

    def test_modified_prediction_or_input_invalidates_review(self):
        from scripts.review_action_semantics import validate_review
        inputs, labels, predictions = self.data()
        review = self.reviewed(inputs, labels, predictions)
        predictions[0]['items'][0]['description'] = '采购服务器'
        with self.assertRaisesRegex(ValueError, 'hash'):
            validate_review(review, inputs, labels, predictions)
        inputs[0]['segments'][0]['text'] = '不同原话'
        with self.assertRaisesRegex(ValueError, 'hash'):
            validate_review(review, inputs, labels, predictions)

    def test_unreviewed_or_duplicate_match_is_rejected(self):
        from scripts.review_action_semantics import export_review, validate_review
        inputs, labels, predictions = self.data()
        with self.assertRaises(ValueError):
            validate_review(export_review(inputs, labels, predictions), inputs, labels, predictions)
        predictions[0]['items'].append(copy.deepcopy(predictions[0]['items'][0]))
        review = self.reviewed(inputs, labels, predictions)
        with self.assertRaisesRegex(ValueError, 'one-to-one'):
            validate_review(review, inputs, labels, predictions)

    def test_two_tasks_in_same_utterance_can_match_separately(self):
        from scripts.score_action_semantics import score_semantics
        inputs, labels, predictions = self.data()
        labels.append({**labels[0], 'event_id':'X.2', 'description':'另一件事'})
        predictions[0]['items'].append({**predictions[0]['items'][0], 'description':'另一件事'})
        review = self.reviewed(inputs, labels, predictions)
        review['cases'][0]['judgments'][1]['gold_event_id'] = 'X.2'
        self.assertEqual(score_semantics(predictions, labels, review)['content']['hits'], 2)

    def test_field_error_prevents_fully_correct_and_safe_create(self):
        from scripts.score_action_semantics import score_semantics
        for field in ('owner_correct', 'commitment_correct', 'time_correct', 'operation_correct'):
            inputs, labels, predictions = self.data()
            predictions[0]['items'][0]['operation'] = 'create'
            review = self.reviewed(inputs, labels, predictions)
            review['cases'][0]['judgments'][0][field] = False
            report = score_semantics(predictions, labels, review)
            self.assertEqual(report['content']['hits'], 1)
            self.assertEqual(report['fully_correct']['hits'], 0)
            self.assertEqual(report['unsafe_create_proposals'], 1)

    def test_failed_case_remains_in_recall_denominator(self):
        from scripts.score_action_semantics import score_semantics
        inputs, labels, predictions = self.data(failed=True)
        report = score_semantics(predictions, labels, self.reviewed(inputs, labels, predictions))
        self.assertEqual(report['content']['expected'], 1)
        self.assertEqual(report['content']['hits'], 0)
        self.assertEqual(report['failed_cases'], ['X'])

    def test_dataset_rejects_untraceable_reference_and_blind_overlap(self):
        from meeting_eval.inputs import digest
        from scripts.verify_action_semantics import verify_dataset
        inputs, labels, _ = self.data()
        inputs[0].update(series='series-1', meeting_id='meeting-1', participants=[])
        labels[0].update(owner_ref=None, field_evidence={'work':[dict(segment_id='s1',start=0,end=2,quote='我们')]})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def save(view, cases, refs):
                folder = root/view
                folder.mkdir(exist_ok=True)
                for name, rows in [('input',cases),('labels',refs)]:
                    (folder/(name+'.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
                (folder/'manifest.json').write_text(json.dumps(dict(status='frozen',input_hash=digest(cases),labels_hash=digest(refs))),encoding='utf-8')
            save('regression',inputs,labels)
            self.assertEqual(verify_dataset(root)['regression']['actions'],1)
            bad = copy.deepcopy(labels)
            bad[0]['field_evidence']['work'][0]['quote']='他们'
            save('regression',inputs,bad)
            with self.assertRaisesRegex(ValueError,'span'):
                verify_dataset(root)
            save('regression',inputs,labels)
            save('blind',inputs,labels)
            with self.assertRaisesRegex(ValueError,'overlap'):
                verify_dataset(root)


if __name__ == '__main__':
    unittest.main()
