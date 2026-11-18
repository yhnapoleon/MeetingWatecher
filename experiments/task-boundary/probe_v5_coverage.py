"""Freeze the known omitted interpretation; exercise current check/repair only.

This controlled probe is not an independent end-to-end accuracy sample.
"""
import copy
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.context_v5 import ContextV5Pipeline
from meeting_eval.context_v3 import reduce_v3
from meeting_eval.model_client import ModelClient
from run_context_v3 import snapshot, ENV, INFERENCE
from scripts.run_action_baseline import write_json


def read(p):return json.loads(p.read_text(encoding='utf8'))


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--thinking',action='store_true');args=parser.parse_args()
    source=ROOT/'runs/2026-11-16-context-v5-fixes/focused-v2/r2/context/CTX_ES2002a_roles'
    out=args.out
    out.mkdir(exist_ok=False);snapshot(out)
    meta=next(p for p in source.rglob('meta.json') if read(p)['stage']=='check_work')
    payload=json.loads(read(meta.with_name('request.json'))['messages'][1]['content'])
    trace=read(source/'result.json')['extraction']['_task_trace']
    imeta=next(p for p in source.rglob('meta.json') if read(p)['stage']=='interpret_work')
    original_raw=json.loads(read(imeta.with_name('response.json'))['choices'][0]['message']['content'])
    meeting=copy.deepcopy(payload['meeting']);meeting['source_key']=meeting['case_id']
    history=payload['history']
    write_json(out/'input.json',dict(meeting=meeting,history=history,source=source.as_posix(),
        frozen_stages=['track_context','interpret_work'],fresh_stages=['check_work','repair_work','check_repair'],
        interpretation={k:payload[k] for k in ('records','events','candidates')},
        metric_note='Controlled downstream probe, excluded from fresh regression accuracy.'))
    class Pipeline(ContextV5Pipeline):
        def _stage(self,stage,p,validate,folder,resume):
            if stage=='track_context':
                end=p['meeting']['segments'][-1]['id']
                return copy.deepcopy(next(c['ledger'] for c in trace['checkpoints'] if c['through_segment']==end))
            if stage=='interpret_work':
                return validate(copy.deepcopy(original_raw))
            return super()._stage(stage,p,validate,folder,resume)
    inference=copy.deepcopy(INFERENCE)
    if args.thinking:inference['check_work']=dict(thinking='enabled',reasoning_effort='high',temperature=1,max_tokens=16384)
    write_json(out/'inference.json',inference)
    result=Pipeline(ModelClient(ENV,out/'model'),out,inference).run(meeting,history)
    write_json(out/'pipeline.json',result)
    reduced=reduce_v3(result,meeting,history)
    write_json(out/'reduced.json',reduced)
    checks=dict(no_errors=not result['errors'],repair_checked=result['trace'].get('repair',{}).get('status')=='checked',
        three_works=len(reduced['items'])==3,
        ui_candidate=any(i['operation']=='candidate' and i['owner_ref']=='MEE007' for i in reduced['items']),
        two_accepted=sum(i['operation']=='create' for i in reduced['items'])==2,
        no_findings=not result['coverage_findings'])
    write_json(out/'assessment.json',dict(checks=checks,passed=all(checks.values())))
    print(json.dumps(checks),flush=True)


if __name__=='__main__':main()
