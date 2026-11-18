"""One durable Service retry grant, retaining the original full-run failure."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import time

spec=importlib.util.spec_from_file_location('full_run',Path(__file__).with_name('run.py'))
run=importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('out',type=Path)
    args=parser.parse_args()
    out=args.out
    prior=read(out/'result.json')
    assert prior['status']=='partial' and prior.get('recovery')
    archive=out/'first-attempt'
    archive.mkdir(exist_ok=False)
    for name in ('result.json','summary.json','requirements.json','tasks.json','minutes.md',
                 'collected-issues.json','state.sqlite'):
        shutil.copy2(out/name,archive/name)
    settings=read(out/'inference.json')
    ex=run.Extractor(run.ROOT.parent.parent/'meeting-agent/.env',out/'model','context-v5',
                     inference_config=settings,review_decisions=True)
    assert ex.config==read(out/'config.json'), 'Recovery must use the same production configuration'
    before=set((out/'model').rglob('meta.json'))
    started=time.perf_counter()
    store=run.Store(out/'state.sqlite')
    try:
        svc=run.Service(store,ex)
        result=svc.retry_extraction(prior['source_id'],run.ACTOR,'full-v19-technical-recovery-1',run.AT)
        sid=result['source_id']
        run.write(out/'result.json',result)
        minutes=svc.minutes(sid,run.ACTOR)
        requirements=svc.requirements(sid,run.ACTOR)
        (out/'minutes.md').write_text(minutes,encoding='utf8')
        run.write(out/'requirements.json',requirements)
        run.write(out/'tasks.json',store.tasks())
        run.write(out/'collected-issues.json',svc.collected_issues(sid,run.ACTOR))
        count=len(list((out/'model').rglob('meta.json')))
        assert svc.retry_extraction(sid,run.ACTOR,'full-v19-technical-recovery-1',run.AT)==result
        if result['status']=='processed':
            assert svc.process(read(out/'input.json'),run.ACTOR,run.AT)==result
        assert count==len(list((out/'model').rglob('meta.json')))
    finally:
        store.close()
    store=run.Store(out/'state.sqlite')
    try:
        svc=run.Service(store)
        assert svc.result(sid)==result and svc.minutes(sid,run.ACTOR)==minutes
        assert svc.requirements(sid,run.ACTOR)==requirements
    finally:
        store.close()
    paths=list((out/'model').rglob('meta.json'))
    meta=[read(p) for p in paths]
    seconds=round(time.perf_counter()-started,2)
    first=read(archive/'summary.json')
    extraction=result['extraction']
    summary=dict(status=result['status'],initial_status=prior['status'],
        seconds=round(first['seconds']+seconds,2),recovery_seconds=seconds,
        calls=len(meta),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in meta),
        recovery_calls=len(set(paths)-before),
        recovery_stages=[read(p)['stage'] for p in paths if p not in before],
        usage_unknown=sum(bool(m.get('usage_unknown')) for m in meta),
        counts={k:len(extraction.get(k,[])) for k in ('items','facts','unresolved','decisions','updates')},
        errors=extraction.get('_errors',[]),repeat_no_model_calls=True,reopen_consistent=True)
    run.write(out/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
