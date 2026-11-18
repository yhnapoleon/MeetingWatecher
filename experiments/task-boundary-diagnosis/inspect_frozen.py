"""Inspect frozen traces and replay reducers. No model calls or baseline writes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.context_state import reduce_context
from meeting_eval.inputs import normalize

BASE = ROOT / 'runs/2026-11-15-full-validation'
CASES = ['C01', 'C04', 'C05', 'C06', 'C24', 'C26', 'C30', 'C29', 'C17', 'C11']


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_summary(record):
    return {k: v for k, v in record.items() if k != 'check'}


def collect(result_path, source):
    result = read(result_path)
    extraction = result['extraction']
    trace = extraction['_task_trace']
    repair = trace.get('repair')
    initial = repair['before'] if repair else trace
    return dict(
        result_path=result_path.relative_to(ROOT).as_posix(), sha256=sha(result_path),
        source=source, ledger=trace.get('ledger'),
        initial_records=initial['records'], initial_events=initial['events'],
        initial_record_checks=[dict(record_id=r['record_id'], **r['check']) for r in initial['checked_records']],
        final_records=[record_summary(r) for r in trace['checked_records']],
        final_events=trace['checked_events'],
        repair=None if not repair else {k: repair[k] for k in ('status', 'target_record_ids')},
        facts=extraction['facts'], decisions=extraction['decisions'], unresolved=extraction['unresolved'],
        items=extraction['items'], updates=extraction['updates'],
        review_records=trace['review_records'], pending=trace['pending'],
    )


def replay(path, raw):
    extraction = read(path)['extraction']
    trace = extraction['_task_trace']
    reduced = reduce_context(trace['checked_events'], trace['uncovered_spans'],
                             trace['checked_records'], normalize(raw, 'evaluator'), {'tasks': []})
    expected = {k: extraction[k] for k in ('items', 'updates')}
    expected.update({k: trace[k] for k in ('pending', 'review_records', 'item_records', 'reports')})
    differences = [k for k, v in expected.items() if reduced[k] != v]
    if differences:
        raise AssertionError(f'Frozen reducer differs: {path}: {differences}')
    return dict(case_id=raw['case_id'], matched_fields=list(expected),
                items=len(reduced['items']), cards=len(reduced['review_records']))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    inputs = {r['case_id']: r for r in map(json.loads, (BASE / 'corpus/input.jsonl').read_text(encoding='utf-8').splitlines())}
    evidence = [collect(BASE / 'corpus' / cid / 'result.json', inputs[cid]) for cid in CASES]
    evidence += [collect(BASE / rel, read(ROOT / 'examples/m2.json')) for rel in
                 ('cross-meeting/m2-result.json', 'updates/M2/result.json')]
    evidence.append(collect(BASE / 'recovery/corpus/C14/result.json', inputs['C14']))
    replays = [replay(BASE / 'corpus' / cid / 'result.json', inputs[cid]) for cid in CASES]
    replays.append(replay(BASE / 'recovery/corpus/C14/result.json', inputs['C14']))
    frozen_comparison = []
    with zipfile.ZipFile(BASE / 'source.zip') as archive:
        for name in archive.namelist():
            current = ROOT / name
            if current.is_file() and current.suffix in ('.py', '.txt'):
                frozen_comparison.append(dict(path=name, current_sha256=sha(current),
                    frozen_sha256=hashlib.sha256(archive.read(name)).hexdigest(),
                    matches=current.read_bytes() == archive.read(name)))
    surface = []
    for p in sorted((BASE / 'corpus').glob('C*/result.json')):
        extraction = read(p)['extraction']
        surface.append(dict(case_id=p.parent.name, items=len(extraction['items']),
                            cards=len(extraction.get('_task_trace', {}).get('review_records', []))))
    summary = dict(model_calls=0, baseline='runs/2026-11-15-full-validation',
        inspected_traces=len(evidence), frozen_reducer_replays=replays,
        compared_files=len(frozen_comparison),
        changed_since_snapshot=[x['path'] for x in frozen_comparison if not x['matches']],
        corpus_items=sum(r['items'] for r in surface), corpus_review_cards=sum(r['cards'] for r in surface),
        note='Reducer replay proves deterministic routing of stored interpretations, not model reproducibility or improvement.')
    # A fresh directory prevents accidental replacement of another investigation.
    args.output.mkdir(parents=True, exist_ok=False)
    for name, content in [('evidence.json', evidence), ('summary.json', summary),
                          ('source-comparison.json', frozen_comparison), ('corpus-surfaces.json', surface)]:
        (args.output / name).write_text(json.dumps(content, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
