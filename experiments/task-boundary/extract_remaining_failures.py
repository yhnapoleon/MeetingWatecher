"""Collect the 12 effective failures after network recovery, with provenance."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[2]
FULL=ROOT/'runs/2026-11-16-context-v5-full'
RECOVERY=ROOT/'runs/2026-11-16-context-v5-network-recovery'
OUT=ROOT/'runs/2026-11-16-context-v5-failure-analysis'

def read(p):return json.loads(p.read_text(encoding='utf8'))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

def main():
    latest=read(RECOVERY/'final-report.json')
    failures=[r for r in latest['effective_rows'] if not r['full_passed']]
    assert len(failures)==12 and len({r['key'].split('/',1)[1] for r in failures})==9
    assert not (OUT/'manifest.json').exists(),'Completed collection already exists'
    OUT.mkdir(exist_ok=True)
    rows=[]
    for row in failures:
        key=row['key'];base=RECOVERY if row['source']=='network_recovery' else FULL
        source=base/key;dest=OUT/'cases'/key
        shutil.copytree(source,dest,dirs_exist_ok=True)
        hashes={p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                for p in source.rglob('*') if p.is_file()}
        assert all(hashlib.sha256((dest/name).read_bytes()).hexdigest()==sha for name,sha in hashes.items())
        result=read(dest/'result.json');t=result['extraction']['_task_trace'];repair=t.get('repair',{})
        initial=repair.get('before',t)
        compact=lambda rs:[{k:r.get(k) for k in ('record_id','kind','description','proposed_kind','check')} for r in rs]
        timeline=dict(ledger=t.get('ledger'),initial_records=compact(initial.get('records',[])),
            initial_checked_records=compact(initial.get('checked_records',[])),
            repair_status=repair.get('status'),repair_error=repair.get('detail'),repair_targets=repair.get('target_record_ids'),
            repair_proposal=repair.get('proposal'),repair_after=compact(repair.get('after',{}).get('checked_records',[])),
            items=result['extraction']['items'],updates=result['extraction']['updates'],
            reports=t.get('reports',[]),reviews=t.get('review_records',[]),errors=result['extraction'].get('_errors',[]),
            service_pending=result.get('pending',[]))
        write(dest/'stage-timeline.json',timeline)
        rows.append(dict(**row,source_path=source.relative_to(ROOT).as_posix(),copied_to=dest.relative_to(OUT).as_posix(),
            source_hashes=hashes,assessment=read(dest/'assessment.json')))
    shutil.copy2(FULL/'source.zip',OUT/'frozen-source.zip')
    write(OUT/'manifest.json',dict(total=12,unique_scenarios=9,rows=rows,
        selection='False full_passed in recovery final-report effective_rows; r1/C17 uses recovered result, all other failures use original outputs.',
        frozen_source_sha256=hashlib.sha256((OUT/'frozen-source.zip').read_bytes()).hexdigest()))
    print('Collected 12 failed executions / 9 scenarios; all copies hash-verified.')

if __name__=='__main__':main()
