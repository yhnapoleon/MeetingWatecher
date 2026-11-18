"""Offline provenance checks and user-authorized C23 regrading; no model client."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).parent)]
from meeting_eval.context_protocol import validate_schema
from meeting_eval.context_protocol_v3 import REPAIR, prompt_schema, evidence_catalog
from meeting_eval.context_coverage import plan_repair
from meeting_eval.inputs import digest
from run_context_v4 import PromptOnly, INFERENCE
from scripts.run_action_baseline import write_json


def trace_question(out):
    from meeting_eval.context_v3 import reduce_v3
    import meeting_eval.context_v2 as v2
    folder = ROOT/'runs/2026-11-15-context-v4/small-v2/B-r2/M2'
    case, pipeline = read(folder/'input.json'), read(folder/'pipeline.json')
    captured = {}
    original = v2.reduce_context
    def capture(events, uncovered, records, meeting, history):
        record = next(r for r in records if r['record_id']=='R2')
        event = next(e for e in events if e['record_id']=='R2')
        captured.update(record_id='R2', missing_fields=copy.deepcopy(record['missing_fields']),
            question=record['question'], issues=copy.deepcopy(record['check']['issues']),
            gap_checks=copy.deepcopy(record['gap_checks']), commitment=event['commitment']['kind'],
            owner=copy.deepcopy(event['owner']))
        return original(events, uncovered, records, meeting, history)
    with patch.object(v2, 'reduce_context', capture):
        reduced = reduce_v3(pipeline, case['meeting'], case['history'])
    assert reduced['review_records']==read(folder/'summary.json')['reviews']
    assert captured['missing_fields']==[] and captured['question'] is None
    assert reduced['review_records'][0]['missing_fields']==['owner','commitment']
    write_json(out/'question-trace.json', dict(network_calls=0, source=folder.relative_to(ROOT).as_posix(),
        input_to_final_reducer=captured, final_reviews=reduced['review_records'], exact_reproduction=True))


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recorded(folder, stage, case_id=None):
    matches = []
    for p in folder.rglob('meta.json'):
        if read(p)['stage'] != stage:
            continue
        req = read(p.with_name('request.json'))
        payload = json.loads(req['messages'][1]['content'])
        if case_id is not None and payload['meeting']['case_id'] != case_id:
            continue
        response = read(p.with_name('response.json'))
        assert response['choices'][0]['finish_reason'] == 'stop'
        matches.append((p.parent, req, payload, json.loads(response['choices'][0]['message']['content'])))
    assert len(matches) == 1, (folder, stage, len(matches))
    return matches[0]


def trace_protocol(out):
    base = ROOT / 'runs/2026-11-16-baseline-reassessment'
    source, request, payload, raw = recorded(base / 'small-v1/A-r1/G-omitted', 'repair_work')
    validate_schema(raw, REPAIR)
    record_schema = REPAIR['properties']['records']['items']
    binding = dict(source=source.relative_to(ROOT).as_posix(), raw_record=raw['records'][0],
        prose_mentions_field='introduced_by' in request['messages'][0]['content'],
        schema_defines_field='introduced_by' in record_schema['properties'],
        schema_requires_field='introduced_by' in record_schema['required'],
        generated_example_includes_field='introduced_by' in prompt_schema(REPAIR),
        missing_field_passes_initial_schema=True,
        raw_response_sha256=sha(source / 'response.json'))
    assert 'introduced_by' not in binding['raw_record']
    assert binding['prose_mentions_field'] and binding['schema_defines_field']
    assert not binding['schema_requires_field'] and not binding['generated_example_includes_field']
    pipe = PromptOnly(SimpleNamespace(model='deepseek-flash', endpoint='offline-only'), out, INFERENCE)
    rows = []
    for name in ('a-cross-r2', 'small-v1/D-r2/G-omitted'):
        source, request, payload, raw = recorded(base / name, 'check_work', 'M2' if name == 'a-cross-r2' else 'G-same-segment')
        expected = {e['event_id'] for e in payload['events']}
        actual = {e['event_id'] for e in raw['checks']}
        interpreted = {k: payload[k] for k in ('records','events','candidates')}
        catalog = evidence_catalog(payload['meeting'])
        try:
            pipe.check(raw, interpreted, payload['meeting'], catalog)
        except ValueError as exc:
            error = str(exc)
        else:
            raise AssertionError('Recorded invalid event collection unexpectedly passed')
        changed = copy.deepcopy(raw)
        changed['checks'] = [r for r in changed['checks'] if r['event_id'] in expected]
        checked = pipe.check(changed, interpreted, payload['meeting'], catalog)
        plan = plan_repair(checked['checked_records'], changed['coverage_findings'], catalog, 'offline-diagnostic')
        assert expected == {'E1'} and actual == {'E1','E2'} and error == 'Incomplete event checks'
        rows.append(dict(run=name, source=source.relative_to(ROOT).as_posix(),
            input_event_ids=sorted(expected), output_event_ids=sorted(actual),
            missing_ids=sorted(expected-actual), extra_ids=sorted(actual-expected), error=error,
            extra_checks=[r for r in raw['checks'] if r['event_id'] not in expected],
            diagnostic_remove_extra_only=dict(check_passed=True, still_needs_repair=plan['needs_repair'],
                target_record_ids=plan['target_record_ids'], findings=plan['findings']),
            response_sha256=sha(source / 'response.json')))
    write_json(out / 'protocol-trace.json', dict(network_calls=0, introduced_by=binding, event_checks=rows,
        limitation='Removing E2 is an offline isolation test, not a production fix or a new passing model result.'))


def c23_overlay(out):
    # These exact descriptions were read against source before approving the overlay.
    reviewed_descriptions = {
        '会后单独联系袁校长，就其他几个问题继续沟通',
        '会后单独联系袁校长，继续沟通其他几个问题；会上并提到刚才讲解过程中信号不太清楚。',
        '会后由说话人一方单独联系袁校长，沟通其他几个问题；同时提到讲话过程中信号不太清楚。',
    }
    candidates = [('v2', ROOT/'runs/2026-11-15-context-v2/full/corpus/C23')]
    candidates += [('v3', ROOT/f'runs/2026-11-15-context-v3/final-r{r}/C23') for r in (1,2)]
    candidates += [(arm, ROOT/f'runs/2026-11-15-context-v4/{batch}/{arm}-r{r}/C23')
        for arm,batch in [('A','small-v1'),('B','small-v2'),('C','small-v2')] for r in (1,2,3)]
    v2 = next(c for c in read(ROOT/'runs/2026-11-15-context-v2/corpus-review-audited-first.json')['cases'] if c['case_id']=='C23')
    v3 = read(ROOT/'runs/2026-11-15-context-v3/focused-source-review.json')['cases']
    rows = []
    for version, folder in candidates:
        summary = read(folder/'summary.json')
        assert len(summary['items']) == 1 and summary['items'][0]['description'] in reviewed_descriptions, 'Changed output needs source review'
        if version == 'v2':
            judgment = v2['judgments'][0]
            old_pass = all(judgment[k] for k in ('content_supported','content_complete','owner_correct','commitment_correct','time_correct','operation_correct'))
            other_pass = all(judgment[k] for k in ('content_supported','owner_correct','commitment_correct','time_correct','operation_correct'))
        elif version == 'v3':
            old = next(r for r in v3 if r['case']=='C23' and r['batch']==folder.parent.name)
            old_pass, other_pass = old['passed'], old['observable_passed']
        else:
            old = next(r for r in read(folder.parent.parent/'source-review.json')['rows'] if r['case']=='C23' and r['round']==folder.parent.name)
            old_pass, other_pass = old['semantic_case_passed'], old['observable_passed']
        item = summary['items'][0]
        checks = dict(prior_other_checks=other_pass, no_errors=not summary['errors'],
            repair_valid=summary.get('repair')!='failed', candidate=item['operation']=='candidate',
            no_invented_deadline=item['due_date'] is None and item['due_text'] is None,
            only_owner_review=len(summary['reviews'])==1 and summary['reviews'][0]['missing_fields']==['owner'],
            core_content_source_reviewed=True)
        assert not old_pass and all(checks.values())
        rows.append(dict(version=version, source=(folder/'summary.json').relative_to(ROOT).as_posix(),
            output_sha256=sha(folder/'summary.json'), old_passed=old_pass, current_passed=all(checks.values()),
            checks=checks, description=item['description'],
            reason='保留联系对象、会后联系与继续沟通；缺少推断的补问目的不再阻断通过。'))
    policy_path = Path(__file__).with_name('review-policy-2026-11-16.json')
    policy = read(policy_path)
    label = copy.deepcopy(v2['references'][0])
    label.update(description='会后单独联系袁校长，继续沟通其他问题。', required_content=policy['C23']['required_content'],
        review_basis='用户明确放宽推断目的是否必须写入的标准；保留其他语义与操作检查。',
        reviewer=policy['version'])
    write_json(out/'C23-current-label.json', label)
    write_json(out/'c23-review-overlay.json', dict(policy=policy['version'], network_calls=0,
        meaning='User-authorized criterion change, not model improvement. Only C23 original outputs were regraded.',
        totals={v:dict(old_passed=sum(r['old_passed'] for r in rows if r['version']==v),
            current_passed=sum(r['current_passed'] for r in rows if r['version']==v),
            total=sum(r['version']==v for r in rows)) for v in ('v2','v3','A','B','C')}, cases=rows))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    trace_question(args.out)
    trace_protocol(args.out)
    c23_overlay(args.out)
    write_json(args.out/'policy.json', read(Path(__file__).with_name('review-policy-2026-11-16.json')))
    print('Offline diagnosis passed; extra E2 in both failures; 12 C23 outputs regraded under user policy; 0 API calls.')


if __name__ == '__main__':
    main()
