"""Recompute frozen task-update checks and validate recorded reviews/provenance."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest
from scripts.run_action_baseline import write_json
from scripts.review_action_semantics import read_jsonl
from scripts.score_action_semantics import score_semantics
BASE=ROOT/'runs/2026-11-14-task-updates'
EXP=ROOT/'experiments/task-updates'

def read(p):return json.loads(p.read_text(encoding='utf-8'))

def cost(folder):
    provenance=folder/'cache-provenance.json';imported=read(provenance)['imported'] if provenance.exists() else []
    reused={r['path'] for r in imported}
    for row in imported:
        meta=folder/row['path'];assert digest(read(meta.with_name('request.json')))==row['request_hash']
        response=meta.with_name('response.json')
        assert (digest(read(response)) if response.exists() else None)==row['response_hash']
    fresh=[read(p) for p in (folder/'model').rglob('meta.json') if str(p.relative_to(folder)) not in reused]
    return dict(new_calls=len(fresh),new_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in fresh),
                request_seconds=sum(m['duration_seconds'] for m in fresh))

def main():
    fixtures=read(EXP/'fixtures.json');assert digest(fixtures)==read(EXP/'manifest.json')['fixtures_hash']
    mixed=read(EXP/'mixed-control.json');assert digest(mixed['case'])==mixed['case_hash']
    cases=fixtures['cases']+[mixed['case']]
    inspection=read(BASE/'semantic-inspection.json')
    out=dict(annotation_status='agent_inspected',is_blind=False,variants={},regression={},replays={})
    for variant in ('baseline','repaired','final'):
        rows=[]
        for c in cases:
            d=BASE/variant/c['id'];r=read(d/'result.json');checks=read(d/'checks.json');first=read(d/'first-pass/checks.json') if (d/'first-pass/checks.json').exists() else checks
            before=read(d/'tasks-before.json');after=read(d/'tasks-after.json');byid={t['guid']:t for t in after}
            assert checks['checks']['processed']==(r['status']=='processed')
            assert checks['checks']['expected_dates']==all(byid[g].get('due_date')==day for g,day in c['expected']['dates'].items())
            assert checks['checks']['expected_statuses']==all(byid[g]['status']==v for g,v in c['expected']['statuses'].items())
            if variant=='final':
                review=next(x for x in inspection['cases'] if x['case_id']==c['id'])
                assert review['result_hash']==digest(r) and review['tasks_hash']==digest(after)
                assert all(byid[t['guid']]['summary']==t['summary'] and byid[t['guid']]['assignee']==t['assignee'] for t in before)
            rows.append(dict(case_id=c['id'],first_pass=first['passed'],final_pass=checks['passed'],first_errors=first['errors'],**cost(d)))
        out['variants'][variant]=dict(first_pass=sum(x['first_pass'] for x in rows),final_pass=sum(x['final_pass'] for x in rows),total=len(rows),rows=rows,
            **{k:sum(x[k] for x in rows) for k in ('new_calls','new_tokens','request_seconds')})
    for name in ('regression','context'):
        d=BASE/name;s=score_semantics(read_jsonl(d/'predictions.jsonl'),read_jsonl(d/'labels.snapshot.jsonl'),read(d/'semantic-review.completed.json'))
        out['regression'][name]=dict(content=s['content'],fully_correct=s['fully_correct'],missed_content=s['missed_content'],errors=s['errors'],**cost(d))
    for name in ('replay-r1','replay-final'):
        d=BASE/name;r=read(d/'acceptance.json')
        out['replays'][name]=dict(passed=sum(r['checks'].values()),total=len(r['checks']),
            first_pass='failed_before_acceptance_M1_check_JSON' if (d/'first-pass/failure.json').exists() else 'passed',**cost(d))
    out['limitations']=['final reuses all model calls from repaired, not a new independent model trial',
        'initial repaired HT06 structural failure recovered once; TU11 semantics not resampled',
        'regression still misses marketing/requirement purpose and over-interprets suggestion',
        'original task summary can contain historical dates; only structured date fields updated',
        'multiple conflicting final events for one task remain an unresolved contract edge case']
    write_json(BASE/'summary.json',out)
    print(json.dumps({**out,'variants':{k:{a:b for a,b in v.items() if a!='rows'} for k,v in out['variants'].items()}},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
