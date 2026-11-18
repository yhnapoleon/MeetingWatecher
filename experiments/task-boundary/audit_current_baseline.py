"""Compact complete business-output export and hash-bound manual judgments.

This module does not infer semantic grades. record() requires explicit judgments.
"""
import argparse
import json
from pathlib import Path
from run_full_context_v5 import ROOT,read,digest,write_json


def export(folder,keys):
    manifest=read(folder/'manifest.json');jobs={j['group']+'/'+j['id']:j for j in manifest['jobs']}
    for key in keys:
        base=folder/'r1'/key
        print('\n=== '+key+' ===')
        if key in jobs:
            job=jobs[key];m=job['meeting']
            print('IDENTITY',json.dumps({k:m.get(k) for k in ('started_at','participants','speaker_map','roster','account_map') if m.get(k)},ensure_ascii=False))
            print('SOURCE',json.dumps([(s['id'],s.get('speaker'),s['text']) for s in m['segments']],ensure_ascii=False))
            if job.get('tasks'):print('HISTORY',json.dumps(job['tasks'],ensure_ascii=False))
            labels=[r for r in manifest.get('labels',{}).get(job['group'],[]) if r['case_id']==job['id']]
            if labels:print('LABELS',json.dumps([{k:r.get(k) for k in ('operation','description','owner_ref','due_text','due_date','required_content','review_basis')} for r in labels],ensure_ascii=False))
            print('RULE',json.dumps(manifest['rules'][key],ensure_ascii=False))
            if job['group']=='semantic':print('EXPECTED',json.dumps(next(c['expected'] for c in manifest['semantic_labels']['cases'] if c['case_id']==job['id']),ensure_ascii=False))
        else:
            print('M1 SOURCE',json.dumps(read(ROOT/'examples/m1.json'),ensure_ascii=False))
            if (base/'m2-input.json').exists():print('M2 SOURCE',json.dumps(read(base/'m2-input.json'),ensure_ascii=False))
        for name in ('result.json','m1-result.json','m2-result.json'):
            if not (base/name).exists():continue
            r=read(base/name);e=r.get('extraction',{});t=e.get('_task_trace',{})
            print(name,json.dumps(dict(status=r.get('status'),errors=e.get('_errors'),
                **{k:e.get(k) for k in ('facts','decisions','unresolved','items','updates')},
                reviews=[{k:v for k,v in row.items() if k not in ('check_reason','evidence_ids')} for row in t.get('review_records',[])],
                contexts=[r['description'] for r in t.get('context_records',[])],reports=t.get('reports',[]),deferred=t.get('deferred_topics',[]),
                collected_issues=r.get('collected_issues',[]),pending=[{k:v for k,v in row.items() if k not in ('item','update')} for row in r.get('pending',[])],bindings=r.get('bindings',{})),ensure_ascii=False))
        for name in ('tasks.json','assessment.json','error.json','failure.json'):
            if (base/name).exists():
                value=read(base/name)
                if name=='tasks.json':value=[{k:v for k,v in t.items() if k not in ('evidence','readers','writers','source_readers','token')} for t in value]
                print(name,json.dumps(value,ensure_ascii=False))


def record(folder,entries):
    target=folder/'source-review.json'
    review=read(target) if target.exists() else dict(status='in_progress',reviewer='assistant-source-audit',cases={})
    manifest=read(folder/'manifest.json');jobs={j['group']+'/'+j['id']:j for j in manifest['jobs']}
    for key,entry in entries.items():
        if entry['verdict'] not in ('pass','semantic_fail','incomplete'):raise ValueError('Invalid manual verdict')
        base=folder/'r1'/key
        files=[p for n in ('result.json','m1-result.json','m2-result.json','tasks.json','assessment.json','error.json','failure.json') if (p:=base/n).exists()]
        if not files:raise ValueError('No completed evidence for '+key)
        results=[read(p) for p in files if p.name.endswith('result.json')]
        complete=bool(results) and all(r.get('status')=='processed' and not r.get('extraction',{}).get('_errors') for r in results)
        if key.startswith('chains/'):complete=complete and len(results)==2 and not (base/'error.json').exists()
        if entry['verdict']=='pass' and not complete:raise ValueError('Incomplete cannot pass')
        review['cases'][key]=dict(**entry,technical_complete=complete,
            input_hash=digest(jobs[key]) if key in jobs else digest([read(ROOT/'examples/m1.json'),read(base/'m2-input.json') if (base/'m2-input.json').exists() else None]),
            evidence_hashes={p.name:digest(read(p)) for p in files})
    write_json(target,review)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--keys',nargs='+',required=True)
    args=p.parse_args();export(args.out,args.keys)
