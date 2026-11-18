"""Verify a completed one-round audit and aggregate explicit source judgments.

No model calls and no inference of semantic verdicts.
"""
import argparse
from collections import Counter
import hashlib
from pathlib import Path
import statistics

from run_full_context_v5 import ROOT, read, digest, write_json
from run_system_validation import accounting


def finalize(folder, production_hashes):
    manifest = read(folder / 'manifest.json')
    assert manifest['rounds'] == 1
    assert digest(manifest) == read(folder / 'freeze.json')['manifest_hash']
    assert digest(manifest['review_policy']) == manifest['review_policy_hash']
    jobs = {j['group'] + '/' + j['id']: j for j in manifest['jobs']}
    expected = set(jobs) | {'chains/' + c for c in manifest['chains']}
    summary = read(folder / 'summary.json')
    rows = {r['group'] + '/' + r['case_id']: r for r in summary['rows']}
    audit = read(folder / 'source-review.json')
    cases = audit['cases']
    assert len(summary['rows']) == len(rows) == len(expected)
    assert set(cases) == set(rows) == expected, (expected - set(cases), set(cases) - expected)
    for key, entry in cases.items():
        base = folder / 'r1' / key
        for name, value in entry['evidence_hashes'].items():
            assert digest(read(base / name)) == value, (key, name)
        if key in jobs:
            assert entry['input_hash'] == digest(jobs[key]), key
        results = [read(base / name) for name in entry['evidence_hashes'] if name.endswith('result.json')]
        complete = bool(results) and all(r.get('status') == 'processed' and not r.get('extraction', {}).get('_errors') for r in results)
        if key.startswith('chains/'):
            complete = complete and len(results) == 2 and not (base / 'error.json').exists()
            assert entry['input_hash'] == digest([read(ROOT / 'examples/m1.json'), read(base / 'm2-input.json') if (base / 'm2-input.json').exists() else None]), key
        assert entry['technical_complete'] == complete, key
        assert entry['verdict'] != 'pass' or complete, key
    hashes = read(production_hashes)
    changed = [name for name, value in hashes.items() if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != value]
    assert not changed, changed

    def metrics(keys):
        total = len(keys)
        complete = sum(cases[k]['technical_complete'] for k in keys)
        passed = sum(cases[k]['verdict'] == 'pass' for k in keys)
        return dict(total=total, technically_complete=complete, semantic_pass=passed,
                    semantic_fail=sum(cases[k]['verdict'] == 'semantic_fail' for k in keys),
                    incomplete=sum(cases[k]['verdict'] == 'incomplete' for k in keys),
                    automatic_pass=sum(rows[k]['passed'] for k in keys),
                    technical_completion_rate=complete / total,
                    semantic_correctness_given_completion=passed / complete if complete else None,
                    end_to_end_rate=passed / total)

    semantic = [k for k in cases if k.startswith('semantic/')]
    unresolved = dict(required=0, retained=0, extra=0)
    for key in semantic:
        entry = cases[key]
        label = next(c for c in manifest['semantic_labels']['cases'] if c['case_id'] == key.split('/')[1])
        assert entry['unresolved_required'] == len(label['expected']['required_unresolved']), key
        assert 0 <= entry['unresolved_retained'] <= entry['unresolved_required'], key
        assert entry['unresolved_extra'] >= 0, key
        for name in unresolved:
            unresolved[name] += entry['unresolved_' + name]
    unresolved['missing'] = unresolved['required'] - unresolved['retained']
    unresolved['recall'] = unresolved['retained'] / unresolved['required'] if unresolved['required'] else None
    times = sorted(r['seconds'] for r in rows.values() if 'seconds' in r)
    usage = accounting(folder)
    assert all(summary[k] == v for k, v in usage.items()), 'usage changed after run'
    result = dict(
        version='current-baseline-2026-11-17', reviewer=audit['reviewer'],
        manifest_hash=digest(manifest), review_policy_hash=manifest['review_policy_hash'],
        source_review_hash=digest(cases), production_files_checked=len(hashes), production_unchanged=True,
        overall=metrics(list(cases)), core95=metrics([k for k in cases if not k.startswith('semantic/')]),
        semantic20=metrics(semantic),
        groups={g: metrics([k for k in cases if k.startswith(g + '/')]) for g in sorted({k.split('/')[0] for k in cases})},
        unresolved_semantic20=unresolved, usage=usage,
        timing=dict(wall_seconds=summary['seconds'], scenario_median_seconds=statistics.median(times),
                    scenario_p95_seconds=times[min(len(times)-1, int((len(times)-1)*.95+.999999))],
                    scenario_max_seconds=max(times), measured_scenarios=len(times)),
        automatic_false_passes=[k for k in sorted(cases) if rows[k]['passed'] and cases[k]['verdict'] != 'pass'],
        semantic_pass_despite_automatic_failure=[k for k in sorted(cases) if not rows[k]['passed'] and cases[k]['verdict'] == 'pass'],
        failures={k: {f: v for f, v in e.items() if f not in ('evidence_hashes', 'input_hash')} for k, e in cases.items() if e['verdict'] != 'pass'},
        issue_counts=dict(Counter(issue for e in cases.values() for issue in e.get('issues', []))))
    write_json(folder / 'audited-summary.json', result)
    audit['status'] = 'complete'
    audit['completed_cases'] = len(cases)
    write_json(folder / 'source-review.json', audit)
    lines = ['# 115例逐例原文审计', '', '评分规则在预测前冻结。助手逐例对照原文、标签、完整业务输出及实际任务状态；不是独立人工盲评。', '',
             '| 场景 | 技术完成 | 原文审计 | 依据 |', '|---|---|---|---|']
    for key in sorted(cases):
        e = cases[key]
        reason = e['reason'].replace('|', '\\|').replace('\n', ' ')
        lines.append(f"| {key} | {'是' if e['technical_complete'] else '否'} | {e['verdict']} | {reason} |")
    (folder / 'source-review.md').write_text('\n'.join(lines) + '\n', encoding='utf8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--production-hashes', type=Path, required=True)
    args = parser.parse_args()
    result = finalize(args.out, args.production_hashes)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
