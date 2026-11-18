"""One frozen pass over 60 new cases, using the unchanged Service entry."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from validate import DATA,read,sha,validate,input_job
sys.path.insert(0,str(ROOT/'experiments/task-boundary'))
from run_full_context_v5 import one
from run_context_v3 import snapshot
from run_system_validation import accounting
from scripts.run_action_baseline import write_json,credentials

def verify_frozen(record,root=ROOT,model_identity=None):
    for rel,expected in record['files'].items():assert sha(root/rel)==expected,('Frozen artifact changed',rel)
    if model_identity is not None:assert record['model_identity']==model_identity,'Model identity changed'

def finalize_row(row,folder):
    return {**row,**accounting(folder)}

def freeze():
    validation=validate()
    files=[DATA/name for name in ('natural-inputs.json','control-inputs.json','labels.json','annotation-guide.md','provenance.json','annotation-review.json','sources-and-rights.md')]
    files += sorted((ROOT/'meeting_eval').glob('*.py'))+sorted((ROOT/'prompts').glob('*.txt'))
    files += [ROOT/'experiments/action-context/compact-check.json']
    files += sorted(Path(__file__).parent.glob('*.py'))
    files += sorted((ROOT/'scripts').glob('*.py'))
    files += sorted((ROOT/'experiments/task-boundary').glob('*.py'))
    _,model,endpoint=credentials(ROOT.parent.parent/'meeting-agent/.env')
    record=dict(created_at=datetime.now(timezone.utc).isoformat(),validation=validation,
        files={p.relative_to(ROOT).as_posix():sha(p) for p in files},
        model_identity=dict(model=model,endpoint=endpoint),
        policy='Frozen before Service predictions. One pass, built-in node recovery only; no case reruns. Labels never passed to Service.')
    path=DATA/'freeze.json'
    if path.exists():
        old=read(path);verify_frozen(old,model_identity=record['model_identity']);assert old['files']==record['files'],'Freeze file list changed';return old
    write_json(path,record);return record

def main():
    p=argparse.ArgumentParser();p.add_argument('--freeze-only',action='store_true');p.add_argument('--out',type=Path,default=ROOT/'runs/2026-11-17-generalization-v1');p.add_argument('--workers',type=int,default=4);args=p.parse_args()
    frozen=freeze()
    if args.freeze_only:print(json.dumps(frozen['validation']));return
    args.out.mkdir(parents=True,exist_ok=False)
    cases=read(DATA/'natural-inputs.json')+read(DATA/'control-inputs.json')
    jobs=[input_job(c) for c in cases if c['split']=='test'];assert len(jobs)==60
    config=read(ROOT/'experiments/action-context/compact-check.json')
    write_json(args.out/'manifest.json',dict(jobs=jobs,strategy='context-v5',inference=config,freeze=frozen,rounds=1,case_reruns=0))
    snapshot(args.out)
    with zipfile.ZipFile(args.out/'source.zip','a',zipfile.ZIP_DEFLATED) as z:
        for rel in frozen['files']:
            if rel.startswith(('experiments/generalization-v1/','data/generalization-v1/')):z.write(ROOT/rel,rel)
        z.write(DATA/'freeze.json','data/generalization-v1/freeze.json')
    rows=[];started=time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(one,j,args.out/j['group']/j['id'],{},config):j for j in jobs}
        for future in as_completed(futures):
            job=futures[future]
            try:row=future.result()
            except Exception as exc:row=dict(group=job['group'],case_id=job['id'],status='runner_failed',error=str(exc)[:800],passed=False,calls=0,tokens=0,seconds=0)
            row=finalize_row(row,args.out/job['group']/job['id'])
            rows.append(row);write_json(args.out/'progress.json',rows)
            print(f'{len(rows)}/60 {row["case_id"]} {row["status"]} calls={row["calls"]} tokens={row["tokens"]}',flush=True)
    write_json(args.out/'summary.json',dict(cases=len(rows),rows=rows,**accounting(args.out),seconds=round(time.perf_counter()-started,3),task_review='pending'))
    print('60 cases completed; task matching remains required.',flush=True)

if __name__=='__main__':main()
