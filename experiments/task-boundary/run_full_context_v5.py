"""Frozen full Service evaluation of context-v5; independent rounds, no retries."""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(Path(__file__).parent)]
from meeting_eval.inputs import digest
from scripts.run_action_baseline import write_json
from run_context_v3 import snapshot
from verify_user_solutions import service
import run as boundary

OLD=ROOT/'runs/2026-11-15-full-validation'
HERE=Path(__file__).parent


def read(p):return json.loads(p.read_text(encoding='utf8'))
def jsonl(p):return [json.loads(s) for s in p.read_text(encoding='utf8').splitlines() if s.strip()]


def build_manifest():
    jobs=copy.deepcopy(read(OLD/'manifest.json')['jobs'])+copy.deepcopy(read(HERE/'fixtures.json')['cases'])
    labels={g:jsonl(OLD/g/('labels.audited.jsonl' if g=='corpus' else 'labels.snapshot.jsonl'))
            for g in ('corpus','context','probes','cancellation')}
    c23=next(r for r in labels['corpus'] if r['case_id']=='C23')
    c23.update(description='会后单独联系袁校长，继续沟通其他问题。',required_content=['会后或稍后单独联系袁校长','继续沟通其他问题'],
               review_basis='用户2026-11-16裁定：推断的补问目的不作为必写门槛。')
    rules={}
    for job in jobs:
        g,cid=job['group'],job['id'];rule={}
        if g in labels:
            refs=[r for r in labels[g] if r['case_id']==cid and r['operation'] in ('create','candidate')]
            rule=dict(item_counts=[len(refs)],signatures=[[r['operation'],r.get('owner_ref')] for r in refs],
                no_review=not any(r['operation']=='candidate' for r in refs),
                no_deadline=all(r.get('due_text') is None and r.get('due_date') is None for r in refs))
            if refs and all(r['operation']=='candidate' for r in refs):rule['review_count']=len(refs)
            if cid in ('C25','C26','CP06'):
                rule.update(no_review=False,needs_implicit=cid!='C26',needs_proposal=cid=='C26')
            if cid=='C14':rule['conditional']=True
            if cid in ('C19','C20','C21','C22','C23'):rule['only_owner']=True
            if cid=='C17':rule['report_states']=['completed','progress']
        elif g=='pairs':
            rule=copy.deepcopy(next(r for r in read(HERE/'expectations.json')['cases'] if r['case_id']==cid))
            if cid=='P07a':rule['needs_proposal']=True
        elif g=='updates':
            rule=dict(update_expected=job['expected'],original_task_ids=[t['guid'] for t in job['tasks']])
            if cid=='M2':rule.update(item_counts=[1],only_owner=True,today_visible=True,scope_objects=True,operations=['candidate'])
        rules[g+'/'+cid]=rule
    originals={j['id']:j for j in jobs}
    for name,lines in {
        'S-C23-explicit':['因为刚才信号不好，有些讲解没听清，会后我们单独联系袁校长，把没听清的问题补问清楚。','好的，稍后联系。'],
        'S-C23-unrelated':['刚才的信号问题已经解决，讲解内容也都听清了。另外还有几个报名问题，会后我们单独联系袁校长沟通。','好的，稍后联系沟通报名问题。'],
        'S-no-date':['我来整理登录失败案例并发到研发群。'],
        'S-activate':['上线后要不要再做个监控面板？先放着，今天不定。','刚才的监控面板还是做吧，我来完成。'],
    }.items():
        job=copy.deepcopy(originals['C23']);job.update(id=name,group='supplemental')
        m=job['meeting'];m.update(case_id=name,meeting_id=name)
        template=m['segments'][0]
        m['segments']=[dict(template,id=f'{name}.{i}',text=text,start_ms=i*1000,end_ms=(i+1)*1000) for i,text in enumerate(lines,1)]
        jobs.append(job);rules['supplemental/'+name]=dict(item_counts=[1],operations=['candidate'],only_owner=True,no_deadline=True,no_deferred=True)
    job=copy.deepcopy(originals['M2']);job.update(id='S-same-segment',group='supplemental');job['meeting'].update(case_id=job['id'],meeting_id=job['id'])
    job['meeting']['segments'][1]['text']+='另外，陈可今天下班前把测试结果发给客服。'
    jobs.append(job);rules['supplemental/S-same-segment']=dict(item_counts=[2],operations=['candidate','candidate'],
        update_expected=job['expected'],original_task_ids=[t['guid'] for t in job['tasks']],separate_scope_delivery=True)
    m1=dict(id='S-M1',group='supplemental',meeting=read(ROOT/'examples/m1.json'),actor='host',tasks=[])
    jobs.append(m1);rules['supplemental/S-M1']=dict(item_counts=[1],signatures=[['create','chen']],no_review=True,deferred_count=1,no_duplicate_unresolved=True)
    assert len(jobs)==93
    return dict(status='frozen',strategy='context-v5',jobs=jobs,labels=labels,rules=rules,
        chains=['M2-service','positive-service'],rounds=2,retries=0,frozen_model_stages=False,
        policy=read(HERE/'review-policy-2026-11-16.json'),
        scope_notes=['87 existing scenarios + 6 supplements + 2 full M1→M2 chains = 95 per round.',
            'P03a/P12a remain statements of a decision/current value, not an imperative to implement; retain original contracts and flag ambiguity in source review.',
            'M2 today-change directive is actionable; C23 inferred purpose is optional.',
            'Historical dev/holdout cases have been inspected in prior tuning; this is regression, not a blind holdout.',
            'Structured checks are not semantic truth. All source/output descriptions and review questions require source review.'],
        sources={str(p.relative_to(ROOT)).replace('\\','/'):digest(read(p)) for p in (OLD/'manifest.json',HERE/'fixtures.json',HERE/'expectations.json')})


def assess_result(result,tasks,rule):
    e=result.get('extraction',{});t=e.get('_task_trace',{});items=e.get('items',[]);reviews=t.get('review_records',[])
    checks=dict(processed=result.get('status')=='processed',no_extraction_errors=not e.get('_errors'),
        repair_valid=t.get('repair',{}).get('status')!='failed',no_interpretation_unresolved=not any(r['category']=='interpretation_unresolved' for r in reviews))
    if 'item_counts' in rule:checks['item_count']=len(items) in rule['item_counts']
    if 'signatures' in rule:checks['operation_owner']=sorted([[i['operation'],i.get('owner_ref')] for i in items],key=repr)==sorted(rule['signatures'],key=repr)
    if rule.get('no_review'):checks['no_review']=not reviews
    if rule.get('needs_implicit'):checks['implicit_need']=any(r['category']=='implicit_need' for r in reviews)
    if rule.get('needs_proposal'):checks['proposal']=any(r['category']=='proposal' for r in reviews)
    if rule.get('needs_report'):checks['report_retained']=bool(t.get('reports'))
    if rule.get('report_states'):checks['report_states']=set(rule['report_states'])<=set(r.get('state') for r in t.get('reports',[]))
    if rule.get('no_deadline'):checks['no_deadline']=all(i.get('due_date') is None and i.get('due_text') is None for i in items)
    if rule.get('operations'):checks['operations']=sorted(i['operation'] for i in items)==sorted(rule['operations'])
    if 'review_count' in rule:checks['review_count']=len(reviews)==rule['review_count']
    if rule.get('only_owner'):
        checks['only_owner']=len(reviews)==len(items) and bool(reviews) and all(r['missing_fields']==['owner'] and '具体内容' not in r['question'] and '是否执行' not in r['question'] for r in reviews)
    if rule.get('today_visible'):checks['today_visible']=bool(items) and all('今天' in i['description'] or i.get('due_text')=='今天' or i.get('due_date')=='2026-11-16' for i in items)
    if rule.get('scope_objects'):checks['scope_objects']=len(items)==1 and all(s in items[0]['description'] for s in ('内部员工','试点客户'))
    if rule.get('no_deferred'):checks['no_deferred']=not t.get('deferred_topics')
    if 'deferred_count' in rule:checks['deferred_count']=len(t.get('deferred_topics',[]))==rule['deferred_count']
    if rule.get('no_duplicate_unresolved'):checks['no_duplicate_unresolved']=not e.get('unresolved')
    if rule.get('conditional'):
        checks['condition_retained']=any(r.get('commitment_kind')=='conditional' and r.get('commitment_quotes') for r in reviews)
        checks['no_automatic_creation']=all(i['operation']=='candidate' for i in items) and not tasks
    if rule.get('promoted_context'):
        checks['multiple_checkpoints']=len(t.get('checkpoints',[]))>=2
        checks['context_retained']=bool(t.get('context_records'))
    if rule.get('separate_scope_delivery'):
        scope=[r for r in reviews if '范围' in r['description']];delivery=[r for r in reviews if '测试结果' in r['description']]
        checks['independent_gaps']=len(scope)==len(delivery)==1 and scope[0]['missing_fields']==['owner'] and delivery[0]['missing_fields']==['commitment']
    if 'update_expected' in rule:
        expected=rule['update_expected'];byid={t['guid']:t for t in tasks};new=[t for t in tasks if t['guid'] not in rule['original_task_ids']]
        checks.update(statuses=all(byid.get(g,{}).get('status')==v for g,v in expected['statuses'].items()),
            dates=all(g in byid and byid[g].get('due_date')==v for g,v in expected['dates'].items()),new_tasks=len(new)==expected['new_tasks'])
        if expected.get('new_due'):checks['new_due']=all(t.get('due_date')==expected['new_due'] for t in new)
        if expected['no_review']:checks['no_review']=not reviews
        if expected['pending']:checks['pending']=bool(result.get('pending') or reviews or e.get('unresolved'))
        if expected.get('review_type'):checks['review_type']=any(r['category']==expected['review_type'] for r in reviews)
    return dict(checks=checks,passed=all(checks.values()),semantic_review='pending')


def one(job,folder,rule,inference_config=None):
    row=boundary.one(job,folder,'b','none',strategy='context-v5',inference_config=inference_config)
    result=read(folder/'result.json') if (folder/'result.json').exists() else dict(status='failed')
    tasks=read(folder/'tasks.json') if (folder/'tasks.json').exists() else []
    grade=assess_result(result,tasks,rule)
    grade.update(group=job['group'],case_id=job['id'],result_hash=digest(result))
    write_json(folder/'assessment.json',grade)
    return dict(group=job['group'],case_id=job['id'],passed=grade['passed'],failed=[k for k,v in grade['checks'].items() if not v],
        calls=row['calls'],tokens=row['tokens'],seconds=row['seconds'],status=row['status'])


def chain(name,folder,inference_config=None):
    started=time.perf_counter();grade=service(name=='positive-service',folder,inference_config=inference_config)
    metas=[read(p) for p in folder.rglob('meta.json')]
    return dict(group='chains',case_id=name,passed=grade['observable_passed'],failed=[k for k,v in grade['checks'].items() if not v],
        calls=len(metas),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),seconds=round(time.perf_counter()-started,3),status='completed')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    manifest=build_manifest();write_json(args.out/'manifest.json',manifest);write_json(args.out/'freeze.json',dict(manifest_hash=digest(manifest)))
    snapshot(args.out);all_rows=[];started=time.perf_counter()
    for round_no in (1,2):
        rows=[];out=args.out/f'r{round_no}';out.mkdir()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures=[pool.submit(one,j,out/j['group']/j['id'],manifest['rules'][j['group']+'/'+j['id']]) for j in manifest['jobs']]
            futures += [pool.submit(chain,name,out/'chains'/name) for name in manifest['chains']]
            for future in as_completed(futures):
                row=future.result();row['round']=round_no;rows.append(row);all_rows.append(row)
                write_json(out/'progress.json',rows)
                print(f"r{round_no} {len(rows)}/95 {row['group']}/{row['case_id']} {'PASS' if row['passed'] else 'FAIL'} {row['failed']}",flush=True)
        write_json(out/'summary.json',dict(rows=rows,passed=sum(r['passed'] for r in rows),total=len(rows)))
    write_json(args.out/'summary.json',dict(rows=all_rows,passed=sum(r['passed'] for r in all_rows),total=len(all_rows),
        calls=sum(r['calls'] for r in all_rows),tokens=sum(r['tokens'] for r in all_rows),seconds=round(time.perf_counter()-started,3),retries=0,
        semantic_review='pending',manifest_hash=digest(manifest)))
    print('Finished both rounds; semantic source review still required.',flush=True)


if __name__=='__main__':main()
