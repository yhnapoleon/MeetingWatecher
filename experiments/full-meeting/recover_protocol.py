"""Bounded full-Service recovery with explicitly revalidated tracking imports."""
import argparse
import copy
from contextlib import contextmanager,closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace
import urllib.request
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.context_v5 import ContextV5Pipeline
from meeting_eval.context_tracking_reliable import expand_tracking
from meeting_eval.context_state import ledger_candidates
from meeting_eval.extract import Extractor,model_input,validate
from meeting_eval.inputs import normalize,digest
from meeting_eval.model_client import ModelResponseError
from meeting_eval.service import Service
from meeting_eval.store import Store
from meeting_eval.stage_runner import atomic_json,node_lock

LOCK=threading.Lock()
TRACKING_DEPS=('context_tracking_reliable.py','context_checkpoints.py','context_state.py',
    'context_protocol.py','context_protocol_v3.py','context_protocol_v4.py','context_protocol_v5.py',
    'context_pipeline.py','context_v2.py','context_v3.py','task_pipeline.py','inputs.py')


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(condition,message):
    if not condition:raise ValueError(message)


def preflight(source):
    source=Path(source).resolve();raw=read(source/'input.json');meeting=normalize(raw,'evaluator')
    result=read(source/'result.json');config=read(source/'config.json');settings=read(source/'inference.json')
    trace=result['extraction']['_task_trace'];tracking=trace['tracking'];projected=model_input(meeting)
    require(tracking['input_hash']==digest(projected),'Frozen tracking input changed')
    require(tracking['status']=='complete' and tracking['completed_segments']==len(meeting['segments']),'Tracking incomplete')
    with closing(sqlite3.connect((source/'state.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        read_context=json.loads(db.execute('SELECT body FROM extraction_context WHERE source_id=?',(result['source_id'],)).fetchone()[0])
        body=json.loads(db.execute('SELECT body FROM sources WHERE id=?',(result['source_id'],)).fetchone()[0])
    require(read_context['actor']=='evaluator' and read_context['context']=={'tasks':[],'decisions':[]},'Unexpected frozen history')
    require(body==meeting,'Stored source differs from input, permissions or account mapping')
    require({e['field'] for e in result['extraction'].get('_errors',[])}<={'items','updates'},'Source minutes or decisions incomplete')
    require(result['extraction']['_minutes_review']['status']=='accepted','Source minutes not accepted')
    validate(result['extraction'],meeting,read_context['context'])
    pipe=ContextV5Pipeline(SimpleNamespace(model=config['model'],endpoint=config['endpoint']),source/'unused',settings)
    with zipfile.ZipFile(source/'source.zip') as z:
        dependencies={}
        for name in TRACKING_DEPS:
            path=ROOT/'meeting_eval'/name
            require(z.read('meeting_eval/'+name)==path.read_bytes(),'Tracking dependency changed: '+name)
            dependencies[name]=sha(path)
    require(pipe.inference['track_context']==config['task_pipeline']['inference']['track_context'],'Tracking inference changed')
    requests={}
    for p in (source/'model').rglob('track_context/*/accepted.json'):
        state=read(p.parent/'state.json');attempt=next(a for a in reversed(state['attempts']) if a['status']=='accepted')
        folder=p.parent/attempt['directory'];request=read(folder/'request.json')
        require(request['messages'][0]['content']==pipe.prompts['track_context'],'Tracking prompt changed')
        payload=read(folder/'stage-request.json')
        key=tuple(payload['new_segment_ids']);require(key not in requests,'Duplicate tracking window')
        requests[key]=(folder,payload,p,attempt)
    ledger=None;nodes=[];through=0
    for start,end in tracking['accepted_ranges']:
        require(start==through and start<end<=len(meeting['segments']),'Tracking ranges have a gap')
        ids=tuple(s['id'] for s in meeting['segments'][start:end]);require(ids in requests,'Missing accepted tracking window')
        folder,payload,accepted,attempt=requests[ids]
        require(payload['meeting']==model_input({**meeting,'segments':meeting['segments'][:end]}) and payload['previous']==ledger,'Tracking prefix/history mismatch')
        candidate=folder/attempt.get('candidate_file','raw.json')
        ledger=expand_tracking(read(candidate),payload)
        saved=read(accepted);require(saved['hash']==digest(saved['value']) and ledger==saved['value'],'Tracking response no longer validates identically')
        nodes.append(dict(start=start,end=end,files={str(p.relative_to(source)):sha(p) for p in
            (candidate,accepted,folder/'request.json',folder/'stage-request.json',accepted.parent/'state.json')}))
        through=end
    require(through==len(meeting['segments']) and ledger==trace['ledger'],'Final tracking ledger differs')
    require(ledger_candidates(ledger)==trace['candidates'],'Derived candidates differ')
    files={name:sha(source/name) for name in ('input.json','result.json','config.json','inference.json','source.zip','state.sqlite')}
    return dict(source=str(source),meeting=raw,context=read_context['context'],config=config,settings=settings,
        extraction=result['extraction'],tracking_nodes=nodes,tracking_segments=through,dependencies=dependencies,source_files=files)


def reserve_request(state_path,limit,destination):
    if type(limit) is not int or not 1<=limit<=8:raise ValueError('HTTP limit must be 1..8')
    state_path=Path(state_path);state_path.parent.mkdir(parents=True,exist_ok=True)
    with LOCK,node_lock(state_path.parent,'full-meeting-budget','experiment'):
        state=read(state_path) if state_path.exists() else dict(limit=limit,used=0,destination=str(Path(destination).resolve()))
        require(state['limit']==limit and state['destination']==str(Path(destination).resolve()),'Budget belongs to another output or limit')
        if state['used']>=limit or state.get('closed'):
            raise ModelResponseError('Full-meeting recovery HTTP budget closed/exhausted','terminal_error')
        state['used']+=1;atomic_json(state_path,state)
        return state['used']


@contextmanager
def limited_http(state_path,limit,out):
    send=urllib.request.urlopen
    def bounded(req,*args,**kwargs):
        request=json.loads(req.data)
        require(request.get('max_tokens',0)<=32768,'Output token cap exceeded')
        number=reserve_request(state_path,limit,out)
        print(json.dumps(dict(event='http_start',request=number,thinking=request.get('thinking'),max_tokens=request.get('max_tokens'))),flush=True)
        return send(req,*args,**kwargs)
    with patch('urllib.request.urlopen',side_effect=bounded):yield


class RecoveryExtractor(Extractor):
    def __init__(self,env_file,out,frozen):
        super().__init__(env_file,out,'context-v5',inference_config=frozen['settings'])
        require(self.client.model==frozen['config']['model'] and self.client.endpoint==frozen['config']['endpoint'],'Model identity differs')
        self.frozen=frozen
        self.config['experiment']=dict(kind='full-service-protocol-recovery',source_files=frozen['source_files'],
            imported=['validated_tracking','facts','decisions'],fresh=['interpretation','work_checks','minutes_review'])
        def tracking(meeting,folder,trace,resume):
            require(model_input(meeting)==model_input(normalize(frozen['meeting'],'evaluator')),'Imported tracking input mismatch')
            old=frozen['extraction']['_task_trace']
            trace.update({k:copy.deepcopy(old[k]) for k in ('tracking','checkpoints')})
            return copy.deepcopy(old['ledger'])
        self.task_pipeline._track_ledger=tracking
        original_review=self.minutes_reviewer.review
        def review(meeting,minutes,context):
            if context.get('work_errors'):
                return dict(**copy.deepcopy(minutes),errors=[],trace=dict(status='not_refreshed',reason='work branch incomplete'))
            return original_review(meeting,minutes,context)
        self.minutes_reviewer.review=review

    def stage(self,name,payload,fresh=False):
        require(model_input(normalize(self.frozen['meeting'],'evaluator'))==payload['meeting'],'Imported content input mismatch')
        old=self.frozen['extraction']
        if name=='facts':return {k:copy.deepcopy(old[k]) for k in ('facts','unresolved')}
        if name=='decisions':
            require(payload['decisions']==self.frozen['context']['decisions'],'Decision history changed')
            return dict(decisions=copy.deepcopy(old['decisions']))
        raise ValueError('Unexpected independent stage '+name)


def execute(source,out,limit,live):
    frozen=preflight(source);out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    sources=sorted((ROOT/'meeting_eval').glob('*.py'))+sorted((ROOT/'prompts').glob('*.txt'))+[Path(__file__)]
    manifest=dict(source=frozen['source'],source_files=frozen['source_files'],tracking_nodes=frozen['tracking_nodes'],
        dependencies=frozen['dependencies'],files={str(p.relative_to(ROOT)):sha(p) for p in sources},limit=limit)
    if (out/'manifest.json').exists():require(read(out/'manifest.json')==manifest,'Frozen recovery configuration changed')
    else:
        atomic_json(out/'manifest.json',manifest)
        atomic_json(out/'input.json',frozen['meeting'])
        with zipfile.ZipFile(out/'source.zip','w',zipfile.ZIP_DEFLATED) as z:
            for p in sources:z.write(p,p.relative_to(ROOT))
    if not live:
        print(json.dumps(dict(preflight='passed',tracking_segments=frozen['tracking_segments'],tracking_nodes=len(frozen['tracking_nodes']),live=False)),flush=True)
        return
    if (out/'summary.json').exists():print(json.dumps(read(out/'summary.json'),ensure_ascii=False));return
    # Budget is keyed by original evidence, outside the caller-selected output folder.
    budget=ROOT/'runs/2026-11-17-evidence-protocol-implementation/budgets'/('es2002a-'+frozen['source_files']['result.json'][:16]+'.json')
    budget.parent.mkdir(parents=True,exist_ok=True)
    with node_lock(out,'full-meeting-recovery','experiment'):
        ex=RecoveryExtractor(ROOT.parent.parent/'meeting-agent/.env',out/'model',frozen)
        atomic_json(out/'config.json',ex.config)
        store=Store(out/'state.sqlite');started=time.perf_counter()
        try:
            svc=Service(store,ex)
            with limited_http(budget,limit,out):result=svc.process(frozen['meeting'],'evaluator','2026-11-17T13:00:00+08:00')
            sid=result['source_id'];minutes=svc.minutes(sid,'evaluator');requirements=svc.requirements(sid,'evaluator')
            atomic_json(out/'result.json',result);atomic_json(out/'requirements.json',requirements)
            atomic_json(out/'tasks.json',store.tasks());atomic_json(out/'collected-issues.json',svc.collected_issues(sid,'evaluator'))
            (out/'minutes.md').write_text(minutes,encoding='utf8')
            repeat=False
            if result['status']=='processed':
                with patch('urllib.request.urlopen',side_effect=AssertionError('Duplicate processing called model')):
                    require(svc.process(frozen['meeting'],'evaluator','2026-11-17T13:00:00+08:00')==result,'Duplicate result changed')
                repeat=True
        finally:store.close()
        reopened=Store(out/'state.sqlite')
        try:
            reader=Service(reopened)
            require(reader.result(sid)==result and reader.minutes(sid,'evaluator')==minutes and reader.requirements(sid,'evaluator')==requirements,'Reopened result changed')
        finally:reopened.close()
        meta=[read(p) for p in (out/'model').rglob('meta.json')]
        state=read(budget) if budget.exists() else dict(limit=limit,used=0,destination=str(out))
        state['closed']=True;atomic_json(budget,state);atomic_json(out/'budget.json',state)
        summary=dict(status=result['status'],seconds=round(time.perf_counter()-started,3),http_calls=state['used'],
            recorded_attempts=len(meta),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in meta),
            counts={k:len(result['extraction'][k]) for k in ('items','facts','unresolved','decisions','updates')},
            errors=result['extraction'].get('_errors',[]),repeat_no_model_calls=repeat,reopen_consistent=True)
        atomic_json(out/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--live',action='store_true');parser.add_argument('--limit',type=int,choices=range(1,9),default=8)
    args=parser.parse_args();execute(args.source,args.out,args.limit,args.live)
