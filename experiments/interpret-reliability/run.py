"""Two-case targeted Service experiment; GN29 reuses validated tracking only."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'experiments/task-boundary')]
from run import read,configure
from run_context_v3 import snapshot
from run_system_validation import accounting
from meeting_eval.extract import Extractor,model_input
from meeting_eval.inputs import digest,normalize
from meeting_eval.context_state import canonical_ledger
from meeting_eval.service import Service
from meeting_eval.store import Store
from scripts.run_action_baseline import write_json
from scripts.replay_mvp import audit

BASE=ROOT/'runs/2026-11-17-interpret-reliability'
PREVIOUS=ROOT/'runs/2026-11-17-tracking-recovery-v2/payment-resume'


def one(job,out,config):
    out.mkdir(parents=True,exist_ok=False);started=time.perf_counter()
    ex=Extractor(ROOT.parent.parent/'meeting-agent/.env',out/'model','context-v5',inference_config=config)
    mode='none';frozen=None
    if job['id']=='GN29':
        mode='ledger';source=PREVIOUS/job['group']/job['id']/'result.json';frozen=read(source)['extraction']
        trace=frozen['_task_trace'];meeting=normalize(job['meeting'],job['actor'],{})
        assert trace['tracking']['status']=='complete'
        assert trace['tracking']['input_hash']==digest(model_input(meeting))
        assert trace['tracking']['completed_segments']==len(meeting['segments'])
        positions={s['id']:i for i,s in enumerate(meeting['segments'])};previous=None
        for checkpoint in trace['checkpoints']:
            end=positions[checkpoint['through_segment']]+1
            previous=canonical_ledger(checkpoint['ledger'],dict(meeting,segments=meeting['segments'][:end]),previous)
            assert previous==checkpoint['ledger']
        assert previous==trace['ledger']
        write_json(out/'frozen-tracking.json',dict(source=source.relative_to(ROOT).as_posix(),
            result_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),checkpoints=len(trace['checkpoints']),
            segments=len(meeting['segments']),input_hash=trace['tracking']['input_hash']))
    configure(ex,'b',frozen,mode)
    write_json(out/'config.json',ex.config);write_json(out/'input.json',job)
    store=Store(out/'state.sqlite')
    try:
        svc=Service(store,ex);result=svc.process(job['meeting'],job['actor'],'2026-11-17T15:00:00+08:00')
        write_json(out/'result.json',result);write_json(out/'tasks.json',store.tasks());audit(store,out/'operations.jsonl')
        (out/'minutes.md').write_text(svc.minutes(result['source_id'],job['actor']),encoding='utf8')
    finally:store.close()
    row=dict(case_id=job['id'],status=result['status'],mode=mode,seconds=round(time.perf_counter()-started,3),**accounting(out))
    write_json(out/'summary.json',row);return row


def main():
    manifest=read(PREVIOUS/'manifest.json');jobs=[j for j in manifest['jobs'] if j['id'] in ('GN25','GN29')]
    assert len(jobs)==2;out=BASE/'focus';out.mkdir(exist_ok=False)
    # Model predictions never receive these labels; hash checks freeze the scoring source.
    freeze=read(ROOT/'data/generalization-v1/freeze.json')
    for rel,expected in freeze['files'].items():
        if rel.startswith('data/generalization-v1/'):assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==expected
    write_json(out/'manifest.json',dict(jobs=jobs,inference=manifest['inference'],rounds=1,case_reruns=0,
        policy='GN29 validated frozen tracking prefix; GN25 normal Service; labels never passed to predictions.'))
    snapshot(out);rows=[];started=time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(one,j,out/j['group']/j['id'],manifest['inference']):j for j in jobs}
        for f in as_completed(futures):
            j=futures[f]
            try:row=f.result()
            except Exception as exc:row=dict(case_id=j['id'],status='runner_failed',error=repr(exc))
            rows.append(row);write_json(out/'progress.json',rows);print(row,flush=True)
    write_json(out/'summary.json',dict(rows=rows,**accounting(out),seconds=round(time.perf_counter()-started,3)))


if __name__=='__main__':main()
