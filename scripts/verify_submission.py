"""Check the repository without model requests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--copilot', action='store_true')
    args = parser.parse_args()
    manifest = ROOT / '源码文件清单.json'
    if manifest.exists():
        rows = json.loads(manifest.read_text(encoding='utf8'))
        for row in rows:
            if hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() != row['sha256']:
                raise ValueError('File hash mismatch: ' + row['path'])
        print(f'Checked {len(rows)} packaged files', flush=True)
    env = dict(os.environ, PYTHONUTF8='1', PYTHONPATH=str(ROOT / 'tests'))
    commands = [
        ['scripts/verify_release_evidence.py'],
        ['-m', 'unittest', 'test_unclear_intent', 'test_context_system', 'test_requirement_review',
         'test_report_routing', 'test_context_state', 'test_context_v5_regressions'],
        ['scripts/run_current.py', '--input', 'examples/m1.json', '--out', 'runs/submission-preflight'],
    ]
    if args.copilot:
        commands.append(['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_copilot*.py'])
    for command in commands:
        subprocess.run([sys.executable] + command, cwd=ROOT, env=env, check=True)
    print('Offline verification passed; no model calls.')

if __name__ == '__main__':
    main()
