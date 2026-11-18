"""Revalidate source-bound reviews and summarize the prerequisite repair experiments."""
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from summarize import run_summary
from scripts.run_action_baseline import write_json


def main():
    base=ROOT/'runs/2026-11-14-context-prerequisites'
    contract=ROOT/'experiments/action-context/prerequisites-contract.json'
    selected=['boundary-r1','regression-r1','context-r1','regression-final',
              'context-final-r1','context-final-r2','context-final-r3','synthetic-final','contrasts-final',
              'guarded-regression','guarded-context-r1','guarded-context-r2','guarded-context-r3',
              'guarded-synthetic','guarded-contrasts']
    rows={}
    for name in selected:
        rubric=ROOT/'data/context-prerequisites-v1/behavior.json' if 'contrasts' in name else contract
        rows[name]=run_summary(base/name,rubric)
        provenance=base/name/'cache-provenance.json'
        if provenance.exists():
            imported=json.loads(provenance.read_text(encoding='utf-8'))
            reused={r['path'] for r in imported['imported']}
            fresh=[json.loads(p.read_text(encoding='utf-8')) for p in (base/name/'model').rglob('meta.json')
                   if str(p.relative_to(base/name)) not in reused]
            assert all(m['stage']=='check_work' for m in fresh),'Upstream was regenerated; not a checker-only contrast'
            rows[name].update(mode=imported['mode'],new_model_calls=len(fresh),
                new_model_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in fresh),
                new_request_seconds=sum(m['duration_seconds'] for m in fresh))
    contexts=[rows['context-final-r'+str(i)] for i in (1,2,3)]
    replay=json.loads((base/'replay-final/acceptance.json').read_text(encoding='utf-8'))
    first=base/'replay-final/first-pass/acceptance.json'
    first_replay=json.loads(first.read_text(encoding='utf-8')) if first.exists() else replay
    guarded_dir=base/'guarded-replay'
    guarded=json.loads((guarded_dir/'acceptance.json').read_text(encoding='utf-8'))
    guarded_first=json.loads((guarded_dir/'first-pass/acceptance.json').read_text(encoding='utf-8'))
    imported=json.loads((guarded_dir/'cache-provenance.json').read_text(encoding='utf-8'))
    reused={r['path'] for r in imported['imported']}
    fresh=[json.loads(p.read_text(encoding='utf-8')) for p in (guarded_dir/'model').rglob('meta.json')
           if str(p.relative_to(guarded_dir)) not in reused]
    result=dict(annotation_status='agent_reviewed',is_blind=False,runs=rows,
        final_context_mean={k:statistics.mean(r[k] for r in contexts) for k in
            ('content_f1','fully_correct_recall','task_tokens','wall_seconds')},
        replay=dict(passed=sum(replay['checks'].values()),total=len(replay['checks']),
                    first_pass_passed=sum(first_replay['checks'].values())),
        guarded_replay=dict(passed=sum(guarded['checks'].values()),total=len(guarded['checks']),
            first_pass_passed=sum(guarded_first['checks'].values()),
            failed_checks=[k for k,v in guarded['checks'].items() if not v],
            mode='partially_reused_upstream_new_task_guid_regenerated_m2_interpretation',
            new_model_calls=len(fresh),new_stages=[m['stage'] for m in fresh],
            new_model_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in fresh),
            new_request_seconds=sum(m['duration_seconds'] for m in fresh)))
    write_json(base/'comparison-summary.json',result)
    print(json.dumps({k:{f:v for f,v in row.items() if f in ('content_f1','fully_correct_recall',
        'behavior_passed','behavior_total','task_tokens','wall_seconds','first_pass','mode',
        'new_model_calls','new_model_tokens','new_request_seconds')} for k,row in rows.items()},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
