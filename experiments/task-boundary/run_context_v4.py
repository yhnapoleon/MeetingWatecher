"""Frozen-upstream A/B/C experiment; separate normal-entry integration suites."""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(Path(__file__).parent)]
from meeting_eval.context_v3 import ContextV3Pipeline,reduce_v3
from meeting_eval.context_v4 import ContextV4Pipeline,COVERAGE_RULES
from meeting_eval.context_content_qa import ContextQAPipeline
from meeting_eval.context_state import canonical_ledger,ledger_candidates
from meeting_eval.extract import model_input
from meeting_eval.inputs import digest
from meeting_eval.model_client import ModelClient
from scripts.run_action_baseline import write_json
from scripts import replay_mvp
from validate_m2 import positive_meeting,assess as assess_cross
from run_context_v3 import snapshot
from assess_context_v3 import assess

BASE=ROOT/'runs/2026-11-15-context-v4'
ENV=ROOT.parent.parent/'meeting-agent/.env'
def read(p):return json.loads(p.read_text(encoding='utf8'))
INFERENCE=read(ROOT/'experiments/action-context/compact-check.json')


def full_flow_checks(result,out):
    result=copy.deepcopy(result)
    result.setdefault('original_contract_passed',result['passed'])
    for meeting in ('m1','m2'):
        extraction=read(out/(meeting+'-result.json'))['extraction'];trace=extraction.get('_task_trace',{})
        result['checks'][meeting+'_no_interpretation_unresolved']=not any(r['category']=='interpretation_unresolved' for r in trace.get('review_records',[]))
        result['checks'][meeting+'_repair_valid']=trace.get('repair',{}).get('status')!='failed'
        result['checks'][meeting+'_no_extraction_errors']=not extraction.get('_errors')
    result['passed']=all(result['checks'].values())
    return result


class PromptOnly(ContextV3Pipeline):
    def __init__(self,*args):
        super().__init__(*args)
        self.prompts['check_work']+='\n'+next(line for line in (ROOT/'prompts/check-work-context-v2.txt').read_text(encoding='utf8').splitlines() if line.startswith('仅输出新版本 coverage_findings'))
        self.prompts['check_work']+='\n'+'\n'.join(COVERAGE_RULES.strip().splitlines()[-2:])
        self.config.update(protocol='context-v3-coverage-prompt-control',prompts={s:digest(p) for s,p in self.prompts.items()})


def prepare():
    out=BASE/'fixtures';out.mkdir(exist_ok=False)
    cases={}
    for name in ('M2','positive','G-same-segment','C23'):
        folder=ROOT/'runs/2026-11-15-context-v3/final-r1'/name
        inp=read(folder/'input.json');trace=read(folder/'pipeline.json')['trace']
        cases[name]=dict(**inp,frozen=dict(ledger=trace['ledger'],interpreted={k:trace[k] for k in ('records','events','candidates')}))
    old=read(ROOT/'runs/2026-11-15-m2-repair-study/check-contract/inputs.json')['G-same-segment']
    p=old['payload']
    cases['G-omitted']=dict(meeting=old['meeting'],history=p['history'],frozen=dict(ledger=p['ledger'],interpreted={k:p[k] for k in ('records','events','candidates')}))
    texts={
        'C23-paraphrase':['还有几个问题，会后我们再单独联系袁校长。刚才您讲的时候信号不太好，有些内容没听清。','好的，那我们稍后再联系。'],
        'C23-explicit':['因为刚才信号不好，有些讲解没听清，会后我们单独联系袁校长，把没听清的问题补问清楚。','好的，稍后联系。'],
        'C23-unrelated':['刚才的信号问题已经解决，讲解内容也都听清了。另外还有几个报名问题，会后我们单独联系袁校长沟通。','好的，稍后联系沟通报名问题。']}
    for name,lines in texts.items():
        meeting=copy.deepcopy(cases['C23']['meeting']);meeting.update(case_id=name,source_key=name)
        for segment,text in zip(meeting['segments'],lines):segment['text']=text
        folder=out/name;folder.mkdir();client=ModelClient(ENV,folder/'model');pipe=ContextV3Pipeline(client,folder,INFERENCE)
        projected=model_input(meeting);history={'tasks':[]}
        ledger=pipe._stage('track_context',dict(meeting=projected,previous=None,new_segment_ids=[s['id'] for s in meeting['segments']]),
                           lambda raw:canonical_ledger(raw,meeting,None),folder,False)
        candidates=ledger_candidates(ledger)
        interpreted=pipe._stage('interpret_work',dict(meeting=projected,ledger=ledger,candidates=candidates,history=history),
                                lambda raw:pipe.interpret(raw,ledger,candidates,meeting,history),folder,False)
        cases[name]=dict(meeting=meeting,history=history,frozen=dict(ledger=ledger,interpreted=interpreted))
    write_json(out/'inputs.json',cases)
    write_json(out/'plan.json',dict(arms=['A prompt only','B typed coverage and scoped patches','C B plus source-first QA'],rounds=3,retries=0,
        expected={'M2':'old done, no scope work/review','positive':'old done and accepted config work','G-same-segment':'old done and candidate delivery, commitment question only','G-omitted':'same as G-same-segment; omitted task must be restored',
                  'C23':'contact purpose includes unheard material without invented obligations','C23-paraphrase':'same intended relation; separately flag source ambiguity',
                  'C23-explicit':'preserve explicit clarification purpose','C23-unrelated':'registration questions only, no unheard clarification purpose'},
        scoring='observable contracts plus source review; frozen upstream isolates checker/repair effects, not end-to-end scores'))
    print('Prepared',len(cases),'cases',flush=True)


def one(arm,round_no,name,case,out,frozen=True):
    folder=out/f'{arm}-r{round_no}'/name;folder.mkdir(parents=True,exist_ok=False)
    write_json(folder/'input.json',case)
    parent={'A':PromptOnly,'B':ContextV4Pipeline,'C':ContextQAPipeline}[arm]
    class Pipeline(parent):
        def _stage(self,stage,payload,validate,stage_folder,resume):
            if frozen and stage in ('track_context','interpret_work'):
                return copy.deepcopy(case['frozen']['ledger' if stage=='track_context' else 'interpreted'])
            return super()._stage(stage,payload,validate,stage_folder,resume)
    client=ModelClient(ENV,folder/'model');pipe=Pipeline(client,folder,INFERENCE)
    result=pipe.run(case['meeting'],case['history']);write_json(folder/'pipeline.json',result)
    reduced=reduce_v3(result,case['meeting'],case['history']) if not result['errors'] else None
    write_json(folder/'reduced.json',reduced)
    summary=dict(case='G-same-segment' if name=='G-omitted' else 'C23' if name.startswith('C23-') else name,
        errors=result['errors'],repair=result['trace'].get('repair',{}).get('status'),repair_error=result['trace'].get('repair',{}).get('detail'),
        items=reduced['items'] if reduced else None,reviews=reduced['review_records'] if reduced else None,
        updates=reduced['updates'] if reduced else None,findings=result['coverage_findings'])
    write_json(folder/'summary.json',summary);score=assess(folder);write_json(folder/'contract-review.json',score)
    return dict(arm=arm,round=round_no,case=name,observable_passed=score['observable_passed'],
                failed_checks=[k for k,v in score['checks'].items() if not v],errors=result['errors'],repair_error=summary['repair_error'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--name');p.add_argument('--mode',choices=['small','focus','cross','positive'],default='small')
    p.add_argument('--arms',nargs='+',default=['A','B','C']);p.add_argument('--rounds',type=int,default=3);p.add_argument('--only',nargs='*');p.add_argument('--workers',type=int,default=4);args=p.parse_args()
    if args.prepare:return prepare()
    if not args.name or Path(args.name).name!=args.name:raise ValueError('New output name required')
    out=BASE/args.name;out.mkdir(exist_ok=False);snapshot(out);write_json(out/'plan.json',vars(args))
    if args.mode in ('cross','positive'):
        original=replay_mvp.read
        if args.mode=='positive':write_json(out/'m2-input.json',positive_meeting())
        def source(path):return positive_meeting() if args.mode=='positive' and path==ROOT/'examples/m2.json' else original(path)
        with patch.object(replay_mvp,'read',source):replay_mvp.replay(out,ENV,'context-v4',inference_config=INFERENCE)
        results=full_flow_checks(assess_cross(out,positive=args.mode=='positive'),out)
    else:
        if args.mode=='small':cases=read(BASE/'fixtures/inputs.json')
        else:
            cases={p.parent.name:read(p) for p in (ROOT/'runs/2026-11-15-context-v3/final-r1').glob('*/input.json')}
        if args.only:cases={k:v for k,v in cases.items() if k in args.only}
        results=[]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs=[pool.submit(one,a,r,n,c,out,args.mode=='small') for r in range(1,args.rounds+1) for a in args.arms for n,c in cases.items()]
            for f in as_completed(jobs):
                row=f.result();results.append(row);write_json(out/'progress.json',results);print(json.dumps(row,ensure_ascii=False),flush=True)
    metas=[read(p) for p in out.rglob('meta.json')]
    write_json(out/'summary.json',dict(results=results,calls=len(metas),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),
        received=sum(m.get('status')=='received' for m in metas)))


if __name__=='__main__':main()
