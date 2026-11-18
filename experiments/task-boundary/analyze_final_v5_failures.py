"""Diagnose saved final v5 failures offline; never call a model or edit inputs."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.context_state import ledger_candidates
from meeting_eval.context_tracking_v5 import expand_delta
from meeting_eval.context_v2 import reduce_v2
from meeting_eval.context_v3 import reduce_v3

SOURCE = ROOT / 'runs/2026-11-16-context-v5-fixes/full-compact-final'
DEST = ROOT / 'runs/2026-11-16-context-v5-final-failure-analysis'
READ_HASHES = {}


def read(path):
    data = path.read_bytes()
    READ_HASHES[str(path.relative_to(ROOT)).replace('\\', '/')] = hashlib.sha256(data).hexdigest()
    return json.loads(data)


def calls(key):
    result = []
    for path in sorted((SOURCE / key / 'model').rglob('meta.json')):
        meta = read(path)
        request = read(path.with_name('request.json'))
        response = read(path.with_name('response.json'))
        choice = response['choices'][0]
        content = choice['message'].get('content') or ''
        try:
            output = json.loads(content)
        except json.JSONDecodeError:
            output = None
        result.append(dict(path=str(path.parent.relative_to(ROOT)).replace('\\', '/'),
            stage=meta['stage'], request=request, payload=json.loads(request['messages'][1]['content']),
            output=output, content=content, finish_reason=choice['finish_reason'], usage=response.get('usage', {})))
    return result


def load_case(key):
    inp = read(SOURCE / key / 'input.json')
    final = read(SOURCE / key / 'result.json')
    return inp, final['extraction'], calls(key)


def main():
    if DEST.exists():
        raise SystemExit(f'Refusing to overwrite evidence: {DEST}')
    # Replay the very code captured with the evaluated run.
    code_matches = []
    with zipfile.ZipFile(SOURCE / 'source.zip') as frozen:
        for name in frozen.namelist():
            if name.endswith('/'):
                continue
            assert (ROOT / name).read_bytes() == frozen.read(name), name
            code_matches.append(name)
    failures = read(SOURCE / 'failure-index.json')['rows']
    facts_categories = {'stale_unresolved', 'quoted_unresolved', 'description_drift', 'retrospective_unresolved'}
    rows = []
    for failure in failures:
        key = failure['key']
        inp, ext, requests = load_case(key)
        trace = ext.get('_task_trace', {})
        row = dict(key=key, categories=failure['categories'], final_review=failure['note'],
            source=inp['meeting']['segments'], unresolved=ext['unresolved'], items=ext['items'],
            review_records=trace.get('review_records', []), errors=ext.get('_errors', []),
            ledger=trace.get('ledger'), checked_records=trace.get('checked_records', []))
        row['stages'] = [dict(path=c['path'], stage=c['stage'], finish_reason=c['finish_reason'],
            usage=c['usage'], content_chars=len(c['content']), output=c['output']) for c in requests]
        if facts_categories.intersection(failure['categories']):
            fact = next(c for c in requests if c['stage'] == 'facts')
            assert fact['output']['unresolved'] == ext['unresolved'], key
            source = [(s['id'], s['text']) for s in inp['meeting']['segments']]
            supplied = [(s['id'], s['text']) for s in fact['payload']['meeting']['segments']]
            assert source == supplied, key
            checks = [c for c in requests if c['stage'] == 'check_work']
            assert checks and all('unresolved' not in c['payload'] for c in checks), key
            row['facts_verification'] = dict(raw_unresolved_equals_final=True,
                complete_source_supplied=True, work_check_has_no_unresolved_field=True)
        rows.append(row)
    assert len(rows) == 18
    assert sum('facts_verification' in r for r in rows) == 10

    inp, ext, requests = load_case('r1/updates/HT04')
    pipeline = read(next((SOURCE / 'r1/updates/HT04/model/context_v2').rglob('result.json')))
    history = next(c['payload']['history'] for c in requests if c['stage'] == 'interpret_work')
    before = reduce_v2(pipeline, inp['meeting'], history)
    after = reduce_v3(pipeline, inp['meeting'], history)
    assert after['review_records'] == ext['_task_trace']['review_records']
    assert before['review_records'][0]['missing_fields'] == ['commitment']
    assert after['review_records'][0]['missing_fields'] == []
    assert after['review_records'][0]['question'].startswith(before['review_records'][0]['question'])
    assert not after['items'] and not after['updates']
    # Single-variable intervention: supply the missing relation gap at the reducer boundary.
    supplied = copy.deepcopy(pipeline)
    record = supplied['checked_records'][0]
    record['gap_checks'] = [dict(field='relation', verdict='supported', blocking_for='operation',
        reason='Two candidate historical tasks have identical summaries.', evidence=['Q1'])]
    record['clarification'].update(status='needed', fields=['relation'], question='这次完成的是哪一条旧任务？')
    intervention = reduce_v3(supplied, inp['meeting'], history)
    assert intervention['review_records'][0]['missing_fields'] == ['relation']
    assert intervention['review_records'][0]['question'].startswith('这次完成的是哪一条旧任务？')
    assert not intervention['items'] and not intervention['updates']
    ht04 = dict(replayed_saved_output=True, reduce_v2=before['review_records'],
        reduce_v3=after['review_records'], supplied_relation_gap=intervention['review_records'],
        limitation='Intervention changes only an in-memory checked-record gap, not production code or model output.')

    _, _, requests = load_case('r1/corpus/C14')
    broken = next(c for c in requests if c['stage'] == 'track_context' and c['output'] is None)
    try:
        json.loads(broken['content'])
        raise AssertionError('Expected JSON error')
    except json.JSONDecodeError as error:
        assert error.pos == 811
        position = error.pos
    corrected_text = broken['content'][:position] + ']' + broken['content'][position:]
    corrected = json.loads(corrected_text)
    ledger = expand_delta(corrected, broken['payload'])
    c14 = dict(request=broken['path'], finish_reason=broken['finish_reason'], error_position=position,
        original_tail=broken['content'][-100:], inserted_character=']', json_and_delta_validation_passed=True,
        ledger=ledger, candidate_count=len(ledger_candidates(ledger)),
        limitation='One-character offline probe only; downstream interpretation was not run, so task recovery is unproven.')

    cp01 = []
    for key in ('r1/probes/CP01', 'r2/probes/CP01'):
        inp, _, requests = load_case(key)
        tracks = [c for c in requests if c['stage'] == 'track_context']
        assert len(tracks) == 1
        call = tracks[0]
        assert call['finish_reason'] == 'length' and call['request']['max_tokens'] == 16384
        assert len(call['payload']['meeting']['segments']) == 8 and len(inp['meeting']['segments']) == 10
        cp01.append(dict(key=key, request=call['path'], max_tokens=call['request']['max_tokens'],
            usage=call['usage'], content_chars=len(call['content']), input_segments=8, full_segments=10,
            unreached_segments=inp['meeting']['segments'][8:]))

    controls = {}
    for key in ('r2/corpus/C11', 'r1/corpus/C20', 'r2/updates/HT04', 'r2/pairs/P05b', 'r1/corpus/C13'):
        _, ext, requests = load_case(key)
        trace = ext.get('_task_trace', {})
        controls[key] = dict(unresolved=ext['unresolved'], ledger=trace.get('ledger'),
            checked_records=trace.get('checked_records'), review_records=trace.get('review_records'),
            stages=[dict(stage=c['stage'], path=c['path'], output=c['output']) for c in requests
                    if c['stage'] in ('interpret_work', 'check_work', 'repair_work', 'recheck_work')])
    # Confirm analysis and all offline interventions left saved run evidence untouched.
    assert all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
               for name, digest in READ_HASHES.items())
    report = dict(source=str(SOURCE.relative_to(ROOT)).replace('\\', '/'), model_calls=0,
        code_snapshot_matches=len(code_matches), failures=rows, ht04_replay=ht04, c14_probe=c14,
        cp01=cp01, successful_controls=controls, unchanged_read_files=READ_HASHES)
    DEST.mkdir(parents=True)
    (DEST / 'analysis.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(failures=len(rows), facts_failures=10, model_calls=0,
        code_snapshot_matches=len(code_matches), unchanged_read_files=len(READ_HASHES),
        ht04_replayed=True, c14_json_and_delta_validated=True, output=str(DEST / 'analysis.json')), ensure_ascii=False))


if __name__ == '__main__':
    main()
