"""Audit a saved unseen-meeting run; no inference or automatic semantic labels."""
import argparse
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
import zipfile

import run
from score_retest import inventory, metrics


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('out',type=Path)
    args=parser.parse_args()
    out=args.out
    manifest=read(out/'manifest.json')
    assert sha(out/'input.json')==manifest['input_sha256']
    assert sha(out/'reference.json')==manifest['reference_sha256']
    assert sha(out/'rubric-before-run.json')==manifest['rubric_sha256']
    assert read(out/'config.json')==read(run.ROOT/'runs/2026-11-18-full-v19-retest/ES2002b/config.json')
    with zipfile.ZipFile(out/'source.zip') as z:
        files=[n for n in z.namelist() if n.startswith(('meeting_eval/','prompts/')) and not n.endswith('/')]
        assert all(z.read(n)==(run.ROOT/n).read_bytes() for n in files)
    result=read(out/'result.json')
    source=read(out/'input.json')
    inv=inventory(out)
    run.write(out/'audit-inventory.json',inv)
    store=run.Store(out/'state.sqlite')
    try:
        assert store.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        svc=run.Service(store)
        sid=result['source_id']
        frozen=json.loads(store.db.execute('SELECT body FROM extraction_context WHERE source_id=?',(sid,)).fetchone()[0])
        assert frozen['context']=={'tasks':[],'decisions':[]} and frozen['actor']==run.ACTOR
        assert svc.result(sid)==result
        assert svc.minutes(sid,run.ACTOR)==(out/'minutes.md').read_text(encoding='utf8')
        assert svc.requirements(sid,run.ACTOR)==read(out/'requirements.json')
        assert store.tasks()==read(out/'tasks.json')
        if result['status']=='processed':
            with patch('urllib.request.urlopen',side_effect=AssertionError('Unexpected inference')):
                assert svc.process(source,run.ACTOR,run.AT)==result
    finally:
        store.close()
    trace=result['extraction']['_task_trace']
    tracking=trace['tracking']
    states=[read(p) for p in (out/'model').rglob('state.json')]
    meta_paths=sorted((out/'model').rglob('meta.json'))
    metas=[read(p) for p in meta_paths]
    assert sum(len(s['attempts']) for s in states)==len(metas)
    acceptance=dict(final_status=result['status'],source_unchanged=True,source_snapshot_files=len(files),
        same_configuration_as_two_meeting_retest=True,reference_unchanged=True,input_unchanged=True,
        tracking_status=tracking['status'],completed_segments=tracking['completed_segments'],
        total_segments=len(source['segments']),tracking_splits=len(tracking['splits']),
        final_errors=result['extraction']['_errors'],database_integrity=True,reopen_consistent=True,
        offline_repeat_no_inference=result['status']=='processed',independent_empty_history=True)
    if result['status']=='processed':
        assert not acceptance['final_errors']
        assert tracking['status']=='complete' and tracking['completed_segments']==len(source['segments'])
    run.write(out/'acceptance.json',acceptance)
    usage=dict(requests=len(metas),known_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),
        requests_with_unknown_usage=sum(m.get('usage') is None for m in metas),
        attempts=[dict(path=str(p.relative_to(out)),stage=m['stage'],tokens=(m.get('usage') or {}).get('total_tokens'),
            outcome=m.get('outcome'),duration_seconds=m.get('duration_seconds')) for p,m in zip(meta_paths,metas)])
    run.write(out/'usage-audit.json',usage)
    if not (out/'annotations.json').exists():
        print(json.dumps(dict(acceptance=acceptance,task_predictions=len(inv['tasks']),decision_rows=len(inv['decisions']),
            note='Inventory exported. Human annotations are required for semantic scoring.'),ensure_ascii=False,indent=2))
        return
    labels=read(out/'annotations.json')
    assert labels['result_sha256']==inv['result_sha256']
    refs=read(out/'reference.json')
    task_ids={r['id'] for r in refs['actions']}
    decision_ids={r['id'] for r in refs['decisions']}
    tasks={r['record_id']:r for r in labels['tasks']}
    assert len(tasks)==len(labels['tasks']) and set(tasks)=={t['record_id'] for t in inv['tasks']}
    task_hits=set()
    for t in tasks.values():
        assert t['verdict'] in ('TP','FP') and t['reason']
        assert set(t['reference_hits'])<=task_ids
        assert not t['reference_hits'] or t['verdict']=='TP'
        task_hits.update(t['reference_hits'])
    rows={r['index']:r for r in labels['decisions']}
    assert len(rows)==len(labels['decisions']) and set(rows)=={r['index'] for r in inv['decisions']}
    units={}
    decision_hits=set()
    for row in rows.values():
        assert row['claims'] and set(row['reference_hits'])<=decision_ids
        decision_hits.update(row['reference_hits'])
        for i,c in enumerate(row['claims']):
            assert c['verdict'] in ('TP','FP') and c['reason'] and c['name']
            key=c.get('unit',f"row-{row['index']}-{i}")
            if key in units:
                assert row.get('grouping_reason')
                assert (units[key]['name'],units[key]['verdict'])==(c['name'],c['verdict'])
            units[key]=c
    tp=sum(t['verdict']=='TP' for t in tasks.values())
    dtp=sum(c['verdict']=='TP' for c in units.values())
    summary=read(out/'summary.json')
    result_metrics=dict(meeting_id=source['meeting_id'],status=result['status'],
        metric_scope=labels.get('metric_scope','Task identity and independent decision claims; field accuracy separate.'),
        initial_status=summary.get('initial_status',summary['status']),explicit_recovery_calls=summary.get('recovery_calls',0),
        tasks=metrics(tp,len(tasks)-tp,len(task_hits),len(task_ids)),
        decisions=metrics(dtp,len(units)-dtp,len(decision_hits),len(decision_ids)),
        missing_tasks=sorted(task_ids-task_hits),missing_decisions=sorted(decision_ids-decision_hits),
        decision_rows=len(rows),review_counts=inv['review_counts'],
        result_sha256=inv['result_sha256'],reference_sha256=sha(out/'reference.json'),
        limitations=manifest.get('limitations',['One previously unused local meeting, related office series previously exposed.',
            'Reference recall uses original AMI annotations, not exhaustive full-transcript gold.',
            'Human precision audit of task identity and independent decision claims; field accuracy separate.']))
    run.write(out/'evaluation.json',result_metrics)
    print(json.dumps(result_metrics,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
