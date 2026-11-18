"""Run independently recorded repeated trials; no cross-trial response reuse."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))
from scripts.run_meeting_eval import evaluate
from scripts.run_action_baseline import write_json


def aggregate(out):
    results = {}
    for strategy in ('baseline','actions','combined','split','actions-v2','split-v2','split-v3'):
        runs = sorted(out.glob(strategy+'-r*/summary.json'))
        if not runs:
            continue
        values = [json.loads(p.read_text(encoding='utf-8')) for p in runs]
        f1 = [v['action_anchors']['f1'] for v in values if v['action_anchors']]
        results[strategy] = dict(repeats=len(values),f1=f1,
            mean_f1=statistics.mean(f1) if f1 else None,
            precision=[v['action_anchors']['precision'] for v in values if v['action_anchors']],
            recall=[v['action_anchors']['recall'] for v in values if v['action_anchors']],
            mean_tokens=statistics.mean(v['total_tokens'] for v in values),
            mean_case_seconds=statistics.mean(v['wall_seconds']/v['excerpts'] for v in values),
            calls=sum(v['calls'] for v in values),failed=sum(v['excerpts']-v['successful'] for v in values))
    write_json(out/'comparison.json',results)
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--env-file',type=Path,default=ROOT.parent.parent/'meeting-agent/.env')
    p.add_argument('--strategies',nargs='+',default=['baseline','actions','combined','split'])
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--cases',nargs='+')
    args = p.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    jobs = [(s,r) for r in range(1,args.repeats+1) for s in args.strategies]
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(evaluate,args.out/f'{s}-r{r}',args.env_file,s,'dev',args.cases):(s,r) for s,r in jobs}
        for future in as_completed(futures):
            s,r = futures[future]
            result = future.result()
            print(f'FINISHED {s}-r{r}: {result["action_anchors"]}',flush=True)
            aggregate(args.out)
    print(json.dumps(aggregate(args.out),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
