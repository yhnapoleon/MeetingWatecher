"""Audit saved results and carry forward frozen matches only for unchanged tasks."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.service import Service
from meeting_eval.store import Store
from meeting_eval.stage_runner import atomic_json

read=lambda p:json.loads(p.read_text(encoding='utf8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def predictions(result):
    ex=result['extraction'];trace=ex['_task_trace'];rids=trace['item_records']
    out={'item:'+str(i):item for i,item in enumerate(ex['items'])}
    out.update({'review:'+r['record_id']:r for r in trace['review_records']
                if r['record_id'] not in rids and r.get('can_add_task')
                and r['category'] in ('ambiguous','conditional_work')})
    return out


def audit(out):
    base=ROOT/'runs/2026-11-17-interpret-budget-low'
    labels=ROOT/'data/generalization-v1/labels.json'
    freeze=read(ROOT/'data/generalization-v1/freeze.json')
    for name,expected in freeze['files'].items():
        if name.startswith('data/generalization-v1/'):assert sha(ROOT/name)==expected,name
    matches=read(base/'task-matches.json')
    old29=read(base/'natural/GN29/result.json');new29=read(out/'gn29-replay/result.json')
    assert new29['extraction']['items']==old29['extraction']['items']
    before=predictions(old29);after=predictions(new29)
    assert set(before)-set(after)=={'review:R8','review:R23'} and not set(after)-set(before)
    assert all(after[k]==before[k] for k in after)
    units=[u for k in after for u in matches['GN29']['predictions'][k]]
    tp=sum(u['gold_id'] is not None for u in units);fp=len(units)-tp
    assert (tp,fp)==(8,5)
    summary=dict(gn29_fixed_model_replay=dict(tp=tp,fp=fp,fn=0,precision=tp/(tp+fp),recall=1,
        previous_fp=7,field_issues=[u for u in units if u['field_issues']]),
        labels_sha256=sha(labels),runs=[],http_requests=0,known_tokens=0,unknown_usage=0)
    old25=read(base/'natural/GN25/result.json')
    for run in ('live-r2','live-r3-low-check'):
        folder=out/run;manifest=read(folder/'manifest.json')
        # Verify the executed source against its snapshot, not a post-run edit.
        with zipfile.ZipFile(folder/'source.zip') as z:
            assert all(hashlib.sha256(z.read(name)).hexdigest()==h for name,h in manifest['sources'].items())
        budget=read(folder/'http-budget.json')
        assert budget['used']<=budget['limit']==manifest['limit']
        row=dict(run=run,cases=[],http_requests=budget['used'],known_tokens=0,unknown_usage=0,requests=[])
        for cid in ('GN25','BG01'):
            case=folder/cid;result=read(case/'result.json');trace=result['extraction']['_task_trace']
            assert result['status']=='processed' and not result['extraction']['_errors']
            assert not trace['coverage_findings'] and not trace.get('repair')
            if cid=='GN25':
                assert result['extraction']['items']==old25['extraction']['items']
                assert set(predictions(result))==set(matches['GN25']['predictions'])
                assert trace['records']==old25['extraction']['_task_trace']['records']
                r6=next(r for r in trace['checked_records'] if r['record_id']=='R6')
                row['cases'].append(dict(case_id=cid,tp=2,fp=0,fn=1,missed=['T3'],r6_check=r6['check']['reason']))
            else:
                assert not result['extraction']['items'] and not trace['review_records']
                row['cases'].append(dict(case_id=cid,false_positive_tasks=0,review_cards=0))
            store=Store(case/'state.sqlite')
            try:
                assert Service(store).result(result['source_id'])==result
                assert store.tasks()==[]
            finally:store.close()
            for path in case.glob('model/**/meta.json'):
                meta=read(path);usage=meta.get('usage') or {};request=read(path.with_name('request.json'))
                assert meta['stage']=='check_work' and request['max_tokens']==16384
                row['known_tokens']+=usage.get('total_tokens',0);row['unknown_usage']+=not bool(usage)
                row['requests'].append(dict(case_id=cid,path=path.relative_to(out).as_posix(),
                    duration_seconds=meta.get('duration_seconds'),usage=usage,thinking=request['thinking'],
                    reasoning_effort=request.get('reasoning_effort'),finish_reason=meta.get('finish_reason')))
        assert len(row['requests'])==row['http_requests']
        summary['runs'].append(row)
        for k in ('http_requests','known_tokens','unknown_usage'):summary[k]+=row[k]
    assert summary['http_requests']==4 and summary['http_requests']<=6
    def request(run):
        return read(next((out/run/'GN25/model').glob('context_v2/*/check_work/*/attempt-1/request.json')))
    a=request('live-r2');b=request('live-r3-low-check')
    assert a['messages']==b['messages'] and a['max_tokens']==b['max_tokens']
    summary['comparison']=dict(same_prompt_and_payload=True,same_max_tokens=True,
        changed=['thinking','reasoning_effort','temperature'])
    atomic_json(out/'evaluation.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('runs','gn29_fixed_model_replay')},ensure_ascii=False))


if __name__=='__main__':audit(Path(sys.argv[1]).resolve())
