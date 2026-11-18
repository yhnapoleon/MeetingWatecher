"""Fresh full evaluation, isolated databases and no imported response caches."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import csv
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.extract import Extractor
from meeting_eval.inputs import digest
from meeting_eval.service import Service
from meeting_eval.store import Store
from scripts.run_action_baseline import write_json
from scripts.replay_mvp import audit

BASE=ROOT/'runs/2026-11-15-full-validation'


def read(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s.strip()]
def jsonl(p,rs):p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rs),encoding='utf-8')


def prepare():
    BASE.mkdir(exist_ok=False)
    jobs=[]
    split={r['case_id']:r['split'] for r in csv.DictReader((ROOT/'data/mvp-v1/splits.csv').open(encoding='utf-8-sig'))}
    inputs=rows(ROOT/'data/mvp-v1/input.jsonl')
    dev=rows(ROOT/'data/action-semantics-v2/regression/labels.jsonl')
    labels=dev+[{**r,'event_id':r['label_id'],'required_content':[r['description']],
                'annotation_status':'agent_reviewed','reviewer':'inherited-mvp-source-review',
                'uncertainty':r.get('uncertainty',[])} for r in rows(ROOT/'data/mvp-v1/labels.jsonl') if split[r['case_id']]=='holdout']
    audited=copy.deepcopy(labels)
    patch={r['event_id']:r for r in rows(ROOT/'data/action-semantics-v2/pragmatic-audit/labels.jsonl')}
    for i,r in enumerate(audited):
        if r['event_id'] in ('C09.1','C03.2'):audited[i]=patch[r['event_id']]
        elif r['case_id'] in ('C22','C23'):
            r.update(due_text=None,due_date=None,time_text='会后',time_kind='work_window',
                     review_basis='沿用v2时间语义，会后表示开展时段，不是交付期限。')
    for group,rs,labs in [('corpus',inputs,labels),
                         ('context',rows(ROOT/'data/action-semantics-v2/context/input.jsonl'),rows(ROOT/'data/action-semantics-v2/context/labels.jsonl')),
                         ('probes',rows(ROOT/'data/context-probes-v1/input.jsonl'),rows(ROOT/'data/context-probes-v1/labels.jsonl')),
                         ('cancellation',rows(ROOT/'data/context-prerequisites-v1/input.jsonl'),rows(ROOT/'data/context-prerequisites-v1/labels.jsonl'))]:
        folder=BASE/group;folder.mkdir()
        jsonl(folder/'input.jsonl',rs);jsonl(folder/'labels.snapshot.jsonl',labs)
        for r in rs:jobs.append(dict(group=group,id=r['case_id'],meeting=r,actor='evaluator'))
    jsonl(BASE/'corpus/labels.audited.jsonl',audited)
    updates=read(ROOT/'experiments/task-updates/fixtures.json')['cases']+[read(ROOT/'experiments/task-updates/mixed-control.json')['case']]
    (BASE/'updates').mkdir()
    write_json(BASE/'updates/fixtures.json',updates)
    jobs.extend(dict(**c,group='updates',actor='host') for c in updates)
    write_json(BASE/'manifest.json',dict(status='frozen',strategy='context-v1',protocol=6,split=split,
        cases=len(jobs),case_hash=digest(jobs),jobs=jobs,labels_hash=digest(labels),audited_labels_hash=digest(audited),
        trials=1,cache_imports=0,policy='First pass, fixed source/prompt/config. No tuning during run. Retain structural failures.',
        holdout_note='Historical holdout has previously been used; not a new blind set.'))
    with zipfile.ZipFile(BASE/'source.zip','w',zipfile.ZIP_DEFLATED) as z:
        for folder in ['meeting_eval','prompts','tests','scripts','experiments/full-validation']:
            for p in (ROOT/folder).rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts:z.write(p,p.relative_to(ROOT).as_posix())
    return jobs


def one(job):
    out=BASE/job['group']/job['id'];out.mkdir()
    started=time.perf_counter()
    extractor=Extractor(ROOT.parent.parent/'meeting-agent/.env',out/'model','context-v1',
                        inference_config=read(ROOT/'experiments/action-context/compact-check.json'))
    write_json(out/'config.json',extractor.config)
    store=Store(out/'state.sqlite')
    try:
        svc=Service(store,extractor)
        for task in job.get('tasks',[]):svc.sim.seed(task,'2026-11-15T00:00:00+08:00')
        result=svc.process(job['meeting'],job['actor'],'2026-11-16T10:02:00+08:00')
        write_json(out/'result.json',result);write_json(out/'tasks.json',store.tasks())
        audit(store,out/'operations.jsonl')
        (out/'minutes.md').write_text(svc.minutes(result['source_id'],job['actor']),encoding='utf-8')
        trace=result['extraction'].get('_task_trace',{})
        row=dict(group=job['group'],case_id=job['id'],status=result['status'],items=result['extraction']['items'],
            errors=result['extraction'].get('_errors',[]),pending=result['pending'],repair=trace.get('repair',{}).get('status'))
    except Exception as exc:
        row=dict(group=job['group'],case_id=job['id'],status='failed',items=[],errors=[dict(type=type(exc).__name__,message=str(exc))])
        write_json(out/'failure.json',row)
    finally:store.close()
    meta=[read(p) for p in (out/'model').rglob('meta.json')]
    row.update(calls=len(meta),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in meta),
               seconds=round(time.perf_counter()-started,3))
    write_json(out/'summary.json',row)
    return row


def main():
    jobs=prepare();results=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(one,j) for j in jobs]):
            row=f.result();results.append(row)
            write_json(BASE/'progress.json',results)
            print(f"{len(results)}/{len(jobs)} {row['group']} {row['case_id']} {row['status']} items={len(row['items'])} repair={row.get('repair')}",flush=True)
    for group in {j['group'] for j in jobs}:
        jsonl(BASE/group/'predictions.jsonl',sorted([r for r in results if r['group']==group],key=lambda r:r['case_id']))
    write_json(BASE/'run-summary.json',dict(cases=len(results),statuses={s:sum(r['status']==s for r in results) for s in {r['status'] for r in results}},
        calls=sum(r['calls'] for r in results),tokens=sum(r['tokens'] for r in results),results=results))


if __name__=='__main__':main()
