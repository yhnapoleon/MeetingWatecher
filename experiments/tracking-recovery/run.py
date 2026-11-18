"""Targeted Service regression, reusing four frozen natural-meeting inputs."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'experiments/task-boundary')]
from run_full_context_v5 import one
from run_context_v3 import snapshot
from run_system_validation import accounting
from scripts.run_action_baseline import write_json, credentials


def main():
    old = json.loads((ROOT/'runs/2026-11-17-generalization-v1/manifest.json').read_text(encoding='utf8'))
    selected = {'GN25', 'GN26', 'GN29', 'GN38'}
    jobs = [j for j in old['jobs'] if j['id'] in selected]
    assert len(jobs) == 4
    config = old['inference']
    for rel, expected in old['freeze']['files'].items():
        if rel.startswith('data/generalization-v1/'):
            assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest() == expected, rel
    _, model, endpoint = credentials(ROOT.parent.parent/'meeting-agent/.env')
    assert dict(model=model, endpoint=endpoint) == old['freeze']['model_identity']
    out = ROOT/'runs/2026-11-17-tracking-recovery-v2/focus'
    out.mkdir(parents=True, exist_ok=False)
    write_json(out/'manifest.json', dict(jobs=jobs, inference=config, model_identity=dict(model=model,endpoint=endpoint),
        rounds=1, case_reruns=0, policy='Four targeted old failures; original inputs/labels/inference unchanged; labels not sent to Service.'))
    snapshot(out)
    with zipfile.ZipFile(out/'source.zip', 'a', zipfile.ZIP_DEFLATED) as archive:
        archive.write(Path(__file__), 'experiments/tracking-recovery/run.py')
    rows = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(one, j, out/j['group']/j['id'], {}, config): j for j in jobs}
        for future in as_completed(futures):
            job = futures[future]
            folder = out/job['group']/job['id']
            try:
                row = future.result()
            except Exception as exc:
                row = dict(group=job['group'],case_id=job['id'],status='runner_failed',error=str(exc)[:800])
            row.update(accounting(folder))
            rows.append(row)
            write_json(out/'progress.json', rows)
            print(f'{len(rows)}/4 {job["id"]} {row["status"]} calls={row["calls"]} tokens={row["tokens"]}',flush=True)
    write_json(out/'summary.json', dict(rows=rows, cases=len(rows), **accounting(out), seconds=round(time.perf_counter()-started,3)))


if __name__ == '__main__':
    main()
