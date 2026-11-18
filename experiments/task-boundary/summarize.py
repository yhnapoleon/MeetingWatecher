"""Combine separately frozen semantic reviews, first responses and one-shot recoveries."""
import copy
from collections import Counter
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest
from scripts.review_action_semantics import export_review,read_jsonl,JUDGMENTS
from scripts.score_action_semantics import score_semantics
from scripts.run_action_baseline import write_json
from assess import updates

BASE=ROOT/'runs/2026-11-15-task-boundary'
OLD=ROOT/'runs/2026-11-15-full-validation'
FINAL=BASE/'full-v2'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def freeze(path,value):
    if path.exists():assert read(path)==value,'Changed outputs require a fresh source review: '+str(path)
    else:write_json(path,value)

BEHAVIOR={
 'CP01':'第8段范围和承接仍待定；末尾明确移动端设置页、不含登录页，小林接受，仅一个create且无期限。',
 'CP02':'第8段保留Web对象；后文撤回Web并改为移动端，旧历史保留，核对resolved，无重复工作。',
 'CP03':'第8段名单尚待整理且活动未取消；最终名单和替代场地需求撤回，是否继续已解决，无遗留卡片。',
 'CP04':'A/B两个首页实体以distinct区分，各自检查工作分别保留，小林/小周分别接受，分开保存只作为约束。',
 'CP05':'说明书、设备实体及提及保留，无工作或卡片；上下文说明仅为现场物品。',
 'CP06':'保留指南未阅读、恢复出厂咨询和减少咨询目的，以implicit_need询问是否推进及范围，无虚构交付/承诺。',
 'CP07':'第8段两类原因尚待判断，无分派；末尾小林承接调查，保留找不到/认为无用两类原因及减少咨询目标，无重复需求。',
 'CP08':'小林发送季度预算表给财务，日期2026-11-20，单项create。',
 'PF01':'名单撤回，取消后的通知由小周接受并创建，未因活动取消关闭善后。',
 'PF02':'仅春季名单撤回，小周继续秋季名单，无重复确认。'}


def main():
    run=read(FINAL/'summary.json')
    behavior=[]
    for group,source in [('probes','context-probes-v1'),('cancellation','context-prerequisites-v1')]:
        for case in read(ROOT/'data'/source/'behavior.json')['cases']:
            result=read(FINAL/group/case['case_id']/'result.json')
            assert result['status']=='processed'
            behavior.append(dict(case_id=case['case_id'],result_hash=digest(result),
                criteria=[dict(**c,passed=True,reason=BEHAVIOR[case['case_id']]) for c in case['criteria']]))
    freeze(FINAL/'behavior-review.json',dict(status='agent_reviewed',cases=behavior,
        extra_observation='CP01开关命名问题保存在账本和上下文，没有独立潜在需求卡；冻结标准未要求额外命名任务。'))
    # Manually source-reviewed continuous-role example, with explicit output matching.
    context=read(FINAL/'context/CTX_ES2002a_roles/result.json')
    items=context['extraction']['items']
    assert [i['owner_ref'] for i in items]==['MEE006','MEE007','MEE008']
    assert [i['operation'] for i in items]==['create','candidate','create']
    freeze(FINAL/'context-review.json',dict(status='agent_reviewed',result_hash=digest(context),correct=3,total=3,
        reason='工作设计/技术功能/产品需求三项及角色对应正确；本人Yep/Okay分别承接，UI无人承接保留候选，工作时段不当期限。'))
    update_report=updates(FINAL)
    scores=read(FINAL/'corpus-scores.json')
    inputs=read_jsonl(OLD/'corpus/input.jsonl')
    predictions=[read(FINAL/'corpus'/c['case_id']/'summary.json') for c in inputs]
    recovered_prediction=read(BASE/'corpus-v2-recovery/corpus/C19/summary.json')
    overlay=[recovered_prediction if p['case_id']=='C19' else p for p in predictions]
    recovered_note=read(BASE/'corpus-v2-recovery/source-review.json')['cases'][0]
    recovery_scores={}
    for version,label in [('original','labels.snapshot.jsonl'),('audited','labels.audited.jsonl')]:
        labels=read_jsonl(OLD/'corpus'/label)
        review=export_review(inputs,labels,overlay)
        review.update(status='agent_reviewed',reviewer='codex-source-review-task-boundary-recovery-overlay')
        originals={r['case_id']:r for r in read(FINAL/f'corpus-review-{version}.json')['cases']}
        for case in review['cases']:
            case['reviewed']=True
            if case['case_id']!='C19':case['judgments']=copy.deepcopy(originals[case['case_id']]['judgments'])
            else:
                assert recovered_note['result_hash']==digest(read(BASE/'corpus-v2-recovery/corpus/C19/result.json'))
                for row,note in zip(case['judgments'],recovered_note['matches']):
                    row.update({k:True for k in JUDGMENTS})
                    row.update(gold_event_id=note['gold_event_id'],reason=note['reason'],evidence_ids=case['predictions'][row['prediction_index']]['evidence_ids'])
        score=score_semantics(overlay,labels,review)
        write_json(BASE/'corpus-v2-recovery'/f'overlay-review-{version}.json',review)
        recovery_scores[version]=score
    write_json(BASE/'corpus-v2-recovery/overlay-scores.json',recovery_scores)
    cross=read(BASE/'cross-v2/acceptance.json')
    cross2=read(BASE/'cross-v2/m2-result.json')
    cross_review=dict(result_hash=digest(cross2),m1_no_extra_items=len(read(BASE/'cross-v2/m1-result.json')['extraction']['items'])==1,
        m2_no_extra_items=not cross2['extraction']['items'],m2_no_extra_questions=not cross2['extraction']['_task_trace']['review_records'],
        reason='旧任务完成和决策替代正确，但另生成范围调整候选，并将今天误写为截止日期。')
    write_json(BASE/'cross-v2/semantic-review.json',cross_review)
    usage=[]
    for p in sorted(BASE.iterdir()):
        if not p.is_dir():continue
        if (p/'summary.json').exists():
            s=read(p/'summary.json');usage.append(dict(run=p.name,calls=s['calls'],tokens=s['tokens']))
        elif (p/'acceptance.json').exists():
            meta=[read(m) for m in (p/'model').rglob('meta.json')]
            usage.append(dict(run=p.name,calls=len(meta),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in meta)))
    write_json(BASE/'usage.json',dict(runs=usage,calls=sum(r['calls'] for r in usage),tokens=sum(r['tokens'] for r in usage),
        note='Recovery rows count new calls only; smoke includes one sandbox-denied zero-token call.'))
    # Verify production files match the final model run, not merely the test count.
    with zipfile.ZipFile(FINAL/'source.zip') as archive:
        changed=[n for n in archive.namelist() if n.startswith(('meeting_eval/','prompts/')) and archive.read(n)!=(ROOT/n).read_bytes()]
    assert not changed,changed
    pairs=read(BASE/'pairs-v2/contract-review.json')
    reviews=read(FINAL/'source-review.json')['cases']
    summary=dict(corpus_first={v:dict(fully_correct=s['fully_correct'],exact_cases=s['exact_cases']['correct'],failed_cases=s['failed_cases']) for v,s in scores.items()},
        corpus_after_one_recovery={v:s['fully_correct'] for v,s in recovery_scores.items()},
        confirmations=dict(first_total=sum(len(r['cards']) for r in reviews),first_inappropriate=sum(not c['appropriate'] for r in reviews for c in r['cards']),
                           after_recovery_total=sum(len(r['cards']) for r in reviews)+len(recovered_note['cards'])),
        behavior=dict(passed_cases=len(behavior),cases=len(behavior),passed_criteria=sum(len(r['criteria']) for r in behavior)),
        continuous_roles=dict(correct=3,total=3),updates=dict(passed=update_report['passed'],total=update_report['total']),
        cross_meeting=dict(passed=sum(cross['checks'].values()),total=len(cross['checks']),additional_semantic=cross_review),
        pairs=dict(first_passed=pairs['passed'],total=pairs['total'],first_failed=[r['case_id'] for r in pairs['cases'] if not r['passed']],
                   recovered=['P07a','P08b'],remaining=['P07b']),
        first_pass_statuses=dict(Counter(r['status'] for r in run['results'])),
        final_full_run=dict(calls=run['calls'],tokens=run['tokens']),usage=usage,production_matches_final_snapshot=True)
    write_json(BASE/'summary.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='usage'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
