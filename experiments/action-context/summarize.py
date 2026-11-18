"""Validate completed reviews and summarize recorded context experiments without model calls."""
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.review_action_semantics import read_jsonl
from scripts.score_action_semantics import score_semantics
from scripts.run_action_baseline import write_json
from review_behavior import score as score_behavior

TASK_STAGES={'actions','locate_work','track_context','interpret_work','check_work'}


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def run_summary(folder,contract,with_cost=True):
    semantic=score_semantics(read_jsonl(folder/'predictions.jsonl'),read_jsonl(folder/'labels.snapshot.jsonl'),read(folder/'semantic-review.completed.json'))
    behavior=score_behavior(folder,contract,read(folder/'behavior-review.completed.json'))
    result=dict(path=str(folder.relative_to(ROOT)),content_f1=semantic['content']['f1'],
        fully_correct_recall=semantic['fully_correct']['recall'],fully_correct_f1=semantic['fully_correct']['f1'],
        predicted=semantic['content']['predicted'],unsupported=semantic['unsupported_predictions'],
        unsafe_create_proposals=semantic['unsafe_create_proposals'],failed_cases=semantic['failed_cases'],
        behavior_passed=behavior['passed'],behavior_total=behavior['total'],
        behavior_cases_passed=behavior['cases_passed'],behavior_cases_total=behavior['cases_total'])
    if with_cost:
        meta=[read(p) for p in (folder/'model').rglob('meta.json')]
        tasks=[m for m in meta if m['stage'] in TASK_STAGES]
        result.update(task_calls=len(tasks),task_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in tasks),
            total_calls=len(meta),total_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in meta),
            wall_seconds=sum(t['seconds'] for t in read(folder/'timings.json')))
    first=folder/'first-pass'
    if with_cost and (first/'semantic-review.completed.json').exists():
        result['first_pass']=run_summary(first,contract,False)
    return result


def main():
    contract=ROOT/'experiments/action-context/behavior-contract.json'
    result=dict(annotation_status='agent_reviewed',is_blind=False,groups={})
    for version,base in [('initial','2026-11-14-context-final'),('final','2026-11-14-context-v3')]:
        for view in ('regression','context'):
            rows=[run_summary(ROOT/'runs'/base/(view+f'-r{n}'),contract) for n in (1,2,3)]
            group=dict(runs=rows,mean={k:statistics.mean(r[k] for r in rows) for k in
                ('content_f1','fully_correct_recall','fully_correct_f1','task_calls','task_tokens','wall_seconds')},
                behavior_passed=sum(r['behavior_passed'] for r in rows),behavior_total=sum(r['behavior_total'] for r in rows),
                unsafe_create_proposals=sum(r['unsafe_create_proposals'] for r in rows))
            result['groups'][version+'_'+view]=group
    result['synthetic']=run_summary(ROOT/'runs/2026-11-14-context-v3/synthetic-r1',ROOT/'data/context-probes-v1/behavior.json')
    replays=[]
    for n in (1,2,3):
        folder=ROOT/f'runs/2026-11-14-context-v3/replay-r{n}'
        report=read(folder/'acceptance.json')
        first=read(folder/'first-pass/acceptance.json') if (folder/'first-pass/acceptance.json').exists() else report
        replays.append(dict(run=n,passed=sum(report['checks'].values()),total=len(report['checks']),
                            first_pass_passed=sum(first['checks'].values()),failures=[k for k,v in report['checks'].items() if not v]))
    result['replays']=replays
    path=ROOT/'runs/2026-11-14-context-implementation/comparison-summary.json'
    write_json(path,result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
