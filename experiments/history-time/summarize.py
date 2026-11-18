"""Verify frozen inputs, model-cache provenance, task state, and source-bound inspection."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest
from scripts.run_action_baseline import write_json
BASE=ROOT/'runs/2026-11-14-history-time'
EXP=ROOT/'experiments/history-time'

def read(p):return json.loads(p.read_text(encoding='utf-8'))

def costs(folder):
    provenance=folder/'cache-provenance.json'
    imported=read(provenance)['imported'] if provenance.exists() else []
    reused={r['path'] for r in imported}
    for row in imported:
        meta=folder/row['path'];request=meta.with_name('request.json');response=meta.with_name('response.json')
        assert digest(read(request))==row['request_hash']
        assert (digest(read(response)) if response.exists() else None)==row['response_hash']
    fresh=[read(p) for p in (folder/'model').rglob('meta.json') if str(p.relative_to(folder)) not in reused]
    return dict(new_calls=len(fresh),new_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in fresh),
                new_request_seconds=sum(m['duration_seconds'] for m in fresh))

def main():
    manifest=read(EXP/'manifest.json');fixtures=read(EXP/'fixtures.json')
    assert digest(fixtures)==manifest['fixtures_hash']
    for name,h in manifest['prompts'].items():assert digest((EXP/(name+'.txt')).read_text(encoding='utf-8'))==h
    review=read(BASE/'semantic-inspection.json');assert review['fixtures_hash']==manifest['fixtures_hash']
    output=dict(annotation_status='agent_inspected',is_blind=False,variants={},replays={})
    for variant in ('baseline','current-time'):
        rows=[]
        for case in fixtures['cases']:
            folder=BASE/variant/case['id'];result=read(folder/'result.json')
            before=read(folder/'tasks-before.json');after=read(folder/'tasks-after.json');checks=read(folder/'checks.json')
            judgment=next(r for r in review['cases'] if r['variant']==variant and r['case_id']==case['id'])
            assert judgment['result_hash']==digest(result) and judgment['tasks_after_hash']==digest(after)
            ids={t['guid'] for t in before};current={t['guid']:t for t in after};new=[t for t in after if t['guid'] not in ids]
            assert checks['checks']['processed']==(result['status']=='processed')
            assert checks['checks']['expected_statuses']==all(current[g]['status']==s for g,s in case['expected']['statuses'].items())
            assert checks['checks']['expected_new_task_count']==(len(new)==case['expected']['new_tasks'])
            assert checks['checks']['historical_dates_preserved']==all(current[t['guid']].get('due_date')==t.get('due_date') and current[t['guid']].get('due_text')==t.get('due_text') for t in before)
            first=read(folder/'first-pass/checks.json') if (folder/'first-pass/checks.json').exists() else checks
            rows.append(dict(case_id=case['id'],first_pass=first['passed'],final_pass=checks['passed'],
                first_errors=first['errors'],final_errors=checks['errors'],inspection=judgment['finding'],**costs(folder)))
        output['variants'][variant]=dict(first_pass=sum(r['first_pass'] for r in rows),
            final_pass=sum(r['final_pass'] for r in rows),total=len(rows),rows=rows,
            **{k:sum(r[k] for r in rows) for k in ('new_calls','new_tokens','new_request_seconds')})
    for folder in sorted(BASE.glob('replay-r*')):
        if not (folder/'acceptance.json').exists():raise ValueError('Replay incomplete: '+str(folder))
        report=read(folder/'acceptance.json')
        output['replays'][folder.name]=dict(passed=sum(report['checks'].values()),total=len(report['checks']),
            failures=[k for k,v in report['checks'].items() if not v],**costs(folder))
    output['limitations']=['Targeted synthetic checks; not a blind quality score',
        'HT06/HT07 current-time each required one structural recovery',
        'HT07 cannot apply a due-date edit; generic confirmation persists in HT07/HT08',
        'Baseline M2 reused the recorded failing response; other pairs share upstream raw calls',
        'Production prompts and default strategy are unchanged']
    write_json(BASE/'summary.json',output)
    print(json.dumps({**output,'variants':{k:{a:b for a,b in v.items() if a!='rows'} for k,v in output['variants'].items()}},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
