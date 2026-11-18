"""First-attempt user-policy verification, isolated files and SQLite simulator."""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(Path(__file__).parent)]
from meeting_eval.context_v5 import ContextV5Pipeline
from meeting_eval.context_v3 import reduce_v3
from meeting_eval.extract import Extractor
from meeting_eval.model_client import ModelClient
from meeting_eval.service import Service
from meeting_eval.store import Store
from scripts.run_action_baseline import write_json
from validate_m2 import positive_meeting
from run_context_v4 import ENV,INFERENCE
from probe_source_work import usage
from run_context_v3 import snapshot


def read(p):return json.loads(p.read_text(encoding='utf8'))


def cases():
    fixtures=read(ROOT/'runs/2026-11-15-context-v4/fixtures/inputs.json')
    selected={k:fixtures[k] for k in ('G-omitted','C23','C23-explicit','C23-unrelated')}
    for k in ('CP06','HT04'):
        selected[k]=read(ROOT/f'runs/2026-11-15-context-v3/final-r1/{k}/input.json')
    for name,lines in {
        'no-date':['我来整理登录失败案例并发到研发群。'],
        'activate':['上线后要不要再做监控面板？先放着，今天不定。','刚才的监控面板还是做吧，我来完成。'],
    }.items():
        m=copy.deepcopy(fixtures['C23']['meeting'])
        m.update(case_id=name,source_key=name)
        template=m['segments'][0]
        m['segments']=[dict(template,id=f'{name}.{i}',text=text,start_ms=i*1000,end_ms=(i+1)*1000) for i,text in enumerate(lines,1)]
        selected[name]=dict(meeting=m,history={'tasks':[]})
    return selected


def focused(name,case,out):
    out.mkdir(parents=True,exist_ok=False);write_json(out/'input.json',case)
    class Pipeline(ContextV5Pipeline):
        def _stage(self,stage,payload,validate,folder,resume):
            if name=='G-omitted' and stage in ('track_context','interpret_work'):
                return copy.deepcopy(case['frozen']['ledger' if stage=='track_context' else 'interpreted'])
            return super()._stage(stage,payload,validate,folder,resume)
    pipe=Pipeline(ModelClient(ENV,out/'model'),out,INFERENCE)
    result=pipe.run(case['meeting'],case['history']);write_json(out/'pipeline.json',result)
    reduced=reduce_v3(result,case['meeting'],case['history']) if not result['errors'] else None
    write_json(out/'reduced.json',reduced)
    checks=dict(no_errors=not result['errors'],repair_valid=result['trace'].get('repair',{}).get('status')!='failed',
                no_unresolved_findings=not result['coverage_findings'])
    if reduced:
        items,reviews=reduced['items'],reduced['review_records']
        checks['no_interpretation_unresolved']=not any(r['category']=='interpretation_unresolved' for r in reviews)
        if name.startswith('C23'):
            checks.update(one_contact=len(items)==1,only_owner_review=len(reviews)==1 and reviews[0]['missing_fields']==['owner'],
                candidate=all(i['operation']=='candidate' for i in items),no_invented_deadline=all(i['due_date'] is None and i['due_text'] is None for i in items))
        elif name=='G-omitted':
            scope=[r for r in reviews if '范围' in r['description']]
            delivery=[r for r in reviews if '测试结果' in r['description']]
            checks.update(two_independent_works=len(items)==2,old_done=len(reduced['updates'])==1,
                scope_only_owner=len(scope)==1 and scope[0]['missing_fields']==['owner'],
                delivery_only_acceptance=len(delivery)==1 and delivery[0]['missing_fields']==['commitment'])
        elif name in ('no-date','activate'):
            checks.update(one_work=len(items)==1,no_deferred=not reduced['deferred_topics'],no_scope_or_time_question=not any(set(r['missing_fields'])&{'scope','time','work'} for r in reviews))
        elif name=='CP06':checks.update(implicit_need=len(reviews)==1 and reviews[0]['category']=='implicit_need',no_item=not items)
        elif name=='HT04':checks.update(relation_choice=len(reviews)==1 and reviews[0]['missing_fields']==['relation'],no_item=not items)
    else:checks['has_result']=False
    row=dict(case=name,checks=checks,observable_passed=all(checks.values()),semantic_review='pending')
    write_json(out/'assessment.json',row);return row


def service(positive,out,inference_config=None):
    out.mkdir(parents=True,exist_ok=False)
    store=Store(out/'state.sqlite')
    model=Extractor(ENV,out/'model','context-v5',inference_config=INFERENCE if inference_config is None else inference_config)
    svc=Service(store,model);checks={}
    try:
        m1=svc.process(read(ROOT/'examples/m1.json'),'host','2026-11-09T10:02:00+08:00')
        write_json(out/'m1-result.json',m1)
        (out/'M1.md').write_text(svc.minutes(m1['source_id'],'host'),encoding='utf8')
        t=m1['extraction']['_task_trace'];created=[g for g in m1['bindings'].values() if g]
        checks.update(m1_one_created=len(created)==1,m1_no_errors=not m1['extraction']['_errors'],
            m1_collect_only=len(t.get('deferred_topics',[]))==1 and not t['review_records'],
            m1_no_duplicate_unresolved=not m1['extraction']['unresolved'],m1_repair_valid=t.get('repair',{}).get('status')!='failed')
        if len(created)!=1:raise ValueError('M1 must create one existing task before M2')
        guid=created[0]
        checks['repeat_no_duplicate']=svc.process(read(ROOT/'examples/m1.json'),'host','2026-11-09T10:02:00+08:00')['bindings']==m1['bindings']
        store.close();store=Store(out/'state.sqlite');svc=Service(store,model)
        checks['restart_no_duplicate']=svc.process(read(ROOT/'examples/m1.json'),'host','2026-11-09T10:02:00+08:00')['bindings']==m1['bindings']
        m2input=positive_meeting() if positive else read(ROOT/'examples/m2.json');write_json(out/'m2-input.json',m2input)
        m2=svc.process(m2input,'host','2026-11-16T10:02:00+08:00');write_json(out/'m2-result.json',m2)
        (out/'M2.md').write_text(svc.minutes(m2['source_id'],'host'),encoding='utf8')
        e=m2['extraction'];t=e['_task_trace'];items=e['items'];reviews=t['review_records']
        checks.update(m2_no_errors=not e['_errors'],old_task_done=svc.sim.get(guid,'host')['status']=='done',
            m2_one_work=len(items)==1,m2_no_deferred=not t.get('deferred_topics'),
            m2_repair_valid=t.get('repair',{}).get('status')!='failed')
        if positive:
            checks.update(accepted_config=len(items)==1 and items[0]['operation']=='create',no_questions=not reviews,
                          exactly_two_written_tasks=len(store.tasks())==2)
        else:
            checks.update(scope_candidate=len(items)==1 and items[0]['operation']=='candidate',
                only_owner_question=len(reviews)==1 and reviews[0]['missing_fields']==['owner'],
                no_invented_person=len(items)==1 and items[0]['owner_ref'] is None,only_original_written=len(store.tasks())==1,
                today_visible=len(items)==1 and ('今天' in items[0]['description'] or items[0].get('due_text')=='今天' or items[0].get('due_date')=='2026-11-16'))
        decisions=svc.decisions('登录改版','host','2026-11-16T10:02:00+08:00',history=True)
        checks['decision_replaced']=len(decisions)==2 and decisions[-1]['supersedes']==decisions[0]['id']
    except Exception as exc:
        write_json(out/'error.json',dict(type=type(exc).__name__,detail=str(exc)));checks['completed']=False
    finally:store.close()
    row=dict(case='positive-service' if positive else 'M2-service',checks=checks,observable_passed=all(checks.values()),semantic_review='pending')
    write_json(out/'assessment.json',row);return row


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--rounds',type=int,default=1)
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    snapshot(args.out)
    selected=cases();write_json(args.out/'manifest.json',dict(rounds=args.rounds,retries=0,cases=list(selected),
        service=['M2','positive'],policy=read(Path(__file__).with_name('review-policy-2026-11-16.json')),
        frozen_upstream=['G-omitted'],other_cases='full pipeline / full Service'))
    rows=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs=[]
        for i in range(1,args.rounds+1):
            for name,case in selected.items():jobs.append(pool.submit(focused,name,case,args.out/f'r{i}'/name))
            for positive in (False,True):jobs.append(pool.submit(service,positive,args.out/f'r{i}'/('positive-service' if positive else 'M2-service')))
        for future in as_completed(jobs):
            row=future.result();rows.append(row);print(row['case'],row['observable_passed'],[k for k,v in row['checks'].items() if not v],flush=True)
    write_json(args.out/'results.json',dict(rows=rows,usage=usage(args.out)))
    print(json.dumps(usage(args.out)),flush=True)


if __name__=='__main__':main()
