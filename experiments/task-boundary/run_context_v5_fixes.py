"""Fresh regression using the latest explicit policy, preserving historical runners."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from run_full_context_v5 import ROOT, build_manifest, one, chain, read, write_json, snapshot, digest


def current_manifest():
    manifest=build_manifest()
    overlay=read(ROOT/'runs/2026-11-16-context-v5-full/policy-overlay.json')
    for key, overrides in overlay['rule_overrides'].items():
        manifest['rules'][key].update(overrides)
    manifest['policy_overlay']=overlay
    manifest['scope_notes']=[n for n in manifest['scope_notes'] if not n.startswith('P03a/P12a')]
    manifest['scope_notes'].append('P03a/P12a use the explicit user-policy overlay; P07a clarification remains acceptable.')
    return manifest


def batches(manifest,gate):
    if not gate:return [dict(name='all',jobs=manifest['jobs'],chains=manifest['chains'])]
    selected=set(gate)
    missing=selected-{j['id'] for j in manifest['jobs']}-set(manifest['chains'])
    if missing:raise ValueError('Unknown gate cases: '+repr(sorted(missing)))
    return [dict(name=name,jobs=[j for j in manifest['jobs'] if (j['id'] in selected)==chosen],
                 chains=[n for n in manifest['chains'] if (n in selected)==chosen])
            for name,chosen in [('gate',True),('remaining',False)]]


def main():
    from pathlib import Path
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--only',nargs='+')
    parser.add_argument('--rounds',type=int,default=2)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--inference',type=Path,default=ROOT/'experiments/action-context/compact-check.json')
    parser.add_argument('--gate',nargs='+')
    args=parser.parse_args()
    manifest=current_manifest()
    if args.only:
        selected=set(args.only)
        jobs=[j for j in manifest['jobs'] if j['id'] in selected]
        chains=[n for n in manifest['chains'] if n in selected]
        missing=selected-{j['id'] for j in jobs}-set(chains)
        if missing:raise ValueError('Unknown cases: '+repr(sorted(missing)))
        manifest.update(jobs=jobs,chains=chains)
    inference=read(args.inference)
    phases=batches(manifest,args.gate)
    manifest.update(rounds=args.rounds,workers=args.workers,inference=inference,gate=args.gate)
    args.out.mkdir(parents=True,exist_ok=False)
    write_json(args.out/'manifest.json',manifest)
    write_json(args.out/'freeze.json',dict(manifest_hash=digest(manifest)))
    snapshot(args.out)
    started=time.perf_counter();rows=[]
    status='complete'
    for phase in phases:
        phase_rows=[]
        for rd in range(1,args.rounds+1):
            folder=args.out/f'r{rd}';folder.mkdir(exist_ok=True)
            current=[r for r in rows if r['round']==rd]
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures={pool.submit(one,j,folder/j['group']/j['id'],manifest['rules'][j['group']+'/'+j['id']],inference):
                    (j['group'],j['id']) for j in phase['jobs']}
                futures.update({pool.submit(chain,n,folder/'chains'/n,inference):('chains',n) for n in phase['chains']})
                for future in as_completed(futures):
                    group,cid=futures[future]
                    try:row=future.result()
                    except Exception as exc:
                        row=dict(group=group,case_id=cid,passed=False,failed=['runner_exception'],
                            error=type(exc).__name__+': '+str(exc),calls=0,tokens=0,seconds=0,status='failed')
                    row['round']=rd;current.append(row);rows.append(row);phase_rows.append(row)
                    write_json(folder/'progress.json',current)
                    print(f"{phase['name']} r{rd} {len(current)} {group}/{cid} {'PASS' if row['passed'] else 'FAIL'} {row['failed']}",flush=True)
            write_json(folder/'summary.json',dict(rows=current,passed=sum(r['passed'] for r in current),total=len(current)))
        write_json(args.out/(phase['name']+'-summary.json'),dict(rows=phase_rows,passed=sum(r['passed'] for r in phase_rows),total=len(phase_rows)))
        if phase['name']=='gate' and not all(r['passed'] for r in phase_rows):
            status='gate_failed';break
    write_json(args.out/'summary.json',dict(rows=rows,passed=sum(r['passed'] for r in rows),total=len(rows),
        calls=sum(r['calls'] for r in rows),tokens=sum(r['tokens'] for r in rows),seconds=round(time.perf_counter()-started,3),
        retries=0,status=status,semantic_review='pending',manifest_hash=digest(manifest)))


if __name__=='__main__':main()
