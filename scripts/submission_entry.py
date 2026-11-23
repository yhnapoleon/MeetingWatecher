"""Reconstruct and check the submitted project, without model requests."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'check'], nargs='?', default='check')
    parser.add_argument('--workdir', type=Path, help='Optional independent verification directory')
    parser.add_argument('--copilot', action='store_true', help='Also run Copilot offline tests; install locked dependencies first')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    entries = json.loads((root / '提交文件清单.json').read_text(encoding='utf8'))['files']
    for row in entries:
        p = root / row['path']
        if hashlib.sha256(p.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('提交文件哈希不一致: ' + row['path'])
    print(f'提交清单核对通过：{len(entries)} 个文件', flush=True)
    work = (args.workdir or root / '_运行工作区').resolve()
    for row in entries:
        if not row['runtime_path']:
            continue
        src, dst = root / row['path'], work / row['runtime_path']
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and dst.read_bytes() != src.read_bytes():
            raise FileExistsError(f'保留已修改文件，请指定新的 --workdir：{dst}')
        if not dst.exists():
            shutil.copy2(src, dst)
    print('运行工作区：' + str(work), flush=True)
    if args.action == 'prepare':
        return
    env = dict(os.environ, PYTHONUTF8='1', PYTHONPATH=str(work / 'tests'))
    commands = [
        ['scripts/verify_release_evidence.py'],
        ['-m', 'unittest', 'test_unclear_intent', 'test_context_system', 'test_requirement_review',
         'test_report_routing', 'test_context_state', 'test_context_v5_regressions'],
        ['scripts/run_current.py', '--input', 'examples/m1.json', '--out', 'runs/submission-preflight'],
    ]
    if args.copilot:
        commands.append(['-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_copilot*.py'])
    for command in commands:
        subprocess.run([sys.executable] + command, cwd=work, env=env, check=True)
    print('离线检查通过；未调用模型。完整应用启动命令见 04_技术报告/CONFIG.md。')


if __name__ == '__main__':
    main()
