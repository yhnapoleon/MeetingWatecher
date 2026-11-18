"""Reproduce source-reviewed scores and actual Service checks, without model calls."""
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest
from scripts.run_action_baseline import write_json
from scripts.review_action_semantics import export_review, JUDGMENTS, read_jsonl
from scripts.score_action_semantics import score_semantics

BASE=ROOT/'runs/2026-11-15-pragmatic-checking'
OLD=ROOT/'runs/2026-11-15-field-preservation/regression'
EXP=Path(__file__).parent


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def reviewed_scores(variant,labels,audited):
    cases=read(EXP/'regression.json')['cases']
    inputs=[c['meeting'] for c in cases]
    predictions=[]
    for c in cases:
        result=read(BASE/variant/c['id']/'result.json')
        assert digest(result)==read(EXP/'reviewed-output-hashes.json')[variant][c['id']], 'Changed reviewed output; re-review before scoring'
        predictions.append(dict(case_id=c['id'],items=result['extraction']['items'],status=result['status'],
                                errors=result['extraction'].get('_errors',[]),pending=result['pending']))
    review=export_review(inputs,labels,predictions)
    review.update(status='agent_reviewed',reviewer='codex-source-review-2026-11-15')
    for c in review['cases']:
        c['reviewed']=True
        for j in c['judgments']:
            item=c['predictions'][j['prediction_index']]
            # Explicit source review: C03 has two different role assignments.
            target=('C03.1' if item['owner_ref']=='MEE007' else 'C03.2') if c['case_id']=='C03' else c['case_id']+'.1'
            gold=next(g for g in c['references'] if g['event_id']==target)
            j.update({k:True for k in JUDGMENTS})
            j.update(gold_event_id=target if gold['operation']!='none' else None,
                     evidence_ids=item['evidence_ids'],reason='原文的动作、对象与对应角色一致，时间没有扩成新期限；操作按分派和承接分别核对。')
            if c['case_id']=='C09':
                j['content_complete']=audited
                j['reason']='工作问答支持研究说明书及使用背景；旧标签额外要求消费者看法，新审计口径不把该具体化作为必需内容。'
            if item['operation']!=gold['operation']:
                j.update(commitment_correct=False,operation_correct=False,
                         reason='分派后的本人回应应接受；或仅有试探提议被解读成团队承诺，导致操作类别与当前标签不符。')
    suffix='audited' if audited else 'original'
    write_json(BASE/variant/f'review-{suffix}.json',review)
    score=score_semantics(predictions,labels,review)
    write_json(BASE/variant/f'scores-{suffix}.json',score)
    return score


def main():
    original=read_jsonl(OLD/'labels.snapshot.jsonl')
    audited=read_jsonl(ROOT/'data/action-semantics-v2/pragmatic-audit/labels.jsonl')
    manifest=read(ROOT/'data/action-semantics-v2/pragmatic-audit/manifest.json')
    assert digest(original)==manifest['source_hash'] and digest(audited)==manifest['labels_hash']
    scores={}
    for v in ['check-only','check-frozen-recovered','interpret-check','integrated','final-regression']:
        scores[v]={name:reviewed_scores(v,labels,name=='audited') for name,labels in [('original',original),('audited',audited)]}
    baseline_review=read(OLD/'semantic-review.completed.json')
    predictions=read_jsonl(OLD/'predictions.jsonl')
    # Apply the same audited labels to the unchanged baseline predictions.
    baseline_new=export_review(baseline_review['inputs'],audited,predictions)
    baseline_new.update(status='agent_reviewed',reviewer='codex-source-review-2026-11-15')
    old_cases={c['case_id']:c for c in baseline_review['cases']}
    for c in baseline_new['cases']:
        c['reviewed']=True;c['judgments']=copy.deepcopy(old_cases[c['case_id']]['judgments'])
    write_json(BASE/'baseline-review-audited.json',baseline_new)
    scores['baseline']={'original':score_semantics(predictions,original,baseline_review),
                        'audited':score_semantics(predictions,audited,baseline_new)}
    controls=[]
    for fixture,variant in [('contrast.json','contrast'),('binding.json','binding'),('personal.json','personal')]:
        for c in read(EXP/fixture)['cases']:
            folder=BASE/variant/c['id'];r=read(folder/'result.json');items=r['extraction']['items'];tasks=read(folder/'tasks.json');e=c['expected']
            checks=dict(processed=r['status']=='processed',items=len(items)==e['items'],created=len(tasks)==e['created'])
            if e['no_due']:checks['no_due']=all(i.get('due_date') is None and i.get('due_text') is None for i in items)
            # These source judgments are explicit rather than inferred from task counts.
            semantic_errors=[]
            if variant=='contrast' and c['id']=='PT01':semantic_errors=['任务无截止被扩写成付款条款无截止']
            if variant=='contrast' and c['id']=='PT04':semantic_errors=['已回答的付款时间事实被扩成核对目的']
            audited_checks=dict(checks)
            if c['id']=='PN02':
                # "营销这边" is a group, not a named personal assignment.
                audited_checks['created']=len(tasks)==0
                audited_checks['group_candidate']=len(items)==1 and items[0]['operation']=='candidate' and items[0]['owner_kind']=='group'
            controls.append(dict(variant=variant,case_id=c['id'],checks=checks,audited_checks=audited_checks,
                semantic_errors=semantic_errors,passed=all(audited_checks.values()) and not semantic_errors))
    updates=[]
    for c in read(EXP/'updates.json')['cases']:
        f=BASE/'updates'/c['id'];r=read(f/'result.json');tasks=read(f/'tasks.json');by_id={t['guid']:t for t in tasks};e=c['expected']
        checks=dict(processed=r['status']=='processed',statuses=all(by_id[g]['status']==v for g,v in e['statuses'].items()),
            dates=all(by_id[g].get('due_date')==v for g,v in e['dates'].items()),new_count=len(tasks)-len(c['tasks'])==e['new_tasks'])
        if e['no_review']:checks['no_review']=not r['extraction']['_task_trace']['review_records']
        if e['pending']:checks['pending']=bool(r['pending'] or r['extraction']['_task_trace']['review_records'])
        updates.append(dict(case_id=c['id'],checks=checks,passed=all(checks.values())))
    cost=[]
    for p in BASE.glob('*/summary.json'):
        rows=read(p)
        if isinstance(rows,list) and rows and 'calls' in rows[0]:
            cost.append(dict(variant=p.parent.name,calls=sum(r['calls'] for r in rows),tokens=sum(r['tokens'] for r in rows)))
    summary=dict(scores=scores,controls=controls,updates=updates,cost=cost,
                 total_new_calls=sum(r['calls'] for r in cost),total_new_tokens=sum(r['tokens'] for r in cost))
    write_json(BASE/'summary.json',summary)
    print(json.dumps(dict(scores={v:{k:s['fully_correct'] for k,s in ss.items()} for v,ss in scores.items()},
        controls=controls,updates=updates,new_calls=summary['total_new_calls'],new_tokens=summary['total_new_tokens']),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
