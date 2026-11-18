"""Re-run captured semantic traces through final reducer and Service, no models."""
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.context_state import reduce_context
from meeting_eval.inputs import digest
from meeting_eval.service import Service
from meeting_eval.store import Store
from scripts.run_action_baseline import write_json

BASE=ROOT/'runs/2026-11-15-field-preservation'


def read(path):return json.loads(path.read_text(encoding='utf-8'))


class TraceExtractor:
    strategy='context-v1'
    def __init__(self, extraction):self.saved=extraction
    def extract(self, meeting, history):
        trace=copy.deepcopy(self.saved['_task_trace'])
        reduced=reduce_context(trace['checked_events'],trace['uncovered_spans'],trace['checked_records'],meeting,history)
        trace.update({k:v for k,v in reduced.items() if k not in ('items','updates')})
        return {**copy.deepcopy(self.saved),'items':reduced['items'],'updates':reduced['updates'],'_task_trace':trace}


def one(group,cid,raw,extraction,tasks=None):
    out=BASE/'trace-replay'/group/cid;out.mkdir(parents=True,exist_ok=False)
    store=Store(out/'state.sqlite')
    try:
        service=Service(store,TraceExtractor(extraction))
        for task in tasks or []:service.sim.seed(task,'2026-11-15T10:00:00+08:00')
        result=service.process(raw,'host' if tasks is not None else 'evaluator','2026-11-16T10:02:00+08:00')
        write_json(out/'result.json',result);write_json(out/'tasks.json',store.tasks())
        write_json(out/'provenance.json',dict(source_extraction_hash=digest(extraction),model_calls=0))
        return result,store.tasks()
    finally:store.close()


def main():
    rows=[]
    for group,folder in [('previous-regression',ROOT/'runs/2026-11-14-task-updates/regression'),('regression',BASE/'regression'),('context',BASE/'context')]:
        for raw in map(json.loads,(folder/'input.jsonl').read_text(encoding='utf-8').splitlines()):
            cid=raw['case_id'];extraction=read(folder/(cid+'.json'))['extraction']
            assert not extraction['_errors']
            result,tasks=one(group,cid,raw,extraction)
            same=all(result['extraction'][k]==extraction[k] for k in ('items','updates'))
            if group!='previous-regression':assert same,(group,cid)
            rows.append(dict(group=group,case_id=cid,status=result['status'],same_items_updates=same,items=len(result['extraction']['items'])))
    fixtures=read(ROOT/'experiments/task-updates/fixtures.json')['cases']+[read(ROOT/'experiments/task-updates/mixed-control.json')['case']]
    for case in fixtures:
        folder=ROOT/'runs/2026-11-14-task-updates/final'/case['id']
        result,tasks=one('old-updates',case['id'],case['meeting'],read(folder/'result.json')['extraction'],case['tasks'])
        byid={t['guid']:t for t in tasks};expected=case['expected']
        assert all(byid[g]['status']==status for g,status in expected['statuses'].items())
        assert all(byid[g].get('due_date')==value for g,value in expected['dates'].items())
        assert len(tasks)-len(case['tasks'])==expected['new_tasks']
        if expected['no_review']:assert not result['extraction']['_task_trace']['review_records']
        rows.append(dict(group='old-updates',case_id=case['id'],passed=True))
    write_json(BASE/'trace-replay/summary.json',dict(rows=rows,model_calls=0))
    print(json.dumps(dict(replays=len(rows),old_updates=13,current_regression_context=7,previous_regression=6,model_calls=0),indent=2))


if __name__=='__main__':main()
