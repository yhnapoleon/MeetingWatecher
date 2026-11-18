"""Persist human semantic adjudications and deterministic request/accounting audit."""
import copy
from pathlib import Path
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).parent))
from run_repair_study import ROOT, OUT, read, write_json, digest
from repair_contract import validate_check_alignment


def main():
    pairs=[]
    for round_ in (1,2):
        for name in ('M2','positive','C20','P07b'):
            a=OUT/'c3'/f'{name}-visible-r{round_}';b=OUT/'c3'/f'{name}-blind-r{round_}'
            av=read(next((a/'model').rglob('request.json')));bv=read(next((b/'model').rglob('request.json')))
            import json
            ap=json.loads(av['messages'][1]['content']);bp=json.loads(bv['messages'][1]['content'])
            upstream=ap.pop('upstream');assert ap==bp and upstream
            ac=copy.deepcopy(av);bc=copy.deepcopy(bv);ac['messages']=ac['messages'][:1];bc['messages']=bc['messages'][:1]
            assert ac==bc
            pairs.append(dict(case=name,round=round_,only_payload_difference='upstream'))
    manual=[]
    for stage in ('c3','merge'):
        for folder in sorted((OUT/stage).iterdir()):
            if not folder.is_dir():continue
            name,arm,roundtext=folder.name.rsplit('-',2);round_=int(roundtext[1:])
            if stage=='c3':
                passed=name=='positive' or name=='M2' and arm=='blind'
                reason=('all case criteria met' if passed else 'scope misclassified as work' if name=='M2' else
                        'manuscript unresolved' if name=='C20' and arm=='visible' else
                        'invented manuscript processing/confirmation work' if name=='C20' else 'unwarranted reference/scope gap')
                artifact='raw.json'
            else:
                passed=not (name=='M2' and round_==1 or name=='C20' and arm=='visible' and round_==1 or name=='P07b' and arm=='blind' and round_==1)
                reason=('all reducer-stage case criteria met' if passed else
                    'R2 classification dispute plus stale U' if name=='M2' and arm=='blind' else
                    'stale U despite final supported context' if name=='M2' else
                    'repair Wrong case_id; manuscript question remains' if name=='C20' else 'reference gap still blocks accepted work')
                artifact='pipeline.json'
            manual.append(dict(stage=stage,case=name,arm=arm,round=round_,passed=passed,reason=reason,
                artifact=(folder/artifact).relative_to(ROOT).as_posix(),artifact_hash=digest(read(folder/artifact))))
    inputs=read(OUT/'check-contract/inputs.json');alignment=[]
    for folder in sorted((OUT/'check-contract').glob('*-contract-r*')):
        result=read(folder/'result.json');name=result['case']
        try:
            validate_check_alignment(inputs[name]['payload']['records'],read(folder/'raw.json')['record_checks'])
            check=dict(status='valid')
        except (ValueError,KeyError,TypeError) as exc:check=dict(status='failed',error=type(exc).__name__,detail=str(exc))
        alignment.append(dict(case=name,round=result['round'],first_validation=result['status'],alignment_audit=check))
    stats={}
    for name in ('c3','merge','check-contract'):
        metas=[read(p) for p in (OUT/name).rglob('meta.json')]
        stats[name]=dict(calls=len(metas),received=sum(m['status']=='received' for m in metas),
            tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),call_seconds=round(sum(m['duration_seconds'] for m in metas),3))
    unchanged=[]
    with zipfile.ZipFile(OUT/'before.zip') as z:
        for name in z.namelist():
            if name.startswith(('meeting_eval/','prompts/')):
                if z.read(name)!=(ROOT/name).read_bytes():raise AssertionError('Production changed: '+name)
                unchanged.append(name)
    summary=dict(model_usage=stats,total_calls=sum(v['calls'] for v in stats.values()),total_tokens=sum(v['tokens'] for v in stats.values()),
        c3_pair_audit=pairs,production_unchanged=unchanged,
        c3_passes={arm:sum(r['passed'] for r in manual if r['stage']=='c3' and r['arm']==arm) for arm in ('visible','blind')},
        merge_passes={arm:sum(r['passed'] for r in manual if r['stage']=='merge' and r['arm']==arm) for arm in ('visible','blind')},
        conclusion='C3 does not meet end-to-end promotion; local checker improves frozen M2 but fails contract/guard gate; no production adoption',
        scope='classification, frozen downstream task pipeline, checker experiment, record-level deterministic prototype; NOT fresh Service cross-meeting acceptance')
    write_json(OUT/'semantic-audit.json',dict(method='manual reading of all records, event fields, reviews and stage traces; booleans not model-graded',rows=manual))
    write_json(OUT/'alignment-audit.json',dict(model_calls=0,validator='repair_contract.validate_check_alignment',rows=alignment))
    write_json(OUT/'summary.json',summary)
    print({k:v for k,v in summary.items() if k not in ('production_unchanged','c3_pair_audit')})


if __name__=='__main__':main()
