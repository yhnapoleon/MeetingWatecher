"""Fresh, recorded context-v3 validation. No automatic model retries."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import sys
import zipfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(Path(__file__).parent)]
from meeting_eval.context_v3 import ContextV3Pipeline,reduce_v3
from meeting_eval.model_client import ModelClient
from scripts.run_action_baseline import write_json
from scripts import replay_mvp
from validate_m2 import positive_meeting,assess
import run as boundary


def read(p):return json.loads(p.read_text(encoding='utf8'))
BASE=ROOT/'runs/2026-11-15-context-v3'
INFERENCE=read(ROOT/'experiments/action-context/compact-check.json')
ENV=ROOT.parent.parent/'meeting-agent/.env'


def snapshot(out):
    with zipfile.ZipFile(out/'source.zip','w',zipfile.ZIP_DEFLATED) as z:
        for d in ('meeting_eval','prompts','tests','scripts','experiments/task-boundary'):
            for p in (ROOT/d).rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts:z.write(p,p.relative_to(ROOT))


def focus_one(name,case,out):
    folder=out/name;folder.mkdir()
    meeting=case['meeting'];history=case['payload']['history']
    write_json(folder/'input.json',dict(meeting=meeting,history=history))
    client=ModelClient(ENV,folder/'model');pipe=ContextV3Pipeline(client,folder,INFERENCE)
    result=pipe.run(meeting,history);write_json(folder/'pipeline.json',result)
    reduced=reduce_v3(result,meeting,history) if not result['errors'] else None
    write_json(folder/'reduced.json',reduced)
    summary=dict(case=name,errors=result['errors'],repair=result['trace'].get('repair',{}).get('status'),
        repair_error=result['trace'].get('repair',{}).get('detail'),
        items=reduced['items'] if reduced else None,reviews=reduced['review_records'] if reduced else None,
        updates=reduced['updates'] if reduced else None,findings=result['coverage_findings'])
    write_json(folder/'summary.json',summary)
    return dict(case=name,errors=result['errors'],items=len(reduced['items']) if reduced else None,
        reviews=len(reduced['review_records']) if reduced else None,repair=summary['repair'],repair_error=summary['repair_error'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--name',required=True);p.add_argument('--suite',choices=['focus','cross','positive','full','pairs'],required=True);p.add_argument('--only',nargs='*');p.add_argument('--workers',type=int,default=4);p.add_argument('--recover-from');args=p.parse_args()
    if Path(args.name).name!=args.name:raise ValueError('Name must be one directory component')
    if args.recover_from and (Path(args.recover_from).name!=args.recover_from or args.suite not in ('full','pairs')):raise ValueError('Recovery needs a full/pairs source directory name')
    out=BASE/args.name;out.mkdir(exist_ok=False);snapshot(out)
    write_json(out/'plan.json',dict(strategy='context-v3',suite=args.suite,inference=INFERENCE,first_attempt=not bool(args.recover_from),recover_from=args.recover_from,
        expected='M2 no scope work/review/finding; positive preserves accepted config work; C20 only video; P07b accepted work; guards preserve true reference, explicit manuscript, same-segment delivery',retries=0))
    if args.suite=='focus':
        cases=read(ROOT/'runs/2026-11-15-m2-repair-study/check-contract/inputs.json')
        for group,cid in [('corpus','C19'),('corpus','C23'),('updates','HT04'),('probes','CP01'),('probes','CP05'),('probes','CP06'),('probes','CP07')]:
            folder=ROOT/'runs/2026-11-15-context-v2/full'/group/cid
            request=next(p.with_name('request.json') for p in folder.rglob('meta.json') if read(p)['stage']=='interpret_work')
            payload=__import__('json').loads(read(request)['messages'][1]['content'])
            cases[cid]=dict(meeting={**payload['meeting'],'source_key':cid},payload=dict(history=payload['history']))
        if args.only:cases={k:v for k,v in cases.items() if k in args.only}
        results=[]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs=[pool.submit(focus_one,n,c,out) for n,c in cases.items()]
            for f in as_completed(jobs):
                v=f.result();results.append(v);print(json.dumps(v,ensure_ascii=False),flush=True)
    elif args.suite in ('full','pairs'):
        jobs=read(ROOT/'runs/2026-11-15-full-validation/manifest.json')['jobs'] if args.suite=='full' else read(Path(__file__).with_name('fixtures.json'))['cases']
        if args.only:jobs=[j for j in jobs if j['id'] in args.only]
        if args.recover_from:jobs=[j for j in jobs if read(BASE/args.recover_from/j['group']/j['id']/'summary.json')['status']=='partial']
        write_json(out/'manifest.json',dict(jobs=jobs,arguments=vars(args)))
        original_extractor=boundary.Extractor
        def extractor(env,folder,strategy,**kwargs):return original_extractor(env,folder,'context-v3',**kwargs)
        results=[]
        with patch.object(boundary,'Extractor',extractor),ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs=[pool.submit(boundary.recover,j,out/j['group']/j['id'],BASE/args.recover_from/j['group']/j['id']) if args.recover_from else
                  pool.submit(boundary.one,j,out/j['group']/j['id'],'b','none') for j in jobs]
            for f in as_completed(jobs):
                row=f.result();results.append(row);write_json(out/'progress.json',results)
                print(json.dumps(dict(case=row['case_id'],status=row['status'],items=len(row['items']),reviews=len(row.get('reviews',[])),errors=row['errors']),ensure_ascii=False),flush=True)
    else:
        original=replay_mvp.read
        if args.suite=='positive':write_json(out/'m2-input.json',positive_meeting())
        def source(path):return positive_meeting() if args.suite=='positive' and path==ROOT/'examples/m2.json' else original(path)
        with patch.object(replay_mvp,'read',source):
            replay_mvp.replay(out,ENV,'context-v3',inference_config=INFERENCE)
        results=assess(out,positive=args.suite=='positive')
        print(json.dumps(results,ensure_ascii=False),flush=True)
    meta=[read(x) for x in out.rglob('meta.json')]
    calls=sum(r['calls'] for r in results) if args.recover_from else len(meta)
    tokens=sum(r['tokens'] for r in results) if args.recover_from else sum((m.get('usage') or {}).get('total_tokens',0) for m in meta)
    write_json(out/'summary.json',dict(results=results,calls=calls,tokens=tokens,recovery_new_usage_only=bool(args.recover_from)))


if __name__=='__main__':main()
