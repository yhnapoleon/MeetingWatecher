import json
from pathlib import Path
import tempfile
import unittest
from run_system_validation import include_semantic,accounting
from run_context_v5_fixes import current_manifest


class CurrentBaselineTests(unittest.TestCase):
    def test_complete_suite_contains_original_and_new_cases_without_label_leakage(self):
        m=include_semantic(current_manifest())
        self.assertEqual(len(m['jobs'])+len(m['chains']),115)
        self.assertEqual(len({(j['group'],j['id']) for j in m['jobs']}),113)
        self.assertEqual(len([j for j in m['jobs'] if j['group']=='semantic']),20)
        for j in m['jobs']:
            self.assertNotIn('expected',j['meeting']);self.assertNotIn('review_policy',j['meeting'])
        self.assertTrue({'C11','C24','P08b','CP01','SV15','C14','SV05','SV17'}<={j['id'] for j in m['jobs']})

    def test_current_recovery_states_and_local_normalization_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            for i,status in enumerate(('accepted','recovery_required','waiting_retry','terminal_error')):
                d=p/str(i);d.mkdir()
                (d/'state.json').write_text(json.dumps(dict(status=status,attempts=[dict(status=status,candidate_file='normalized.json' if i==0 else 'raw.json')])),encoding='utf8')
            got=accounting(p)
            self.assertEqual([got[k] for k in ('exhausted_nodes','deferred_nodes','terminal_nodes','normalized_nodes')],[1,1,1,1])
            self.assertEqual(got['calls'],0)


if __name__=='__main__':unittest.main()
