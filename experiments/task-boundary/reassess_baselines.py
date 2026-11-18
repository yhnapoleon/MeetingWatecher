"""Read-only regrading of stored Service runs with the v4 M1/M2 checks."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).parent)]
from run_context_v4 import full_flow_checks
from scripts.run_action_baseline import write_json


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def regrade(folder):
    previous = read(folder / 'summary.json')['results']
    # Remove exactly the six appended checks so every version gets the same rule.
    old = copy.deepcopy(previous)
    for meeting in ('m1', 'm2'):
        for suffix in ('no_interpretation_unresolved', 'repair_valid', 'no_extraction_errors'):
            old['checks'].pop(f'{meeting}_{suffix}', None)
    old['passed'] = all(old['checks'].values())
    old['original_contract_passed'] = old['passed']
    result = full_flow_checks(old, folder)
    evidence = {}
    for meeting in ('m1', 'm2'):
        output = read(folder / f'{meeting}-result.json')
        extraction = output['extraction']
        trace = extraction['_task_trace']
        evidence[meeting] = dict(status=output['status'], items=extraction['items'],
            reviews=trace.get('review_records', []), errors=extraction.get('_errors', []),
            repair={k: trace.get('repair', {}).get(k) for k in ('status', 'stage', 'detail')})
    files = ['summary.json', 'm1-result.json', 'm2-result.json', 'acceptance.json', 'm2-validation.json']
    return dict(source=folder.relative_to(ROOT).as_posix(),
        sha256={f: hashlib.sha256((folder / f).read_bytes()).hexdigest() for f in files},
        original_passed=old['passed'], passed=result['passed'], checks=result['checks'],
        failed_checks=[k for k, v in result['checks'].items() if not v], evidence=evidence,
        historical_input_hashes=read(folder / 'acceptance.json')['input_sha256'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    rows = []
    for version in ('v2', 'v3', 'v4'):
        for name in ('cross-r1', 'cross-r2', 'positive-r1', 'positive-r2'):
            row = regrade(ROOT / f'runs/2026-11-15-context-{version}' / name)
            row.update(version=version, run=name)
            rows.append(row)
    summary = dict(network_calls=0,
        method='Stored legacy checks plus recomputed full_flow_checks; no historical model or DB execution.',
        versions={v: dict(original_passed=sum(r['original_passed'] for r in rows if r['version'] == v),
            passed=sum(r['passed'] for r in rows if r['version'] == v), total=4) for v in ('v2','v3','v4')},
        cases=rows)
    write_json(args.out / 'summary.json', summary)
    print(json.dumps(summary['versions'], ensure_ascii=False))


if __name__ == '__main__':
    main()
