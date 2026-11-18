"""Isolated, recorded boundary experiments through the normal Service entry point."""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys
import time
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.extract import Extractor
from meeting_eval.inputs import digest
from meeting_eval.service import Service
from meeting_eval.store import Store
from scripts.run_action_baseline import write_json
from scripts.replay_mvp import audit

BASE = ROOT/'runs/2026-11-15-task-boundary'
OLD = ROOT/'runs/2026-11-15-full-validation'
FOCUS = {'C01','C02','C03','C04','C05','C06','C07','C09','C11','C17',
         'C19','C20','C21','C22','C23','C24','C26','C29','C30','M2'}


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def configure(extractor, variant, frozen, mode):
    pipe = extractor.task_pipeline
    if variant in ('a','check-only','interpret-only'):
        if variant == 'a':
            # Same semantics and reducer; A uses the existing non-action container.
            def prompt_only(text):
                text = text.replace('- entity_only：纯实体提及，无后续工作线索；只保存，不强行提问。\n', '')
                text = text.replace('- context_only：有用的决定', '- context_only：纯实体提及或有用的决定')
                text = text.replace('entity_only=纯提及无工作线索；context_only=', 'context_only=纯提及无工作线索，或')
                text = text.replace('entity_only/context_only', 'context_only')
                return text.replace('context_only', 'entity_only')
            pipe.prompts = {k:prompt_only(v) for k,v in pipe.prompts.items()}
        else:
            with zipfile.ZipFile(BASE/'before.zip') as archive:
                untouched = ['interpret_work','repair_work'] if variant=='check-only' else ['check_work','check_repair']
                for stage in untouched:
                    source = 'interpret-work' if stage in ('interpret_work','repair_work') else 'check-work'
                    pipe.prompts[stage] = archive.read('prompts/'+source+'-context-v1.txt').decode('utf-8')
    if mode=='interpretation' or variant in ('check-only','interpret-only'):
        pipe.repair_enabled = False
    pipe.config.update(repair_enabled=pipe.repair_enabled,experiment_variant=variant,
                       experiment_freeze=mode,prompts={k:digest(v) for k,v in pipe.prompts.items()})
    if mode != 'none':
        if frozen is None:raise ValueError('Frozen experiment needs a source trace')
        trace = frozen['_task_trace']
        initial = trace.get('repair',{}).get('before',trace)
        stage_call = pipe._stage
        def stage(name,payload,validate,folder,resume):
            if name=='track_context':
                end=payload['meeting']['segments'][-1]['id']
                ledger=next(x['ledger'] for x in trace['checkpoints'] if x['through_segment']==end)
                return validate(copy.deepcopy(ledger))
            if name=='interpret_work' and mode=='interpretation':
                return validate(copy.deepcopy(dict(records=initial['records'],events=initial['events'])))
            return stage_call(name,payload,validate,folder,resume)
        pipe._stage=stage
        original_stage=extractor.stage
        def other_stage(name,payload,fresh=False):
            if name=='facts':return {k:copy.deepcopy(frozen[k]) for k in ('facts','unresolved')}
            if name=='decisions':return dict(decisions=copy.deepcopy(frozen['decisions']))
            return original_stage(name,payload,fresh)
        extractor.stage=other_stage


def one(job, out, variant, mode, strategy='context-v1', inference_config=None):
    out.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter()
    frozen_path=OLD/job['group']/job['id']/'result.json'
    frozen=read(frozen_path)['extraction'] if mode!='none' else None
    extractor=Extractor(ROOT.parent.parent/'meeting-agent/.env',out/'model',strategy,
                        inference_config=read(ROOT/'experiments/action-context/compact-check.json') if inference_config is None else inference_config)
    configure(extractor,variant,frozen,mode)
    write_json(out/'config.json',extractor.config)
    write_json(out/'input.json',dict(meeting=job['meeting'],actor=job.get('actor','evaluator'),tasks=job.get('tasks',[])))
    for key,value in extractor.task_pipeline.prompts.items():
        (out/(key+'.txt')).write_text(value,encoding='utf-8')
    if frozen is not None:
        write_json(out/'frozen-source.json',dict(path=frozen_path.relative_to(ROOT).as_posix(),
                   hash=digest(read(frozen_path)),mode=mode))
    store=Store(out/'state.sqlite')
    try:
        svc=Service(store,extractor)
        for task in job.get('tasks',[]):svc.sim.seed(task,'2026-11-15T00:00:00+08:00')
        result=svc.process(job['meeting'],job.get('actor','evaluator'),'2026-11-16T10:02:00+08:00')
        write_json(out/'result.json',result)
        write_json(out/'tasks.json',store.tasks())
        audit(store,out/'operations.jsonl')
        (out/'minutes.md').write_text(svc.minutes(result['source_id'],job.get('actor','evaluator')),encoding='utf-8')
        extraction=result['extraction'];trace=extraction.get('_task_trace',{})
        row=dict(group=job['group'],case_id=job['id'],status=result['status'],items=extraction['items'],
                 errors=extraction.get('_errors',[]),reviews=trace.get('review_records',[]),
                 contexts=trace.get('context_records',[]),repair=trace.get('repair',{}).get('status'))
    except Exception as exc:
        row=dict(group=job['group'],case_id=job['id'],status='failed',items=[],
                 errors=[dict(error=type(exc).__name__,detail=str(exc)[:500])])
        write_json(out/'failure.json',row)
    finally:store.close()
    meta=[read(p) for p in (out/'model').rglob('meta.json')]
    row.update(calls=len(meta),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in meta),
               seconds=round(time.perf_counter()-started,3))
    write_json(out/'summary.json',row)
    return row


def snapshot(out):
    with zipfile.ZipFile(out/'source.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for folder in ('meeting_eval','prompts','tests','experiments/task-boundary'):
            for path in (ROOT/folder).rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts:
                    archive.write(path,path.relative_to(ROOT).as_posix())


def recover(job,out,source,strategy='context-v1'):
    """One retry on a copy, preserving first-pass results and call accounting."""
    shutil.copytree(source,out)
    original=read(source/'summary.json')
    before={p.relative_to(out).as_posix() for p in (out/'model').rglob('meta.json')}
    ex=Extractor(ROOT.parent.parent/'meeting-agent/.env',out/'model',strategy,
                 inference_config=read(ROOT/'experiments/action-context/compact-check.json'))
    configure(ex,'b',None,'none')
    assert ex.config==read(source/'config.json'),'Recovery must use identical configuration'
    store=Store(out/'state.sqlite')
    try:
        svc=Service(store,ex)
        result=svc.process(job['meeting'],job.get('actor','evaluator'),'2026-11-16T10:02:00+08:00')
        write_json(out/'result.json',result)
        write_json(out/'tasks.json',store.tasks())
        audit(store,out/'operations.jsonl')
        (out/'minutes.md').write_text(svc.minutes(result['source_id'],job.get('actor','evaluator')),encoding='utf-8')
        trace=result['extraction'].get('_task_trace',{})
        meta=[read(p) for p in (out/'model').rglob('meta.json') if p.relative_to(out).as_posix() not in before]
        row=dict(group=job['group'],case_id=job['id'],status=result['status'],items=result['extraction']['items'],
                 errors=result['extraction'].get('_errors',[]),reviews=trace.get('review_records',[]),
                 contexts=trace.get('context_records',[]),repair=trace.get('repair',{}).get('status'),
                 calls=len(meta),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in meta),
                 first_pass=original,source=source.relative_to(ROOT).as_posix())
        write_json(out/'summary.json',row)
        return row
    finally:store.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--name',required=True)
    parser.add_argument('--variant',choices=['a','b','check-only','interpret-only','c1'],default='b')
    parser.add_argument('--mode',choices=['none','ledger','interpretation'],default='none')
    parser.add_argument('--suite',choices=['focus','pairs','full','cross'],default='focus')
    parser.add_argument('--only',nargs='*')
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--recover-from')
    args=parser.parse_args()
    if args.suite=='cross':
        import scripts.replay_mvp as cross
        if args.variant=='c1':
            class WithDecisionHistory(Extractor):
                def evidence_extract(self,meeting,context,retry_fields,resume=False):
                    original=self.task_pipeline.run
                    def with_history(meeting,history,**kwargs):
                        return original(meeting,{**history,'decisions':copy.deepcopy(context['decisions'])},**kwargs)
                    self.task_pipeline.run=with_history
                    try:return super().evidence_extract(meeting,context,retry_fields,resume)
                    finally:self.task_pipeline.run=original
            cross.Extractor=WithDecisionHistory
        out=BASE/args.name
        out.mkdir(exist_ok=False)
        snapshot(out)
        write_json(out/'manifest.json',dict(arguments=vars(args),policy='Only Service-authorized historical decisions added; same prompts.'))
        report=cross.replay(out,ROOT.parent.parent/'meeting-agent/.env','context-v1',
                      inference_config=read(ROOT/'experiments/action-context/compact-check.json'))
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return
    if args.variant=='c1':raise ValueError('Decision-history arm requires the cross-meeting suite')
    jobs=read(OLD/'manifest.json')['jobs'] if args.suite!='pairs' else read(Path(__file__).with_name('fixtures.json'))['cases']
    if args.suite=='focus':jobs=[j for j in jobs if j['id'] in FOCUS and j['group'] in ('corpus','updates')]
    if args.only:jobs=[j for j in jobs if j['id'] in args.only]
    if not jobs:raise ValueError('Empty experiment')
    if args.recover_from:
        jobs=[j for j in jobs if read(BASE/args.recover_from/j['group']/j['id']/'summary.json')['status']=='partial']
        if not jobs:raise ValueError('No partial cases to recover')
    out=BASE/args.name
    out.mkdir(exist_ok=False)
    snapshot(out)
    write_json(out/'manifest.json',dict(arguments=vars(args),jobs=jobs,jobs_hash=digest(jobs),
        policy='First responses only. Frozen stages explicitly recorded; labels are never model inputs.'))
    rows=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(recover,j,out/j['group']/j['id'],BASE/args.recover_from/j['group']/j['id'])
                 if args.recover_from else pool.submit(one,j,out/j['group']/j['id'],args.variant,args.mode) for j in jobs]
        for f in as_completed(futures):
            row=f.result();rows.append(row)
            write_json(out/'progress.json',rows)
            print(f"{len(rows)}/{len(jobs)} {row['group']}/{row['case_id']} {row['status']} items={len(row['items'])} cards={len(row.get('reviews',[]))} calls={row['calls']}",flush=True)
    write_json(out/'summary.json',dict(cases=len(rows),calls=sum(r['calls'] for r in rows),
        tokens=sum(r['tokens'] for r in rows),results=rows))


if __name__=='__main__':main()
