"""Offline causal probes of frozen context-v2 failures; never calls a model.

Counterfactuals are diagnostic interventions, not repaired model outputs or scores.
Only writes a new diagnostic directory. Production and original runs stay intact.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.context_v2 import ContextV2Pipeline, reduce_v2
from meeting_eval.context_coverage import plan_repair, apply_repair

BASE = ROOT / 'runs/2026-11-15-context-v2'
PIPE = object.__new__(ContextV2Pipeline)  # Pure validators only: no client exists.
ASSERTIONS = []
SOURCES = {}


def read(path):
    SOURCES[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return json.loads(path.read_text(encoding='utf8'))


def check(name, condition):
    ASSERTIONS.append(dict(name=name, passed=bool(condition)))
    assert condition, name


def call(folder, stage):
    matches = []
    for path in folder.rglob('meta.json'):
        meta = read(path)
        if meta['stage'] == stage and path.with_name('response.json').exists():
            matches.append(path)
    # Recovery folders contain the original calls; use the saved retry if present.
    path = sorted(matches, key=lambda p: ('retry-' in str(p), str(p)))[-1]
    req = read(path.with_name('request.json'))
    res = read(path.with_name('response.json'))
    return json.loads(req['messages'][1]['content']), json.loads(res['choices'][0]['message']['content'])


def interpreted(payload):
    return {k: payload[k] for k in ('records', 'events', 'candidates')}


def verify(raw, payload, recheck=False):
    return PIPE.check(raw, interpreted(payload), payload['meeting'], payload['evidence_catalog'], recheck)


def error_of(fn):
    try:
        fn()
    except ValueError as exc:
        return str(exc)
    return None


def pipeline(checked, trace=None):
    return dict(checked_records=checked['checked_records'], checked_events=checked['checked_events'],
                coverage_findings=[], trace=trace or {})


def observable(reduced):
    return {k: reduced[k] for k in ('items', 'updates', 'review_records', 'context_records')}


def c19():
    payload, raw = call(BASE/'full/corpus/C19', 'interpret_work')
    def interpret(value):
        return PIPE.interpret(value, payload['ledger'], payload['candidates'], payload['meeting'], payload['history'])
    first_error = error_of(lambda: interpret(raw))
    check('C19 original quote failure reproduced', first_error == 'Missing or ambiguous exact quote; provide occurrence')
    span = raw['events'][0]['time']['evidence'][0]
    text = next(s['text'] for s in payload['meeting']['segments'] if s['id'] == span['segment_id'])
    positions = [i for i in range(len(text)) if text.startswith(span['quote'], i)]
    check('C19 repeated time quote is the offending input', span['quote'] == '会后' and len(positions) == 2)
    occurrence_results = []
    for occurrence in (1, 2):
        changed = copy.deepcopy(raw)
        changed['events'][0]['time']['evidence'][0]['occurrence'] = occurrence
        accepted = interpret(changed)
        occurrence_results.append(dict(occurrence=occurrence, records=len(accepted['records']), events=len(accepted['events'])))
        check(f'C19 occurrence {occurrence} alone admits original interpretation', len(accepted['events']) == 1)
    payload, raw = call(BASE/'full-recovery/corpus/C19', 'check_work')
    second_error = error_of(lambda: verify(raw, payload))
    check('C19 recovered check failure reproduced', second_error == 'Cleared question requires question repair issue')
    changed = copy.deepcopy(raw)
    row = next(r for r in changed['record_checks'] if r['record_id'] == 'R2')
    row['issues'].append('question')
    accepted = verify(changed, payload)
    plan = plan_repair(accepted['checked_records'], changed['coverage_findings'], payload['evidence_catalog'], 'diagnostic')
    check('C19 adding missing derivative issue admits check', plan['target_record_ids'] == ['R2'])
    check('C19 recovery changed task decomposition', len(payload['events']) == 4)
    return dict(first_error=first_error, quote=span, positions=positions, occurrence_interventions=occurrence_results,
                recovered_error=second_error, recovered_original_issue=['reference'],
                add_question_issue=dict(accepted=True, repair_targets=plan['target_record_ids']),
                original_event_count=1, recovered_event_count=4,
                limit='No replacement repair response generated. Four-event decomposition is observed drift, not scored here.')


def ht04():
    payload, raw = call(BASE/'full-recovery/updates/HT04', 'check_work')
    baseline = error_of(lambda: verify(raw, payload))
    check('HT04 original clarification failure reproduced', baseline == 'Unsupported clarification')
    changed = copy.deepcopy(raw)
    changed['record_checks'][0]['gap_checks'][0]['blocking_for'] = 'operation'
    accepted = verify(changed, payload)
    plan = plan_repair(accepted['checked_records'], [], payload['evidence_catalog'], 'diagnostic')
    reduced = reduce_v2(pipeline(accepted), payload['meeting'], payload['history'])
    check('HT04 one gap field change admits check but still schedules repair', plan['target_record_ids'] == ['R1'])
    check('HT04 unchanged semantic verdict routes to system dispute', reduced['review_records'][0]['category'] == 'interpretation_unresolved')
    check('HT04 no accidental update after gap-only intervention', not reduced['items'] and not reduced['updates'])
    # Diagnostic oracle: a correctly stated ambiguity can be faithful and supported.
    changed['record_checks'][0].update(verdict='supported', issues=[])
    accepted_faithful = verify(changed, payload)
    reduced_faithful = reduce_v2(pipeline(accepted_faithful), payload['meeting'], payload['history'])
    faithful_plan = plan_repair(accepted_faithful['checked_records'], [], payload['evidence_catalog'], 'diagnostic')
    check('HT04 faithful record verdict restores specific user question',
          reduced_faithful['review_records'][0]['missing_fields'] == ['relation'] and
          'H-HT04-other' in reduced_faithful['review_records'][0]['question'] and
          not reduced_faithful['review_records'][0]['can_add_task'])
    check('HT04 event relation verdict independently still schedules repair', faithful_plan['needs_repair'])
    changed['checks'][0]['fields']['relation']['verdict'] = 'supported'
    accepted_event = verify(changed, payload)
    event_plan = plan_repair(accepted_event['checked_records'], [], payload['evidence_catalog'], 'diagnostic')
    event_reduced = reduce_v2(pipeline(accepted_event), payload['meeting'], payload['history'])
    check('HT04 faithful ambiguous event needs no repair and never executes',
          not event_plan['needs_repair'] and not event_reduced['items'] and not event_reduced['updates'])
    return dict(original_error=baseline, gap_only=dict(repair_targets=plan['target_record_ids'], output=observable(reduced)),
                faithful_record=dict(still_needs_repair=faithful_plan['needs_repair'], output=observable(reduced_faithful)),
                faithful_record_and_event=dict(needs_repair=False, output=observable(event_reduced)),
                limit='Post-gap routing is tested directly before repair; no claim about a new model repair response. Supported-verdict variants are diagnostic oracles, not automatic normalizations.')


def c23():
    folder = BASE/'full/corpus/C23'
    payload, _ = call(folder, 'check_work')
    trace = read(folder/'result.json')['extraction']['_task_trace']
    original = pipeline(trace, trace)
    baseline = reduce_v2(original, payload['meeting'], payload['history'])
    check('C23 final item reproduced from saved checked state', baseline['items'] == read(folder/'summary.json')['items'])
    complete = '会后单独联系袁校长，继续沟通其他问题并核对刚才未听清的内容。'
    record_only = copy.deepcopy(original)
    record_only['checked_records'][0]['description'] = complete
    record_reduced = reduce_v2(record_only, payload['meeting'], payload['history'])
    check('C23 record description does not determine item content', record_reduced['items'] == baseline['items'])
    event_only = copy.deepcopy(original)
    event_only['checked_events'][0]['work']['description'] = complete
    event_reduced = reduce_v2(event_only, payload['meeting'], payload['history'])
    check('C23 event description determines item content', event_reduced['items'][0]['description'] == complete)
    check('C23 all content checks passed despite omission',
          trace['checked_records'][0]['check']['verdict'] == 'supported' and
          trace['checked_events'][0]['checks']['work']['verdict'] == 'supported' and
          not trace['coverage_findings'] and not trace['coverage_plan']['needs_repair'])
    return dict(original_record_description=trace['checked_records'][0]['description'],
                original_event_description=trace['checked_events'][0]['work']['description'],
                original_item=baseline['items'][0], record_only_item=record_reduced['items'][0], event_only_item=event_reduced['items'][0],
                content_check_and_coverage_missed_omission=True,
                limit='Description swaps isolate reducer provenance using frozen verdicts; they are not newly verified model answers.')


def cp01():
    folder = BASE/'full/probes/CP01'
    payload, raw = call(folder, 'repair_work')
    recheck_payload, recheck_raw = call(folder, 'check_repair')
    trace = read(folder/'result.json')['extraction']['_task_trace']
    baseline = reduce_v2(pipeline(trace, trace), payload['meeting'], payload['history'])
    check('CP01 extra unresolved review reproduced', [r['record_id'] for r in baseline['review_records']] == ['R4'])
    check('CP01 repair did not follow background correction',
          raw['records'][0]['kind'] == 'implicit_need' and recheck_raw['record_checks'][0]['proposed_kind'] == 'context_only')
    # A manually supplied closed interpretation tests whether identity/merge force retention.
    changed = copy.deepcopy(raw)
    changed['records'][0].update(kind='context_only', content_basis='explicit',
        description='设置页有一些开关名称还没统一，是功能清单讨论的背景。', missing_fields=[], question=None)
    fixed = PIPE.interpret(changed, payload['ledger'], payload['candidates'], payload['meeting'], payload['history'], True)
    modified_check = copy.deepcopy(recheck_raw)
    modified_check['record_checks'][0].update(verdict='supported', issues=[], proposed_kind=None, gap_checks=[], reason='诊断用正确关闭状态；非新模型核验')
    checked = PIPE.check(modified_check, fixed, payload['meeting'], payload['evidence_catalog'], True)
    merged = apply_repair(trace['coverage_plan'], checked['checked_records'], [], [])
    check('CP01 stable record/thread identity allows validated context closure', merged['status'] == 'checked')
    final = dict(checked_records=merged['records'], checked_events=trace['checked_events'])
    corrected = reduce_v2(pipeline(final, trace), payload['meeting'], payload['history'])
    check('CP01 corrected closure keeps main task and removes only extra review',
          corrected['items'] == baseline['items'] and not corrected['review_records'] and
          any(r['record_id'] == 'R4' for r in corrected['context_records']))
    control_folder = BASE/'full/probes/CP06'
    control_payload, _ = call(control_folder, 'check_work')
    control_trace = read(control_folder/'result.json')['extraction']['_task_trace']
    control = reduce_v2(pipeline(control_trace, control_trace), control_payload['meeting'], control_payload['history'])
    check('CP06 genuine goal-linked implicit need remains reviewable',
          len(control['review_records']) == 1 and control['review_records'][0]['category'] == 'implicit_need' and not control['items'])
    return dict(original=observable(baseline), hypothetical_verified_context=observable(corrected),
                genuine_need_control=observable(control),
                limit='Oracle closure proves merge/identity supports context_only. It does not prove a prompt change makes the model produce or verify that closure.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=ROOT/'runs/2026-11-15-context-v2-diagnosis')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    before = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for folder in ('meeting_eval', 'prompts') for p in (ROOT/folder).rglob('*')
              if p.is_file() and '__pycache__' not in p.parts}
    results = dict(C19=c19(), HT04=ht04(), C23=c23(), CP01=cp01())
    check('Production and prompts unchanged', all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == h for p,h in before.items()))
    check('Original evidence unchanged', all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == h for p,h in SOURCES.items()))
    summary = dict(network_calls=0, production_changed=False, assertions=ASSERTIONS, passed=len(ASSERTIONS),
                   cases=results, source_sha256=SOURCES, production_sha256=before)
    (args.out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(f'{len(ASSERTIONS)} diagnostic assertions passed; 0 network calls; production unchanged.')


if __name__ == '__main__':
    main()
