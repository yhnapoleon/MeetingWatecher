"""Offline diagnosis from frozen accepted outputs; never invokes a model.

Controls change copied inputs only. They are not production fixes or new scores.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from meeting_eval.context_coverage import plan_repair
from meeting_eval.context_protocol_v3 import evidence_catalog
from meeting_eval.context_protocol_v5 import check_contract, expand_checks
from meeting_eval.context_state import reduce_context
from meeting_eval.context_v3 import reduce_v3
from meeting_eval.context_wire import decode_output
from meeting_eval.extract import model_input
from meeting_eval.inputs import normalize
from meeting_eval.service import Service
from meeting_eval.store import Store
from test_context_updates import fixture

BASE = ROOT / 'runs/2026-11-17-interpret-budget-low/natural'
SOURCES = {}


def read(path):
    SOURCES[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return json.loads(path.read_text(encoding='utf8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def load(case):
    folder = BASE / case
    job = read(folder / 'input.json')
    saved = read(folder / 'result.json')
    pipeline = read(next(folder.glob('model/context_v2/*/result.json')))
    return job, saved, pipeline, normalize(job['meeting'], job['actor'])


def summarize(result):
    return dict(items=len(result['items']), updates=len(result['updates']),
                reports=result['reports'], reviews=result['review_records'], pending=result['pending'])


class FrozenExtractor:
    def __init__(self, pipeline):
        self.pipeline = pipeline

    def extract(self, meeting, context):
        assert not context['tasks'] and not context['decisions']
        result = reduce_v3(self.pipeline, meeting, {'tasks': []})
        return dict(items=result['items'], updates=result['updates'], facts=[], decisions=[], unresolved=[],
                    _task_trace={k: result[k] for k in ('pending', 'review_records', 'reports', 'item_records',
                                                      'context_records', 'deferred_topics')})


def diagnose(out):
    job, saved, pipeline, meeting = load('GN29')
    history = {'tasks': []}
    baseline = reduce_v3(pipeline, meeting, history)
    assert baseline['items'] == saved['extraction']['items']
    for key in ('review_records', 'pending', 'reports', 'item_records'):
        assert baseline[key] == saved['extraction']['_task_trace'][key], key
    controls = {}
    for rid in ('R8', 'R23'):
        original = next(e for e in pipeline['checked_events'] if e['record_id'] == rid)
        review = next(r for r in baseline['review_records'] if r['record_id'] == rid)
        assert original['state']['kind'] == 'progress' and original['time']['change'] == 'set'
        assert review['can_add_task'] and review['question'] == '' and review['missing_fields'] == []
        changed = copy.deepcopy(pipeline)
        event = next(e for e in changed['checked_events'] if e['record_id'] == rid)
        event['time']['change'] = 'keep'  # Single-variable diagnostic intervention.
        result = reduce_v3(changed, meeting, history)
        assert result['items'] == baseline['items'] and result['updates'] == baseline['updates']
        assert result['review_records'] == [r for r in baseline['review_records'] if r['record_id'] != rid]
        added_reports = [r for r in result['reports'] if r not in baseline['reports']]
        assert len(added_reports) == 1 and added_reports[0]['description'] == original['work']['description']
        assert all(r in result['reports'] for r in baseline['reports'])
        controls[rid] = dict(changed_field='time.change: set -> keep', before_event=original,
                             before_review=review, after_report=added_reports[0])

    # Exercise the normal Service entry with the original frozen model output.
    store = Store(out / 'service-baseline.sqlite')
    try:
        service = Service(store, FrozenExtractor(pipeline))
        result = service.process(job['meeting'], job['actor'], '2026-11-17T20:00:00+08:00')
        assert result['status'] == 'processed'
        assert result['pending'] == saved['pending']
        requirements = service.requirements(result['source_id'], job['actor'])
        cards = [r for r in requirements if r['record_id'] in ('R8', 'R23')]
        assert len(cards) == 2 and all(r['can_add_task'] and r['question'] == '' for r in cards)
        assert result['collected_issues'] == [] and store.tasks() == []
        write(out / 'service-baseline.json', result)
        service_evidence = dict(cards=cards, collected_issues=[], tasks=0, pending_matches_saved=True)
    finally:
        store.close()

    # Existing fixture supplies supported events to isolate routing contracts.
    routing = {}
    for name, state, change, relation, commitment in (
        ('progress_keep', 'progress', 'keep', 'new', 'unknown'),
        ('progress_set', 'progress', 'set', 'new', 'unknown'),
        ('future_work', 'future_work', 'set', 'new', 'self_committed'),
        ('conditional_work', 'future_work', 'set', 'new', 'conditional'),
        ('existing_date_update', 'progress', 'set', 'existing', 'self_committed'),
    ):
        _, m, e, r, task = fixture(change, state)
        e['relation'].update(kind=relation, target_guid='T' if relation == 'existing' else None)
        e['commitment']['kind'] = commitment
        result = reduce_context([e], [], [r], m, {'tasks': [task] if relation == 'existing' else []})
        routing[name] = summarize(result)
    assert len(routing['progress_keep']['reports']) == 1 and not routing['progress_keep']['reviews']
    assert routing['progress_set']['reviews'][0]['can_add_task']
    assert routing['future_work']['items'] == 1
    assert routing['conditional_work']['items'] == 1
    assert routing['conditional_work']['reviews'][0]['category'] == 'conditional_work'
    assert routing['existing_date_update']['updates'] == 1 and not routing['existing_date_update']['reviews']

    job25, saved25, pipeline25, meeting25 = load('GN25')
    folder25 = BASE / 'GN25'
    attempt = next(folder25.glob('model/context_v2/*/check_work/*/attempt-1'))
    request = read(attempt / 'stage-request.json')
    normalized = read(attempt / 'normalized.json')
    interpreted = read(next(folder25.glob('model/context_v2/*/interpret_work/*/accepted.json')))['value']
    checked = read(next(folder25.glob('model/context_v2/*/check_work/*/accepted.json')))['value']
    sid = 'qm.Bed011.639'
    record = next(r for r in checked['checked_records'] if r['record_id'] == 'R6')
    assert record['kind'] == 'context_only' and record['check']['verdict'] == 'supported'
    assert sid in [s['segment_id'] for s in record['evidence']]
    assert sid not in request['coverage_review']['unrepresented_evidence']
    assert sid in [s['id'] for s in request['meeting']['segments']]
    assert not normalized['coverage_findings'] and not checked['plan']['needs_repair']
    catalog = {f'Q{i}': dict(segment_id=s['id'], quote=s['text'])
               for i, s in enumerate(meeting25['segments'], 1) if s['text']}
    payload = dict(meeting=model_input(meeting25), ledger=pipeline25['trace']['ledger'],
                   **interpreted, history={'tasks': []}, evidence_catalog=catalog)
    raw = decode_output(normalized, meeting25)
    _, binding = check_contract(payload)
    assert raw['scope'] == binding['scope']  # Exact historical check-input reconstruction.
    expand_checks(raw, payload)
    qid = next(q for q, s in evidence_catalog(meeting25).items() if s['segment_id'] == sid)
    injected = copy.deepcopy(raw)
    finding = dict(description='If the group decides Grad B should attend Santa Barbara, the team will pay.',
                   evidence=[qid], relation='new_work', related_record_ids=[])
    injected['coverage_findings'] = [finding]
    expanded = expand_checks(injected, payload)
    plan = plan_repair(checked['checked_records'], expanded['coverage_findings'], catalog, 'offline-probe')
    assert plan['needs_repair'] and len(plan['findings']) == 1
    coverage = dict(source_segment=next(s for s in meeting25['segments'] if s['id'] == sid),
                    checked_record=record, present_in_full_input=True, included_in_unrepresented_evidence=False,
                    original_findings=normalized['coverage_findings'], original_needs_repair=False,
                    injected_finding=finding, injected_finding_passed_contract=True,
                    injected_plan=plan, note='Injected finding tests plumbing only; no model or repair generation ran.')
    write(out / 'gn25-coverage-probe.json', coverage)
    summary = dict(scope='offline diagnosis, not a fix or fresh evaluation', model_requests=0,
                   gn29_baseline_matches_saved=True, gn29_single_field_controls=controls,
                   service=service_evidence, routing_controls=routing,
                   gn25=dict(source_in_input=True, source_in_unrepresented_evidence=False,
                             actual_needs_repair=False, injected_finding_accepted=True, injected_needs_repair=True))
    write(out / 'diagnosis.json', summary)
    for name in ('context_state.py', 'context_new_work.py', 'context_v2.py', 'context_v3.py', 'context_v5.py',
                 'context_coverage.py', 'context_protocol_v5.py', 'requirement_review.py', 'service.py'):
        path = ROOT / 'meeting_eval' / name
        SOURCES[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in SOURCES.items())
    write(out / 'source-hashes.json', SOURCES)
    print(json.dumps(dict(status='all diagnosis assertions passed', model_requests=0,
                          single_field_controls=2, routing_controls=5, output=str(out)), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    output = Path(args.out).resolve()
    output.mkdir(parents=True, exist_ok=False)
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('Offline diagnosis forbids network')):
        diagnose(output)
