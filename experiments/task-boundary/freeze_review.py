"""Freeze this run's manually inspected judgments, bound to exact output hashes."""
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest
from scripts.run_action_baseline import write_json
BASE=ROOT/'runs/2026-11-15-task-boundary'
def read(p):return json.loads(p.read_text(encoding='utf-8'))

# Reviewed against full-v2 inputs and outputs, not inherited from baseline matches.
MATCHES={
    'C02':['C02.1'],'C03':['C03.1','C03.2'],'C06':['C06.1'],
    'C07':['C07.1','C07.2','C07.3'],'C08':['C08.1'],'C09':['C09.1'],
    'C14':['C14.1'],'C15':['C15.1'],'C16':['C16.1','C16.2'],
    'C20':['C20.1'],'C21':['C21.1'],'C22':['C22.1'],'C23':['C23.1']}
REASONS={
    'C02':'工业设计师接到工作设计安排后本人Yep接受，未把开会时段当期限。',
    'C03':'连续分工保留UI技术功能和市场需求；UI未接受为candidate，营销本人Okay为create。',
    'C06':'只有主持人上传纪要工作；30分钟作为安排保存，无额外任务。',
    'C07':'分别保留组件概念、界面和趋势研究三项分工及对应角色；没有本人接受，均为candidate；午饭后30分钟不作期限。',
    'C08':'本人承诺上传纪要，保留as soon as possible且未编造日期。',
    'C09':'问答及本人Okay支持营销研究说明书，保留下一场会前相对期限；未强补消费者调查方法。',
    'C14':'保留电视/录像功能范围核查，负责人为回应的PM；If I can原话显示在条件卡，candidate不自动创建。',
    'C15':'Alima工作设计分工由本人Yeah接受。',
    'C16':'保留整理纪要和邮件附件发送幻灯片两项本人承诺；纪要邮件仍保留probably。',
    'C20':'视频剪辑并发大家确认的团队工作正确；文稿只出现在另一个有争议的确认卡，不计为任务。',
    'C21':'团队明确会整理意见，负责人未实名，candidate；篇幅背景未阻断工作。',
    'C22':'保留会后联系夏校长和学习文化类型对学校建设帮助，未知个人账号，candidate；会后为时段。',
    'C23':'保留团队会后联系袁校长、沟通其他问题及信号背景，未因议题未细列阻断；会后为时段。'}
NOTES={
    'C01':'白板练习仅作上下文。','C04':'排除图文电视只作决定/背景。','C05':'电视专用范围只作决定/背景。',
    'C11':'备用产品方案作为上下文保留，无任务或负责人确认。','C17':'已发送、正放入文件夹两项状态汇报，无兜底确认。',
    'C19':'首次interpret引文校验失败，不生成任务；恢复另计。','C24':'两条教师问题保留外层转述，不成任务或卡片。',
    'C25':'投资项目对接和机构合作孵化分别保留潜在需求，无自动任务。',
    'C26':'细化场景保留待采纳提议，无已承诺任务。','C29':'主持交接/可选会后交流作为上下文，无卡片。',
    'C30':'导览与集合是活动安排，无任务或卡片。'}


def main():
    rows=[]
    for number in range(1,31):
        cid=f'C{number:02}';result=read(BASE/'full-v2/corpus'/cid/'result.json')
        targets=MATCHES.get(cid,[])
        assert len(targets)==len(result['extraction']['items']),cid
        matches=[dict(gold_event_id=t,reason=REASONS[cid],wrong=[],
                      original_wrong=['content_complete'] if cid=='C09' else ['time_correct'] if cid in ('C22','C23') else []) for t in targets]
        reviews=result['extraction']['_task_trace'].get('review_records',[])
        cards=[]
        for r in reviews:
            bad=cid=='C20' and r['record_id']=='R2'
            cards.append(dict(record_id=r['record_id'],appropriate=not bad,
                reason='文稿未被安排与视频一并确认，修正后仍保留错误动作假设和泛化追问。' if bad else
                       '保留实际承接/个人账号缺口。' if cid in ('C03','C07','C20','C21','C22','C23') else
                       '条件工作保留原条件。' if cid=='C14' else
                       '询问是否落实具体合作目标，没有预设已分派。' if cid=='C25' else '待采纳提议，未预设已承诺。'))
        rows.append(dict(case_id=cid,result_hash=digest(result),matches=matches,cards=cards,
                         note=NOTES.get(cid,REASONS.get(cid,'原文未形成独立工作，无任务或确认。'))))
    value=dict(status='agent_reviewed',scope='full-v2 first responses; source-based review, original labels unchanged',cases=rows)
    target=BASE/'full-v2/source-review.json'
    if target.exists():assert read(target)==value
    else:write_json(target,value)
    # Recovery is a separate, explicit overlay; first-pass outputs are never replaced.
    recovered=read(BASE/'corpus-v2-recovery/corpus/C19/result.json')
    extra=dict(case_id='C19',result_hash=digest(recovered),
        matches=[dict(gold_event_id='C19.1',wrong=[],original_wrong=[],reason='恢复后保留整理问题、老师解答、形成文字稿和公众号发布链条；团队候选，未编造期限。')],
        cards=[dict(record_id=r['record_id'],appropriate=True,reason='团队未指派个人负责人。') for r in recovered['extraction']['_task_trace']['review_records']])
    write_json(BASE/'corpus-v2-recovery/source-review.json',dict(status='agent_reviewed',cases=[extra]))
    print(json.dumps(dict(task_predictions=sum(len(r['matches']) for r in rows),cards=sum(len(r['cards']) for r in rows),
          inappropriate_cards=sum(not c['appropriate'] for r in rows for c in r['cards'])),ensure_ascii=False))


if __name__=='__main__':main()
