"""First-pass contrasts through the normal Service entry point."""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.extract import Extractor
from meeting_eval.inputs import digest
from meeting_eval.service import Service
from meeting_eval.store import Store
from scripts.run_action_baseline import write_json

BASE = ROOT/'runs/2026-11-15-pragmatic-checking'
OLD = ROOT/'runs/2026-11-15-field-preservation'
spec = importlib.util.spec_from_file_location('seed', ROOT/'experiments/task-updates/run.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def read(p): return json.loads(p.read_text(encoding='utf-8'))


def one(case, variant):
    out = BASE/variant/case['id']
    out.mkdir(parents=True, exist_ok=False)
    stages = {'track_context', 'facts', 'decisions'}
    if variant == 'check-only': stages.add('interpret_work')
    source = ROOT/case.get('source', str((OLD/'regression'/'model').relative_to(ROOT)))
    if variant == 'integrated':
        source = BASE/'interpret-check'/case['id']/'model'
        stages.update({'interpret_work','check_work'})
    if variant == 'check-frozen-recovered':
        source = BASE/'check-frozen'/case['id']/'model'
        stages.add('check_work')
    imported = helper.seed_raw(source, out/'model', stages, latest=True) if source.exists() else []
    write_json(out/'cache-provenance.json', {'imported': imported})
    extractor = Extractor(ROOT.parent.parent/'meeting-agent/.env', out/'model', 'context-v1',
                          inference_config=read(ROOT/'experiments/action-context/compact-check.json'))
    pipe = extractor.task_pipeline
    if variant == 'check-only':
        with zipfile.ZipFile(BASE/'before.zip') as archive:
            pipe.prompts['interpret_work'] = archive.read('prompts/interpret-work-context-v1.txt').decode('utf-8')
        pipe.config['prompts']['interpret_work'] = digest(pipe.prompts['interpret_work'])
    if variant.startswith('check-frozen'):
        trace = read(OLD/'regression'/(case['id']+'.json'))['extraction']['_task_trace']
        original_call = extractor.client.call
        def frozen_call(prompt,payload,stage,*args,**kwargs):
            if stage=='interpret_work':
                return copy.deepcopy(dict(case_id=case['id'],records=trace['records'],events=trace['events']))
            return original_call(prompt,payload,stage,*args,**kwargs)
        extractor.client.call = frozen_call
        write_json(out/'frozen-interpretation.json',dict(source=str(OLD/'regression'/(case['id']+'.json')),
                   records_hash=digest(trace['records']),events_hash=digest(trace['events'])))
    if variant in ('check-only', 'interpret-check') or variant.startswith('check-frozen'):
        pipe.repair_enabled = False
        pipe.config['repair_enabled'] = False
    write_json(out/'config.json', extractor.config)
    write_json(out/'input.json', case)
    store = Store(out/'state.sqlite')
    try:
        svc = Service(store, extractor)
        for task in case.get('tasks', []):svc.sim.seed(task, '2026-11-15T00:00:00+08:00')
        result = svc.process(case['meeting'], case.get('actor', 'evaluator'), '2026-11-15T10:00:00+08:00')
        write_json(out/'result.json', result)
        write_json(out/'tasks.json', store.tasks())
        (out/'minutes.md').write_text(svc.minutes(result['source_id'], case.get('actor', 'evaluator')), encoding='utf-8')
        reused = {i['path'] for i in imported}
        fresh = [read(p) for p in (out/'model').rglob('meta.json') if str(p.relative_to(out)) not in reused]
        row = dict(case_id=case['id'], status=result['status'], items=result['extraction']['items'],
                   errors=result['extraction'].get('_errors', []), calls=len(fresh),
                   tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in fresh))
        write_json(out/'summary.json', row)
        return row
    finally:store.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--variant', required=True)
    p.add_argument('--fixture', default='regression.json')
    args = p.parse_args()
    fixture = read(Path(__file__).with_name(args.fixture))
    assert digest(fixture['cases']) == fixture['cases_hash']
    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for f in as_completed([pool.submit(one, c, args.variant) for c in fixture['cases']]):
            row = f.result(); rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    write_json(BASE/args.variant/'summary.json', rows)


if __name__ == '__main__':main()
