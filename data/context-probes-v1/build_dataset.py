"""Freeze authored mechanism probes, with references kept out of model inputs.

This is synthetic development material, not an unseen-corpus benchmark.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.inputs import digest

HERE = Path(__file__).resolve().parent
REVIEWER = 'codex-independent-contract-review-2026-11-14'
PEOPLE = [
    {'speaker': 'P', 'speaker_name': '主持人', 'person_ref': 'probe_pm'},
    {'speaker': 'L', 'speaker_name': '小林', 'person_ref': 'probe_lin'},
    {'speaker': 'Z', 'speaker_name': '小周', 'person_ref': 'probe_zhou'},
]
BY_SPEAKER = {p['speaker']: p for p in PEOPLE}


def case(cid, rows):
    return dict(case_id=cid, meeting_id=cid, series='synthetic-context-'+cid,
                language='zh', source='synthetic_mechanism_check', meeting_date='2026-11-14',
                participants=PEOPLE, segments=[
                    dict(id=f'{cid}.s{i}', **BY_SPEAKER[speaker], text=text)
                    for i, (speaker, text) in enumerate(rows, 1)])


CASES = [
    case('CP01', [
        ('P', '小林，界面功能清单这件事先记着，具体范围稍后定。'),
        ('L', '范围确定以后我再确认是否接这项工作。'),
        ('P', '产品目前有移动端和 Web 端两个入口。'),
        ('Z', '这次讨论主要围绕移动端。'),
        ('P', '移动端里有登录页和设置页。'),
        ('Z', '登录页的功能说明已经比较完整。'),
        ('P', '设置页有一些开关名称还没统一。'),
        ('L', '我听到了，清单的范围还需要你明确。'),
        ('P', '刚才那份清单，只整理移动端设置页的功能，不包括登录页。'),
        ('L', '好，我来整理移动端设置页的功能清单，不含登录页。'),
    ]),
    case('CP02', [
        ('P', '小林，请整理 Web 端登录页的功能清单。'),
        ('L', '好，我来整理 Web 端登录页的功能清单。'),
        ('P', '我们先核对一下页面名称。'),
        ('Z', '产品有 Web 端，也有移动端。'),
        ('P', '两个端都有登录页。'),
        ('Z', 'Web 端登录页当前使用密码登录。'),
        ('P', '移动端登录页还有短信验证码登录。'),
        ('L', '我先等你核对完对象。'),
        ('P', '刚才我说错了，要整理的是移动端登录页，Web 端不用整理。'),
        ('L', '收到，我改为整理移动端登录页的功能清单，不整理 Web 端。'),
    ]),
    case('CP03', [
        ('L', '我会整理这次活动的报名名单。'),
        ('P', '先核对一下活动安排。'),
        ('Z', '原计划的场地只能容纳二十人。'),
        ('P', '目前登记了十五个人。'),
        ('Z', '但场地临时有了其他用途。'),
        ('P', '我们还没有替代场地。'),
        ('L', '报名名单我还没有开始整理。'),
        ('P', '活动是否继续，需要现在确定。'),
        ('P', '这次活动取消，报名名单也不用整理了。'),
        ('L', '收到，我取消整理报名名单这项工作。'),
    ]),
    case('CP04', [
        ('P', '项目 A 和项目 B 都有一个页面叫“首页”，它们是两个不同的页面。'),
        ('P', '小林，请检查项目 A 的首页按钮文案。'),
        ('L', '我来检查项目 A 的首页按钮文案。'),
        ('P', '小周，请检查项目 B 的首页按钮文案。'),
        ('Z', '我来检查项目 B 的首页按钮文案。'),
        ('P', '这两个首页的检查结果分别保留，不要合并。'),
    ]),
    case('CP05', [
        ('P', '桌上有一本产品说明书和一台演示设备。'),
        ('Z', '说明书的封面是蓝色，设备外壳是白色。'),
        ('P', '这些只是现场物品，今天没有与它们相关的后续安排。'),
    ]),
    case('CP06', [
        ('P', '客服说，用户经常来问设备怎么恢复出厂设置。'),
        ('Z', '操作指南里其实写了步骤，但很多用户说自己从来没看过那本指南。'),
        ('P', '这个现象和我们希望减少重复咨询的目标有关。'),
        ('P', '目前还没有确定要做什么，也没有安排负责人。'),
    ]),
    case('CP07', [
        ('P', '客服说，用户经常来问设备怎么恢复出厂设置。'),
        ('Z', '操作指南里其实写了步骤，但很多用户说自己从来没看过那本指南。'),
        ('P', '这个现象和我们希望减少重复咨询的目标有关。'),
        ('P', '具体要做什么，我们接着讨论。'),
        ('Z', '现有指南同时包含安装、维护和重置三个部分。'),
        ('L', '重置步骤位于最后一节。'),
        ('P', '目前不清楚用户是没找到指南，还是觉得指南没有用。'),
        ('L', '我还在听你们讨论，暂时没有认领工作。'),
        ('P', '小林，请调查用户不阅读操作指南的原因，重点区分找不到指南和觉得没有用这两种情况。'),
        ('L', '好，我来调查这些原因，区分找不到指南和觉得指南没有用。'),
    ]),
    case('CP08', [
        ('L', '我会在2026年11月20日前把季度预算表发给财务部。'),
    ]),
]
CASE_INDEX = {c['case_id']: c for c in CASES}


def spans(cid, numbers):
    return [dict(segment_id=(s := CASE_INDEX[cid]['segments'][n-1])['id'],
                 start=0, end=len(s['text']), quote=s['text']) for n in numbers]


def label(cid, number, operation, description, work, *, owner=None, owner_ev=(),
          commitment=(), deadline=None, due_date=None, temporal=(), event_type=None, reason=''):
    evidence_numbers = list(dict.fromkeys([*work, *owner_ev, *commitment, *temporal]))
    fields = dict(work=spans(cid, work), owner=spans(cid, owner_ev),
                  commitment=spans(cid, commitment), time=spans(cid, temporal))
    return dict(case_id=cid, event_id=f'{cid}.{number}', label_id=f'{cid}.{number}',
                event_type=event_type or ('自我承诺' if operation == 'create' else '非执行工作'),
                operation=operation, description=description,
                owner_ref=owner, owner_label=next((p['speaker_name'] for p in PEOPLE if p['person_ref']==owner), None),
                owner_kind='corpus_person' if owner else None,
                due_text=deadline, due_date=due_date,
                evidence_ids=[f'{cid}.s{n}' for n in evidence_numbers],
                action_anchor=f'{cid}.s{work[0]}' if operation in ('create','candidate') else None,
                source_annotation=None, prior_label=None, prior_relation=None,
                work_window_text=None, required_content=[description], uncertainty=[],
                annotation_status='agent_reviewed', reviewer=REVIEWER,
                review_basis=reason, reason=reason,
                time_text=deadline, time_kind='deadline' if deadline else 'unspecified',
                field_evidence=fields)


LABELS = [
    label('CP01', 1, 'create', '整理移动端设置页的功能清单，不包括登录页', [9,10],
          owner='probe_lin', owner_ev=[1,9,10], commitment=[10], event_type='补全后分派并承接',
          reason='第8段时范围未定且本人明确未承接；第9段补全范围，第10段本人明确接受。'),
    label('CP02', 1, 'create', '整理移动端登录页的功能清单，不整理 Web 端', [9,10],
          owner='probe_lin', owner_ev=[1,9,10], commitment=[10], event_type='纠正后分派并承接',
          reason='第9段明确纠正工作对象，第10段接受新对象；旧 Web 端工作不再有效。'),
    label('CP03', 1, 'none', '整理报名名单的工作已取消', [1,9,10], event_type='撤回工作',
          reason='最后两段明确取消活动及对应工作；保留撤回历史，不能创建待办或继续要求接受。'),
    label('CP04', 1, 'create', '检查项目 A 的首页按钮文案', [2,3],
          owner='probe_lin', owner_ev=[2,3], commitment=[3], event_type='分派并承接',
          reason='项目 A 的首页与项目 B 的首页是不同实体；小林明确承接项目 A 的工作。'),
    label('CP04', 2, 'create', '检查项目 B 的首页按钮文案', [4,5],
          owner='probe_zhou', owner_ev=[4,5], commitment=[5], event_type='分派并承接',
          reason='小周明确承接项目 B 的工作；不能因页面同名、动作同类而合并。'),
    label('CP05', 1, 'none', '说明书和演示设备是现场物品，无后续工作安排', [1,2,3],
          event_type='纯实体描述', reason='物品及颜色事实不意味着需要处理它们，且原话明确无后续安排。'),
    label('CP06', 1, 'none', '用户不阅读操作指南可能与重复咨询有关，具体工作和负责人未定', [1,2,3,4],
          event_type='隐式需求线索', reason='原话表达问题和业务目标，但没有明确安排研究、改写指南或其他行动。'),
    label('CP07', 1, 'create', '调查用户不阅读操作指南的原因，区分找不到指南与觉得指南没有用', [9,10],
          owner='probe_lin', owner_ev=[9,10], commitment=[10], event_type='隐式线索明确化后承接',
          reason='前8段只有问题线索；第9段明确调查任务及范围，第10段承接，同一线索不再保留重复隐式待确认项。'),
    label('CP08', 1, 'create', '将季度预算表发给财务部', [1], owner='probe_lin',
          owner_ev=[1], commitment=[1], deadline='2026年11月20日前', due_date='2026-11-20', temporal=[1],
          reason='单句中动作、对象、接收方、个人承诺和交付期限均明确。'),
]


def criterion(key, description, cid, evidence, checkpoint=None):
    value = dict(id=key, description=description, evidence_ids=[f'{cid}.s{n}' for n in evidence])
    if checkpoint is not None:
        value['checkpoint_after_segment'] = f'{cid}.s{checkpoint}'
    return value


def behavior(cid, title, criteria):
    return dict(case_id=cid, title=title, criteria=[criterion(k, text, cid, ev, checkpoint)
                for k, text, ev, checkpoint in criteria])


BEHAVIOR = dict(version='context-behavior-v1', status='frozen', annotation_status='agent_reviewed',
    reviewer=REVIEWER, evaluation_role='synthetic_mechanism_check', is_blind=False,
    input_hash=digest(CASES), labels_hash=digest(LABELS),
    scoring='Independent source-based boolean judgments per criterion; checkpoints and final results are evaluated separately. No keyword-match scoring.',
    cases=[
        behavior('CP01', '跨检查点补范围并承接', [
            ('prefix_unaccepted', '第8段时保留界面功能清单线索，范围待定且未承接；不得使用第9/10段信息。', [1,2,8], 8),
            ('final_content', '最终完整保留移动端、设置页、功能清单及不含登录页的范围。', [9,10], None),
            ('final_acceptance', '最终仅一项小林承接的创建提议，无重复旧待确认项，无虚构期限。', [9,10], None),
        ]),
        behavior('CP02', '纠正对象', [
            ('prefix_object', '第8段时工作对象是 Web 端登录页，尚不知道后续纠正。', [1,2,8], 8),
            ('final_object', '最终只保留移动端登录页工作，不同时创建 Web 端工作；负责人小林。', [9,10], None),
            ('revision_history', '保留旧对象到新对象的更新依据，不能改写旧检查点使其提前知道新对象。', [1,2,9,10], None),
        ]),
        behavior('CP03', '后文取消', [
            ('prefix_commitment', '第8段时保留小林整理报名名单的明确承诺，不能提前视为取消。', [1,7], 8),
            ('final_withdrawn', '最终无创建提议；线索保留明确撤回状态及取消依据。', [9,10], None),
            ('no_stale_question', '已取消工作不再作为待采纳任务询问用户；纯历史说明不算待确认。', [9,10], None),
        ]),
        behavior('CP04', '同名实体不合并', [
            ('distinct_entities', '项目 A 首页和项目 B 首页分别可识别；相同页面名不构成 same_as。', [1,2,4], None),
            ('distinct_work', '保留两项检查按钮文案的工作，小林对应 A，小周对应 B，均已承接。', [2,3,4,5], None),
        ]),
        behavior('CP05', '孤立名词', [
            ('entities_retained', '实体账本保留产品说明书和演示设备及原话提及。', [1,2], None),
            ('no_task_or_question', '不产生任务、隐式需求或待确认卡；可以保留 entity_only 记录。', [3], None),
        ]),
        behavior('CP06', '问题背景中的隐式需求', [
            ('need_retained', '待确认内容保留用户不阅读指南、重复重置咨询及减少咨询目标，区分事实与推测的工作目的。', [1,2,3,4], None),
            ('targeted_question', '提出需要确认的具体工作方向或是否开展调查；不能只问“确认吗”。', [1,2,3,4], None),
            ('no_invented_commitment', '无创建或更新提议，不断言已指派某人，不新增访谈、问卷、报告或改写指南等确定交付。', [4], None),
        ]),
        behavior('CP07', '隐式需求后明确化', [
            ('prefix_implicit', '第8段时保留问题线索但尚未分派、未承接，不使用第9/10段信息。', [1,2,3,4,7,8], 8),
            ('final_explicit', '最终保留调查不阅读原因及两种情况的范围，小林明确接受，形成一个创建提议。', [9,10], None),
            ('no_duplicate_need', '同一问题线索得到补全后，不再同时保留“是否开展该调查”的旧待确认项；更新历史仍可见。', [1,2,9,10], None),
        ]),
        behavior('CP08', '明确单句工作', [
            ('full_action', '保留发送季度预算表给财务部的工作，负责人小林，不误分为隐式需求或模糊工作。', [1], None),
            ('deadline', '生成一个创建提议，交付日期为2026-11-20；标题无需重复日期。', [1], None),
        ]),
    ])


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    for name, rows in [('input', CASES), ('labels', LABELS)]:
        (HERE/(name+'.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), encoding='utf-8')
    write_json(HERE/'behavior.json', BEHAVIOR)
    write_json(HERE/'manifest.json', dict(status='frozen', input_hash=digest(CASES), labels_hash=digest(LABELS),
        behavior_hash=digest(BEHAVIOR), annotation_status='agent_reviewed', reviewer=REVIEWER,
        provenance='Authored before context-v1 outputs; synthetic development probes for the proposed mechanism.',
        evaluation_role='synthetic_mechanism_check', is_blind=False, checkpoint_segments=8,
        case_count=len(CASES), reference_action_count=sum(x['operation'] in ('create','candidate') for x in LABELS)))
    print(json.dumps(dict(cases=len(CASES), labels=len(LABELS), input_hash=digest(CASES), labels_hash=digest(LABELS)), ensure_ascii=False))


if __name__ == '__main__':
    main()
