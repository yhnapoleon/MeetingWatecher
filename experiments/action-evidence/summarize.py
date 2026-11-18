"""Recompute saved, source-reviewed results and costs. No model calls."""
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest,normalize
from meeting_eval.task_events import reduce_task_events
from scripts.review_action_semantics import read_jsonl,export_review
from scripts.score_action_semantics import score_semantics


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def costs(folder):
    meta=[read(f) for f in (folder/'model').rglob('meta.json')]
    task=[m for m in meta if m['stage'] in ('actions','locate_work','interpret_work','check_work')]
    return dict(all_calls=len(meta),task_calls=len(task),
        all_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in meta),
        task_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in task),
        task_request_seconds=round(sum(m['duration_seconds'] for m in task),3))


def main():
    groups={
        'direct':('2026-11-14-evidence-probes','direct-r*'),
        'thinking':('2026-11-14-evidence-probes','thinking-r*'),
        'initial_evidence':('2026-11-14-evidence-probes','evidence-r*'),
        'refined_evidence':('2026-11-14-evidence-refined','evidence-r*'),
        'context_thinking':('2026-11-14-evidence-context','actions-r*'),
        'context_evidence':('2026-11-14-evidence-context','evidence-v1-r*'),
    }
    report={};policy=[]
    for name,(group,pattern) in groups.items():
        rounds=[]
        for folder in sorted((ROOT/'runs'/group).glob(pattern)):
            inputs=read_jsonl(folder/'input.jsonl')
            predictions=read_jsonl(folder/'predictions.jsonl')
            labels=read_jsonl(folder/'semantic-labels.snapshot.jsonl')
            review=read(folder/'semantic-review.completed.json')
            score=score_semantics(predictions,labels,review)
            assert score==read(folder/'semantic-scores.json')
            languages={}
            for lang in sorted({c['language'] for c in inputs}):
                selected=[c for c in inputs if c['language']==lang];ids={c['case_id'] for c in selected}
                subp=[p for p in predictions if p['case_id'] in ids];subl=[g for g in labels if g['case_id'] in ids]
                subr=export_review(selected,subl,subp)
                subr.update(status=review['status'],reviewer=review['reviewer'],cases=[c for c in review['cases'] if c['case_id'] in ids])
                languages[lang]=score_semantics(subp,subl,subr)
            row=dict(run=str(folder.relative_to(ROOT)),score=score,languages=languages,cost=costs(folder),
                     wall_seconds=read(folder/'summary.json')['wall_seconds'])
            if (folder/'precheck-review.json').exists():
                pre=read(folder/'precheck-review.json')
                for case in pre['cases']:
                    trace=read(folder/(case['case_id']+'.json'))['extraction']['_task_trace']
                    assert case['trace_hash']==digest(trace)
                    assert {e['event_id'] for e in trace.get('events',[])}=={j['event_id'] for j in case['judgments']}
                row['precheck']=dict(covered=sum(j['gold_event_id'] is not None and j['content_supported'] and j['content_complete'] for c in pre['cases'] for j in c['judgments']),
                    expected=score['content']['expected'],events=sum(len(c['judgments']) for c in pre['cases']),
                    unsupported=sum(not j['content_supported'] for c in pre['cases'] for j in c['judgments']))
            if 'evidence' in name:
                for src in inputs:
                    result=read(folder/(src['case_id']+'.json'));trace=result['extraction']['_task_trace']
                    if trace.get('errors'):continue
                    reduced=reduce_task_events(trace['checked_events'],trace['uncovered_spans'],normalize(src,'evaluator'),{'tasks':[]})
                    same=all(reduced[k]==result['extraction'][k] for k in ('items','updates'))
                    policy.append(dict(run=row['run'],case_id=src['case_id'],identical_items_updates=same))
                    assert same,'Policy changed saved experimental task results'
            rounds.append(row)
        report[name]=dict(rounds=rounds,mean_content_f1=statistics.mean(r['score']['content']['f1'] for r in rounds),
            mean_fully_correct_recall=statistics.mean(r['score']['fully_correct']['recall'] for r in rounds),
            total_unsupported=sum(r['score']['unsupported_predictions'] for r in rounds),
            total_predictions=sum(r['score']['content']['predicted'] for r in rounds),
            mean_task_tokens=statistics.mean(r['cost']['task_tokens'] for r in rounds),
            mean_wall_seconds=statistics.mean(r['wall_seconds'] for r in rounds))
    report['final_policy_audit']=dict(code_hash=digest((ROOT/'meeting_eval/task_events.py').read_text(encoding='utf-8')),comparisons=policy)
    out=ROOT/'runs/2026-11-14-evidence-implementation/comparison-summary.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:{a:b for a,b in v.items() if a!='rounds'} for k,v in report.items() if k!='final_policy_audit'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
