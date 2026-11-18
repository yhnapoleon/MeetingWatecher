"""Frozen targeted cases through real Extractor/Service, paired by upstream cache."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT/'runs/2026-11-15-field-preservation'
sys.path.insert(0, str(ROOT))
if '--baseline' in sys.argv:
    sys.path.insert(0, str(BASE/'baseline-code'))
from meeting_eval.extract import Extractor
from meeting_eval.inputs import digest
from meeting_eval.service import Service
from meeting_eval.store import Store
from scripts.run_action_baseline import write_json

spec = importlib.util.spec_from_file_location('cache_helpers', ROOT/'experiments/task-updates/run.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def one(case, variant):
    out = BASE/variant/case['id']
    out.mkdir(parents=True, exist_ok=False)
    imported = []
    if variant == 'repaired':
        imported = helper.seed_raw(BASE/'baseline'/case['id']/'model', out/'model', {'track_context', 'facts', 'decisions'})
    write_json(out/'cache-provenance.json', dict(imported=imported))
    extractor = Extractor(ROOT.parent.parent/'meeting-agent/.env', out/'model', 'context-v1',
                          inference_config=read(ROOT/'experiments/action-context/compact-check.json'))
    write_json(out/'config.json', extractor.config)
    store = Store(out/'state.sqlite')
    try:
        service = Service(store, extractor)
        result = service.process(case['meeting'], 'host', '2026-11-15T10:00:00+08:00')
        write_json(out/'result.json', result)
        tasks = store.tasks()
        write_json(out/'tasks.json', tasks)
        reviews = service.requirements(result['source_id'], 'host')
        write_json(out/'reviews.json', reviews)
        (out/'minutes.md').write_text(service.minutes(result['source_id'], 'host'), encoding='utf-8')
        expected = case['expected']
        items = result['extraction']['items']
        checks = dict(processed=result['status']=='processed', created=len(tasks)==expected['created'],
                      items=len(items)==expected['items'], review=bool(reviews)==expected['review'])
        if 'due_text' in expected:
            checks['deadline'] = len(tasks)==1 and tasks[0].get('due_text')==expected['due_text'] and tasks[0].get('due_date') is None
        if expected.get('no_date'):
            checks['no_date'] = all(i.get('due_date') is None and i.get('due_text') is None for i in items)
        if expected.get('missing'):
            checks['correct_gap'] = any(set(expected['missing'])<=set(r['missing_fields']) for r in reviews)
        if expected.get('category'):
            checks['category'] = any(r['category']==expected['category'] for r in reviews)
        row = dict(case_id=case['id'], checks=checks, passed=all(checks.values()), errors=result['extraction'].get('_errors', []))
        write_json(out/'checks.json', row)
        return row
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    fixture = read(Path(__file__).with_name('fixtures.json'))
    assert digest(fixture['cases']) == fixture['cases_hash']
    variant = 'baseline' if args.baseline else 'repaired'
    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(one, case, variant) for case in fixture['cases']]
        for future in as_completed(futures):
            row = future.result(); rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    write_json(BASE/variant/'summary.json', dict(results=rows, passed=sum(r['passed'] for r in rows), total=len(rows), is_blind=False))


if __name__ == '__main__':
    main()
