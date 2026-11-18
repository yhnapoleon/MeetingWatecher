"""Minimal experiment-boundary checks; no model calls."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import probe_source_work as probe
import reassess_baselines


class ReassessmentTests(unittest.TestCase):
    def test_failed_service_is_scored_and_preserves_original_error(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with patch.object(probe, 'service_replay', side_effect=ValueError('M1 did not create exactly one task')):
                result = probe.scored_service_replay(out, False)
            self.assertFalse(result['passed'])
            self.assertFalse(result['checks']['replay_completed'])
            self.assertEqual(result['failure']['type'], 'ValueError')
            self.assertIn('M1 did not create', result['failure']['detail'])
            self.assertEqual(probe.read(out / 'replay-error.json'), result['failure'])

    def test_source_sees_no_upstream_and_same_g_source_is_shared(self):
        cases = probe.read(probe.FIXTURES)
        source = probe.source_payload(cases['G-omitted'])
        self.assertEqual(set(source), {'meeting', 'history', 'evidence_catalog'})
        self.assertEqual(source, probe.source_payload(cases['G-same-segment']))
        poisoned = copy.deepcopy(cases['G-omitted'])
        poisoned['frozen'] = {'ledger': 'unexpected instruction', 'interpreted': 'wrong record'}
        self.assertEqual(probe.source_payload(poisoned), source)

    def test_unknown_source_quote_is_rejected(self):
        case = probe.read(probe.FIXTURES)['M2']
        payload = probe.source_payload(case)
        raw = dict(case_id=payload['meeting']['case_id'], works=[dict(description='work', evidence=['Q999'])],
            implicit_need=[], context=[])
        with self.assertRaises(ValueError):
            probe.validate_inventory(raw, payload)

    def test_offline_regrade_exposes_m1_failure_without_rewriting_history(self):
        folder = probe.ROOT / 'runs/2026-11-15-context-v3/positive-r1'
        files = list(folder.glob('*.json'))
        before = {p:p.read_bytes() for p in files}
        result = reassess_baselines.regrade(folder)
        self.assertTrue(result['original_passed'])
        self.assertFalse(result['passed'])
        self.assertEqual(set(result['failed_checks']), {'m1_no_interpretation_unresolved','m1_repair_valid'})
        self.assertEqual(before, {p:p.read_bytes() for p in files})


if __name__ == '__main__':
    unittest.main()
