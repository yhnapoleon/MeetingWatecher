"""Primary assistant's manual source review. No model judges or network calls."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'runs/2026-11-18-two-unseen-v19'


def write(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def task(rid, hits, reason, turns, **kwargs):
    return dict(record_id=rid, verdict='TP', reference_hits=hits, reason=reason,
                checked_turns=turns, **kwargs)


def decision(index, hits, claims, turns, **kwargs):
    return dict(index=index, reference_hits=hits,
                claims=[dict(name=name, verdict='TP', reason=reason) for name, reason in claims],
                checked_turns=turns, **kwargs)


LABELS = {
    'IS1000a': dict(
        tasks=[
            task('R16', ['T1', 'T2'],
                 '370–377段确有一般设计与技术功能设计分派，输出保留两种工作及灵活设计要求，按工作内容可同时命中。C紧邻回应Yeah,sure使其承接并非凭空捏造，但文本连续you不足以证实两份职责均归C；原角色/AMI分别指向UI与ID。主分计内容正确，负责人字段保留争议；含负责人绑定的严格伴随评分不通过本条。',
                 [294, 295, 305, 370, 372, 373, 375, 376, 377, 388],
                 owner_review='两份职责合并后全绑定C不可靠。应拆分UI一般设计/ID技术设计，或显式待确认；不能宣称负责人验证通过。',
                 strict_record_verdict='FP', strict_reference_hits=[]),
            task('R15', ['T3'],
                 '337、340及378–382段明确要求思考用户需求和互联网取舍，描述受支持。原文you two/you and you指代含混，输出保留组且以candidate/承接确认呈现，可接受；不强行要求已定位到Anna才算工作内容召回。',
                 [337, 340, 378, 379, 381, 382, 388],
                 owner_review='任务内容正确，人员尚未落实；原AMI营销角色未被结构化定位。',
                 strict_record_verdict='TP', strict_reference_hits=['T3'])],
        decisions=[
            decision(1, ['D8'], [('功能、概念、详细设计阶段', '63–67段主持人说明三个阶段，并说后续阶段同样开会讨论。')], [63, 64, 65, 66, 67]),
            decision(2, ['D7'], [('原创、时尚、易用的设计目标', '60–62段提出，271段再次作为讨论前提。按一组产品设计目标计，不按每个形容词增加TP。')], [60, 61, 62, 271]),
            decision(3, [], [('使用共享文件夹与白板开展协作和会中熟悉', '51–54、76–88段有工具安排并实际试用。可以算操作性安排；没有把会中练习变为会后任务，也没有声称已掌握共享文件夹。')], [51, 54, 76, 78, 79, 82, 83, 84, 88, 238], routing_issue='操作性安排，可放流程/事实，不算虚构'),
            decision(4, ['D1', 'D2'], [('售价约25欧元', '243段明确目标售价，输出保留约数。'), ('生产成本上限12.5欧元', '255段明确maximal，输出最高12.50正确。')], [243, 247, 255, 256, 257]),
            decision(5, ['D3'], [('利润目标5000万欧元', '251段profit aim，未写成已实现利润。'), ('销量目标约400万台', '259、263段计算并获265–267回应。结合利润目标语境，输出以实现利润可接受，不解释为会计学普遍盈亏平衡公式。')], [251, 259, 263, 265, 266, 267, 268]),
            decision(6, ['D5', 'D6'], [('电视遥控应用范围', '281–283段确认电视应用，输出也明说电视遥控器。'), ('基础电视控制功能方向', '274–287、323–324、356–358段支持开关、频道、音量、图文电视的功能方向。359段延期的是具体按钮方案，输出未断言实体按钮布局已最终锁定；因此不按措辞边界判FP。')], [274, 276, 281, 283, 287, 320, 323, 324, 347, 356, 358, 359]),
            decision(7, [], [('预算内舍弃过分花哨功能', '348–349段主持人直接提出取舍。没有无限扩张成永久禁止互联网等一切高级功能。')], [333, 340, 347, 348, 349, 378, 381])],
        missing_decisions=[dict(reference='D4', cause='分段扫描已发现目标市场区域，最终裁决未保留；事实第7条准确保留欧洲/北美及可能的亚洲。', cross_section_fact_index=7)],
        missing_tasks=[],
        non_task_review_audit=[dict(record_id='R8', verdict='合理保留需求', reason='133–135段对有线设备不便的抱怨/下项目建议无具体承接；implicit_need且can_add_task=false正确。')],
        corpus_reference_coverage=dict(
            actions=dict(full=['T1', 'T2', 'T3'], partial=[], note='工作内容覆盖；不代表原AMI三个人员绑定均恢复。'),
            decisions=dict(full=['D1', 'D2', 'D4'], partial=['D3', 'D5'],
                           note='原D3含利润和国际市场，决定栏只有前者；原D5有完整必要按钮及record，输出仅核心功能方向。不能把重注后的7/8直接写成原AMI召回。')),
        cross_section_reference_hits=dict(actions=['T1', 'T2', 'T3'], decisions=[f'D{i}' for i in range(1,9)]),
        field_review=dict(date='due_date均为null；下次会议/30分钟后有原文支持，未伪造日历日期。',
                          owner='R16合并职责绑定不可靠；R15保留组并请求承接确认。内容覆盖3/3，不等于3项均已定位负责人。')),
    'TS3003b': dict(
        tasks=[
            task('R3', ['T4'], '9段承诺记录，398段明确I will put the minutes in project document folder。会后归档动作、A负责人均正确。', [9, 398], strict_record_verdict='TP', strict_reference_hits=['T4']),
            task('R13', ['T3'], '309–313段建议研究老年人额外需求，374段本人说I would have to look into that a little more。合并为继续调研可接受，D归属正确，未扩写成已完成报告。', [309, 310, 311, 312, 313, 358, 369, 370, 374], strict_record_verdict='TP', strict_reference_hits=['T3']),
            task('R14', ['T1'], '398段明示工业设计师做组件概念，C对应ID；candidate保留承接确认不改变任务已被分派这一事实。', [117, 398, 399], strict_record_verdict='TP', strict_reference_hits=['T1']),
            task('R15', ['T2'], '398段明示UI做用户界面概念，B对应UI；趋势观察由R16补齐，合计覆盖重注T2。', [62, 398, 399], strict_record_verdict='TP', strict_reference_hits=['T2']),
            task('R16', [], '398段and the trend-watching确有下一步工作。原句归属有歧义，单列趋势观察并询问负责人属于可接受答案，不因它单列或缺负责人而当作多提；与R15共同覆盖T2，不重复增加参考命中。', [398, 399], strict_record_verdict='TP', strict_reference_hits=[])],
        decisions=[
            decision(1, ['D1'], [('电视专用范围', '128段传达新要求，后文272–274仍作为前提。')], [128, 129, 229, 230, 272, 273, 274]),
            decision(2, ['D2'], [('聚焦60岁以上老年人', '358–371段从40+聚焦真正老年人，374段需进一步调查市场不等于撤销产品方向；60+是合理概括，不机械要求80岁上限。')], [133, 190, 358, 359, 360, 363, 369, 370, 371, 374]),
            decision(3, ['D4'], [('保留teletext', '原131段取消要求已被讨论改变，209–212段无人反对并明确keep。198–199成本条件仍是项目约束，简写保留功能合理；无无限预算承诺。')], [131, 198, 199, 205, 209, 210, 211, 212, 219]),
            decision(4, ['D5'], [('少按钮与简单布局', '220–225确认少按钮，349总结仍保留。'), ('数字键的基本布局方向', '242段说明数字键必要性，258段建议保持熟悉布局，260认可，263承接the numbers。输出不承诺精确总键数，可合理理解为保留数字键方向；后续若过多可再考虑。')], [220, 222, 225, 230, 234, 239, 242, 246, 258, 260, 263, 349]),
            decision(5, ['D6', 'D7'], [('底座设计方向', '293–306段讨论预算后认可底座并把重点放附加功能，349再次列底座。'), ('声音寻物功能', '317–325段明确继续原提议，以声音帮助找到遥控器。'), ('底座充电功能', '49–50段提出的底座包括寻呼和充电，后文整体接受底座、未排除充电。按整体方案采纳可接受，证据没有为其另造工程任务；若只接受逐项重申，单记边界敏感性。')], [49, 50, 293, 294, 295, 301, 304, 305, 306, 317, 318, 324, 325, 349], sensitivity='若必须对充电子功能再次逐项表态，则本行充电主张单独计争议；主口径接受整项方案采纳。'),
            decision(6, ['D8'], [('普通小LCD解释按钮功能', '333–349段以廉价小屏替代昂贵触屏，主持人接受反馈信息并总结LCD；预算核实不抹去已采纳方向。')], [329, 330, 333, 335, 338, 340, 342, 345, 347, 348, 349]),
            decision(7, ['D12'], [('普通塑料等常规材料', '120提议，352–353主持人明确认可默认材料，支持以设计代替昂贵材料投入。')], [120, 121, 122, 352, 353]),
            decision(8, ['D9'], [('时尚外观', '349总结明确fancy design；不等于复杂功能。')], [270, 301, 349]),
            decision(9, ['D10'], [('易于学习', '333说明老年用户需求，349明确easy to learn。')], [43, 333, 349]),
            decision(10, ['D3'], [('体现公司形象', '135段主持人传达明确要求，外观和工作方式均需可见。')], [135])],
        missing_decisions=[dict(reference='D11', cause='草稿已经输出按市场分别适配语言，独立核验因实现未定标open，最终裁决删除；事实第15条仍保留。', cross_section_fact_index=15)],
        missing_tasks=[],
        non_task_review_audit=[],
        corpus_reference_coverage=dict(actions=dict(full=['T1','T2'], partial=[], note='T2由R15用户界面概念与R16趋势观察共同覆盖。'),
                                       decisions=dict(full=[f'D{i}' for i in range(1,11)], partial=[], missing=['D11'], note='原D7后半老年定位由第2行覆盖，声音由第5行覆盖；不重复加独立主张。')),
        cross_section_reference_hits=dict(actions=[f'T{i}' for i in range(1,5)], decisions=[f'D{i}' for i in range(1,13)]),
        field_review=dict(owner='R3/R13负责人正确，R14/R15角色对应正确并保留承接确认，R16负责人明确待确认，不能据此声称5项可无确认执行。',
                          date='均无伪造日历日期；下次会议保留相对期限。'),
        unresolved_audit=[
            dict(index=1, verdict='状态表述偏强', reason='246–263段已倾向熟悉数字布局，条件性再考虑仍可保留；写为整个问题尚未决定与决定第4行不一致。'),
            dict(index=2, verdict='未更新后文', reason='329–330的二选一成本意见后，333–349采用简化小屏并在总结同时列底座与LCD；应写预算待核实，而非仍只在二者间未选择。'),
            dict(index=3, verdict='可接受的剩余核实', reason='344–347仍问成本，349主持人认为可行但没有成本数据；成本核实可保留，须与已选择方向区分。'),
            dict(index=4, verdict='早期替代方案残留', reason='93–111触屏疑虑属实，但335–349已转普通小LCD；不宜继续作为当前必解触屏路线。'),
            dict(index=5, verdict='合理', reason='309–313要求进一步了解老年人的额外需求，与已经选定目标群兼容。'),
            dict(index=6, verdict='合理', reason='374明确继续市场调查；这里写市场判断待核实，未否定老年设计方向。'),
            dict(index=7, verdict='重复且状态偏强', duplicate_of=1, reason='与第1条相同数字键问题。'),
            dict(index=8, verdict='重复并混淆方向与预算', duplicate_of=3, reason='与第3条同一成本缺口，却扩写成是否加入LCD未决定。'),
            dict(index=9, verdict='重复且未更新后文', duplicate_of=2, reason='与第2条同一底座/LCD问题。'),
            dict(index=10, verdict='重复并混淆定位与市场验证', duplicate_of=6, reason='与第6条同一调研依据，却扩写为目标群体未决定。')])}


def main():
    for mid, labels in LABELS.items():
        out=BASE/mid
        labels['result_sha256']=hashlib.sha256((out/'result.json').read_bytes()).hexdigest()
        labels['reviewer']='Primary assistant; personally read full transcript and every final task, decision and review card, with relevant later context. No model judge.'
        labels['metric_scope']='Work-identity/content precision and reference recall; owner/date/review-route quality separately audited. See scoring-clarification.json for frozen strict companion.'
        write(out/'annotations.json',labels)
    write(BASE/'scoring-clarification.json',dict(
        timing='Post-run clarification, explicitly retained alongside frozen pre-run rubric; no input, reference, production or model-output changes.',
        reason='IS1000a merges two real jobs and binds both to C. C has a nearby acceptance, while role/reference mapping separates UI and ID. Content identity can be recalled without treating this ownership binding as verified.',
        main='Content-only task TP/FP and content reference recall, consistent with accepting reasonable source-grounded answers; do not call it full-field accuracy.',
        strict_companion='Apply frozen owner-sensitive record criterion: IS1000a R16 is not accepted as a fully reliable record. R15 remains a supported candidate with explicit confirmation. Report this companion separately rather than silently relaxing the frozen rubric.',
        reference_changes_after_inference=[],
        cross_section='Decision references present only in facts are misses for decision-column recall but recovered for whole-minutes content coverage. Both figures must be labeled.'))
    print('Manual annotations saved; original/frozen references unchanged. Owner-sensitive companion required.')


if __name__=='__main__':
    main()
