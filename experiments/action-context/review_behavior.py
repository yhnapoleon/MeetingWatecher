"""Freeze source/output snapshots for independent review of the behavior contract."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest
from scripts.review_action_semantics import read_jsonl
from scripts.run_action_baseline import write_json


def snapshots(out,contract_path):
    inputs=read_jsonl(out/'input.jsonl')
    outputs={c['case_id']:json.loads((out/(c['case_id']+'.json')).read_text(encoding='utf-8'))
             if (out/(c['case_id']+'.json')).exists() else {'status':'failed'} for c in inputs}
    contract=json.loads(contract_path.read_text(encoding='utf-8'))
    selected=[r for r in contract['cases'] if r['case_id'] in outputs]
    if {r['case_id'] for r in selected}!=set(outputs):raise ValueError('Contract case coverage differs')
    return inputs,outputs,selected,dict(inputs=digest(inputs),outputs=digest(outputs),contract=digest(contract))


def export(out,contract_path):
    inputs,outputs,criteria,hashes=snapshots(out,contract_path)
    return dict(version='context-behavior-review-v1',status='draft',reviewer='',hashes=hashes,
        cases=[dict(case_id=c['case_id'],criteria=[dict(**r,passed=None,reason='') for r in c['criteria']]) for c in criteria])


def score(out,contract_path,review):
    inputs,outputs,criteria,hashes=snapshots(out,contract_path)
    if review['hashes']!=hashes:raise ValueError('Behavior review stale; re-review changed output')
    if review['status'] not in ('agent_reviewed','human_reviewed') or not review['reviewer']:raise ValueError('Review incomplete')
    rows={c['case_id']:c for c in review['cases']}
    if len(rows)!=len(review['cases']) or set(rows)!={c['case_id'] for c in criteria}:raise ValueError('Incomplete review cases')
    reports=[]
    for case in criteria:
        actual=rows[case['case_id']]['criteria']
        if len(actual)!=len(case['criteria']):raise ValueError('Incomplete criteria')
        for reference,row in zip(case['criteria'],actual):
            if any(row.get(k)!=v for k,v in reference.items()):raise ValueError('Changed criterion')
            if type(row.get('passed')) is not bool or not isinstance(row.get('reason'),str) or not row['reason'].strip():raise ValueError('Missing independent judgment')
        reports.append(dict(case_id=case['case_id'],passed=sum(r['passed'] for r in actual),total=len(actual),
            all_passed=all(r['passed'] for r in actual),failures=[r for r in actual if not r['passed']],
            execution_status=outputs[case['case_id']].get('status','failed')))
    return dict(version=review['version'],reviewer=review['reviewer'],annotation_status=review['status'],hashes=hashes,
                passed=sum(r['passed'] for r in reports),total=sum(r['total'] for r in reports),
                cases_passed=sum(r['all_passed'] for r in reports),cases_total=len(reports),cases=reports)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--contract',type=Path,required=True)
    p.add_argument('--review',type=Path)
    a=p.parse_args()
    if a.review:
        value=score(a.out,a.contract,json.loads(a.review.read_text(encoding='utf-8')))
        write_json(a.out/'behavior-scores.json',value)
        print(json.dumps(value,ensure_ascii=False,indent=2))
    else:
        path=a.out/'behavior-review.json'
        if path.exists():raise ValueError('Review draft already exists; do not overwrite independent review')
        write_json(path,export(a.out,a.contract))
        print('Exported behavior review draft')


if __name__=='__main__':main()
