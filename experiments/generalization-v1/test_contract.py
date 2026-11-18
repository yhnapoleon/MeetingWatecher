import copy
import unittest
import tempfile
import hashlib
import json
from pathlib import Path
import importlib.util
from validate import input_job,validate,read,DATA
from score import totals
import score as scoring
from unittest.mock import patch

class DatasetContract(unittest.TestCase):
    def test_full_source_and_label_validation(self):
        self.assertEqual(validate()['formal'],60)

    def test_gold_poison_never_reaches_service_input(self):
        case=read(DATA/'natural-inputs.json')[0]
        expected=input_job(case)
        poisoned=copy.deepcopy(case)
        poisoned['gold']={'tasks':['SECRET_LABEL_CANARY']}
        poisoned['topic_summary']='SECRET_LABEL_CANARY'
        poisoned['meeting']['annotation']='SECRET_LABEL_CANARY'
        self.assertEqual(input_job(poisoned),expected)

    def test_pilot_not_scheduled(self):
        cases=read(DATA/'natural-inputs.json')+read(DATA/'control-inputs.json')
        jobs=[input_job(c) for c in cases if c['split']=='test']
        self.assertEqual(len(jobs),60)
        self.assertTrue(all(not j['id'].startswith('GP') for j in jobs))
        self.assertTrue(all(j['tasks']==[] for j in jobs))

    def test_extra_goal_in_matching_output_is_false_positive(self):
        rows=[dict(required=1,judgments=[dict(location='items',units=[
            dict(gold_id='T1',requirement='required',field_errors=[]),
            dict(gold_id=None,requirement=None,field_errors=[])])])]
        result=totals(rows)
        self.assertEqual((result['tp'],result['fp'],result['fn']),(1,1,0))

    def test_fields_checked_per_atomic_goal_and_optional_neutral(self):
        rows=[dict(required=2,judgments=[dict(location='items',units=[
            dict(gold_id='T1',requirement='required',field_errors=[]),
            dict(gold_id='T2',requirement='required',field_errors=['owner_wrong']),
            dict(gold_id='T3',requirement='optional',field_errors=[])])])]
        result=totals(rows,fields=True)
        self.assertEqual((result['tp'],result['fp'],result['fn'],result['optional_excluded']),(1,1,1,1))

    def test_scope_reply_and_transcript_send_references_present(self):
        labels={l['case_id']:l for l in read(DATA/'labels.json')}
        self.assertEqual(len(labels['GC02a']['tasks']),2)
        self.assertTrue(any(t['action']=='发送会议文字记录' for t in labels['GN33']['tasks']))

    def test_optional_does_not_hide_extra_false_positive(self):
        rows=[dict(required=0,judgments=[dict(location='items',units=[
            dict(gold_id='T1',requirement='optional',field_errors=[]),
            dict(gold_id=None,requirement=None,field_errors=[])])])]
        result=totals(rows)
        self.assertEqual((result['tp'],result['fp'],result['optional_excluded']),(0,1,1))

    def test_duplicate_gold_match_rejected(self):
        out=dict(case_id='X',result_sha256='hash',references=[dict(id='T1',requirement='required')],
                 predictions=[dict(id='item:0',location='items'),dict(id='item:1',location='items')])
        judgment=dict(units=[dict(gold_id='T1',field_errors=[],reason='same objective')],decomposition_reason='one goal')
        review={'X':dict(result_sha256='hash',predictions={'item:0':judgment,'item:1':judgment})}
        with patch.object(scoring,'export',return_value=[out]),patch.object(scoring,'read',return_value=review):
            with self.assertRaises(AssertionError):scoring.score(Path('unused'))

    def load_runner(self):
        spec=importlib.util.spec_from_file_location('generalization_runner',Path(__file__).with_name('run.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

    def test_failed_case_preserves_known_and_unknown_api_usage(self):
        runner=self.load_runner()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'known').mkdir();(root/'unknown').mkdir()
            for sub in ['known','unknown']:(root/sub/'request.json').write_text('{}')
            (root/'known/meta.json').write_text(json.dumps(dict(usage=dict(total_tokens=123))))
            row=runner.finalize_row(dict(status='runner_failed',calls=0,tokens=0),root)
            self.assertEqual((row['calls'],row['tokens'],row['unknown_usage_calls']),(1,123,1))

    def test_frozen_execution_dependency_change_is_rejected(self):
        runner=self.load_runner()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);p=root/'dependency.py';p.write_text('original')
            record=dict(files={'dependency.py':hashlib.sha256(p.read_bytes()).hexdigest()},model_identity={'model':'x','endpoint':'https://example.invalid'})
            runner.verify_frozen(record,root,record['model_identity'])
            p.write_text('changed')
            with self.assertRaises(AssertionError):runner.verify_frozen(record,root,record['model_identity'])

if __name__=='__main__':unittest.main()
