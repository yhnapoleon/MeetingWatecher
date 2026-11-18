"""Offline provenance, accounting, and explicit task-match scoring."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'experiments/task-boundary')]
from run_system_validation import accounting

BASE=ROOT/'runs/2026-11-17-interpret-reliability'
OUT=BASE/'focus'
OLD=ROOT/'runs/2026-11-17-tracking-recovery-v2/payment-resume'
def read(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def main():
    manifest=read(OUT/'manifest.json');old=read(OLD/'manifest.json')
    assert manifest['inference']==old['inference'];oldjobs={j['id']:j for j in old['jobs']}
    frozen=read(ROOT/'data/generalization-v1/freeze.json')
    for rel,expected in frozen['files'].items():
        if rel.startswith('data/generalization-v1/'):assert sha(ROOT/rel)==expected
    labels={r['case_id']:r for r in read(ROOT/'data/generalization-v1/labels.json')}
    rows=[];outputs=[]
    for job in manifest['jobs']:
        cid=job['id'];assert job==oldjobs[cid];folder=OUT/job['group']/cid
        result=read(folder/'result.json');e=result['extraction'];trace=e['_task_trace']
        tracking=trace['tracking'];assert tracking['status']=='complete' and tracking['completed_segments']==len(job['meeting']['segments'])
        assert [i for a,b in tracking['accepted_ranges'] for i in range(a,b)]==list(range(len(job['meeting']['segments'])))
        metas=[read(p) for p in folder.rglob('meta.json')]
        if cid=='GN29':
            proof=read(folder/'frozen-tracking.json');assert sha(ROOT/proof['source'])==proof['result_sha256']
            assert not any(m['stage']=='track_context' for m in metas)
        first=[]
        for p in folder.rglob('stage-request.json'):
            if p.parent.name=='attempt-1' and p.parent.parent.parent.name=='interpret_work':
                request=read(p);meta=read(p.with_name('meta.json'))
                assert 'evidence_catalog' not in request
                first.append(dict(chars=len(json.dumps(request,ensure_ascii=False)),usage=meta.get('usage')))
        assert len(first)==1
        rows.append(dict(case_id=cid,status=result['status'],mode='frozen_tracking' if cid=='GN29' else 'normal_service',
            interpret_first=first[0],**accounting(folder),errors=e.get('_errors',[])))
        predictions=[];rids=trace.get('item_records',[]);assert len(rids)==len(e['items'])
        for i,item in enumerate(e['items']):predictions.append(dict(id='item:'+str(i),record_id=rids[i],output=item))
        for r in trace.get('review_records',[]):
            if r['record_id'] not in rids and r.get('can_add_task') and r['category'] in ('ambiguous','conditional_work'):
                predictions.append(dict(id='review:'+r['record_id'],record_id=r['record_id'],output=r))
        outputs.append(dict(case_id=cid,result_sha256=sha(folder/'result.json'),references=labels[cid]['tasks'],predictions=predictions,
            auxiliary=[r for r in trace.get('review_records',[]) if r['record_id'] not in {p['record_id'] for p in predictions}]))
    write(OUT/'task-output-review.json',outputs)
    evidence=dict(rows=rows,**accounting(OUT),labels_sha256=sha(ROOT/'data/generalization-v1/labels.json'))
    if (OUT/'task-matches.json').exists():
        matches=read(OUT/'task-matches.json');scores=[]
        assert set(matches)=={r['case_id'] for r in outputs}
        for out in outputs:
            m=matches[out['case_id']];assert m['result_sha256']==out['result_sha256']
            assert set(m['predictions'])=={p['id'] for p in out['predictions']}
            refs={t['id']:t for t in out['references']};seen=[];fp=0
            for units in m['predictions'].values():
                assert units
                for unit in units:
                    assert unit['reason']
                    if unit['gold_id'] is None:fp+=1
                    else:assert unit['gold_id'] in refs;seen.append(unit['gold_id'])
            assert len(set(seen))==len(seen)
            required={g for g,t in refs.items() if t['requirement']=='required'};tp=len(required&set(seen))
            scores.append(dict(case_id=out['case_id'],tp=tp,fp=fp,fn=len(required)-tp,missed=sorted(required-set(seen)),notes=m['notes']))
        tp=sum(r['tp'] for r in scores);fp=sum(r['fp'] for r in scores);fn=sum(r['fn'] for r in scores)
        evidence['tasks']=dict(rows=scores,tp=tp,fp=fp,fn=fn,precision=tp/(tp+fp) if tp+fp else None,
            recall=tp/(tp+fn),f1=2*tp/(2*tp+fp+fn),matches_sha256=sha(OUT/'task-matches.json'))
    write(OUT/'audit.json',evidence);print(json.dumps(evidence,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
