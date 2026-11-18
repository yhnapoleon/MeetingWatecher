"""Offline causal probes of routing/repair contracts; no model or production edits."""
import copy
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from meeting_eval.inputs import digest
from meeting_eval.context_state import reduce_context
from meeting_eval.context_pipeline import ContextPipeline
from test_context_pipeline import ContextClient
from test_context_state import ledger_fixture
from scripts.run_action_baseline import write_json

BASE=ROOT/'runs/2026-11-15-task-boundary'
OUT=ROOT/'runs/2026-11-15-m2-system-diagnosis'


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def load_case(relative):
    path=BASE/relative
    result=read(path)
    db=sqlite3.connect((path.parent/'state.sqlite').as_uri()+'?mode=ro',uri=True)
    meeting=json.loads(db.execute('SELECT body FROM sources WHERE id=?',(result['source_id'],)).fetchone()[0])
    db.close()
    history=None
    for request in (path.parent/'model').rglob('request.json'):
        payload=json.loads(read(request)['messages'][-1]['content'])
        if payload.get('meeting',{}).get('case_id')==meeting.get('case_id',meeting['meeting_id']) and 'history' in payload:
            history=payload['history'];break
    assert history is not None
    return dict(path=path.relative_to(ROOT).as_posix(),result_hash=digest(result),
                meeting=meeting,history=history,extraction=result['extraction'])


def reduce(case,trace=None):
    trace=trace or case['extraction']['_task_trace']
    return reduce_context(trace['checked_events'],trace['uncovered_spans'],
                          trace['checked_records'],case['meeting'],case['history'])


def visible(value):
    return dict(items=value['items'],updates=value['updates'],
                reviews=value['review_records'],pending=value['pending'],contexts=value['context_records'])


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'probes.json').exists():raise FileExistsError('Completed diagnosis already exists')
    cases={k:load_case(p) for k,p in {
        'cross_bad':'m2-next-cross-r1/m2-result.json',
        'cross_good':'m2-next-cross-r2/m2-result.json',
        'isolated_old':'full-v2/updates/M2/result.json',
        'C20':'full-v2/corpus/C20/result.json',
        'P07b':'pairs-v2/pairs/P07b/result.json',
        'positive':'m2-next-positive-r2/m2-result.json',
    }.items()}
    results={};probes=[]
    for name,case in cases.items():
        got=reduce(case);expected=case['extraction'];trace=expected['_task_trace']
        keys=('items','updates','pending','review_records','item_records','reports','context_records')
        comparison={k:got[k]==(expected[k] if k in ('items','updates') else trace[k]) for k in keys}
        assert all(comparison.values()),(name,comparison)
        results[name]=dict(comparison=comparison,visible=visible(got))
    # One-field counterfactuals diagnose dependency; they are not candidate fixes.
    case=cases['cross_bad'];original=reduce(case)
    altered=copy.deepcopy(case['extraction']['_task_trace']);altered['uncovered_spans']=[]
    cleared=reduce(case,altered)
    assert cleared['items']==original['items'] and len(cleared['review_records'])==1
    probes.append(dict(name='remove_only_uncovered',before=visible(original),after=visible(cleared),
        conclusion='Removing the stale omission removes U only; the erroneous range candidate and R2 question remain.'))
    good=copy.deepcopy(cases['cross_good']['extraction']['_task_trace'])
    good['uncovered_spans']=copy.deepcopy(case['extraction']['_task_trace']['uncovered_spans'])
    residual=reduce(cases['cross_good'],good)
    assert not residual['items'] and len(residual['review_records'])==1 and residual['review_records'][0]['record_id'].startswith('U-')
    probes.append(dict(name='supported_context_with_stale_omission',after=visible(residual),
        conclusion='Even a supported context-only record cannot close a retained omission.'))
    p=cases['P07b'];edited=copy.deepcopy(p['extraction']['_task_trace'])
    edited['checked_records'][0]['missing_fields']=[]
    unblocked=reduce(p,edited)
    assert len(unblocked['items'])==1 and unblocked['items'][0]['operation']=='create'
    probes.append(dict(name='remove_only_reference_gap',before=visible(reduce(p)),after=visible(unblocked),
        conclusion='The reference flag alone blocks this already accepted work; clearing it is a diagnostic intervention, not a safe general fix.'))

    class OmissionOnly(ContextClient):
        def call(self,prompt,payload,stage,**kwargs):
            value=super().call(prompt,payload,stage,**kwargs)
            if stage=='check_work':value['uncovered_spans']=['Q2']
            return value
    meeting,*_=ledger_fixture()
    meeting['segments'].append(dict(id='s2',speaker='A',person_ref='alice',text='我还会把合同发给法务。'))
    client=OmissionOnly();pipe=ContextPipeline(client,OUT/'mock-omission-only',{})
    response=pipe.run(meeting,{'tasks':[]})
    stages=[s for s,_ in client.calls]
    assert response['errors']==[] and response['uncovered_spans'] and 'repair_work' not in stages
    probes.append(dict(name='omission_without_bad_record',stages=stages,uncovered=response['uncovered_spans'],
        conclusion='A standalone omission cannot trigger repair: targets are only existing record/event check failures.'))
    write_json(OUT/'evidence.json',cases)
    write_json(OUT/'routing-replays.json',results)
    write_json(OUT/'probes.json',dict(model_calls=0,kind='deterministic dependency probes, not model efficacy evaluation',results=probes))
    print(json.dumps(dict(replayed_cases=len(results),matching_fields_per_case=7,contract_probes=len(probes),model_calls=0),ensure_ascii=False))


if __name__=='__main__':main()
