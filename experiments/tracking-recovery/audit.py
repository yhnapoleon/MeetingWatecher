"""Offline coverage and explicit task-match audit for the four-case regression."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'runs/2026-11-17-tracking-recovery-v2/focus'
OLD=ROOT/'runs/2026-11-17-generalization-v1'
def read(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def main():
    manifest=read(OUT/'manifest.json');old=read(OLD/'manifest.json')
    old_jobs={j['id']:j for j in old['jobs']}
    assert manifest['inference']==old['inference']
    for rel,expected in old['freeze']['files'].items():
        if rel.startswith('data/generalization-v1/'):assert sha(ROOT/rel)==expected,rel
    with zipfile.ZipFile(OUT/'source.zip') as archive:
        for name in archive.namelist():
            if name.startswith(('meeting_eval/','prompts/')):
                assert archive.read(name)==(ROOT/name).read_bytes(),name
    labels={r['case_id']:r for r in read(ROOT/'data/generalization-v1/labels.json')}
    old_rows={r['case_id']:r for r in read(OLD/'summary.json')['rows']}
    rows=[];outputs=[]
    for job in manifest['jobs']:
        cid=job['id'];assert job==old_jobs[cid]
        folder=OUT/job['group']/cid;result=read(folder/'result.json')
        extraction=result['extraction'];trace=extraction['_task_trace'];tracking=trace['tracking']
        state_files=list(folder.rglob('tracking-state.json'));assert len(state_files)==1
        assert read(state_files[0])==tracking
        accepted=tracking['accepted_ranges'];covered=[i for a,b in accepted for i in range(a,b)]
        assert covered==list(range(tracking['completed_segments']))
        segments=job['meeting']['segments'];done=tracking['completed_segments']
        assert tracking['pending_segment_ids']==[s['id'] for s in segments[done:]]
        if tracking['status']=='complete':assert done==len(segments) and not tracking['blocked']
        metas=[read(p) for p in folder.rglob('meta.json')]
        old_metas=[read(p) for p in (OLD/job['group']/cid).rglob('meta.json')]
        track_metas=[m for m in metas if m['stage']=='track_context']
        old_track=[m for m in old_metas if m['stage']=='track_context']
        rows.append(dict(case_id=cid,status=result['status'],tracking_status=tracking['status'],segments=len(segments),
            completed=done,old_planned_windows=(len(segments)+7)//8,new_planned_windows=len(tracking['planned_ranges']),
            accepted_windows=len(accepted),splits=len(tracking['splits']),old_tracking_calls=len(old_track),
            tracking_calls=len(track_metas),old_tracking_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in old_track),
            tracking_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in track_metas),
            old_total_calls=old_rows[cid]['calls'],old_total_tokens=old_rows[cid]['tokens'],
            errors=extraction.get('_errors',[])))
        predictions=[];rids=trace.get('item_records',[]);items=extraction['items'];assert len(rids)==len(items)
        for i,item in enumerate(items):
            predictions.append(dict(id='item:'+str(i),record_id=rids[i],output=item))
        for card in trace.get('review_records',[]):
            if card['record_id'] not in rids and card.get('can_add_task') and card['category'] in ('ambiguous','conditional_work'):
                predictions.append(dict(id='review:'+card['record_id'],record_id=card['record_id'],output=card))
        outputs.append(dict(case_id=cid,result_sha256=sha(folder/'result.json'),references=labels[cid]['tasks'],predictions=predictions,
            auxiliary=[r for r in trace.get('review_records',[]) if r['record_id'] not in {p['record_id'] for p in predictions}]))
    write(OUT/'coverage-audit.json',dict(checks='input, label, inference, code snapshot, persisted state and contiguous coverage verified',rows=rows))
    write(OUT/'task-output-review.json',outputs)
    match_path=OUT/'task-matches.json'
    if match_path.exists():
        matches=read(match_path);scores=[]
        assert set(matches)=={o['case_id'] for o in outputs}
        for o in outputs:
            review=matches[o['case_id']];assert review['result_sha256']==o['result_sha256']
            assert set(review['predictions'])=={p['id'] for p in o['predictions']}
            refs={r['id']:r for r in o['references']};matched=[];fp=0
            for units in review['predictions'].values():
                assert units
                for u in units:
                    assert u['reason']
                    if u['gold_id'] is None:fp+=1
                    else:assert u['gold_id'] in refs;matched.append(u['gold_id'])
            assert len(matched)==len(set(matched))
            required={g for g,r in refs.items() if r['requirement']=='required'}
            tp=len(required&set(matched));fn=len(required-set(matched))
            scores.append(dict(case_id=o['case_id'],tp=tp,fp=fp,fn=fn,missed=sorted(required-set(matched)),notes=review['notes']))
        tp=sum(r['tp'] for r in scores);fp=sum(r['fp'] for r in scores);fn=sum(r['fn'] for r in scores)
        write(OUT/'task-metrics.json',dict(rows=scores,tp=tp,fp=fp,fn=fn,precision=tp/(tp+fp) if tp+fp else None,
            recall=tp/(tp+fn),f1=2*tp/(2*tp+fp+fn),scope='Four selected previous failures; task recognition only, not full-field accuracy or generalization.',
            labels_sha256=sha(ROOT/'data/generalization-v1/labels.json'),matches_sha256=sha(match_path)))
    print(json.dumps(rows,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=OUT)
    OUT=parser.parse_args().out.resolve()
    main()
