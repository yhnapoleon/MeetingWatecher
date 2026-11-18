"""Fresh system validation, with bounded recovery and honest attempt accounting."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import time

from run_context_v5_fixes import current_manifest
from run_full_context_v5 import ROOT,one,chain,read,write_json,snapshot,digest


def accounting(folder):
    metas=[read(p) for p in folder.rglob('meta.json')]
    request_dirs={p.parent for p in folder.rglob('request.json')}
    meta_dirs={p.parent for p in folder.rglob('meta.json')}
    interrupted=len(request_dirs-meta_dirs)
    states=[read(p) for p in folder.rglob('state.json') if 'attempts' in read(p)]
    return dict(calls=len(metas),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),
        unknown_usage_calls=sum(m.get('usage') is None for m in metas)+interrupted,
        requests_without_final_metadata=interrupted,request_records=len(request_dirs),
        retries=sum(max(0,len(s['attempts'])-1) for s in states),
        recovered_nodes=sum(len(s['attempts'])>1 and s.get('status')=='accepted' for s in states),
        exhausted_nodes=sum(s.get('status') in ('exhausted','recovery_required') for s in states),
        deferred_nodes=sum(s.get('status') in ('deferred','waiting_retry') for s in states),
        terminal_nodes=sum(s.get('status')=='terminal_error' for s in states),
        normalized_nodes=sum(any(a.get('candidate_file')=='normalized.json' for a in s['attempts']) for s in states),
        first_attempt_failures=sum(bool(s['attempts']) and s['attempts'][0]['status']!='accepted' for s in states))


def include_semantic(manifest):
    labels=read(ROOT/'experiments/task-boundary/semantic-v1.json')
    manifest['jobs'] += [dict(id=c['case_id'],group='semantic',meeting=c['meeting'],actor=c.get('actor','host'),tasks=[]) for c in labels['cases']]
    manifest['rules'].update({'semantic/'+c['case_id']:{} for c in labels['cases']})
    manifest.update(semantic_labels=labels,semantic_labels_hash=digest(labels))
    return manifest


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    p.add_argument('--only',nargs='+');p.add_argument('--semantic',action='store_true')
    p.add_argument('--include-semantic',action='store_true')
    p.add_argument('--review-policy',type=Path)
    p.add_argument('--rounds',type=int,default=2);p.add_argument('--workers',type=int,default=4)
    args=p.parse_args();manifest=current_manifest()
    if args.semantic and args.include_semantic:p.error('Choose semantic only or include-semantic')
    if args.include_semantic:manifest=include_semantic(manifest)
    if args.semantic:
        labels=read(ROOT/'experiments/task-boundary/semantic-v1.json')
        manifest.update(jobs=[dict(id=c['case_id'],group='semantic',meeting=c['meeting'],actor=c.get('actor','host'),tasks=[]) for c in labels['cases']],
            chains=[],rules={'semantic/'+c['case_id']:{} for c in labels['cases']},semantic_labels_hash=digest(labels))
    if args.only:
        selected=set(args.only);manifest['jobs']=[j for j in manifest['jobs'] if j['id'] in selected]
        manifest['chains']=[c for c in manifest['chains'] if c in selected]
        assert selected=={j['id'] for j in manifest['jobs']}|set(manifest['chains'])
    inference=read(ROOT/'experiments/action-context/compact-check.json')
    manifest.update(rounds=args.rounds,inference=inference,retries='bounded: 2 content generations, 2 transport retries, maximum 4 automatic requests per node; no manual grants or outer resampling',
        semantic_review='pending',workers=args.workers)
    if args.review_policy:
        manifest['review_policy']=read(args.review_policy)
        manifest['review_policy_hash']=digest(manifest['review_policy'])
    args.out.mkdir(parents=True,exist_ok=False);write_json(args.out/'manifest.json',manifest)
    write_json(args.out/'freeze.json',dict(manifest_hash=digest(manifest)));snapshot(args.out)
    rows=[];start=time.perf_counter()
    for rd in range(1,args.rounds+1):
        out=args.out/f'r{rd}';out.mkdir();current=[]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures={pool.submit(one,j,out/j['group']/j['id'],manifest['rules'][j['group']+'/'+j['id']],inference):(j['group'],j['id']) for j in manifest['jobs']}
            futures.update({pool.submit(chain,n,out/'chains'/n,inference):('chains',n) for n in manifest['chains']})
            for future in as_completed(futures):
                group,cid=futures[future]
                try:row=future.result()
                except Exception as exc:row=dict(group=group,case_id=cid,passed=False,failed=['runner_exception'],error=type(exc).__name__+': '+str(exc),status='failed')
                row.update(round=rd,**accounting(out/group/cid));rows.append(row);current.append(row)
                write_json(out/'progress.json',current)
                print(f"r{rd} {len(current)} {group}/{cid} {'PASS' if row['passed'] else 'FAIL'} {row['failed']}",flush=True)
        write_json(out/'summary.json',dict(rows=current,passed=sum(r['passed'] for r in current),total=len(current)))
    write_json(args.out/'summary.json',dict(rows=rows,passed=sum(r['passed'] for r in rows),total=len(rows),
        **accounting(args.out),seconds=round(time.perf_counter()-start,3),semantic_review='pending',manifest_hash=digest(manifest)))


if __name__=='__main__':main()
