"""Score frozen source judgments and observable contracts; never infer semantic matches."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest
from scripts.run_action_baseline import write_json
from scripts.review_action_semantics import export_review,read_jsonl,JUDGMENTS
from scripts.score_action_semantics import score_semantics

BASE=ROOT/'runs/2026-11-15-task-boundary'
OLD=ROOT/'runs/2026-11-15-full-validation'
def read(path):return json.loads(path.read_text(encoding='utf-8'))


def pairs(folder):
    rows=[]
    for expected in read(Path(__file__).with_name('expectations.json'))['cases']:
        cid=expected['case_id'];p=folder/'pairs'/cid
        result=read(p/'result.json');ex=result['extraction'];trace=ex.get('_task_trace',{})
        items=ex['items'];reviews=trace.get('review_records',[])
        checks=dict(processed=result['status']=='processed',item_count=len(items) in expected['item_counts'])
        if expected.get('no_review'):checks['no_review']=not reviews
        if expected.get('needs_report'):checks['report_retained']=bool(trace.get('reports'))
        if expected.get('needs_implicit'):checks['implicit_need']=any(r['category']=='implicit_need' for r in reviews)
        if expected.get('no_deadline'):checks['no_deadline']=all(i['due_date'] is None and i['due_text'] is None for i in items)
        if expected.get('operations'):checks['operations']=[i['operation'] for i in items]==expected['operations']
        if expected.get('conditional'):
            checks['condition_retained']=any(r.get('commitment_kind')=='conditional' and r.get('commitment_quotes') for r in reviews)
            checks['no_automatic_creation']=all(i['operation']=='candidate' for i in items) and not read(p/'tasks.json')
        if expected.get('promoted_context'):
            checkpoints=trace.get('checkpoints',[])
            checks['multiple_checkpoints']=len(checkpoints)>=2
            checks['context_retained']=bool(trace.get('context_records'))
        rows.append(dict(case_id=cid,result_hash=digest(result),checks=checks,passed=all(checks.values())))
    report=dict(kind='observable_contracts_not_semantic_score',cases=rows,passed=sum(r['passed'] for r in rows),total=len(rows))
    write_json(folder/'contract-review.json',report)
    return report


def updates(folder):
    rows=[]
    for fixture in read(OLD/'updates/fixtures.json'):
        p=folder/'updates'/fixture['id'];result=read(p/'result.json');tasks=read(p/'tasks.json');e=fixture['expected']
        byid={t['guid']:t for t in tasks};old={t['guid'] for t in fixture['tasks']};new=[t for t in tasks if t['guid'] not in old]
        reviews=result['extraction'].get('_task_trace',{}).get('review_records',[])
        checks=dict(processed=result['status']=='processed',statuses=all(byid[g]['status']==v for g,v in e['statuses'].items()),
                    dates=all(byid[g].get('due_date')==v for g,v in e['dates'].items()),new_tasks=len(new)==e['new_tasks'])
        if e.get('new_due'):checks['new_deadline']=all(t.get('due_date')==e['new_due'] for t in new)
        if e['no_review']:checks['no_review']=not reviews
        if e['pending']:checks['pending']=bool(result['pending'] or reviews or result['extraction'].get('unresolved'))
        if e.get('review_type'):checks['review_type']=any(x['category']==e['review_type'] for x in reviews)
        semantic={}
        if fixture['id']=='M2':semantic=dict(no_extra_items=not result['extraction']['items'],no_range_question=not reviews)
        rows.append(dict(case_id=fixture['id'],result_hash=digest(result),checks=checks,passed=all(checks.values()),extra_semantic_checks=semantic))
    report=dict(cases=rows,passed=sum(r['passed'] for r in rows),total=len(rows))
    write_json(folder/'update-contracts.json',report)
    return report


def corpus(folder,annotations):
    inputs=read_jsonl(OLD/'corpus/input.jsonl')
    predictions=[read(folder/'corpus'/c['case_id']/'summary.json') for c in inputs]
    audit=read(annotations);notes={r['case_id']:r for r in audit['cases']}
    scores={}
    for version,label_file in [('original','labels.snapshot.jsonl'),('audited','labels.audited.jsonl')]:
        labels=read_jsonl(OLD/'corpus'/label_file)
        review=export_review(inputs,labels,predictions)
        review.update(status='agent_reviewed',reviewer='codex-source-review-task-boundary')
        for case in review['cases']:
            cid=case['case_id'];note=notes[cid]
            assert note['result_hash']==digest(read(folder/'corpus'/cid/'result.json')),cid+' changed since review'
            assert len(note['matches'])==len(case['judgments']),cid+' incomplete review'
            case['reviewed']=True
            for row,judgment in zip(case['judgments'],note['matches']):
                row.update({k:True for k in JUDGMENTS})
                row.update(gold_event_id=judgment['gold_event_id'],reason=judgment['reason'],
                           evidence_ids=case['predictions'][row['prediction_index']]['evidence_ids'])
                for field in judgment.get('wrong',[]):row[field]=False
                if version=='original':
                    for field in judgment.get('original_wrong',[]):row[field]=False
        write_json(folder/f'corpus-review-{version}.json',review)
        score=score_semantics(predictions,labels,review)
        exact=[]
        for case,prediction in zip(review['cases'],predictions):
            expected={g['event_id'] for g in case['references'] if g['operation'] in ('create','candidate')}
            correct={j['gold_event_id'] for j in case['judgments'] if j['gold_event_id'] and all(j[k] for k in JUDGMENTS)}
            exact.append(dict(case_id=case['case_id'],passed=prediction['status']=='processed' and expected==correct and len(correct)==len(case['predictions'])))
        score['exact_cases']=dict(correct=sum(r['passed'] for r in exact),total=len(exact),cases=exact)
        scores[version]=score
    write_json(folder/'corpus-scores.json',scores)
    return scores


def main():
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--kind',choices=['pairs','updates','corpus'],required=True)
    p.add_argument('--annotations',type=Path);a=p.parse_args();folder=BASE/a.run
    value=corpus(folder,a.annotations) if a.kind=='corpus' else globals()[a.kind](folder)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
