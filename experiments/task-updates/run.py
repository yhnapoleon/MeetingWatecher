"""Isolated prompt contrast through the real Extractor, ContextPipeline and Service."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import shutil
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
if '--variant' in sys.argv and sys.argv[sys.argv.index('--variant')+1]=='baseline':
    sys.path.insert(0,str(ROOT/'runs/2026-11-14-task-updates/baseline-code'))
from meeting_eval.extract import Extractor
from meeting_eval.inputs import digest
from meeting_eval.service import Service
from meeting_eval.store import Store
from scripts.run_action_baseline import write_json

BASE=ROOT/'runs/2026-11-14-task-updates'
EXP=ROOT/'experiments/task-updates'

def read(path):return json.loads(path.read_text(encoding='utf-8'))

def seed_raw(source,target,stages,latest=False):
    imported=[]
    for meta in source.glob('*/meta.json'):
        base_folder=meta.parent.name
        if latest:
            retries=sorted(meta.parent.glob('retry-*/meta.json'))
            if retries:meta=retries[-1]
        row=read(meta)
        if row['stage'] not in stages:continue
        dest=target/base_folder;dest.mkdir(parents=True,exist_ok=True)
        for name in ('request.json','response.json','meta.json'):
            p=meta.with_name(name)
            if p.exists():shutil.copy2(p,dest/name)
        imported.append(dict(path=str((dest/'meta.json').relative_to(target.parent)),
            source=str(meta.relative_to(ROOT)),request_hash=digest(read(meta.with_name('request.json'))),
            response_hash=digest(read(meta.with_name('response.json'))) if meta.with_name('response.json').exists() else None))
    return imported

def one(case,variant,recover=False):
    out=BASE/variant/case['id']
    if recover:
        previous=read(out/'result.json')
        if previous['status']!='partial':raise ValueError('Only recover a structural failure')
        saved=out/'first-pass';saved.mkdir(exist_ok=False)
        for p in out.iterdir():
            if p.is_file() and p.suffix in ('.json','.md'):shutil.copy2(p,saved/p.name)
        imported=read(out/'cache-provenance.json')['imported']
    else:
        out.mkdir(parents=True,exist_ok=False)
        (out/'model').mkdir()
        imported=[]
    model=out/'model'
    if not recover and variant=='baseline':
        source=ROOT/'runs/2026-11-14-history-time/baseline'/case['id']/'model'
        if source.exists():imported=seed_raw(source,model,{'track_context','interpret_work','check_work','facts','decisions'})
    elif not recover and variant=='final':
        imported=seed_raw(BASE/'repaired'/case['id']/'model',model,{'track_context','interpret_work','check_work','facts','decisions'},latest=True)
    elif not recover and variant=='repaired':
        imported=seed_raw(BASE/'baseline'/case['id']/'model',model,{'track_context','facts','decisions'})
    write_json(out/'cache-provenance.json',dict(imported=imported,mode='paired_prompt_contrast'))
    extractor=Extractor(ROOT.parent.parent/'meeting-agent/.env',model,'context-v1',
                        inference_config=read(ROOT/'experiments/action-context/compact-check.json'))
    write_json(out/'config.json',extractor.config)
    store=Store(out/'state.sqlite');svc=Service(store,extractor);start=time.perf_counter()
    try:
        for t in case['tasks']:svc.sim.seed(t,'2026-11-15T10:00:00+08:00')
        before=store.tasks()
        result=svc.process(case['meeting'],'host','2026-11-16T10:02:00+08:00')
        after=store.tasks()
        write_json(out/'result.json',result)
        write_json(out/'tasks-before.json',before);write_json(out/'tasks-after.json',after)
        write_json(out/'operations.json',[dict(kind=r['kind'],body=json.loads(r['body'])) for r in store.db.execute('SELECT * FROM audit ORDER BY seq')])
        (out/'minutes.md').write_text(svc.minutes(result['source_id'],'host'),encoding='utf-8')
        expected=case['expected'];byid={t['guid']:t for t in after};oldids={t['guid'] for t in before}
        new=[t for t in after if t['guid'] not in oldids]
        checks=dict(processed=result['status']=='processed',
            expected_statuses=all(byid[g]['status']==s for g,s in expected['statuses'].items()),
            expected_dates=all(byid[g].get('due_date')==d for g,d in expected['dates'].items()),
            no_unnecessary_review=not result['extraction'].get('_task_trace',{}).get('review_records') if expected['no_review'] else True,
            expected_review_type=any(r['category']==expected['review_type'] and (r['question'] is None if expected['review_type']=='execution_blocked' else bool(r['question'])) for r in result['extraction'].get('_task_trace',{}).get('review_records',[])) if expected.get('review_type') else True,
            expected_new_task_count=len(new)==expected['new_tasks'],
            new_deadline=all(t.get('due_date')==expected['new_due'] for t in new) if expected.get('new_due') else True,
            required_pending=bool(result['pending'] or result['extraction'].get('unresolved') or result['extraction'].get('_task_trace',{}).get('review_records')) if expected['pending'] else True)
        reused={i['path'] for i in imported}
        fresh=[read(p) for p in model.rglob('meta.json') if str(p.relative_to(out)) not in reused]
        summary=dict(case_id=case['id'],variant=variant,checks=checks,passed=all(checks.values()),
            errors=result['extraction'].get('_errors',[]),wall_seconds=round(time.perf_counter()-start,3),
            new_stages=[m['stage'] for m in fresh],new_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in fresh),
            new_request_seconds=sum(m['duration_seconds'] for m in fresh))
        write_json(out/'checks.json',summary)
        return summary
    finally:store.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--variant',choices=['baseline','repaired','final'],required=True)
    p.add_argument('--mixed',action='store_true')
    p.add_argument('--recover-case',help='One structural recovery only; preserve first-pass artifacts')
    a=p.parse_args();fixtures=read(EXP/'fixtures.json');manifest=read(EXP/'manifest.json')
    assert digest(fixtures)==manifest['fixtures_hash']
    if a.mixed:
        mixed=read(EXP/'mixed-control.json');assert digest(mixed['case'])==mixed['case_hash']
        fixtures={'cases':[mixed['case']]}
    if a.recover_case:
        case=next(c for c in fixtures['cases'] if c['id']==a.recover_case)
        print(json.dumps(one(case,a.variant,True),ensure_ascii=False),flush=True)
        return
    results=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(one,c,a.variant):c['id'] for c in fixtures['cases']}
        for f in as_completed(futures):
            r=f.result();results.append(r)
            print(json.dumps(r,ensure_ascii=False),flush=True)
    write_json(BASE/a.variant/('mixed-summary.json' if a.mixed else 'summary.json'),dict(results=sorted(results,key=lambda r:r['case_id']),
        passed=sum(r['passed'] for r in results),total=len(results),is_blind=False,
        note='mechanical checks require semantic inspection; frozen shared upstream is not a new independent round'))

if __name__=='__main__':main()
