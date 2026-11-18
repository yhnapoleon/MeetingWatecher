"""Replay real extraction and persistent simulator operations; answers are evaluator-only."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from meeting_eval.extract import Extractor, DEFAULT_STRATEGY
from meeting_eval.inputs import digest
from meeting_eval.service import Service
from meeting_eval.store import Store, Simulator
from scripts.run_action_baseline import write_json
from scripts.score_recap import score


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def audit(store,path):
    path.write_text(''.join(json.dumps({'kind':r['kind'],**json.loads(r['body'])},ensure_ascii=False)+'\n'
                           for r in store.db.execute('SELECT * FROM audit ORDER BY seq')),encoding='utf-8')


def workflow(out):
    scenario = read(ROOT/'data/mvp-v1/workflow/scenario.json')
    # Each replay has a fresh persistent platform, so the authorization environment
    # advances with the query events, not with the final state of an earlier replay.
    n = len(list(out.glob('workflow-*.sqlite')))+1
    store = Store(out/f'workflow-{n}.sqlite')
    try:
        sim,svc = Simulator(store),Service(store)
        for t in scenario['tasks_at_0900']:
            sim.seed({**t,'series':scenario['series'],'writers':list(set(['host',t['assignee']]))},
                     '2026-11-16T09:00:00+08:00')
        events = iter(scenario['server_events'])
        event = next(events,None)
        predictions = []
        for q in scenario['queries']:
            while event and event['at'] <= q['as_of']:
                t = sim.get(event['guid'],event['actor'])
                changes = {'status':event['value']} if event['kind'] == 'set_status' else {
                    'readers':[v for v in t['readers'] if v != event['value']]}
                sim.update(event['guid'],changes,event['actor'],event['at'])
                event = next(events,None)
            for viewer in q['viewers']:
                tasks = svc.recap(scenario['series'],viewer,q['as_of'])
                predictions.append(dict(meeting=q['meeting'],viewer=viewer,tasks=sorted(t['guid'] for t in tasks)))
        # Historic queries after revocation still use current permissions.
        assert svc.recap(scenario['series'],'guest',scenario['queries'][0]['as_of']) == []
        gold = read(ROOT/'data/mvp-v1/workflow/expected.json')['recaps']
        report = score(gold,predictions)
        write_json(out/'workflow-predictions.json',predictions)
        write_json(out/'workflow-scores.json',report)
        audit(store,out/'workflow-operations.jsonl')
        return predictions,report
    finally:
        store.close()


def replay(out,env_file,strategy=DEFAULT_STRATEGY,*,inference_config=None):
    out.mkdir(parents=True,exist_ok=True)
    store = Store(out/'state.sqlite')
    model = Extractor(env_file,out/'model',strategy,inference_config=inference_config)
    svc = Service(store,model)
    checks = {}
    try:
        m1 = svc.process(read(ROOT/'examples/m1.json'),'host','2026-11-09T10:02:00+08:00')
        write_json(out/'m1-result.json',m1)
        (out/'M1.md').write_text(svc.minutes(m1['source_id'],'host'),encoding='utf-8')
        created = [g for g in m1['bindings'].values() if g]
        checks['m1_one_task'] = len(created) == 1
        if not checks['m1_one_task']:
            raise ValueError('M1 did not create exactly one task; inspect m1-result.json')
        guid = created[0]
        task = svc.sim.get(guid,'host')
        checks['m1_owner_date_evidence'] = (task['assignee'] == 'chen' and task['due_date'] == '2026-11-13'
            and {'M1.1','M1.2'} <= {e['id'] for e in task['evidence']})
        checks['m1_unresolved_and_decision'] = bool(m1['extraction']['unresolved']) and len(m1['decision_ids']) == 1
        repeated = svc.process(read(ROOT/'examples/m1.json'),'host','2026-11-09T10:02:00+08:00')
        checks['repeat_same_guid'] = repeated['bindings'] == m1['bindings']
        store.close()
        store = Store(out/'state.sqlite')
        svc = Service(store,model)
        checks['restart_same_guid'] = svc.process(read(ROOT/'examples/m1.json'),'host',
            '2026-11-09T10:02:00+08:00')['bindings'] == m1['bindings']
        snapshot = read(ROOT/'examples/before_m2.json')
        # Only external tasks are environment seeds. M1's task and decision come from extraction.
        for t in snapshot['tasks']:
            if t['origin'] == 'shared_tasklist':
                svc.sim.seed({**t,'series':snapshot['series']},snapshot['as_of'])
        predictions = []
        for viewer in ('host','guest'):
            ctx = svc.context(snapshot['series'],viewer,snapshot['as_of'])
            write_json(out/f'context-{viewer}.json',ctx)
            tasks = svc.recap(snapshot['series'],viewer,snapshot['as_of'])
            predictions.append(dict(meeting='M2',viewer=viewer,tasks=sorted('T17' if t['guid']==guid else t['guid'] for t in tasks)))
        write_json(out/'bindings.json',{'T17':guid,'D1':m1['decision_ids']})
        write_json(out/'recap-predictions.json',predictions)
        recap_report = score(read(ROOT/'examples/expected.json')['recaps'],predictions)
        checks['recap_exact'] = all(not c['missed'] and not c['unexpected'] and not c['forbidden_returned'] for c in recap_report['cases'])
        checks['guest_context_private_task_absent'] = guid not in json.dumps(read(out/'context-guest.json'))
        m2 = svc.process(read(ROOT/'examples/m2.json'),'host','2026-11-16T10:02:00+08:00')
        write_json(out/'m2-result.json',m2)
        (out/'M2.md').write_text(svc.minutes(m2['source_id'],'host'),encoding='utf-8')
        checks['m2_updated_original'] = svc.sim.get(guid,'host')['status'] == 'done' and guid in m2['bindings'].values()
        checks['m2_no_duplicate_task'] = len([t for t in store.tasks() if t.get('source_id')]) == 1
        decisions = svc.decisions(snapshot['series'],'host','2026-11-16T10:02:00+08:00',history=True)
        checks['decision_replacement'] = len(decisions) == 2 and decisions[-1]['supersedes'] == decisions[0]['id']
        checks['past_recap_still_open'] = guid in [t['guid'] for t in svc.recap(snapshot['series'],'host',snapshot['as_of'])]
        write_json(out/'decisions.json',decisions)
        write_json(out/'recap-scores.json',recap_report)
        audit(store,out/'operations.jsonl')
    finally:
        store.close()
    _,wf = workflow(out)
    checks['workflow_six_exact'] = all(not c['missed'] and not c['unexpected'] and not c['forbidden_returned'] for c in wf['cases'])
    report = dict(checks=checks,passed=all(checks.values()),annotation_status='agent_labeled / draft_for_review',
                  input_sha256={f:digest(read(ROOT/'examples'/f)) for f in ('m1.json','m2.json')})
    write_json(out/'acceptance.json',report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--env-file',type=Path,default=ROOT.parent.parent/'meeting-agent/.env')
    parser.add_argument('--strategy',choices=('combined','split','split-v2','split-v3','legacy','evidence-v1','context-v1','context-v2','context-v3','context-v4'),default=DEFAULT_STRATEGY)
    parser.add_argument('--inference-config',type=Path)
    args = parser.parse_args()
    inference = json.loads(args.inference_config.read_text(encoding='utf-8')) if args.inference_config else None
    report = replay(args.out,args.env_file,args.strategy,inference_config=inference)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
