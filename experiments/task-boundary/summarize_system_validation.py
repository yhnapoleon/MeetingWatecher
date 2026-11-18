"""Read-only experiment audit; final artifacts are separate from frozen predictions."""
import hashlib
import json
import zipfile
from collections import Counter
from run_full_context_v5 import ROOT,read,write_json
from run_system_validation import accounting

OUT=ROOT/'runs/2026-11-16-context-v5-system-implementation'


def main():
    campaigns={}
    for path in OUT.iterdir():
        if not path.is_dir() or not any(path.rglob('request.json')):continue
        rows=[]
        for p in path.glob('r*/progress.json'):rows+=read(p)
        metas=[read(p) for p in path.rglob('meta.json')]
        campaigns[path.name]=dict(**accounting(path),completed_service_rows=len(rows),
            automatic_passed=sum(r['passed'] for r in rows),
            http_statuses=dict(Counter(str(m.get('http_status')) for m in metas if m.get('http_status'))),
            parsed_responses=sum(m.get('outcome')=='parsed' for m in metas),
            complete=(path/'summary.json').exists())
    write_json(OUT/'usage-audit.json',dict(campaigns=campaigns,total=accounting(OUT),
        unrecorded_health_probe=dict(requests=1,http_status=402,error='insufficient_balance_error',usage=None),
        note='Recorded token total includes failures and probes; missing usage is not zero cost. Source-first/prompt/reasoning probes and cancelled runs are not final evaluation rows.'))
    current={}
    for folder in ('meeting_eval','prompts'):
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts:current[p.relative_to(ROOT).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    with zipfile.ZipFile(OUT/'before-source.zip') as z:
        before={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith(('meeting_eval/','prompts/'))}
    changes=[dict(path=n,before=before.get(n),after=current.get(n)) for n in sorted(set(before)|set(current)) if before.get(n)!=current.get(n)]
    write_json(OUT/'production-changes.json',dict(files=changes,count=len(changes),final_hashes=current))
    label=ROOT/'experiments/task-boundary/semantic-v1.json'
    label_hash=hashlib.sha256(label.read_bytes()).hexdigest()
    assert label_hash=='1f2177786e99cdcc1abbc9f569b524ea577f74be1fe08ace4c010bea1463d9bc','Frozen semantic labels changed'
    with zipfile.ZipFile(OUT/'final-source.zip','w',zipfile.ZIP_DEFLATED) as z:
        for folder in ('meeting_eval','prompts','tests','experiments/task-boundary'):
            for p in (ROOT/folder).rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts:z.write(p,p.relative_to(ROOT).as_posix())
    write_json(OUT/'verification.json',dict(frozen_semantic_labels_sha256=label_hash,
        last_full_project_tests=dict(count=248,passed=True,log='offline-final-tests.log'),
        later_targeted_recovery_tests=dict(count=17,passed=True,new_cases=['proxy_endpoint_keeps_json_recovery','strict_fixed_empty_objects_are_program_owned']),
        experiment_tests=dict(count=35,passed=True,log='experiment-final-tests.log'),
        review='review-report.md',default_strategy='split-v3',
        final_selection='12 original failures + 8 frozen semantic controls, one round; user explicitly replaced full 95x2 plan',
        production_changes=len(changes)))
    print(json.dumps(dict(campaigns=campaigns,changed_production_files=len(changes)),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
