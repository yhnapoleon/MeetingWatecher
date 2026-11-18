"""Resume transport-interrupted cases in copies, preserving frozen first passes."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
import zipfile

from run import ROOT, recover, read, write_json, snapshot
from run_full_context_v5 import assess_result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    source=args.source.resolve();out=args.out.resolve()
    report=read(source/'final-report.json');manifest=read(source/'manifest.json')
    selected=[r for r in report['rows'] if 'transport_failure' in r['source_review']['categories']]
    assert len(selected)==11
    with zipfile.ZipFile(source/'source.zip') as z:
        names=[n for n in z.namelist() if n.startswith(('meeting_eval/','prompts/')) and not n.endswith('/')]
        assert all(z.read(n)==(ROOT/n).read_bytes() for n in names),'Production sources changed'
    hashes={str(f.relative_to(source)):hashlib.sha256(f.read_bytes()).hexdigest()
            for f in source.rglob('*') if f.is_file()}
    jobs={(j['group'],j['id']):j for j in manifest['jobs']}
    out.mkdir(parents=True,exist_ok=False)
    write_json(out/'source-hashes.json',hashes)
    write_json(out/'manifest.json',dict(source=source.as_posix(),selected=selected,workers=2,
        policy='One resume per selected network-interrupted execution; successful stages reused; semantic/protocol failures not retried.',
        original_total=report['total'],original_passed=report['full_passed']))
    snapshot(out)

    def one(row):
        key=f"r{row['round']}/{row['group']}/{row['case_id']}";original=source/key;target=out/key
        previous=read(original/'result.json')
        assert previous['status']=='partial'
        assert all(e['error'] in ('TimeoutError','URLError','RemoteDisconnected') for e in previous['extraction']['_errors'])
        started=time.perf_counter()
        result=recover(jobs[(row['group'],row['case_id'])],target,original,strategy='context-v5')
        rule_key=row['group']+'/'+row['case_id']
        rule={**manifest['rules'][rule_key],**report['policy_overlay']['rule_overrides'].get(rule_key,{})}
        grade=assess_result(read(target/'result.json'),read(target/'tasks.json'),rule)
        write_json(target/'assessment.json',grade)
        result.update(key=key,round=row['round'],observable_passed=grade['passed'],
            failed_checks=[k for k,v in grade['checks'].items() if not v],seconds=round(time.perf_counter()-started,3))
        write_json(target/'recovery-summary.json',result)
        return result

    started=time.perf_counter();rows=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(one,row) for row in selected]
        for future in as_completed(futures):
            row=future.result();rows.append(row);write_json(out/'progress.json',rows)
            print(json.dumps(dict(case=row['key'],status=row['status'],passed=row['observable_passed'],
                errors=row['errors'],failed=row['failed_checks'],new_calls=row['calls']),ensure_ascii=False),flush=True)
    assert hashes=={str(f.relative_to(source)):hashlib.sha256(f.read_bytes()).hexdigest()
                   for f in source.rglob('*') if f.is_file()},'Original evidence changed'
    write_json(out/'summary.json',dict(rows=rows,total=len(rows),observable_passed=sum(r['observable_passed'] for r in rows),
        new_calls=sum(r['calls'] for r in rows),new_tokens=sum(r['tokens'] for r in rows),
        seconds=round(time.perf_counter()-started,3),original_evidence_unchanged=True,source_review='pending'))
    print('Recovery calls complete; source review pending.',flush=True)


if __name__=='__main__':main()
