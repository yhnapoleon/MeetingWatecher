"""Focused M2 replay and observable acceptance; no production prompt changes."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import run as boundary
from meeting_eval.inputs import digest
from meeting_eval.service import Service
from meeting_eval.store import Store
from scripts import replay_mvp
from scripts.run_action_baseline import write_json

BASE = ROOT / 'runs/2026-11-15-task-boundary'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def positive_meeting():
    meeting = read(ROOT / 'examples/m2.json')
    meeting['segments'] += [
        dict(id='M2.3', start_ms=28000, end_ms=32000, speaker='王宁',
             text='陈可今天下班前改好灰度配置并发测试。'),
        dict(id='M2.4', start_ms=33000, end_ms=35000, speaker='陈可', text='好，我来。'),
    ]
    return meeting


def run_positive(name, recover_from=None):
    out = BASE / name
    prior_meta = set()
    if recover_from:
        source = BASE / recover_from
        assert read(source/'m2-result.json')['status']=='partial', 'Only partial outputs can be recovered'
        shutil.copytree(source, out, ignore=shutil.ignore_patterns('m2-idempotency.sqlite*','m2-validation.json'))
        prior_meta = {p.relative_to(out).as_posix() for p in (out/'model').rglob('meta.json')}
    else:
        out.mkdir(exist_ok=False)
    boundary.snapshot(out)
    meeting = positive_meeting()
    write_json(out / 'm2-input.json', meeting)
    write_json(out / 'manifest.json', dict(arm='cross_explicit_implementation',
        input_hash=digest(meeting), recover_from=recover_from,
        policy='Two predeclared rounds; first runs retained. Recovery is one same-config attempt in a separate copy.'))
    original_read = replay_mvp.read
    def scenario_read(path):
        return copy.deepcopy(meeting) if path == ROOT / 'examples/m2.json' else original_read(path)
    started = time.perf_counter()
    with patch.object(replay_mvp, 'read', side_effect=scenario_read):
        replay_mvp.replay(out, ROOT.parent.parent / 'meeting-agent/.env', 'context-v1',
            inference_config=read(ROOT / 'experiments/action-context/compact-check.json'))
    write_json(out / 'timing.json', dict(seconds=round(time.perf_counter()-started, 3)))
    report = assess(out, positive=True)
    if recover_from:
        added = [read(p) for p in (out/'model').rglob('meta.json') if p.relative_to(out).as_posix() not in prior_meta]
        report['recovery'] = dict(source=recover_from, calls=len(added),
            tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in added))
        write_json(out/'m2-validation.json',report)
    return report


def compact_trace(trace):
    first = trace.get('repair', {}).get('before', trace)
    def records(rows):
        return [{k:r[k] for k in ('record_id','kind','description','missing_fields','question','check') if k in r}
                for r in rows]
    return dict(
        tracking=[dict(thread_id=t['thread_id'], **u) for t in trace.get('ledger',{}).get('threads',[])
                  for u in t['updates']],
        first_records=records(first.get('records',[])),
        first_checks=records(first.get('checked_records',[])),
        first_uncovered=first.get('uncovered_spans',[]),
        repair_status=trace.get('repair',{}).get('status'),
        repair_targets=trace.get('repair',{}).get('target_record_ids',[]),
        repair_proposal=records(trace.get('repair',{}).get('proposal',{}).get('records',[])),
        repair_checks=records(trace.get('repair',{}).get('after',{}).get('checked_records',[])),
        final_uncovered=trace.get('uncovered_spans',[]),
        final_reviews=trace.get('review_records',[]), errors=trace.get('errors',[]))


def assess(out, positive=False):
    cross = (out / 'm2-result.json').exists()
    case = out if cross else out / 'updates/M2'
    result = read(case / ('m2-result.json' if cross else 'result.json'))
    extraction = result['extraction']
    trace = extraction.get('_task_trace', {})
    meeting = (read(out / 'm2-input.json') if positive else read(ROOT / 'examples/m2.json')) if cross else read(case / 'input.json')['meeting']
    minutes = (case / ('M2.md' if cross else 'minutes.md')).read_text(encoding='utf-8')
    decision_section = minutes.split('## 已决事项\n',1)[1].split('\n## ',1)[0] if '## 已决事项\n' in minutes else ''
    items = extraction['items']
    checks = dict(processed=result['status']=='processed',
                  no_review_records=not trace.get('review_records'),
                  no_uncovered_spans=not trace.get('uncovered_spans'),
                  scope_visible_in_minutes='内部员工' in decision_section and '试点客户' in decision_section)
    if positive:
        checks['only_explicit_implementation_item'] = (len(items)==1 and
            items[0].get('operation')=='create' and items[0].get('owner_ref')=='chen' and
            items[0].get('due_date')=='2026-11-16' and '灰度配置' in items[0].get('description','') and
            '测试' in items[0].get('description','') and {'M2.3','M2.4'} <= set(items[0].get('evidence_ids',[])))
    else:
        checks['no_new_items'] = items == []
    # Exercise repeat/restart on a database copy, preserving the first-run artifacts.
    copied = case / 'm2-idempotency.sqlite'
    if copied.exists():
        raise FileExistsError(copied)
    original = Store(case / 'state.sqlite')
    target = Store(copied)
    original.db.backup(target.db)
    original.close()
    svc = Service(target)
    guid = read(out/'bindings.json')['T17'] if cross else read(case/'input.json')['tasks'][0]['guid']
    task = target.task(guid)
    checks['original_guid_completed'] = task['status']=='done' and guid in result['bindings'].values()
    checks['original_due_preserved'] = task.get('due_date')=='2026-11-13'
    created = [t for t in target.tasks() if t.get('source_id')]
    checks['persisted_task_count'] = len(created)==((2 if positive else 1) if cross else 0)
    if positive:
        new = [t for t in created if t['guid'] != guid]
        checks['implementation_persisted'] = (len(new)==1 and new[0]['assignee']=='chen' and
            new[0].get('due_date')=='2026-11-16' and '灰度配置' in new[0]['summary'] and '测试' in new[0]['summary'])
    if cross:
        m1 = read(out/'m1-result.json')
        checks['m1_only_original_task'] = len(m1['extraction']['items'])==1
        legacy = read(out/'acceptance.json')['checks']
        checks.update({'legacy_'+k:v for k,v in legacy.items() if k!='m2_no_duplicate_task'})
        decisions = svc.decisions(meeting['series'],'host','2026-11-16T10:02:00+08:00',history=True)
        current = svc.decisions(meeting['series'],'host','2026-11-16T10:02:00+08:00')
        checks['scope_replaced'] = len(decisions)==2 and decisions[-1]['supersedes']==decisions[0]['id'] and len(current)==1
        checks['guest_decisions_private'] = svc.decisions(meeting['series'],'guest','2026-11-16T10:02:00+08:00',history=True)==[]
    before_tasks = target.tasks()
    before_counts = [target.db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('task_events','decisions','intents','audit')]
    if result['status']=='processed':
        repeated = svc.process(meeting,'host','2026-11-16T10:02:00+08:00')
        checks['m2_repeat_same_bindings'] = repeated['bindings']==result['bindings']
        target.close()
        target = Store(copied)
        restarted = Service(target).process(meeting,'host','2026-11-16T10:02:00+08:00')
        checks['m2_restart_same_bindings'] = restarted['bindings']==result['bindings']
        checks['m2_repeat_restart_no_mutation'] = before_tasks==target.tasks() and before_counts==[
            target.db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('task_events','decisions','intents','audit')]
    else:
        checks['m2_repeat_restart_no_mutation'] = False
    target.close()
    meta = [read(p) for p in (case/'model').rglob('meta.json')]
    report = dict(arm='positive' if positive else ('cross' if cross else 'isolated'),
        result_hash=digest(result), checks=checks, passed=all(checks.values()),
        items=items, trace=compact_trace(trace),
        calls=len(meta), tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in meta),
        note='Structural/observable acceptance; semantic reading of descriptions, decisions, and minutes is also required.')
    write_json(case/'m2-validation.json',report)
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--name',required=True)
    parser.add_argument('--run-positive',action='store_true')
    parser.add_argument('--positive',action='store_true')
    parser.add_argument('--recover-positive-from')
    args=parser.parse_args()
    report = (run_positive(args.name,args.recover_positive_from)
              if args.run_positive or args.recover_positive_from else assess(BASE/args.name,args.positive))
    print(json.dumps({k:v for k,v in report.items() if k not in ('trace','items')},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
