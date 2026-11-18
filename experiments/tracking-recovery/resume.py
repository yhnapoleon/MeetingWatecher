"""Authorized post-payment recovery on a copy; preserve all original evidence.

402 is intentionally terminal in production. This experiment-only maintenance
entry archives only verified HTTP-402 nodes before normal Service.process retry.
It never resets content-exhaustion budgets or accepted node caches.
"""
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'experiments/task-boundary')]
from run import read,configure
from meeting_eval.extract import Extractor
from meeting_eval.service import Service
from meeting_eval.store import Store
from scripts.replay_mvp import audit
from scripts.run_action_baseline import write_json
from run_system_validation import accounting

BASE=ROOT/'runs/2026-11-17-tracking-recovery-v2'


def prepare(source,out):
    shutil.copytree(source,out)
    archived=[];accepted={}
    for state_path in list((out/'model').rglob('state.json')):
        state=read(state_path)
        if state.get('status')=='accepted':
            for p in state_path.parent.rglob('meta.json'):
                accepted[p.relative_to(out).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
        if state.get('status')!='terminal_error':continue
        last=state['attempts'][-1]
        last_meta=state_path.parent/last['directory']/'meta.json'
        if not last_meta.exists() or read(last_meta).get('http_status')!=402:
            raise ValueError('Refusing to reset a non-payment terminal node: '+str(state_path))
        node=state_path.parent;relative=node.relative_to(out/'model')
        destination=out/'payment-error-archive'/relative
        assert node.resolve().is_relative_to(out.resolve()) and destination.resolve().is_relative_to(out.resolve())
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.move(str(node),str(destination))
        archived.append(relative.as_posix())
    write_json(out/'payment-resume.json',dict(authorization='User authorized post-payment necessary node continuation',
        source=source.relative_to(ROOT).as_posix(),archived_http402_nodes=archived,accepted_metadata_sha256=accepted))
    return accepted


def one(job,source,out,config):
    before=accounting(source);accepted=prepare(source,out);started=time.perf_counter()
    ex=Extractor(ROOT.parent.parent/'meeting-agent/.env',out/'model','context-v5',inference_config=config)
    configure(ex,'b',None,'none')
    assert ex.config==read(source/'config.json')
    store=Store(out/'state.sqlite')
    try:
        svc=Service(store,ex)
        result=svc.process(job['meeting'],job.get('actor','evaluator'),'2026-11-17T12:00:00+08:00')
        write_json(out/'result.json',result);write_json(out/'tasks.json',store.tasks());audit(store,out/'operations.jsonl')
        (out/'minutes.md').write_text(svc.minutes(result['source_id'],job.get('actor','evaluator')),encoding='utf8')
    finally:store.close()
    for relative,expected in accepted.items():assert hashlib.sha256((out/relative).read_bytes()).hexdigest()==expected
    after=accounting(out)
    row=dict(case_id=job['id'],status=result['status'],seconds=round(time.perf_counter()-started,3),**after,
        added_calls=after['calls']-before['calls'],added_tokens=after['tokens']-before['tokens'],
        accepted_metadata_unchanged=len(accepted),still_payment_blocked=any('402' in e.get('detail','') for e in result['extraction']['_errors']))
    write_json(out/'summary.json',row);print(job['id'],row['status'],'added_calls',row['added_calls'],flush=True)
    return row


def main():
    source=BASE/'focus';out=BASE/'payment-resume';out.mkdir(exist_ok=False)
    manifest=read(source/'manifest.json');write_json(out/'manifest.json',manifest)
    shutil.copy2(source/'source.zip',out/'source.zip')
    rows=[];started=time.perf_counter();jobs=manifest['jobs']
    # A required node is the payment probe: do not fan out if 402 persists.
    first=next(j for j in jobs if j['id']=='GN25')
    rows.append(one(first,source/first['group']/first['id'],out/first['group']/first['id'],manifest['inference']))
    write_json(out/'progress.json',rows)
    if not rows[0]['still_payment_blocked']:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(one,j,source/j['group']/j['id'],out/j['group']/j['id'],manifest['inference']) for j in jobs if j!=first]
            for future in as_completed(futures):
                rows.append(future.result());write_json(out/'progress.json',rows)
    write_json(out/'summary.json',dict(rows=rows,cases=len(rows),**accounting(out),seconds=round(time.perf_counter()-started,3),
        added_calls=sum(r['added_calls'] for r in rows),added_tokens=sum(r['added_tokens'] for r in rows)))


if __name__=='__main__':main()
