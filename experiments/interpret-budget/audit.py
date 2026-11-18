"""Offline provenance, actual HTTP accounting, and task-level manual-match audit."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.stage_runner import atomic_json
from meeting_eval.inputs import digest


def read(p):return json.loads(Path(p).read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def audit(out):
    manifest=read(out/'manifest.json');budget=read(out/'budget.json')
    assert budget['limit']==manifest['limit'] and budget['used']<=budget['limit']<=8
    for paths in manifest['sources'].values():
        for path,expected in paths.items():assert sha(ROOT/path)==expected, path
    freeze=read(ROOT/'data/generalization-v1/freeze.json')
    for path,expected in freeze['files'].items():
        if path.startswith('data/generalization-v1/'):assert sha(ROOT/path)==expected,path
    labels={r['case_id']:r for r in read(ROOT/'data/generalization-v1/labels.json')}
    rows=[];outputs=[];requests=[]
    for cid in manifest['cases']:
        folder=out/'natural'/cid
        if not (folder/'result.json').exists():
            rows.append(dict(case_id=cid,status='not_run'));continue
        result=read(folder/'result.json');e=result['extraction'];trace=e['_task_trace']
        assert e['_experiment']['scope']=='task_branch_only'
        preflight=read(folder/'preflight.json')
        assert preflight['payload_equal'] and preflight['prompt_equal']
        assert digest(preflight['payload'])==preflight['payload_hash']
        assert trace['tracking']['status']=='complete'
        paths=list(folder.rglob('meta.json'))
        for path in paths:
            meta=read(path);req=read(path.with_name('request.json'));usage=meta.get('usage') or {}
            assert meta['stage'] in ('interpret_work','check_work','repair_work','check_repair')
            assert req['max_tokens']<=32768
            response=read(path.with_name('response.json')) if path.with_name('response.json').exists() else {}
            message=(response.get('choices') or [{}])[0].get('message',{})
            requests.append(dict(case_id=cid,stage=meta['stage'],path=path.relative_to(out).as_posix(),
                requested_model=req['model'],returned_model=meta.get('model_returned'),effort=req.get('reasoning_effort'),
                thinking=req.get('thinking'),max_tokens=req['max_tokens'],finish_reason=meta.get('finish_reason'),
                outcome=meta.get('outcome'),http_status=meta.get('http_status'),usage=usage,
                reasoning_tokens=(usage.get('completion_tokens_details') or {}).get('reasoning_tokens'),
                content_characters=len(message.get('content') or ''),
                reasoning_characters=len(message.get('reasoning_content') or '')))
        predictions=[];rids=trace.get('item_records',[])
        assert len(rids)==len(e['items'])
        for i,item in enumerate(e['items']):predictions.append(dict(id='item:'+str(i),record_id=rids[i],output=item))
        for record in trace.get('review_records',[]):
            if record['record_id'] not in rids and record.get('can_add_task') and record['category'] in ('ambiguous','conditional_work'):
                predictions.append(dict(id='review:'+record['record_id'],record_id=record['record_id'],output=record))
        outputs.append(dict(case_id=cid,result_sha256=sha(folder/'result.json'),references=labels[cid]['tasks'],predictions=predictions,
            auxiliary=[r for r in trace.get('review_records',[]) if r['record_id'] not in {p['record_id'] for p in predictions}]))
        rows.append(dict(case_id=cid,status=result['status'],scope='task_branch_only',items=len(e['items']),
            review_tasks=sum(p['id'].startswith('review:') for p in predictions),stored_tasks=len(read(folder/'tasks.json')),
            errors=e.get('_errors',[])))
    atomic_json(out/'task-output-review.json',outputs)
    evidence=dict(rows=rows,requests=requests,reserved_http_requests=budget['used'],metadata_records=len(requests),
        known_tokens=sum(r['usage'].get('total_tokens',0) for r in requests),
        metadata_without_usage=sum(not r['usage'] for r in requests),
        labels_sha256=sha(ROOT/'data/generalization-v1/labels.json'))
    if (out/'task-matches.json').exists():
        matches=read(out/'task-matches.json');scores=[]
        assert set(matches)=={r['case_id'] for r in outputs}
        for row in outputs:
            m=matches[row['case_id']];assert m['result_sha256']==row['result_sha256']
            assert set(m['predictions'])=={p['id'] for p in row['predictions']}
            refs={t['id']:t for t in row['references']};seen=[];fp=0;field_errors=[]
            for units in m['predictions'].values():
                assert units
                for unit in units:
                    assert unit['reason']
                    if unit['gold_id'] is None:fp+=1
                    else:
                        assert unit['gold_id'] in refs;seen.append(unit['gold_id'])
                        assert isinstance(unit['field_issues'],list)
                        if unit['field_issues']:field_errors.append(dict(gold_id=unit['gold_id'],issues=unit['field_issues']))
            assert len(set(seen))==len(seen)
            required={k for k,t in refs.items() if t['requirement']=='required'}
            scores.append(dict(case_id=row['case_id'],tp=len(required&set(seen)),fp=fp,fn=len(required-set(seen)),
                missed=sorted(required-set(seen)),field_errors=field_errors,notes=m['notes']))
        tp=sum(r['tp'] for r in scores);fp=sum(r['fp'] for r in scores);fn=sum(r['fn'] for r in scores)
        evidence['tasks']=dict(rows=scores,tp=tp,fp=fp,fn=fn,precision=tp/(tp+fp) if tp+fp else None,
            recall=tp/(tp+fn) if tp+fn else None,f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None)
        incorrect=sum(len(r['field_errors']) for r in scores)
        evidence['complete_tasks_strict']=dict(tp=tp-incorrect,fp=fp+incorrect,fn=fn+incorrect,
            precision=(tp-incorrect)/(tp+fp) if tp+fp else None,recall=(tp-incorrect)/(tp+fn) if tp+fn else None,
            note='字段问题按冻结参考计；GN29 T1负责人存在预先记录的群体负责解释，另列争议。')
    atomic_json(out/'audit.json',evidence)
    return evidence


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True,type=Path)
    data=audit(parser.parse_args().out)
    print(json.dumps({k:v for k,v in data.items() if k!='requests'},ensure_ascii=False,indent=2))
