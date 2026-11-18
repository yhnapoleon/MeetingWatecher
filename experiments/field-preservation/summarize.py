"""Validate frozen cases, source-bound reviews and cache provenance; no model calls."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest
from scripts.review_action_semantics import read_jsonl
from scripts.score_action_semantics import score_semantics
from scripts.run_action_baseline import write_json

BASE=ROOT/'runs/2026-11-15-field-preservation'


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def cost(folder):
    provenance=folder/'cache-provenance.json'
    imported=read(provenance)['imported'] if provenance.exists() else []
    for row in imported:
        meta=folder/row['path']
        assert digest(read(meta.with_name('request.json')))==row['request_hash']
        response=meta.with_name('response.json')
        assert (digest(read(response)) if response.exists() else None)==row['response_hash']
    reused={row['path'] for row in imported}
    fresh=[read(p) for p in (folder/'model').rglob('meta.json') if str(p.relative_to(folder)) not in reused]
    return dict(new_calls=len(fresh),new_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in fresh),request_seconds=sum(m['duration_seconds'] for m in fresh))


def main():
    fixtures=read(ROOT/'experiments/field-preservation/fixtures.json')
    assert fixtures['cases_hash']==digest(fixtures['cases'])
    out=dict(is_blind=False,annotation_status='agent_reviewed',probes={},regression={},repair={},cost={})
    for variant in ('baseline','repaired'):
        checks=[];costs=[]
        for case in fixtures['cases']:
            folder=BASE/variant/case['id'];row=read(folder/'checks.json');result=read(folder/'result.json')
            assert row['checks']['processed']==(result['status']=='processed')
            assert row['checks']['created']==(len(read(folder/'tasks.json'))==case['expected']['created'])
            assert row['checks']['items']==(len(result['extraction']['items'])==case['expected']['items'])
            checks.append(row);costs.append(cost(folder))
        out['probes'][variant]=dict(passed=sum(row['passed'] for row in checks),total=len(checks),rows=checks)
        out['cost'][variant]={k:sum(row[k] for row in costs) for k in ('new_calls','new_tokens','request_seconds')}
    for name in ('regression','context'):
        folder=BASE/name;review=read(folder/'semantic-review.completed.json')
        score=score_semantics(read_jsonl(folder/'predictions.jsonl'),read_jsonl(folder/'labels.snapshot.jsonl'),review)
        assert score==read(folder/'semantic-scores.json')
        out['regression'][name]=dict(content=score['content'],fully_correct=score['fully_correct'],errors=score['errors'],unsafe_create_proposals=score['unsafe_create_proposals'])
        out['cost'][name]=cost(folder)
    assert read(BASE/'context/first-pass/CTX_ES2002a_roles.json')['status']=='partial'
    out['context_first_pass']='interpret_work: set operation without deadline evidence; recovered once with initial code and same prompts'
    manifest=read(BASE/'repair-probe/manifest.json');assert digest(manifest['cases'])==manifest['cases_hash']
    repair_cost=[]
    for case in manifest['cases']:
        folder=BASE/'repair-probe'/case['case_id'];row=read(folder/'result.json')
        out['repair'][case['case_id']]=dict(status=row['status'],items=len(row.get('reduced',{}).get('items',[])),writes=row['writes'])
        repair_cost.append(cost(folder))
    out['cost']['repair_probe']={k:sum(row[k] for row in repair_cost) for k in ('new_calls','new_tokens','request_seconds')}
    acceptance=read(BASE/'replay-final/acceptance.json')
    assert len(acceptance['checks'])==12 and all(acceptance['checks'].values())
    out['fresh_replay']=dict(passed=12,total=12,first_pass=True)
    out['cost']['fresh_replay']=cost(BASE/'replay-final')
    out['total_cost']={k:sum(row[k] for row in out['cost'].values()) for k in ('new_calls','new_tokens','request_seconds')}
    trace=read(BASE/'trace-replay/summary.json');assert len(trace['rows'])==26 and trace['model_calls']==0
    out['trace_replays']=dict(total=26,old_update_cases=13,current_regression_context=7,previous_regression=6,model_calls=0)
    out['limitations']=['Only directed synthetic paired probes, not blind evaluation.',
        'Content recall improves but acceptance conservatism reduces fully-correct recall.',
        'C09 remains without a useful purpose clarification, including bounded repair.',
        'Bounded repair is an isolated experiment; production has no automatic repair loop.',
        'No calendar/event binding or real Feishu integration was added.']
    write_json(BASE/'summary.json',out)
    print(json.dumps({k:v for k,v in out.items() if k not in ('probes','regression')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
