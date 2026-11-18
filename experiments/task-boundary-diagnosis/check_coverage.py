"""Bounded check/repair experiment; frozen source, tracking and interpretation."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.context_v5 import ContextV5Pipeline
from meeting_eval.context_v3 import reduce_v3
from meeting_eval.extract import Extractor,model_input,resolve_calendar_dates
from meeting_eval.inputs import normalize,digest
from meeting_eval.model_client import ModelClient
from meeting_eval.service import Service
from meeting_eval.store import Store
from meeting_eval.stage_runner import atomic_json,node_lock
from meeting_eval.context_wire import wire_request

spec=importlib.util.spec_from_file_location('budget_runner',ROOT/'experiments/interpret-budget/run.py')
budget=importlib.util.module_from_spec(spec);spec.loader.exec_module(budget)
BASE=ROOT/'runs/2026-11-17-interpret-budget-low/natural/GN25'
read=lambda p:json.loads(Path(p).read_text(encoding='utf8'))


def frozen_gn25():
    job=read(BASE/'input.json');saved=read(BASE/'result.json')
    interpret=read(next(BASE.glob('model/context_v2/*/interpret_work/*/accepted.json')))['value']
    request=read(next(BASE.glob('model/context_v2/*/interpret_work/*/attempt-1/stage-request.json')))
    meeting=normalize(job['meeting'],job['actor'])
    trace=saved['extraction']['_task_trace']
    payload=dict(meeting=model_input(meeting),ledger=trace['ledger'],candidates=trace['candidates'],history={'tasks':[]})
    assert wire_request(payload)==request
    return dict(job=job,meeting=meeting,trace=trace,interpret=interpret)


def background():
    raw=dict(case_id='BG01',meeting_id='BG01',series='coverage-control',audience=['host'],writers=['host'],
        speaker_map={'Host':'host'},segments=[
            dict(id='bg1',speaker='Host',text='The Santa Barbara conference is in June. The published student registration fee is one hundred dollars.'),
            dict(id='bg2',speaker='Host',text='If a student attends, that is the rate listed on the registration page. We have not discussed attendance or funding today.')])
    meeting=normalize(raw,'host')
    spans=[dict(segment_id=s['id'],start=0,end=len(s['text']),quote=s['text']) for s in meeting['segments']]
    record=dict(record_id='R1',thread_ids=[],kind='context_only',content_basis='explicit',
        description='Conference date and published student fee; attendance and funding have not been discussed.',
        evidence=spans,missing_fields=[],question=None,issuer_ref='host',need_basis=dict(goal=None,evidence=[]))
    return dict(job=dict(id='BG01',meeting=raw,actor='host',tasks=[]),meeting=meeting,
        trace=dict(ledger=dict(entities=[],links=[],threads=[]),checkpoints=[]),
        interpret=dict(records=[record],events=[],candidates=[]))


class FrozenPipeline(ContextV5Pipeline):
    def __init__(self,client,out,settings,frozen):
        super().__init__(client,out,settings);self.frozen=frozen
        self.config['experiment']=dict(scope='check_repair_only',frozen_hash=digest(frozen))

    def _track_ledger(self,meeting,folder,trace,resume):
        if model_input(meeting)!=model_input(self.frozen['meeting']):raise ValueError('Frozen meeting changed')
        trace.update({k:copy.deepcopy(v) for k,v in self.frozen['trace'].items() if k in ('checkpoints','tracking')})
        return copy.deepcopy(self.frozen['trace']['ledger'])

    def _stage(self,stage,payload,validate,folder,resume):
        if stage=='interpret_work':
            if payload['history']!={'tasks':[]}:raise ValueError('Frozen history changed')
            return copy.deepcopy(self.frozen['interpret'])
        if stage=='track_context':raise AssertionError('Frozen tracking must not call a model')
        return super()._stage(stage,payload,validate,folder,resume)


class TaskBranch(Extractor):
    def __init__(self,pipeline):
        self.task_pipeline=pipeline;self.strategy='context-v5';self.out=pipeline.out
        self.config=dict(strategy='context-v5',task_pipeline=pipeline.config)
    def extract(self,meeting,context):
        if context!={'tasks':[],'decisions':[]}:raise ValueError('Frozen context changed')
        result=self.evidence_extract(meeting,context,{'items','updates'},False)
        result['_experiment']=dict(scope='task_branch_check_repair_only')
        resolve_calendar_dates(result,meeting)
        return result


def source_hashes():
    files=[*sorted((ROOT/'meeting_eval').glob('*.py')),*sorted((ROOT/'prompts').glob('*.txt')),
           Path(__file__),ROOT/'experiments/interpret-budget/run.py']
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def stop_result(result):
    return any(e.get('recovery',{}).get('status') in ('terminal_error','waiting_retry','recovery_required')
               for e in result['extraction'].get('_errors',[]))


def execute(out,live,check_low=False,limit=6):
    settings=read(BASE/'config.json')['task_pipeline']['inference']
    if check_low:
        settings['check_work'].update(thinking='enabled',reasoning_effort='low',temperature=1)
    frozen=frozen_gn25();control=background()
    identity=dict(sources=source_hashes(),frozen_hash=digest(frozen),control_hash=digest(control),
                  settings=settings,limit=limit,scope='GN25 frozen check/repair and BG01 control')
    manifest=out/'manifest.json'
    if manifest.exists():
        if read(manifest)!=identity:raise ValueError('Experiment changed; use a new run directory')
    else:
        atomic_json(manifest,identity)
        with zipfile.ZipFile(out/'source.zip','x',zipfile.ZIP_DEFLATED) as z:
            for name in identity['sources']:z.write(ROOT/name,name)
    for f in (frozen,control):
        folder=out/f['job']['id'];folder.mkdir(exist_ok=True)
        atomic_json(folder/'frozen.json',f)
    if not live:
        print(json.dumps(dict(status='preflight_ready',settings=settings,cases=['GN25','BG01'],http_limit=limit)));return
    for f in (frozen,control):
        folder=out/f['job']['id']
        # The run is deliberately not an outer retry mechanism. Technical stage
        # recovery remains in stage_runner; do not silently redo a completed case.
        if (folder/'result.json').exists():
            if stop_result(read(folder/'result.json')):
                print('Stopped on saved terminal or pending recovery');break
            continue
        client=ModelClient(ROOT.parent.parent/'meeting-agent/.env',folder/'model')
        old=read(BASE/'config.json')
        if client.model!=old['model'] or client.endpoint!=old['endpoint']:raise ValueError('Historical provider changed')
        pipe=FrozenPipeline(client,folder/'model',settings,f)
        atomic_json(folder/'config.json',pipe.config)
        store=Store(folder/'state.sqlite')
        try:
            with budget.limited_http(out/'http-budget.json',limit):
                result=Service(store,TaskBranch(pipe)).process(f['job']['meeting'],f['job']['actor'],'2026-11-17T21:00:00+08:00')
            atomic_json(folder/'result.json',result)
            atomic_json(folder/'tasks.json',store.tasks())
        finally:store.close()
        print(json.dumps(dict(case=f['job']['id'],status=result['status'],
            items=len(result['extraction']['items']),reviews=len(result['extraction']['_task_trace'].get('review_records',[]))),ensure_ascii=False),flush=True)
        if stop_result(result):
            print('Stopped on terminal or pending recovery');break
    metas=[read(p) for p in out.glob('*/model/**/meta.json')]
    atomic_json(out/'usage.json',dict(http=read(out/'http-budget.json') if (out/'http-budget.json').exists() else {},
        known_tokens=sum(m.get('usage',{}).get('total_tokens',0) for m in metas if m.get('usage')),
        unknown_usage=sum(not m.get('usage') for m in metas),attempts=[{k:m.get(k) for k in
        ('stage','status','http_status','finish_reason','usage','elapsed_seconds')} for m in metas]))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);parser.add_argument('--live',action='store_true')
    parser.add_argument('--check-low',action='store_true');parser.add_argument('--limit',type=int,default=6,choices=range(1,7))
    args=parser.parse_args();out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
    with node_lock(out,'coverage-experiment','experiment'):execute(out,args.live,args.check_low,args.limit)
