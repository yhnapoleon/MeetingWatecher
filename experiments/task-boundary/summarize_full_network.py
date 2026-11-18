"""Offline source-reviewed recovery overlay; never modifies original evidence."""
import argparse
import hashlib
from pathlib import Path
import zipfile

from run import ROOT, read, write_json
from run_full_context_v5 import assess_result
from meeting_eval.inputs import digest


def summarize(source,out):
    original=read(source/'final-report.json');manifest=read(source/'manifest.json')
    selected=read(out/'manifest.json')['selected'];notes=read(out/'source-review-notes.json')
    hashes=read(out/'source-hashes.json')
    assert hashes=={str(f.relative_to(source)):hashlib.sha256(f.read_bytes()).hexdigest()
                   for f in source.rglob('*') if f.is_file()},'Original evidence changed'
    rows=[];all_new=[]
    with zipfile.ZipFile(source/'source.zip') as archive:
        for old in selected:
            key=f"r{old['round']}/{old['group']}/{old['case_id']}";folder=out/key;prior=source/key
            result=read(folder/'result.json');tasks=read(folder/'tasks.json');note=notes[key]
            assert note['reviewed'] and note['sha256']==hashlib.sha256((folder/'result.json').read_bytes()).hexdigest()
            before={p.relative_to(prior).as_posix() for p in (prior/'model').rglob('meta.json')}
            new=[read(p) for p in (folder/'model').rglob('meta.json') if p.relative_to(folder).as_posix() not in before]
            assert new,'No recovery requests recorded'
            all_new+=new
            for name,sha in result['extraction']['_task_trace']['config']['code'].items():
                assert digest(archive.read('meeting_eval/'+name).decode('utf8').replace('\r\n','\n'))==sha
            rule_key=old['group']+'/'+old['case_id']
            rule={**manifest['rules'][rule_key],**original['policy_overlay']['rule_overrides'].get(rule_key,{})}
            grade=assess_result(result,tasks,rule);write_json(folder/'assessment.json',grade)
            errors=result['extraction'].get('_errors',[])
            row=dict(key=key,round=old['round'],group=old['group'],case_id=old['case_id'],status=result['status'],
                errors=errors,network_recovered=not any(e['error'] in ('TimeoutError','URLError','RemoteDisconnected') for e in errors),
                observable_passed=grade['passed'],source_review=note,full_passed=grade['passed'] and note['semantic_passed'],
                failed_checks=[k for k,v in grade['checks'].items() if not v],new_calls=len(new),
                new_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in new))
            rows.append(row);write_json(folder/'recovery-summary.json',row)
            write_json(folder/'summary.json',dict(**row,first_pass_source=prior.as_posix(),
                metric_note='This is a recovery result. New usage excludes copied original requests.'))
    assert len(rows)==len(notes)==11
    replacements={r['key']:r for r in rows};effective=[]
    for old in original['rows']:
        key=f"r{old['round']}/{old['group']}/{old['case_id']}"
        effective.append(dict(key=key,round=old['round'],full_passed=replacements[key]['full_passed'] if key in replacements else old['full_passed'],
            source='network_recovery' if key in replacements else 'original'))
    result=dict(original_total=190,original_passed=original['full_passed'],recovery_total=len(rows),
        network_recovered=sum(r['network_recovered'] for r in rows),recovery_passed=sum(r['full_passed'] for r in rows),
        effective_passed=sum(r['full_passed'] for r in effective),
        rounds={f'r{rd}':dict(total=95,passed=sum(r['full_passed'] for r in effective if r['round']==rd)) for rd in (1,2)},
        new_calls=len(all_new),new_received=sum(m['status']=='received' for m in all_new),
        new_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in all_new),
        original_evidence_unchanged=True,algorithm_unchanged=True,
        metric_note='Recovery-inclusive result, not independent fresh-run accuracy; successful stages reused and original first-pass failures retained.',
        rows=rows,effective_rows=effective)
    write_json(out/'final-report.json',result)
    print({k:v for k,v in result.items() if k not in ('rows','effective_rows')})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();summarize(a.source,a.out)
