"""Controlled task-linking probe: replay real b output, simulate confirmation, infer c excerpts."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.extract import Extractor
from meeting_eval.service import Service
from meeting_eval.store import Store

def read(p): return json.loads(p.read_text(encoding='utf-8'))
def write(p,v): p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')

def run(source,out):
    out.mkdir(parents=True,exist_ok=False)
    original=read(source/'ES2002b/result.json')
    assert original['status']=='processed'
    first=read(source/'ES2002b/input.json')
    second=read(source/'ES2002c/input.json')
    audience=['evaluator',*first['account_map'].values()]
    first['audience']=audience
    second['audience']=audience
    second['case_id']='PROBE-ES2002c-confirmed-reports'
    windows=[(186,277),(664,743),(957,1032)]
    second['segments']=[s for s in second['segments'] if any(s['start_ms']<b*1000 and s['end_ms']>a*1000 for a,b in windows)]
    write(out/'input.json',second)
    write(out/'replayed-first-input.json',first)
    write(out/'manifest.json',{'scope':'Task-linking diagnostic only; not a second full-meeting score',
        'first_output':'Saved actual model output from baseline b, replayed unchanged through normal Service',
        'first_result_sha256':hashlib.sha256((source/'ES2002b/result.json').read_bytes()).hexdigest(),
        'intervention':'Explicit synthetic participant audience plus simulated add_task confirmations, using Service API',
        'windows_seconds':windows,'second_segments':len(second['segments']),
        'account_scope':'Local Simulator only; not statements by real participants'})
    config=read(source/'config.json')
    class Replay:
        strategy='context-v5'
        def __init__(self):self.config=config
        def extract(self,meeting,context):
            assert not context['tasks'] and not context['decisions']
            return copy.deepcopy(original['extraction'])
    store=Store(out/'state.sqlite')
    try:
        service=Service(store,Replay())
        first_result=service.process(first,'evaluator','2026-11-18T10:00:00+08:00')
        sid=first_result['source_id']
        confirmations=[]
        items=original['extraction']['items']
        record_ids=original['extraction']['_task_trace']['item_records']
        for item,rid in zip(items,record_ids):
            if item['owner_ref'] not in ['MEE006','MEE007','MEE008']:continue
            decision={'decision':'add_task','description':item['description'],'owner_ref':item['owner_ref'],
                      'due_text':'午餐后 30 分钟工作时段'}
            resolution=service.resolve_requirement(sid,rid,'evaluator',decision,'2026-11-18T10:05:00+08:00')
            confirmations.append({'record_id':rid,'input':decision,'resolution':resolution})
        assert len(confirmations)==3
        write(out/'simulated-confirmations.json',confirmations)
        context=service.context(first['series'],'evaluator','2026-11-18T12:00:00+08:00',audience=audience)
        assert len(context['tasks'])==5
        write(out/'context-before.json',context)
        print('CONFIRMED PROBE: 5 historical tasks; actual c excerpt inference begins',flush=True)
        extractor=Extractor(ROOT.parent.parent/'meeting-agent/.env',out/'model','context-v5',
            inference_config=read(ROOT/'config/context-v5-v19.json'),review_decisions=True)
        service=Service(store,extractor)
        started=time.monotonic()
        result=service.process(second,'evaluator','2026-11-18T12:00:00+08:00')
        write(out/'result.json',result)
        write(out/'tasks-after.json',store.tasks())
        (out/'minutes.md').write_text(service.minutes(result['source_id'],'evaluator'),encoding='utf-8')
        metas=[read(p) for p in (out/'model').rglob('meta.json')]
        write(out/'summary.json',{'status':result['status'],'seconds':round(time.monotonic()-started,2),
              'calls':len(metas),'tokens':sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),
              'errors':result['extraction'].get('_errors',[])})
        print('CONFIRMED PROBE COMPLETE',result['status'],flush=True)
    finally:store.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();run(a.source,a.out)
