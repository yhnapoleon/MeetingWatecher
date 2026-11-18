"""One fresh four-case acceptance run. Never rerun a failed case automatically."""
import argparse
import time
from pathlib import Path

from run_context_v5_fixes import current_manifest
from run_full_context_v5 import ROOT,read,write_json,digest,assess_result
from run import one,configure
from meeting_eval.extract import Extractor
from meeting_eval.service import Service
from meeting_eval.store import Store


def accounting(folder):
    metas=[read(p) for p in folder.rglob('meta.json')]
    states=[read(p) for p in folder.rglob('state.json') if 'attempts' in read(p)]
    requests={p.parent for p in folder.rglob('request.json')}
    metadata={p.parent for p in folder.rglob('meta.json')}
    return dict(requests=len(requests),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),
        unknown_usage_calls=sum(m.get('usage') is None for m in metas)+len(requests-metadata),
        additional_requests=sum(max(0,len(s['attempts'])-1) for s in states),
        normalized_nodes=sum(any(a.get('candidate_file')=='normalized.json' for a in s['attempts']) for s in states),
        recovered_nodes=sum(len(s['attempts'])>1 and s.get('status')=='accepted' for s in states),
        recovery_required=sum(s.get('status')=='recovery_required' for s in states),
        waiting_retry=sum(s.get('status')=='waiting_retry' for s in states),
        terminal_error=sum(s.get('status')=='terminal_error' for s in states))


def verify(job,folder,inference,rule):
    result=read(folder/'result.json');tasks=read(folder/'tasks.json');e=result['extraction'];cid=job['id']
    checks=dict(processed=result['status']=='processed',no_extraction_errors=not e.get('_errors'))
    if cid=='C14':checks.update(assess_result(result,tasks,rule)['checks'])
    if cid=='SV05':
        issues=result.get('collected_issues',[])
        checks.update(one_lecture_version_issue=len(issues)==1 and '讲义' in issues[0]['statement'] and '版本' in issues[0]['statement'],
            classroom_not_unresolved=not any('教室' in r['statement'] for r in e['unresolved']),no_created_task=not tasks)
    if cid=='SV17':
        facts=' '.join(r['statement'] for r in e['facts'])
        checks.update(deferred_fact='下周' in facts and '登录页' in facts,no_immediate_question=not e['unresolved'],
            no_immediate_work=not e['items'] and not tasks)
    if cid=='SV10':
        actions=' '.join(r['description'] for r in e['items'])
        checks.update(parallel_work='海报' in actions and '文稿' in actions and '时间' in actions,
            owner_and_commitment=bool(e['items']) and all(r['operation']=='create' and r['owner_ref']=='lin' for r in e['items']),
            no_unresolved=not e['unresolved'],created=bool(tasks))
    actor=job['actor'];sid=result['source_id']
    # Reopen the DB through the same normal configuration before testing persistence/reentry.
    extractor=Extractor(ROOT.parent.parent/'meeting-agent/.env',folder/'model','context-v5',inference_config=inference)
    configure(extractor,'b',None,'none')
    store=Store(folder/'state.sqlite')
    try:
        svc=Service(store,extractor);issues=svc.collected_issues(sid,actor)
        checks['issues_survive_reopen']=issues==result.get('collected_issues',[])
        try:svc.collected_issues(sid,'unauthorized-reviewer')
        except PermissionError:checks['issue_access_control']=True
        else:checks['issue_access_control']=False
        if result['status']=='processed':
            before=accounting(folder);events=store.db.execute('SELECT count(*) FROM task_events').fetchone()[0]
            again=svc.process(job['meeting'],actor,'2026-11-17T10:05:00+08:00')
            checks['reentry_no_requests']=accounting(folder)==before
            checks['reentry_no_writes']=events==store.db.execute('SELECT count(*) FROM task_events').fetchone()[0] and store.tasks()==tasks
            checks['reentry_stable_issues']=again.get('collected_issues',[])==issues
        else:checks['reentry_no_requests']=None  # Failed outer runs are preserved, not sampled again.
        (folder/'minutes.md').write_text(svc.minutes(sid,actor),encoding='utf8')
    finally:store.close()
    return dict(case_id=cid,checks=checks,passed=all(v is True for v in checks.values()),
        diagnostic_categories=[r['category'] for r in e.get('_task_trace',{}).get('review_records',[])],
        result_hash=digest(result),semantic_review='pending',**accounting(folder))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    old=current_manifest();labels=read(ROOT/'experiments/task-boundary/semantic-v1.json')
    jobs=[next(j for j in old['jobs'] if j['id']=='C14')]
    jobs.extend(dict(id=c['case_id'],group='semantic',meeting=c['meeting'],actor=c['actor'],tasks=[])
        for identity in ('SV17','SV05','SV10') for c in labels['cases'] if c['case_id']==identity)
    inference=read(ROOT/'experiments/action-context/compact-check.json')
    manifest=dict(jobs=jobs,inference=inference,rounds=1,outer_retries=0,manual_grants=0,
        semantic_labels_hash=digest(labels),c14_rule=old['rules']['corpus/C14'],
        frozen_semantic_errors=['C11','C24','P08b','CP01','SV15'])
    write_json(args.out/'manifest.json',manifest);write_json(args.out/'freeze.json',dict(manifest_hash=digest(manifest)))
    rows=[];start=time.perf_counter()
    for job in jobs:
        folder=args.out/job['id'];one(job,folder,'b','none',strategy='context-v5',inference_config=inference)
        try:row=verify(job,folder,inference,manifest['c14_rule'])
        except Exception as exc:row=dict(case_id=job['id'],passed=False,error=type(exc).__name__+': '+str(exc),**accounting(folder))
        rows.append(row);write_json(folder/'acceptance.json',row);write_json(args.out/'progress.json',rows)
        print(job['id'],row,flush=True)
    write_json(args.out/'summary.json',dict(rows=rows,passed=sum(r['passed'] for r in rows),total=len(rows),
        seconds=round(time.perf_counter()-start,3),**accounting(args.out)))


if __name__=='__main__':main()
