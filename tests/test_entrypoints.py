import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class EntryTests(unittest.TestCase):
    def test_cli_exposes_ingest_and_queries(self):
        p = subprocess.run([sys.executable,'-m','meeting_eval','--help'],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('ingest',p.stdout)
        self.assertIn('recap',p.stdout)

    def test_workflow_runs_six_queries_and_preserves_guid(self):
        from scripts.replay_mvp import workflow
        with tempfile.TemporaryDirectory() as tmp:
            rows, report = workflow(Path(tmp))
            self.assertEqual([r['tasks'] for r in rows],
                             [['W41','W42'],['W42'],['W42'],[],['W41','W42'],[]])
            self.assertEqual(report['forbidden_count'],0)
            self.assertEqual(report['recall'],1)

if __name__ == '__main__':
    unittest.main()
