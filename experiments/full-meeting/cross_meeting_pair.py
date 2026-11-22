"""Two complete AMI meetings, fresh inference, one shared local history store."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.extract import Extractor
from meeting_eval.service import Service
from meeting_eval.store import Store

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location('full_meeting', Path(__file__).with_name('run.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for mid in ('ES2002b', 'ES2002c'):
        module.MID = mid
        directory = out / mid
        module.prepare(directory)
        raw = json.loads((directory/'input.json').read_text(encoding='utf-8'))
        raw['series'] = 'AMI-ES2002-cross-meeting'
        raw['account_map'] = {p['person_ref']: 'demo-'+p['person_ref'] for p in raw['participants']}
        write(directory/'input.json', raw)
        write(directory/'inference.json', json.loads((ROOT/'config/context-v5-v19.json').read_text()))
        manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        manifest.update(scope='Complete transcript; ordered pair; shared SQLite; fresh context-v5 v19 with decision review',
            prior_exposure='ES2002 excerpts and earlier single-meeting runs exist; this is a continuity case study, not an unseen benchmark',
            account_scope='Explicit demo accounts in the local Simulator only; no Feishu writes',
            timestamp_scope='2026 timestamps are import order, not historical recording timestamps',
            inference=json.loads((directory/'inference.json').read_text()))
        write(directory/'manifest.json', manifest)
    write(out/'reference-before-run.json', {
        'basis': 'AMI manual annotations and direct reading of ES2002b/c; frozen before fresh inference',
        'checks': [
            {'id':'audience','expected':'c reaffirms b target age 15–35; one effective version', 'c_seconds':[30.29,42.14]},
            {'id':'power','expected':'c initially reaffirms non-rechargeable battery, then replaces with kinetic support plus battery backup; retain history', 'c_seconds':[30.29,42.14,1916.32,1987.97]},
            {'id':'grouping','expected':'c recalls audio/visual/other categories from b; not a brand-new unrelated decision', 'c_seconds':[30.29,47.59]},
            {'id':'marketing','expected':'Andrew trend presentation relates to b trend-watching assignment; distinguish report from new work and explicit completion', 'c_seconds':[186.86,420]},
            {'id':'interface','expected':'Craig interface research relates to b interface assignment; no duplicate task from report alone', 'c_seconds':[664.93,900]},
            {'id':'components','expected':'David component presentation relates to b components assignment; no duplicate task from report alone', 'c_seconds':[957.91,1290]},
        ],
        'limits':'Focused continuity checks, not exhaustive task/decision recall; manual reference never sent to model',
    })

def run(out):
    assert not (out/'state.sqlite').exists(), 'Use a fresh directory; no whole-meeting reruns'
    settings = json.loads((ROOT/'config/context-v5-v19.json').read_text())
    extractor = Extractor(ROOT.parent.parent/'meeting-agent/.env', out/'model', 'context-v5',
                          inference_config=settings, review_decisions=True)
    write(out/'config.json', extractor.config)
    store = Store(out/'state.sqlite')
    summary = []
    saved = []
    series = 'AMI-ES2002-cross-meeting'
    try:
        service = Service(store, extractor)
        for mid, at in [('ES2002b','2026-11-18T10:00:00+08:00'), ('ES2002c','2026-11-18T12:00:00+08:00')]:
            directory = out/mid
            raw = json.loads((directory/'input.json').read_text(encoding='utf-8'))
            context = service.context(series, 'evaluator', at)
            write(directory/'context-before.json', context)
            print(f'START {mid}: {len(raw["segments"])} segments, history {len(context["tasks"])} tasks / {len(context["decisions"])} decisions', flush=True)
            started = time.monotonic()
            before = len(list((out/'model').rglob('meta.json')))
            result = service.process(raw, 'evaluator', at)
            write(directory/'result.json', result)
            sid = result['source_id']
            (directory/'minutes.md').write_text(service.minutes(sid,'evaluator'), encoding='utf-8')
            write(directory/'requirements.json', service.requirements(sid,'evaluator'))
            write(directory/'state-after.json', {'tasks':store.tasks(), 'active':service.decisions(series,'evaluator',at),
                  'history':service.decisions(series,'evaluator',at,history=True), 'recap':service.recap(series,'evaluator',at)})
            after = len(list((out/'model').rglob('meta.json')))
            duplicate_checked = result['status']=='processed'
            if duplicate_checked:
                repeat = service.process(raw,'evaluator',at)
                assert repeat == result
                assert len(list((out/'model').rglob('meta.json')))==after
            saved.append((sid, service.result(sid)))
            row = {'meeting':mid,'status':result['status'],'seconds':round(time.monotonic()-started,2),
                   'calls':after-before,'errors':result['extraction'].get('_errors',[]),
                   'repeat_no_calls':duplicate_checked}
            summary.append(row)
            write(out/'progress.json',summary)
            print(json.dumps(row,ensure_ascii=False),flush=True)
        final = {'active':service.decisions(series,'evaluator',at), 'history':service.decisions(series,'evaluator',at,history=True),
                 'tasks':store.tasks()}
        write(out/'storage.json',final)
    finally:
        store.close()
    reopened = Store(out/'state.sqlite')
    try:
        reader = Service(reopened)
        assert all(reader.result(sid)==value for sid,value in saved)
        assert reader.decisions(series,'evaluator',at)==final['active']
        assert reopened.tasks()==final['tasks']
    finally:
        reopened.close()
    metas=[json.loads(p.read_text()) for p in (out/'model').rglob('meta.json')]
    write(out/'summary.json', {'meetings':summary,'reopen_consistent':True,'calls':len(metas),
        'tokens':sum((m.get('usage') or {}).get('total_tokens',0) for m in metas)})
    print('PAIR COMPLETE',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    (run if args.live else prepare)(args.out)
