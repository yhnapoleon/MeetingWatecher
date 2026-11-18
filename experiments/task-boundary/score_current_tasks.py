"""Re-score existing predictions at task level, without making model calls.

References below normalize the existing frozen source/labels/contracts. Explicit
matches were reviewed against the source; this is not a model/keyword judge.
The task metric was requested AFTER prediction. Original full-output grades stay
unchanged. This is an assistant audit, not independent blind annotation.
"""
import argparse
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.inputs import digest
from scripts.score_action_semantics import prf


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


# Independent work objectives; a delivery sequence for the same object stays one
# objective. Distinct objects/assignees stay separate. Empty cases are explicitly
# covered by their frozen source and contract; implicit needs/proposals are not
# counted as confirmed work, and are audited separately below.
TASKS = {
    'updates/M2': ['今天将登录改版第一批范围调整为内部员工和试点客户'],
    'updates/HT06': ['整理两个支付失败案例并在2026-11-20下班前发到支付群'],
    'pairs/P01b': ['会后整理白板动物图并发给大家'],
    'pairs/P02b': ['据仅控制电视不支持DVD的约束修改规格并发评审'],
    'pairs/P03a': ['落实取消图文电视功能的决定'],
    'pairs/P03b': ['从规格表移除图文电视功能'],
    'pairs/P04a': ['主持人上传纪要'],
    'pairs/P04b': ['小林在接下来30分钟看组件概念', '小周在接下来30分钟看界面功能', '主持人上传纪要'],
    'pairs/P05b': ['小林核对本园本次名单'],
    'pairs/P07b': ['小林会后细化场景'],
    'pairs/P08b': ['小林有条件了解能否支持录像，保留如果能查到'],
    'pairs/P09b': ['活动开始前排好导览路线并发给导览员'],
    'pairs/P10b': ['安老师跟进客户投诉'],
    'pairs/P11b': ['小林把纪要发给大家再放共享文件夹'],
    'pairs/P12a': ['第一批范围从仅员工改为员工和试点客户'],
    'pairs/P12b': ['小林今天下班前按员工及试点客户范围修改灰度配置并发测试'],
    'pairs/P13b': ['小林会后联系袁老师沟通两个问题'],
    'pairs/P14b': ['小林检查移动端登录页按钮文案'],
    'pairs/R01': ['小林整理移动端登录页功能清单，已承接'],
    'pairs/R02': ['小林整理移动端登录页功能清单，本人未承接'],
    'pairs/R03': ['小林整理移动端登录页功能清单，本人仍需评估'],
    'pairs/R04': ['小周整理电脑端注册页功能清单'],
    'pairs/R05': ['小林核对大班名单中的重复姓名'],
    'supplemental/S-C23-explicit': ['会后联系袁校长补问信号不好未听清的问题'],
    'supplemental/S-C23-unrelated': ['会后联系袁校长沟通报名问题，信号问题已解决'],
    'supplemental/S-no-date': ['整理登录失败案例并发研发群，未定期限'],
    'supplemental/S-activate': ['已激活上线后完成监控面板的工作'],
    'supplemental/S-same-segment': ['今天调整第一批范围为内部员工及试点客户', '陈可今天下班前发测试结果给客服，本人未承接'],
    'supplemental/S-M1': ['陈可整理三个登录失败案例并于本周五下班前发研发群'],
    'semantic/SV03': ['小林下次会前调查校车准点率'],
    'semantic/SV04': ['小林已承接下次会前走访，食堂或校车范围尚未选定'],
    'semantic/SV09': ['小林现在只发课程海报到教师群'],
    'semantic/SV10': ['小林今天发课程海报到教师群', '小林今天修正文稿活动时间后发同一教师群'],
    'semantic/SV12': ['小周明天比较双屏单屏成本并发主持人'],
    'semantic/SV15': ['小林现在开始查离线检索支持，明天下午反馈，即使查不到也反馈经过'],
    'semantic/SV16': ['小林仅在管理员明天开通权限后查询离线检索支持，未开通不查'],
}

# Item indices match the ordered existing event labels or the normalized tasks
# above, except these explicitly adjudicated cases. No automatic semantic match.
ITEM_MATCHES = {
    'corpus/C02': [0], 'corpus/C03': [1], 'corpus/C06': [0],
    'corpus/C07': [0, 1, 2], 'corpus/C08': [0], 'corpus/C14': [0],
    'corpus/C15': [0], 'corpus/C16': [0, 1], 'corpus/C19': [0],
    'corpus/C20': [0], 'corpus/C21': [0], 'corpus/C22': [0], 'corpus/C23': [0],
    'corpus/C24': [None, None], 'context/CTX_ES2002a_roles': [0, 1, 2],
    'probes/CP01': [0], 'probes/CP02': [0], 'probes/CP04': [0, 1],
    'probes/CP07': [0], 'probes/CP08': [0], 'cancellation/PF01': [0],
    'cancellation/PF02': [0],
    'updates/M2': [0], 'updates/HT06': [0],
    'pairs/P01b': [0], 'pairs/P02b': [0], 'pairs/P03a': [0], 'pairs/P03b': [0],
    'pairs/P04a': [0], 'pairs/P04b': [0, 1, 2], 'pairs/P05b': [0],
    'pairs/P07b': [0], 'pairs/P08b': [0], 'pairs/P09b': [0], 'pairs/P10b': [0],
    'pairs/P11b': [0], 'pairs/P12a': [0], 'pairs/P12b': [0], 'pairs/P13b': [0],
    'pairs/P14b': [0], 'pairs/R01': [0], 'pairs/R02': [0], 'pairs/R03': [0],
    'pairs/R04': [0], 'pairs/R05': [0],
    'supplemental/S-C23-explicit': [0], 'supplemental/S-C23-unrelated': [0],
    'supplemental/S-no-date': [0], 'supplemental/S-activate': [0],
    'supplemental/S-same-segment': [0, 1], 'supplemental/S-M1': [0],
    'semantic/SV02': ['optional'], 'semantic/SV03': [0], 'semantic/SV09': [0],
    'semantic/SV10': [0, 1], 'semantic/SV12': [0], 'semantic/SV15': [0],
    'semantic/SV16': [0],
    'chains/M2-service/M1': [0], 'chains/M2-service/M2': [0],
    'chains/positive-service/M1': [0], 'chains/positive-service/M2': [0],
}
CARD_MATCHES = {
    'corpus/C03': {'R1': 0}, 'corpus/C09': {'R1': None},
    'corpus/C20': {'R2': None}, 'semantic/SV04': {'R1': 0},
}
ERRORS = {
    ('corpus/C03', 'review:R1'): ['owner_missing_or_wrong', 'unnecessary_owner_question'],
    ('semantic/SV15', 'item:0'): ['start_time_missing'],
}
REASONS = {
    ('corpus/C03', 'review:R1'): 'UI技术功能工作已在确认卡保留；负责人误判为空，不是工作未被识别。',
    ('corpus/C09', 'review:R1'): '已确定的说明书调查被改成说明书或所有问题的范围待选，动作对象范围未正确确定，计一个FP和一个FN。',
    ('corpus/C20', 'review:R2'): '文稿仅被提及，补成会后交大家确认的工作，无原文依据。',
    ('corpus/C24', 'item:0'): '历史教师举例被当成本场孩子信息核对工作。',
    ('corpus/C24', 'item:1'): '历史教师举例被当成本场体质检查结果发布工作。',
    ('semantic/SV04', 'review:R1'): '已承接走访保留在范围确认卡，未定对象也是正确保留，不应因没有items就说工作未识别。',
    ('semantic/SV15', 'item:0'): '查询与反馈的动作对象完整；立即开始时段缺失，字段指标计错，任务识别仍命中。',
    ('semantic/SV02', 'item:0'): '冻结标签明确允许确定许可的候选工作，但不强制；正确可选项单列，不制造必需召回分母。',
}


def audit(folder):
    manifest = read(folder / 'manifest.json')
    assert digest(manifest) == 'd0fe384991ab840bf7a49b01c2745e82b7778d9ae5d8cc0c41decf429d718a55', 'Manual matches apply only to the frozen current baseline'
    source_review = read(folder / 'source-review.json')
    assert source_review['status'] == 'complete'
    units = []
    for job in manifest['jobs']:
        key = job['group'] + '/' + job['id']
        result_path = folder / 'r1' / key / 'result.json'
        if job['group'] in manifest['labels']:
            refs = [r for r in manifest['labels'][job['group']] if r['case_id'] == job['id'] and r['operation'] in ('create', 'candidate')]
            basis = 'frozen_event_labels'
        else:
            refs = [dict(event_id=job['id'] + '.task' + str(i + 1), description=d,
                         evidence_ids=[s['id'] for s in job['meeting']['segments']]) for i, d in enumerate(TASKS.get(key, []))]
            basis = 'frozen_source_and_contract_normalized_after_prediction'
        units.append((key, key, result_path, refs, basis, digest(job)))
    for chain in manifest['chains']:
        for stage in ('M1', 'M2'):
            parent = 'chains/' + chain
            key = parent + '/' + stage
            desc = '陈可整理三个登录失败案例并本周五下班前发研发群' if stage == 'M1' else (
                '陈可今天下班前按员工及试点客户新范围改好灰度配置并发测试' if chain == 'positive-service'
                else '今天将第一批范围调整为员工和试点客户，负责人未定')
            path = folder / 'r1' / parent / (stage.lower() + '-result.json')
            units.append((key, parent, path, [dict(event_id=stage+'.task1', description=desc)],
                          'frozen_chain_source_and_contract', source_review['cases'][parent]['input_hash']))
    cases = []
    auxiliary = []
    for key, parent, path, refs, basis, input_hash in units:
        result = read(path)
        assert digest(result) == source_review['cases'][parent]['evidence_hashes'][path.name]
        e = result['extraction']; trace = e['_task_trace']
        items = e['items']; item_records = trace.get('item_records', [])
        assert len(item_records) == len(items), key
        matches = ITEM_MATCHES.get(key, [])
        assert len(matches) == len(items), ('output changed, needs review', key)
        preds = []
        for i, (item, match) in enumerate(zip(items, matches)):
            preds.append(dict(id='item:'+str(i), record_id=item_records[i], output=item,
                              match=match, location='items'))
        cards = {r['record_id']: r for r in trace.get('review_records', [])
                 if r.get('can_add_task') and r['record_id'] not in item_records
                 and r['category'] in ('ambiguous', 'conditional_work')}
        assert set(cards) == set(CARD_MATCHES.get(key, {})), ('new card needs review', key, list(cards))
        for rid, card in cards.items():
            preds.append(dict(id='review:'+rid, record_id=rid, output=card,
                              match=CARD_MATCHES[key][rid], location='review_records'))
        for row in preds:
            match = row.pop('match')
            row['judgment'] = 'valid_optional' if match == 'optional' else 'false_positive' if match is None else 'true_positive'
            row['gold_event_id'] = refs[match]['event_id'] if isinstance(match, int) else None
            row['field_errors'] = ERRORS.get((key, row['id']), [])
            row['reason'] = REASONS.get((key, row['id']), '已逐条对照冻结原文与任务要求，动作、对象和工作范围相符；事实/纪要栏错误不影响此项匹配。')
            row['confirmation'] = next((r for r in trace['review_records'] if r['record_id'] == row['record_id']), None)
        for card in trace['review_records']:
            if card.get('can_add_task') and card['record_id'] not in item_records and card['category'] in ('implicit_need', 'proposal'):
                auxiliary.append(dict(case=key, record_id=card['record_id'], category=card['category'],
                                      description=card['description'], question=card.get('question'),
                                      supported=key != 'probes/CP01', question_correct=key not in ('probes/CP01', 'pairs/P06b')))
        matched = [r['gold_event_id'] for r in preds if r['gold_event_id'] is not None]
        assert len(matched) == len(set(matched)), ('duplicate task match', key)
        missed = [r['event_id'] for r in refs if r['event_id'] not in matched]
        cases.append(dict(case=key, scenario=parent, group=parent.split('/')[0], reference_basis=basis,
                          input_hash=input_hash, result_hash=digest(result), result_file=path.relative_to(folder).as_posix(),
                          technical_status=result['status'], references=refs, predictions=preds, missed=missed))

    def score(subset, items_only=False, require_fields=False):
        expected = sum(len(c['references']) for c in subset)
        predictions = [(c, r) for c in subset for r in c['predictions'] if not items_only or r['location'] == 'items']
        optional = sum(r['judgment'] == 'valid_optional' for c, r in predictions)
        tp = sum(r['judgment'] == 'true_positive' and (not require_fields or not r['field_errors']) for c, r in predictions)
        predicted = len(predictions) - optional
        value = prf(tp, expected, predicted)
        return dict(**value, false_positives=predicted-tp, false_negatives=expected-tp,
                    valid_optional_excluded=optional, total_output_units=len(predictions))

    # Historical task effects use their frozen, observable state/write contract.
    update_cases = []
    for job in manifest['jobs']:
        if job['group'] != 'updates': continue
        key = 'updates/' + job['id']
        checks = read(folder / 'r1' / key / 'assessment.json')['checks']
        selected = {k: v for k, v in checks.items() if k in (
            'statuses', 'dates', 'new_tasks', 'new_due', 'pending', 'no_review', 'review_type',
            'operations', 'only_owner', 'today_visible', 'scope_objects', 'item_count')}
        update_cases.append(dict(case=key, passed=all(selected.values()), checks=selected))
    policy = dict(
        timing='User requested task-first metrics after prediction; original frozen full-output review is unchanged.',
        authorship='assistant source audit; not independent blind human gold',
        unit='One independently assigned work objective; include assigned, conditional and scope-pending real work; exclude mere implicit needs, unadopted proposals, past reports and old-task changes from new-work denominators.',
        output='items plus separate ambiguous/conditional_work cards that retain real work; deduplicate by record_id within each result; also report items-only.',
        matching='Explicit source-reviewed one-to-one match of action, object and actual work scope; wrong scope is FP+FN. Owner/time/commitment fields separate. No keyword or automatic model judging.',
        optional='SV02 optional permission-checking work allowed by frozen semantic label is reported separately, excluded from required-task P/R; it is not counted as a required recall hit.',
        partial='Do not remove partial scenarios. Correct retained tasks count as hits; any missing required tasks still count as FN.',
        sources='Original event labels where available; other task units normalized from frozen source, rules and semantic expectations after prediction. No gold rewritten in old manifest.',
        excluded_noise='All implicit_need/proposal cards counted and reviewed in auxiliary_cards, including CP01 false need and P06b wrong question.')
    report = dict(policy=policy, manifest_hash=digest(manifest), source_review_hash=digest(source_review),
                  scenarios=len(manifest['jobs'])+len(manifest['chains']), processing_units=len(cases),
                  new_work=score(cases), items_only=score(cases, items_only=True),
                  new_work_with_fields=score(cases, require_fields=True),
                  matched_task_field_agreement=dict(
                      correct=sum(r['judgment']=='true_positive' and not r['field_errors'] for c in cases for r in c['predictions']),
                      total=sum(r['judgment']=='true_positive' for c in cases for r in c['predictions']),
                      errors=[dict(case=c['case'], prediction=r['id'], errors=r['field_errors']) for c in cases for r in c['predictions'] if r['field_errors']]),
                  by_group={g: score([c for c in cases if c['group']==g]) for g in sorted({c['group'] for c in cases})},
                  core95=score([c for c in cases if c['group']!='semantic']), semantic20=score([c for c in cases if c['group']=='semantic']),
                  historical_update_contract=dict(passed=sum(c['passed'] for c in update_cases), total=len(update_cases), cases=update_cases),
                  structured_field_notes=[dict(case='corpus/C08', field='due_text', issue='as soon as possible只保留在描述，结构化时间字段为空；语义时间保留，字段完整性缺口单列。')],
                  auxiliary_cards=auxiliary,
                  auxiliary_summary=dict(total=len(auxiliary), unsupported=sum(not c['supported'] for c in auxiliary), wrong_question=sum(not c['question_correct'] for c in auxiliary)),
                  cases=cases)
    out = folder/'task-metrics';out.mkdir(exist_ok=True)
    (out/'review-and-score.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    lines = ['# 本轮任务级匹配审计', '', '预测之后按用户要求新增评分视图，旧全输出评分及预测不变。', '',
             '| 场景/处理单元 | 必需任务 | 输出任务（不含有效可选） | TP | FP | FN | 字段错误 |', '|---|---:|---:|---:|---:|---:|---|']
    for c in cases:
        s = score([c]); fields = ', '.join(r['id']+':'+','.join(r['field_errors']) for r in c['predictions'] if r['field_errors'])
        lines.append(f"| {c['case']} | {s['expected']} | {s['predicted']} | {s['hits']} | {s['false_positives']} | {s['false_negatives']} | {fields} |")
    (out/'review.md').write_text('\n'.join(lines)+'\n', encoding='utf8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser();parser.add_argument('--out', type=Path, required=True)
    report = audit(parser.parse_args().out)
    print(json.dumps({k: v for k, v in report.items() if k not in ('cases', 'auxiliary_cards')}, ensure_ascii=False, indent=2))
