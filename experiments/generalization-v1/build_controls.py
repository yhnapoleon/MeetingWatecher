"""Authored counterfactual controls and reference labels, before prediction."""
import hashlib
import json
from pathlib import Path
import tiktoken

ROOT=Path(__file__).resolve().parents[2];DATA=ROOT/'data/generalization-v1'
ENC=tiktoken.get_encoding('cl100k_base')

def task(description,owner=None,commitment='committed',due=None,condition=None,evidence=(),scope=''):
    return dict(description=description,owner_ref=owner,owner_text=owner,commitment=commitment,due_text=due,
                condition=condition,evidence_turns=list(evidence),scope=scope)

PAIRS=[
 ('明确指派与本人承接',
  [('host','北库的货架标签样张需要重新导出，周五午前发给印务。小岚，你来处理。'),('lan','我先记下，今天还不能答应接这个活。'),('host','好的，负责人承接状态保留待确认，任务内容不变。')],
  [task('重新导出北库货架标签样张，周五午前发给印务','lan','assigned_unaccepted','周五午前',evidence=[0,1,2])],
  [('host','北库的货架标签样张需要重新导出，周五午前发给印务。小岚，你来处理。'),('lan','我接下了，周五午前会发给印务。'),('host','好，按这个安排。')],
  [task('重新导出北库货架标签样张，周五午前发给印务','lan',due='周五午前',evidence=[0,1])]),
 ('后续答复消除工作范围歧义',
  [('host','小牧，请导出东仓本月的盘点差异记录。'),('mu','我来导出。只导出冷库还是整个东仓？'),('host','范围我还要核实，会后再回复；先保留这件事。')],
  [task('导出东仓本月盘点差异记录，冷库或全仓范围待确认','mu',evidence=[0,1,2],scope='东仓，本月；冷库还是全仓尚未确定')],
  [('host','小牧，请导出东仓本月的盘点差异记录。'),('mu','我来导出。只导出冷库还是整个东仓？'),('host','只导出冷库，常温库不用。'),('mu','明白，就导出东仓冷库本月的记录。')],
  [task('导出东仓冷库本月盘点差异记录，不包括常温库','mu',evidence=[0,1,2,3],scope='东仓冷库，本月，不含常温库')]),
 ('条件任务与无条件开始',
  [('host','新展柜的灯带需要复测吗？'),('lan','如果明天的抽检仍有闪烁，我就复测全部展柜灯带并提交故障清单；抽检通过则不复测。'),('host','可以，明天只是抽检时点，复测没有约定截止日。')],
  [task('若明天抽检仍有闪烁，复测全部展柜灯带并提交故障清单','lan','conditional',condition='明天抽检仍有闪烁',evidence=[1,2])],
  [('host','新展柜的灯带需要复测吗？'),('lan','不等明天抽检了，我会立即开始复测全部展柜灯带并提交故障清单。'),('host','可以，明天只是抽检时点，复测没有约定截止日。')],
  [task('立即开始复测全部展柜灯带并提交故障清单','lan',evidence=[1,2],scope='全部展柜；立即开始，无截止日')]),
 ('历史引述与当前采纳',
  [('mu','去年复盘会上，顾问说“让小岚做一本供应商问答手册”。'),('host','那只是引用去年的发言，当时没有采纳，今天也不安排这件事。')],[],
  [('mu','去年复盘会上，顾问说“让小岚做一本供应商问答手册”。'),('host','这次我们正式采纳，请小岚编写供应商问答手册。'),('lan','好，这次由我来写。')],
  [task('编写供应商问答手册','lan',evidence=[1,2])]),
 ('已完成状态与新执行指令',
  [('host','访客终端显示语言目前已经是中英双语。这是在核对当前状态。'),('mu','确认，昨天已经改完并验收，不需要新的修改。')],[],
  [('host','访客终端显示语言目前只有中文，请改成中英双语。'),('mu','我来改，完成后交给前台验收。')],
  [task('将访客终端改成中英双语并交给前台验收','mu',evidence=[0,1])]),
 ('问题描述与工作承诺',
  [('lan','售后退换货说明有三处步骤表述冲突，客服最近经常被问到。'),('host','这个问题先记下来，今天不决定怎么处理，也不分派任务。')],[],
  [('lan','售后退换货说明有三处步骤表述冲突，客服最近经常被问到。'),('mu','我来统一这三处说明并把修订版发给客服，周三下班前完成。')],
  [task('统一退换货说明中的三处冲突并将修订版发给客服','mu',due='周三下班前',evidence=[0,1])]),
 ('未定建议与会末激活',
  [('host','要不要给巡检车加一个备用充电点？'),('lan','先作为想法保留，这次不定。'),('host','今天到这里，没有其他安排。')],[],
  [('host','要不要给巡检车加一个备用充电点？'),('lan','先作为想法保留，这次不定。'),('host','结束前再明确一下，这个备用充电点我们还是要建，请小牧先画位置图。'),('mu','我来画备用充电点的位置图。')],
  [task('绘制巡检车备用充电点的位置图','mu',evidence=[2,3])]),
 ('会上已答复与会后待办',
  [('host','新制服样衣的尺码对照表在哪里？'),('lan','就在资料盘的制服目录，我已经把链接贴在本次会议聊天里了。'),('host','看到了，可以打开，这个问题解决了。')],[],
  [('host','新制服样衣的尺码对照表在哪里？'),('lan','现在不在资料盘。我会后找供应商索取对照表，再发到资料盘的制服目录。'),('host','好，拿到后放进去即可，未约定截止日。')],
  [task('会后向供应商索取新制服样衣尺码对照表并上传资料盘制服目录','lan',evidence=[0,1,2])]),
 ('撤销与独立通知任务',
  [('host','原先商量的门店海报拍摄取消，当前没有已建任务。'),('mu','了解，不拍了，也不用另发通知，大家已经知道。')],[],
  [('host','原先商量的门店海报拍摄取消，当前没有已建任务。'),('mu','了解，不拍了。我另外负责通知印务撤销对应的纸张预留。')],
  [task('通知印务撤销门店海报对应的纸张预留','mu',evidence=[0,1])]),
 ('独立对象与重复提及去重',
  [('lan','我会提交南区展台的用电清单。'),('mu','北区展台的用电清单由我提交。'),('host','南北区是两个独立展台，各自交付自己的清单。')],
  [task('提交南区展台用电清单','lan',evidence=[0,2]),task('提交北区展台用电清单','mu',evidence=[1,2])],
  [('lan','我会提交南区展台的用电清单。'),('host','再确认一下，小岚要交的是南区展台用电清单。'),('lan','对，还是刚才同一份南区清单，不是新增另一份。')],
  [task('提交南区展台用电清单','lan',evidence=[0,1,2])]),
]

def main():
    cases=[];labels=[]
    for i,(mechanism,a,ta,b,tb) in enumerate(PAIRS,1):
        for suffix,lines,tasks in [('a',a,ta),('b',b,tb)]:
            cid=f'GC{i:02}{suffix}';segments=[dict(id=f'{cid}.{j+1}',speaker=s,text=t) for j,(s,t) in enumerate(lines)]
            meeting=dict(meeting_id=cid,series=f'CTRL{i:02}',participants=[dict(speaker=s,speaker_name=n,person_ref=s) for s,n in [('host','主持人'),('lan','小岚'),('mu','小牧')]],speaker_map={s:s for s in ['host','lan','mu']},audience=['host'],segments=segments)
            cases.append(dict(case_id=cid,split='test',kind='control',language='zh',source='authored',source_meeting=cid,series=f'CTRL{i:02}',domain='operations',mechanism=mechanism,measured_tokens=len(ENC.encode('\n'.join(t for _,t in lines))),meeting=meeting))
            gold=[]
            for j,t in enumerate(tasks,1):
                ev=[dict(segment_id=segments[k]['id'],quote=segments[k]['text']) for k in t.pop('evidence_turns')]
                gold.append(dict(id=f'T{j}',requirement='required',action=t['description'],object=t['description'],rationale=f'控制机制：{mechanism}；依据所列完整原句。',evidence=ev,**t))
            labels.append(dict(case_id=cid,topic_summary=mechanism,tasks=gold,exclusions=[] if gold else [dict(category='other',description=mechanism,evidence=[dict(segment_id=s['id'],quote=s['text']) for s in segments],reason='完整对话没有留下当前确定的会后工作，保留非任务/取消/建议边界。')],boundary_notes=[],coverage=dict(first_segment=segments[0]['id'],last_segment=segments[-1]['id'],all_segments_read=True),annotation_method='assistant authored control, before prediction'))
    for name,data in [('control-inputs.json',cases),('control-labels.json',labels)]:
        path=DATA/name
        if path.exists():raise FileExistsError(path)
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(f'{len(cases)} controls; {sum(len(l["tasks"]) for l in labels)} required tasks')

if __name__=='__main__':main()
