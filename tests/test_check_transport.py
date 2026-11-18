import json
from pathlib import Path
import unittest
from unittest.mock import patch

try:
    from meeting_eval.check_transport import normalize_check_output
except ImportError:
    normalize_check_output=None
from meeting_eval.context_protocol_v4 import closed_validate

FIXTURES=json.loads((Path(__file__).parent/'fixtures/check_transport_failures.json').read_text(encoding='utf8'))


class CheckTransportTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(normalize_check_output,'Missing bounded structure normalizer')

    def test_four_recorded_failures_recover_without_changing_checks(self):
        for f in FIXTURES:
            with self.subTest(case=f['case_id'],attempt=f['attempt']):
                out=normalize_check_output(f['text'],f['contract'])
                self.assertIsNotNone(out);closed_validate(out['value'],f['contract'])
                self.assertEqual(out['value']['case_id'],f['case_id'])
                row=out['value']['record_checks']['R1']
                self.assertEqual(row['kind'],'work' if f['case_id']=='C14' else 'deferred_topic')
                if f['case_id']=='C14':self.assertEqual(out['value']['checks']['E1.commitment']['verdict'],'supported')
                self.assertIn('before_hash',out['normalization'])
                self.assertIsNone(normalize_check_output(json.dumps(out['value']),f['contract']))

    def test_rejects_truncation_missing_values_duplicate_keys_and_conflicting_roots(self):
        f=FIXTURES[0];good=normalize_check_output(f['text'],f['contract'])['value']
        encoded=json.dumps(good,ensure_ascii=False)
        for text in (encoded[:-30],encoded.replace('"case_id": "C14"','"case_id": '),
                     encoded.replace('"case_id": "C14"','"case_id": "C14", "case_id": "C14"')):
            self.assertIsNone(normalize_check_output(text,f['contract']))
        good['record_checks']['checks']=good['checks']
        self.assertIsNone(normalize_check_output(json.dumps(good),f['contract']))

    def test_does_not_edit_delimiters_in_strings_or_missing_content(self):
        f=FIXTURES[0]
        text=f['text'].replace('本场当前话语','文字中的 } , "checks": 不是容器')
        self.assertIsNone(normalize_check_output(text,f['contract']))
        self.assertIsNone(normalize_check_output('{"case_id":"C14","record_checks":{},"checks":',f['contract']))

    def test_ambiguous_schema_candidates_are_rejected(self):
        # Both legal insertion locations are permitted by an intentionally loose validator.
        text='{"record_checks":{"R1":{},"checks":{},"coverage_findings":[]}'
        with patch('meeting_eval.check_transport.closed_validate'):
            self.assertIsNone(normalize_check_output(text,FIXTURES[0]['contract']))


if __name__=='__main__':unittest.main()
