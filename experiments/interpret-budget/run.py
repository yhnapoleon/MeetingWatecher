"""Bounded task-branch experiment using validated frozen tracking."""
import argparse
from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.extract import Extractor,model_input,resolve_calendar_dates
from meeting_eval.inputs import digest,normalize
from meeting_eval.context_state import canonical_ledger,ledger_candidates
from meeting_eval.context_wire import wire_request,wire_prompt
from meeting_eval.model_client import ModelResponseError
from meeting_eval.stage_runner import atomic_json,node_lock
from meeting_eval.service import Service
from meeting_eval.store import Store
from scripts.replay_mvp import audit as operation_audit

PREVIOUS=ROOT/'runs/2026-11-17-interpret-reliability/focus'


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reserve_request(state_path: Path, limit: int = 8) -> None:
    if type(limit) is not int or not 1<=limit<=8:raise ValueError('Request limit must be 1..8')
    state_path=Path(state_path)
    state=read(state_path) if state_path.exists() else dict(limit=limit,used=0)
    if state['limit']!=limit:raise ValueError('Persisted request limit changed')
    if state['used']>=limit:raise ModelResponseError('Experiment HTTP request limit reached','terminal_error')
    state['used']+=1
    atomic_json(state_path,state)


@contextmanager
def limited_http(state_path,limit=8):
    """Runner holds one process lock; only the task pipeline accesses the network."""
    send=urllib.request.urlopen
    def bounded(req,*args,**kwargs):
        request=json.loads(req.data)
        if request.get('max_tokens',0)>32768:raise ValueError('Experiment generation cap exceeded')
        reserve_request(Path(state_path),limit)
        print(json.dumps(dict(event='http_start',request=read(state_path)['used'],
            effort=request.get('reasoning_effort'),thinking=request.get('thinking'),max_tokens=request.get('max_tokens'))),flush=True)
        return send(req,*args,**kwargs)
    with patch('urllib.request.urlopen',side_effect=bounded):yield


def validate_frozen_case(job,trace,prior_payload):
    meeting=normalize(job['meeting'],job['actor'],{})
    tracking=trace['tracking'];projected=model_input(meeting)
    if tracking['status']!='complete' or tracking['completed_segments']!=len(meeting['segments']):
        raise ValueError('Incomplete frozen tracking')
    if tracking['input_hash']!=digest(projected):raise ValueError('Frozen meeting hash mismatch')
    ranges=tracking['accepted_ranges']
    if [i for a,b in ranges for i in range(a,b)]!=list(range(len(meeting['segments']))):
        raise ValueError('Frozen ranges do not cover source')
    positions={s['id']:i for i,s in enumerate(meeting['segments'])};previous=None
    for checkpoint in trace['checkpoints']:
        end=positions[checkpoint['through_segment']]+1
        previous=canonical_ledger(checkpoint['ledger'],dict(meeting,segments=meeting['segments'][:end]),previous)
        if previous!=checkpoint['ledger']:raise ValueError('Frozen checkpoint not canonical')
    if previous!=trace['ledger'] or trace['ledger']!=tracking['last_ledger']:
        raise ValueError('Frozen ledger mismatch')
    payload=dict(meeting=projected,ledger=trace['ledger'],candidates=ledger_candidates(trace['ledger']),history=prior_payload['history'])
    if wire_request(payload)!=prior_payload:raise ValueError('Frozen interpretation payload mismatch')
    if job.get('tasks') or prior_payload['history']!={'tasks':[]}:
        raise ValueError('This experiment supports the frozen empty-history cases only')
    return meeting


def load_frozen_case(case_id: str) -> dict:
    if case_id not in ('GN29','GN25'):raise ValueError('Case outside experiment scope')
    folder=PREVIOUS/'natural'/case_id
    job=read(folder/'input.json');result=read(folder/'result.json');trace=result['extraction']['_task_trace']
    attempts=list(folder.glob('model/context_v2/*/interpret_work/*/attempt-1'))
    if len(attempts)!=1:raise ValueError('Ambiguous prior interpretation request')
    attempt=attempts[0];prior=read(attempt/'stage-request.json');request=read(attempt/'request.json')
    meeting=validate_frozen_case(job,trace,prior)
    paths=[folder/'input.json',folder/'result.json',folder/'config.json',attempt/'stage-request.json',attempt/'request.json']
    return dict(job=job,trace=trace,meeting=meeting,history=prior['history'],prior_payload=prior,
        prior_prompt=request['messages'][0]['content'],config=read(folder/'config.json'),
        source_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in paths})


class TaskOnlyExtractor(Extractor):
    def __init__(self,env_file,out,frozen):
        settings=copy.deepcopy(frozen['config']['task_pipeline']['inference'])
        settings['interpret_work'].update(thinking='enabled',reasoning_effort='low',max_tokens=32768)
        super().__init__(env_file,out,'context-v5',inference_config=settings)
        self.frozen=frozen
        self.config['experiment']=dict(scope='task_branch_only',source_hashes=frozen['source_hashes'])
        def tracking(meeting,folder,trace,resume):
            if model_input(meeting)!=model_input(frozen['meeting']):raise ValueError('Service source differs from frozen input')
            trace.update({k:copy.deepcopy(frozen['trace'][k]) for k in ('checkpoints','tracking')})
            return copy.deepcopy(frozen['trace']['ledger'])
        self.task_pipeline._track_ledger=tracking

    def extract(self,meeting,context,previous=None):
        if context!={'tasks':[],'decisions':[]}:raise ValueError('Service history differs from frozen history')
        result=self.evidence_extract(meeting,context,{'items','updates'},bool(previous))
        result['_experiment']=dict(scope='task_branch_only',skipped=['facts','unresolved','decisions','minutes_review'],
            reused=['validated_tracking'],history_hash=digest(self.frozen['history']))
        resolve_calendar_dates(result,meeting)
        atomic_json(self.out/'task-branch-result.json',result)
        return result


def preflight(ex,frozen):
    payload=wire_request(dict(meeting=model_input(frozen['meeting']),ledger=frozen['trace']['ledger'],
        candidates=ledger_candidates(frozen['trace']['ledger']),history=frozen['history']))
    prompt=wire_prompt(ex.task_pipeline.prompts['interpret_work'],model_input(frozen['meeting']))
    if payload!=frozen['prior_payload'] or prompt!=frozen['prior_prompt']:
        raise ValueError('Preflight interpretation differs from historical control')
    return dict(payload=payload,prompt=prompt,payload_equal=True,prompt_equal=True,
        payload_hash=digest(payload),prompt_hash=digest(prompt),settings=ex.task_pipeline.inference)


def snapshot(out):
    with zipfile.ZipFile(out/'source.zip','w',zipfile.ZIP_DEFLATED) as z:
        for directory in ('meeting_eval','prompts','tests','scripts','experiments/interpret-budget'):
            for p in (ROOT/directory).rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts:z.write(p,p.relative_to(ROOT))


def execute_case(frozen,folder):
    job=frozen['job']
    ex=TaskOnlyExtractor(ROOT.parent.parent/'meeting-agent/.env',folder/'model',frozen)
    check=preflight(ex,frozen)
    if (folder/'config.json').exists() and read(folder/'config.json')!=ex.config:
        raise ValueError('Experiment code/config changed; use a new run')
    atomic_json(folder/'config.json',ex.config);atomic_json(folder/'preflight.json',check)
    atomic_json(folder/'input.json',job)
    store=Store(folder/'state.sqlite')
    try:
        svc=Service(store,ex)
        result=svc.process(job['meeting'],job['actor'],'2026-11-17T15:00:00+08:00')
        atomic_json(folder/'result.json',result);atomic_json(folder/'tasks.json',store.tasks())
        operation_audit(store,folder/'operations.jsonl')
    finally:store.close()
    return result


def should_stop(folder,result):
    for path in folder.rglob('meta.json'):
        meta=read(path)
        if meta.get('http_status')==400 or meta.get('stage')=='interpret_work' and meta.get('finish_reason')=='length':return True
    return any(e.get('recovery',{}).get('status')=='terminal_error' for e in result['extraction'].get('_errors',[]) if e.get('recovery'))


def cached_or_resume(frozen,folder):
    if (folder/'result.json').exists():
        result=read(folder/'result.json')
        waiting=any(r.get('status')=='waiting_retry' for r in result.get('recovery',[]))
        if result['status']!='partial' or not waiting:return result
    return execute_case(frozen,folder)


def freeze_preflight(out,identity,preflights,configs):
    # Check every case before changing any prior evidence, including completed cases.
    manifest=out/'manifest.json'
    if manifest.exists() and read(manifest)!=identity:raise ValueError('Resume identity changed')
    for cid in identity['cases']:
        folder=out/'natural'/cid
        for name,value in [('config.json',configs[cid]),('preflight.json',preflights[cid])]:
            path=folder/name
            if path.exists() and read(path)!=value:raise ValueError('Resume identity changed: '+cid+'/'+name)
    if not manifest.exists():atomic_json(manifest,identity)
    for cid in identity['cases']:
        folder=out/'natural'/cid
        for name,value in [('config.json',configs[cid]),('preflight.json',preflights[cid])]:
            if not (folder/name).exists():atomic_json(folder/name,value)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',required=True,type=Path);parser.add_argument('--cases',nargs='+',default=['GN29','GN25'])
    parser.add_argument('--max-requests',type=int,default=8);parser.add_argument('--resume',action='store_true')
    parser.add_argument('--preflight-only',action='store_true');args=parser.parse_args()
    if args.cases not in (['GN29'],['GN29','GN25']):parser.error('Run GN29 first, optionally followed by GN25')
    if not 1<=args.max_requests<=8:parser.error('max-requests must be 1..8')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=args.resume)
    with node_lock(out,'interpret-budget','experiment'):
        frozen=[load_frozen_case(cid) for cid in args.cases]
        code=[Path(__file__).resolve()]
        code.extend((ROOT/'meeting_eval').glob('*.py'));code.extend((ROOT/'prompts').glob('*.txt'))
        identity=dict(cases=args.cases,limit=args.max_requests,sources={f['job']['id']:f['source_hashes'] for f in frozen},scope='task_branch_only',
            execution_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in code})
        preflights={};configs={}
        for f in frozen:
            folder=out/'natural'/f['job']['id'];folder.mkdir(parents=True,exist_ok=True)
            ex=TaskOnlyExtractor(ROOT.parent.parent/'meeting-agent/.env',folder/'model',f)
            preflights[f['job']['id']]=preflight(ex,f);configs[f['job']['id']]=ex.config
        freeze_preflight(out,identity,preflights,configs)
        if not (out/'source.zip').exists():snapshot(out)
        if args.preflight_only:print('Preflight passed; no HTTP',flush=True);return
        rows=[]
        with limited_http(out/'budget.json',args.max_requests):
            for f in frozen:
                cid=f['job']['id'];folder=out/'natural'/cid
                result=cached_or_resume(f,folder)
                rows.append(dict(case_id=cid,status=result['status'],errors=result['extraction'].get('_errors',[])))
                atomic_json(out/'progress.json',rows)
                print(json.dumps(dict(event='case_complete',case_id=cid,status=result['status'])),flush=True)
                if should_stop(folder,result):break
        atomic_json(out/'summary.json',dict(rows=rows,scope='task_branch_only',budget=read(out/'budget.json')))


if __name__=='__main__':main()
