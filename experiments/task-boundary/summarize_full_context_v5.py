"""Verify the frozen run and aggregate source-reviewed full-validation results."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path(__file__).parent))
from meeting_eval.inputs import digest
from run_full_context_v5 import assess_result


def read(p):return json.loads(p.read_text(encoding='utf8'))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def summarize(base):
    manifest=read(base/'manifest.json');raw=read(base/'summary.json');notes=read(base/'source-review-notes.json')
    overlay=read(base/'policy-overlay.json') if (base/'policy-overlay.json').exists() else {'rule_overrides':{}}
    assert digest(manifest)==read(base/'freeze.json')['manifest_hash']==raw['manifest_hash']
    expected={(r,g,c) for r in (1,2) for g,c in [(j['group'],j['id']) for j in manifest['jobs']]+[('chains',name) for name in manifest['chains']]}
    found={(r['round'],r['group'],r['case_id']) for r in raw['rows']}
    assert len(raw['rows'])==len(expected)==190 and found==expected
    rows=[];code_audits=[]
    with zipfile.ZipFile(base/'source.zip') as archive:
        for row in raw['rows']:
            key=f"r{row['round']}/{row['group']}/{row['case_id']}";folder=base/key
            note=notes[key];assert note['reviewed']
            paths=[folder/'m1-result.json',folder/'m2-result.json'] if row['group']=='chains' else [folder/'result.json']
            if not all(p.exists() for p in paths):paths=[folder/'failure.json']
            if len(paths)==1:expected_sha=hashlib.sha256(paths[0].read_bytes()).hexdigest()
            else:expected_sha=digest([read(p) for p in paths])
            assert note['sha256']==expected_sha,key+' output changed after review'
            traces=[]
            for path in paths:
                result=read(path)
                if 'extraction' in result:traces.append(result['extraction'].get('_task_trace',{}))
            for trace in traces:
                mismatches=[]
                for name,sha in trace.get('config',{}).get('code',{}).items():
                    source=archive.read('meeting_eval/'+name).decode('utf8').replace('\r\n','\n')
                    if digest(source)!=sha:mismatches.append(name)
                code_audits.append(dict(case=key,mismatches=mismatches))
            rule_key=row['group']+'/'+row['case_id'];current_passed=row['passed'];current_checks=None
            if rule_key in overlay['rule_overrides']:
                rule={**manifest['rules'][rule_key],**overlay['rule_overrides'][rule_key]}
                grade=assess_result(read(folder/'result.json'),read(folder/'tasks.json'),rule)
                current_passed=grade['passed'];current_checks=grade['checks']
            rows.append(dict(**row,current_observable_passed=current_passed,current_checks=current_checks,
                source_review=note,full_passed=current_passed and note['semantic_passed']))
    assert not any(r['mismatches'] for r in code_audits)
    assert not list(base.rglob('retry-*')), 'Unexpected retry directory'
    groups={}
    for round_no in (1,2):
        selected=[r for r in rows if r['round']==round_no]
        groups['r'+str(round_no)]={}
        for group in sorted({r['group'] for r in selected}):
            subset=[r for r in selected if r['group']==group]
            groups['r'+str(round_no)][group]=dict(total=len(subset),original_observable_passed=sum(r['passed'] for r in subset),
                current_observable_passed=sum(r['current_observable_passed'] for r in subset),full_passed=sum(r['full_passed'] for r in subset))
    pairs=defaultdict(list)
    for row in rows:pairs[row['group']+'/'+row['case_id']].append(row)
    stability=Counter('both_pass' if all(r['full_passed'] for r in pair) else 'both_fail' if not any(r['full_passed'] for r in pair) else 'flipped' for pair in pairs.values())
    categories=Counter(cat for row in rows for cat in set(row['source_review'].get('categories',[])))
    metas=[read(p) for p in base.rglob('meta.json')]
    usage=dict(calls=len(metas),received=sum(m['status']=='received' for m in metas),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),
        retries=0,wall_seconds=raw['seconds'],median_case_seconds=statistics.median(r['seconds'] for r in rows))
    assert usage['calls']==raw['calls'] and usage['tokens']==raw['tokens']
    report=dict(total=len(rows),original_observable_passed=sum(r['passed'] for r in rows),
        current_observable_passed=sum(r['current_observable_passed'] for r in rows),full_passed=sum(r['full_passed'] for r in rows),
        policy_overlay=overlay,
        source_review_only_passed=sum(r['source_review']['semantic_passed'] for r in rows),
        groups=groups,stability=dict(stability),case_error_categories=dict(categories),usage=usage,
        review_status='assistant_source_reviewed_not_independent_human_gold',rows=rows,
        limitations=['Regression set previously inspected, not blind holdout.','95 scenarios repeated twice; not 190 independent samples.',
            'Full pass requires the effective observable contract (frozen rules plus the recorded policy overlay) and source review; disagreements remain visible.'])
    write(base/'source-code-audit.json',code_audits);write(base/'final-report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);summarize(p.parse_args().out)
