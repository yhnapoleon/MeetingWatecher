"""Service-level frozen-output regression; no model or network access."""
import copy
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.context_v3 import reduce_v3
from meeting_eval.service import Service
from meeting_eval.store import Store


class Frozen:
    def __init__(self,pipeline):self.pipeline=pipeline;self.calls=0
    def extract(self,meeting,context):
        self.calls+=1
        assert not context['tasks'] and not context['decisions']
        reduced=reduce_v3(self.pipeline,meeting,{'tasks':[]})
        return dict(items=reduced['items'],updates=reduced['updates'],facts=[],unresolved=[],decisions=[],
            _task_trace={k:reduced[k] for k in ('review_records','reports','pending','item_records','context_records','deferred_topics')})


def run(out):
    out.mkdir(parents=True,exist_ok=False)
    folder=ROOT/'runs/2026-11-17-interpret-budget-low/natural/GN29'
    read=lambda p:json.loads(p.read_text(encoding='utf8'))
    job=read(folder/'input.json');old=read(folder/'result.json')
    pipeline=read(next(folder.glob('model/context_v2/*/result.json')))
    extractor=Frozen(pipeline);store=Store(out/'state.sqlite')
    try:
        svc=Service(store,extractor)
        result=svc.process(job['meeting'],job['actor'],'2026-11-17T20:00:00+08:00')
        trace=result['extraction']['_task_trace'];before=old['extraction']['_task_trace']
        assert result['extraction']['items']==old['extraction']['items']
        assert result['extraction']['updates']==old['extraction']['updates']
        assert trace['item_records']==before['item_records']
        assert trace['review_records']==[r for r in before['review_records'] if r['record_id'] not in ('R8','R23')]
        assert len(trace['reports'])==len(before['reports'])+2
        for rid in ('R8','R23'):
            event=next(e for e in pipeline['checked_events'] if e['record_id']==rid)
            report=next(r for r in trace['reports'] if r['description']==event['work']['description'])
            assert report['time']==event['time'] and report['state']=='progress'
        assert not any(p.get('event_id') in ('E5','E15') for p in result['pending'])
        assert svc.process(job['meeting'],job['actor'],'2026-11-17T20:01:00+08:00')==result
        assert extractor.calls==1 and store.tasks()==[]
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    finally:store.close()
    store=Store(out/'state.sqlite')
    try:
        svc=Service(store)
        assert svc.result(result['source_id'])==result
        minutes=svc.minutes(result['source_id'],job['actor'])
        assert '工作进展与完成汇报' in minutes
        (out/'minutes.md').write_text(minutes,encoding='utf8')
    finally:store.close()
    summary=dict(items=len(trace['item_records']),removed_review_ids=['R8','R23'],reports=len(trace['reports']),
        other_reviews_unchanged=True,preserved_event_time=True,restart_and_repeat_consistent=True,model_requests=0)
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    with patch.object(socket.socket,'connect',side_effect=AssertionError('Offline only')):
        run(Path(sys.argv[1]).resolve())
