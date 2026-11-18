"""Audit fresh v5 regression, including interrupted Service chains."""
import argparse
from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import zipfile

from run_full_context_v5 import ROOT, read, write_json, digest, assess_result


def artifacts(folder, chain):
    names=('m1-result.json','m2-result.json','error.json') if chain else ('result.json','failure.json')
    found=[folder/n for n in names if (folder/n).exists()]
    if not found:raise ValueError('Missing output: '+str(folder))
    return found


def output_hash(folder, chain):
    paths=artifacts(folder,chain)
    if not chain:return hashlib.sha256(paths[0].read_bytes()).hexdigest()
    if [p.name for p in paths]==['m1-result.json','m2-result.json']:
        return digest([read(p) for p in paths])
    return digest([dict(file=p.name,data=read(p)) for p in paths])


def summarize(base):
    manifest=read(base/'manifest.json');raw=read(base/'summary.json')
    notes=read(base/'source-review-notes.json')
    assert digest(manifest)==raw['manifest_hash']==read(base/'freeze.json')['manifest_hash']
    expected={f'r{rd}/{g}/{cid}' for rd in range(1,manifest['rounds']+1)
        for g,cid in [(j['group'],j['id']) for j in manifest['jobs']]+[('chains',n) for n in manifest['chains']]}
    assert len(raw['rows'])==len(expected)==190
    assert set(notes)==expected
    found=set();rows=[];audits=[]
    with zipfile.ZipFile(base/'source.zip') as archive:
        for row in raw['rows']:
            key=f"r{row['round']}/{row['group']}/{row['case_id']}"
            assert key not in found;found.add(key)
            folder=base/key;note=notes[key];chain=row['group']=='chains'
            assert note['reviewed'] and note['sha256']==output_hash(folder,chain),key
            if not chain and (folder/'result.json').exists():
                grade=assess_result(read(folder/'result.json'),read(folder/'tasks.json'),manifest['rules'][row['group']+'/'+row['case_id']])
                assert grade['passed']==row['passed'],key
            if chain and (folder/'assessment.json').exists():
                assert read(folder/'assessment.json')['observable_passed']==row['passed'],key
            for path in artifacts(folder,chain):
                trace=read(path).get('extraction',{}).get('_task_trace',{})
                mismatch=[]
                for name,sha in trace.get('config',{}).get('code',{}).items():
                    source=archive.read('meeting_eval/'+name).decode('utf8').replace('\r\n','\n')
                    if digest(source)!=sha:mismatch.append(name)
                if trace:audits.append(dict(case=key,output=path.name,mismatches=mismatch))
            rows.append(dict(**row,source_review=note,full_passed=row['passed'] and note['semantic_passed']))
        current=[p for d in ('meeting_eval','prompts') for p in (ROOT/d).rglob('*') if p.is_file() and p.suffix in ('.py','.txt')]
        source_match=all(p.read_bytes()==archive.read(p.relative_to(ROOT).as_posix()) for p in current)
    assert found==expected and not any(a['mismatches'] for a in audits) and source_match
    assert not list(base.rglob('retry-*'))
    metas=[read(p) for p in base.rglob('meta.json')]
    usage=dict(calls=len(metas),received=sum(m['status']=='received' for m in metas),
        tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),wall_seconds=raw['seconds'],retries=0)
    assert usage['calls']==raw['calls'] and usage['tokens']==raw['tokens']
    grouped=defaultdict(list)
    for row in rows:grouped[row['group']+'/'+row['case_id']].append(row)
    stability=Counter('both_pass' if all(r['full_passed'] for r in rs) else 'both_fail' if not any(r['full_passed'] for r in rs) else 'flipped' for rs in grouped.values())
    rounds={f'r{rd}':dict(total=sum(r['round']==rd for r in rows),
        automatic_passed=sum(r['round']==rd and r['passed'] for r in rows),
        full_passed=sum(r['round']==rd and r['full_passed'] for r in rows)) for rd in (1,2)}
    report=dict(total=len(rows),automatic_passed=sum(r['passed'] for r in rows),full_passed=sum(r['full_passed'] for r in rows),
        rounds=rounds,stability=dict(stability),usage=usage,source_files=len(current),source_matches_snapshot=source_match,
        policy_overlay=manifest['policy_overlay'],rows=rows,
        review_status='assistant_source_reviewed_not_independent_human_gold',
        limitations=['Previously inspected regression set, not blind holdout.','95 scenarios repeated twice, not 190 independent scenarios.',
                    'No retries; frozen-upstream probes and other tuning runs excluded.'])
    write_json(base/'source-code-audit.json',audits);write_json(base/'final-report.json',report)
    print({k:v for k,v in report.items() if k not in ('rows','policy_overlay')})
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    summarize(parser.parse_args().out)
