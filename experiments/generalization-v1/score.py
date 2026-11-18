"""Export all outputs, then score explicit source-reviewed task matches offline."""
import argparse
import hashlib
import json
from pathlib import Path
import random
from collections import Counter

ROOT=Path(__file__).resolve().parents[2];DATA=ROOT/'data/generalization-v1'
def read(p):return json.loads(p.read_text(encoding='utf8'))
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def export(folder):
    frozen=read(DATA/'freeze.json')
    for name in ('natural-inputs.json','control-inputs.json','labels.json','annotation-guide.md'):
        path=DATA/name;assert sha(path)==frozen['files'][path.relative_to(ROOT).as_posix()],'Frozen data changed'
    cases=read(DATA/'natural-inputs.json')+read(DATA/'control-inputs.json');gold={l['case_id']:l for l in read(DATA/'labels.json')};rows=[]
    for case in cases:
        if case['split']!='test':continue
        cid=case['case_id'];path=folder/case['kind']/cid/'result.json'
        result=read(path) if path.exists() else dict(status='failed',extraction={})
        e=result.get('extraction',{});trace=e.get('_task_trace',{});items=e.get('items',[]);rids=trace.get('item_records',[])
        assert len(items)==len(rids),(cid,'items/record_id mismatch')
        predictions=[]
        for i,item in enumerate(items):
            predictions.append(dict(id='item:'+str(i),location='items',record_id=rids[i],output=item,
                confirmation=next((r for r in trace.get('review_records',[]) if r['record_id']==rids[i]),None)))
        auxiliary=[]
        for card in trace.get('review_records',[]):
            if card['record_id'] in rids:continue
            if card.get('can_add_task') and card['category'] in ('ambiguous','conditional_work'):
                predictions.append(dict(id='review:'+card['record_id'],location='review_records',record_id=card['record_id'],output=card,confirmation=card))
            else:auxiliary.append(card)
        rows.append(dict(case_id=cid,kind=case['kind'],language=case['language'],source=case['source'],series=case['series'],
            measured_tokens=case['measured_tokens'],status=result.get('status'),result_sha256=sha(path) if path.exists() else None,
            references=gold[cid]['tasks'],predictions=predictions,auxiliary=auxiliary,errors=e.get('_errors',[])))
    write(folder/'task-output-review.json',rows)
    return rows

def totals(rows,fields=False,items_only=False):
    expected=sum(r['required'] for r in rows);predicted=0;tp=0;optional=0
    for r in rows:
        for p in r['judgments']:
            if items_only and p['location']!='items':continue
            for unit in p['units']:
                if unit['requirement']=='optional':optional+=1;continue
                predicted+=1
                tp+=int(unit['gold_id'] is not None and (not fields or not unit['field_errors']))
    return dict(expected=expected,predicted=predicted,tp=tp,fp=predicted-tp,fn=expected-tp,
        precision=tp/predicted if predicted else None,recall=tp/expected if expected else None,
        f1=2*tp/(predicted+expected) if predicted+expected else None,optional_excluded=optional)

def bootstrap(rows):
    rng=random.Random(20261117);values={k:[] for k in ('precision','recall','f1')}
    # Natural case == one distinct original meeting; controls are not bootstrapped.
    for _ in range(2000):
        score=totals(rng.choices(rows,k=len(rows)))
        for key in values:
            if score[key] is not None:values[key].append(score[key])
    out={}
    for key,v in values.items():
        v.sort();out[key]=dict(low=v[int((len(v)-1)*.025)] if v else None,high=v[int((len(v)-1)*.975)] if v else None,defined_replicates=len(v))
    return out

def score(folder):
    outputs=export(folder);review=read(folder/'task-matches.json');assert set(review)=={r['case_id'] for r in outputs}
    rows=[]
    for out in outputs:
        cid=out['case_id'];decision=review[cid];assert decision['result_sha256']==out['result_sha256']
        refs={t['id']:t for t in out['references']};preds={p['id']:p for p in out['predictions']}
        assert set(decision['predictions'])==set(preds),(cid,'unreviewed predictions')
        judgments=[];matched=[]
        for pid,pred in preds.items():
            judgment=decision['predictions'][pid];assert judgment['units'] and judgment['decomposition_reason']
            units=[]
            for unit in judgment['units']:
                gid=unit['gold_id'];assert gid is None or gid in refs
                assert unit['reason'] and isinstance(unit['field_errors'],list)
                if gid is not None:matched.append(gid)
                units.append(dict(**unit,requirement=refs[gid]['requirement'] if gid is not None else None))
            judgments.append(dict(id=pid,location=pred['location'],units=units,decomposition_reason=judgment['decomposition_reason']))
        assert len(matched)==len(set(matched)),(cid,'duplicate gold matches; duplicates must be unmatched FP')
        row={k:out[k] for k in ('case_id','kind','language','source','series','measured_tokens','status')}
        row.update(required=sum(t['requirement']=='required' for t in refs.values()),judgments=judgments,
            missed=[g for g,t in refs.items() if t['requirement']=='required' and g not in matched],review_notes=decision['notes'],auxiliary_count=len(out['auxiliary']))
        rows.append(row)
    natural=[r for r in rows if r['kind']=='natural'];controls=[r for r in rows if r['kind']=='control']
    groups={}
    for name,subset in [('natural',natural),('control',controls),('batch_overview',rows)]+[(f'language:{lang}',[r for r in natural if r['language']==lang]) for lang in ['zh','en']]+[(f'source:{source}',[r for r in natural if r['source']==source]) for source in ['VCSum','QMSum']]+[(f'length:{label}',[r for r in natural if lo<=r['measured_tokens']<hi]) for label,lo,hi in [('short',0,3000),('medium',3000,8000),('long',8000,10**9)]]:
        zeros=[r for r in subset if not r['required']]
        groups[name]=dict(cases=len(subset),recognition=totals(subset),complete_fields=totals(subset,fields=True),items_only=totals(subset,items_only=True),
            zero_required_task_cases=len(zeros),zero_task_cases_with_fp=sum(totals([r])['fp']>0 for r in zeros))
    pair_results={}
    for series in sorted({r['series'] for r in controls}):
        pair=[r for r in controls if r['series']==series];s=totals(pair);sf=totals(pair,fields=True)
        pair_results[series]=dict(recognition_pass=s['fp']==s['fn']==0,fields_pass=sf['fp']==sf['fn']==0)
    report=dict(groups=groups,natural_meeting_bootstrap_95=bootstrap(natural),control_pairs=pair_results,
        technical_status=dict(Counter(r['status'] for r in rows)),labels_sha256=sha(DATA/'labels.json'),matches_sha256=sha(folder/'task-matches.json'),rows=rows)
    write(folder/'task-metrics.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=ROOT/'runs/2026-11-17-generalization-v1');p.add_argument('--export-only',action='store_true');args=p.parse_args()
    if args.export_only:print('exported',len(export(args.out)))
    else:score(args.out)
