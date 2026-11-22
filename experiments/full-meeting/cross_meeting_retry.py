"""One existing Service recovery grant on a copy of the completed pair database."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.extract import Extractor
from meeting_eval.service import Service
from meeting_eval.store import Store


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def run(out):
    recovery = out/'recovery'
    recovery.mkdir(exist_ok=False)
    with sqlite3.connect(out/'state.sqlite') as source, sqlite3.connect(recovery/'state.sqlite') as target:
        source.backup(target)
    original = json.loads((out/'ES2002c/result.json').read_text(encoding='utf-8'))
    assert original['status'] == 'partial'
    extractor = Extractor(ROOT.parent.parent/'meeting-agent/.env', out/'model', 'context-v5',
        inference_config=json.loads((ROOT/'config/context-v5-v19.json').read_text()), review_decisions=True)
    before = set((out/'model').rglob('meta.json'))
    started = time.monotonic()
    store = Store(recovery/'state.sqlite')
    try:
        service = Service(store, extractor)
        result = service.retry_extraction(original['source_id'], 'evaluator',
            'ami-bc-one-stage-recovery', '2026-11-18T12:00:00+08:00')
        write(recovery/'result.json', result)
        (recovery/'minutes.md').write_text(service.minutes(result['source_id'], 'evaluator'), encoding='utf-8')
        write(recovery/'requirements.json', service.requirements(result['source_id'], 'evaluator'))
        state = {'tasks': store.tasks(),
            'active': service.decisions('AMI-ES2002-cross-meeting', 'evaluator', '2026-11-18T12:00:00+08:00'),
            'history': service.decisions('AMI-ES2002-cross-meeting', 'evaluator', '2026-11-18T12:00:00+08:00', history=True)}
        write(recovery/'storage.json', state)
        after = set((out/'model').rglob('meta.json'))
        assert service.retry_extraction(original['source_id'], 'evaluator',
            'ami-bc-one-stage-recovery', '2026-11-18T12:00:00+08:00') == result
        assert set((out/'model').rglob('meta.json')) == after
    finally:
        store.close()
    reopened = Store(recovery/'state.sqlite')
    try:
        assert Service(reopened).result(original['source_id']) == result
        assert reopened.tasks() == state['tasks']
    finally:
        reopened.close()
    metas = [json.loads(p.read_text()) for p in after-before]
    summary = {'scope':'One stage recovery grant; baseline database and baseline result remain unchanged',
        'status':result['status'], 'seconds':round(time.monotonic()-started,2),
        'calls':len(metas), 'tokens':sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),
        'stages':[m['stage'] for m in metas], 'errors':result['extraction'].get('_errors',[]),
        'repeat_no_calls':True, 'reopen_consistent':True}
    write(recovery/'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out)
