"""Freeze the source review of this run; score with original and audited labels."""
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest
from scripts.review_action_semantics import export_review, read_jsonl, JUDGMENTS
from scripts.score_action_semantics import score_semantics
from scripts.run_action_baseline import write_json

BASE=ROOT/'runs/2026-11-15-full-validation'

# Each entry follows the actual output order, reviewed against the complete input.
# Null is an extra task. False fields below distinguish contextual errors.
MATCHES={
    'C01':[None], 'C02':['C02.1'], 'C03':['C03.1','C03.2'], 'C04':[None], 'C05':[None],
    'C06':[None,'C06.1'], 'C07':['C07.1','C07.2','C07.3'], 'C08':['C08.1'], 'C09':['C09.1'],
    'C10':[], 'C11':[], 'C12':[], 'C13':[], 'C14':[], 'C15':['C15.1'], 'C16':['C16.1','C16.2'],
    'C17':[], 'C18':[], 'C19':['C19.1'], 'C20':['C20.1'], 'C21':['C21.1'], 'C22':['C22.1'],
    'C23':['C23.1'], 'C24':[None], 'C25':[], 'C26':[None], 'C27':[], 'C28':[], 'C29':[], 'C30':[None]}
REASONS={
    'C01':'本人确实接受现场白板练习，但这是当场活动，不是会后项目待办。',
    'C02':'工业设计师对应工作设计分工并说Yep；工作时段没有变成截止日期。',
    'C03':'连续角色分工恢复技术功能工作，UI未接受为候选；市场负责人Okay接受自己的分工。',
    'C04':'公司已决定排除图文电视，是设计约束；同一内容已进入decisions，又多出一条待办。',
    'C05':'只控制电视是产品范围决定；未另行安排一项执行工作，却生成团队任务候选。',
    'C06':'第一项仅为下一阶段工作时段，缺少独立任务内容；第二项本人明确承诺上传纪要，正确。',
    'C07':'三位角色各自对应组件概念、用户界面和趋势研究，均未本人承接；午后30分钟是工作时段。',
    'C08':'本人承诺上传纪要，保留as soon as possible而未编造日历日期。',
    'C09':'问答及Okay支持营销研究说明书相关问题；消费者看法是旧标签的具体化，新口径允许该研究对象及使用背景。',
    'C15':'Alima的工作设计分派由对应工业设计师Yeah接受。',
    'C16':'本人明确承诺整理纪要，并在请求后明确将幻灯片作为附件发邮件；可能邮件发纪要仍以probably标明。',
    'C19':'保留整理问题、老师解答、形成文字稿、公众号发布的完整链条；我们未指派个人，故候选。',
    'C20':'保留剪辑视频并交大家确认的团队工作，没有把未确定的文稿处理加到任务。',
    'C21':'明确会整理意见，但没有个人负责人；背景的篇幅讨论不添加范围缺口。',
    'C22':'本人明确会后联系并深入学习文化类型对学校建设的帮助；没有个人身份映射，保留说话人候选。会后不是交付期限。',
    'C23':'保留会后单独联系袁校长沟通问题的工作；信号不清是联系背景，不要求逐字写入标题。会后不是交付期限。',
    'C24':'原文是举例转述老师常问的问题，不是本场人事部门分派给与会者的工作；解释丢失转述语境。',
    'C26':'目前标签将我们可以会后细化视为提议；输出却按已承诺团队工作处理，只追问个人负责人。',
    'C30':'介绍稍后的导览和集合安排，不是新增项目待办；输出将活动说明变成待指派任务。'}


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def main():
    folder=BASE/'corpus'
    inputs=read_jsonl(folder/'input.jsonl')
    predictions=[read(folder/c['case_id']/'summary.json') for c in inputs]
    hashes={c['case_id']:digest(read(folder/c['case_id']/'result.json')) for c in inputs}
    freeze=BASE/'corpus/reviewed-output-hashes.json'
    if freeze.exists():assert read(freeze)==hashes,'Output changed; new source review required'
    else:write_json(freeze,hashes)
    scores={}
    for version,label_file in [('original','labels.snapshot.jsonl'),('audited','labels.audited.jsonl')]:
        labels=read_jsonl(folder/label_file)
        review=export_review(inputs,labels,predictions)
        review.update(status='agent_reviewed',reviewer='codex-full-source-review-2026-11-15')
        for case in review['cases']:
            cid=case['case_id'];case['reviewed']=True
            assert len(case['predictions'])==len(MATCHES[cid]),cid
            for row,target in zip(case['judgments'],MATCHES[cid]):
                item=case['predictions'][row['prediction_index']]
                row.update({f:True for f in JUDGMENTS})
                row.update(gold_event_id=target,reason=REASONS[cid],evidence_ids=item['evidence_ids'])
                if target is None:
                    row['operation_correct']=False
                    if cid in ('C04','C05','C06','C24','C26'):row['commitment_correct']=False
                    if cid=='C06':row['content_complete']=False
                    if cid=='C24':row.update(content_supported=False,owner_correct=False)
                if version=='original':
                    if cid=='C09':row['content_complete']=False
                    if cid in ('C22','C23'):row['time_correct']=False
        write_json(folder/f'semantic-review-{version}.json',review)
        score=score_semantics(predictions,labels,review)
        exact=[]
        for c in review['cases']:
            expected={g['event_id'] for g in c['references'] if g['operation'] in ('create','candidate')}
            correct={j['gold_event_id'] for j in c['judgments'] if j['gold_event_id'] and all(j[k] for k in JUDGMENTS)}
            status=next(p['status'] for p in predictions if p['case_id']==c['case_id'])
            exact.append(dict(case_id=c['case_id'],passed=status=='processed' and expected==correct and len(correct)==len(c['predictions'])))
        score['exact_cases']=dict(correct=sum(r['passed'] for r in exact),total=len(exact),cases=exact)
        write_json(folder/f'semantic-scores-{version}.json',score);scores[version]=score
    write_json(folder/'review-summary.json',scores)
    print(json.dumps({v:{k:s[k] for k in ['content','fully_correct','exact_cases','failed_cases','missed_content']} for v,s in scores.items()},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
