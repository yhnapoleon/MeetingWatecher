"""Human-authored source-first references, frozen before new model inference."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'runs/2026-11-18-two-unseen-v19'


def write(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def ref(identity, text, turns, acceptable, reject, corpus=None, owner=None):
    return dict(id=identity, text=text, evidence_turns=turns, acceptable_answers=acceptable,
                unacceptable_answers=reject, original_reference=corpus, owner=owner)


DATA = {
    'IS1000a': dict(
        actions=[
            ref('T1', '界面设计师准备概括性的设计，保持可增加功能的灵活性。', [294, 305, 370, 372],
                ['一般／初步设计、界面工作设计；可与技术设计合并但要保留职责'], ['明确完整按钮清单已定；改成已完成报告'], 'T1', 'C / MIO050 / Matthew / UI'),
            ref('T2', '工业设计师准备技术功能设计。', [294, 375, 376],
                ['技术功能设计、工作原理设计；职称或人物标识均可'], ['只写会中展示现成材料'], 'T2', 'D / MIO016 / Mael / ID'),
            ref('T3', '营销专家研究用户需求，包括是否需要互联网或基本电视功能。', [295, 306, 340, 378, 381, 382],
                ['用户需求分析；无需逐项列互联网，只要保留需求研究职责'], ['把互联网连接当已决定必做功能'], 'T3', 'A / FIE081 / Anna / ME')],
        decisions=[
            ref('D1', '遥控器售价目标约25欧元。', [243, 247, 348, 349], ['约25欧元或25欧元目标价'], ['生产成本25欧元'], 'D1'),
            ref('D2', '生产成本上限12.5欧元。', [255], ['不超过／最多12.5欧元'], ['必须恰好花12.5欧元；售价12.5欧元'], 'D2'),
            ref('D3', '利润目标约5000万欧元。', [251], ['利润目标／profit aim 50 million'], ['已经获得利润5000万'], 'D3-part-profit'),
            ref('D4', '面向国际市场，主要考虑欧洲和北美。', [252, 254, 268], ['国际市场；欧洲北美为重点；亚洲可选'], ['仅允许欧洲北美；亚洲已强制纳入'], 'D3-part-market'),
            ref('D5', '产品面向电视遥控。', [281, 283, 349, 381], ['电视遥控器／电视应用，后续额外功能仍可研究'], ['此时已确定多设备通用遥控'], 'D4'),
            ref('D6', '保留电视遥控的基础功能方向，如开关、频道与音量；具体按钮留待下次。', [274, 276, 283, 287, 323, 347, 359],
                ['基础电视控制／开关频道音量；可补充录制或teletext的讨论但须区分未定布局', '最终具体按钮清单未定，同时说明基础功能方向'],
                ['已确定不可再改的完整实体按钮清单；必须具备高级PVR/互联网'], 'D5-reannotated'),
            ref('D7', '产品应原创、时尚且易用，预算内正常可靠功能优先。', [60, 61, 271, 347, 349],
                ['原创／差异化、时尚、用户友好；可分列或合并', '普通但好用、预算内避免过分花哨'], ['所有高级功能永久禁止']),
            ref('D8', '按功能、概念、详细设计三个阶段推进。', [63, 65, 66, 67], ['三个阶段及其顺序'], ['把会中白板训练算产品开发阶段'])],
        notes=['原D3一个句子包含利润与国际市场，拆成两个参考单位。',
               '原D5把必要功能写成最终按钮；原文359段明确延期讨论具体按钮，因此重注为基础功能方向，保留“具体未定”。',
               'T1/T2末段you指代依赖角色和原标注：支持按角色归属；不因现场应答声次序反推换人。',
               '白板画动物、调设备、会中发言均非会后待办；无线麦克风是吐槽／建议，没有执行承接。',
               '下次会议30分钟后可作为有据的额外日程事实或决定，不要求凭录制日期捏造硬日历日期。',
               '原文完整通读389段后冻结，未查看任何该会议模型输出。']),
    'TS3003b': dict(
        actions=[
            ref('T1', '工业设计师为下一次会议准备组件概念。', [398, 399], ['组件概念／部件方案'], ['只描述已经展示的工作原理'], 'T1', 'C / MTD0010ID / ID'),
            ref('T2', '界面设计师准备用户界面概念；团队继续趋势观察。', [398, 399],
                ['用户界面概念与trend-watching合并', '界面概念单列，趋势观察单列；末句趋势观察归属含混，不强制把它归给营销人员'],
                ['仅有趋势观察而无界面概念'], 'T2-reannotated', 'B / MTD011UID / UI'),
            ref('T3', '营销人员继续了解老年用户／60至80岁市场需求与可行性。', [309, 310, 312, 313, 358, 369, 370, 374],
                ['调查老年群体需求、市场潜力或定位；可合并趋势调研', '保留需要进一步调查的个人承接'], ['把“我需要进一步了解”写成已经完成调研'], None, 'D / MTD012ME / Freek / ME'),
            ref('T4', '主持人整理／保存本次纪要到项目文档目录。', [9, 398], ['归档／上传会议纪要；记录并保存可合并'], ['只要求当场做口头汇报'], None, 'A / MTD009PM / PM')],
        decisions=[
            ref('D1', '仅针对电视，不做多设备遥控。', [128, 129, 272], ['电视专用'], ['还必须控制DVD音响'], 'D1'),
            ref('D2', '将目标从40岁以上进一步聚焦老年人，约60至80岁，市场还需调研。', [133, 190, 358, 363, 369, 370, 371, 374],
                ['老年用户／60至80岁方向；可明确需验证', '40+范围内聚焦老年人'], ['仍主攻16至45岁；年龄边界已经市场验证'], 'D2'),
            ref('D3', '公司形象应体现在产品设计和使用方式中。', [135], ['体现企业／品牌形象'], ['另开品牌设计项目作为已分派任务'], 'D3'),
            ref('D4', '保留teletext，兼顾成本，服务字幕需求。', [131, 198, 199, 209, 210, 211, 212, 219],
                ['成本可控则保留teletext', '保留teletext／字幕；最后有明确keep，省略早先成本措辞可接受'], ['最终取消teletext；不计成本必须触屏'], 'D4'),
            ref('D5', '保持少按钮、简单易用的总体设计。', [220, 222, 225, 263, 349], ['少按钮／简洁布局；具体数量待定'], ['精确只有2或3键已确定'], 'D5'),
            ref('D6', '采用预算内的底座／docking station。', [293, 294, 295, 301, 304, 305, 306, 349],
                ['底座；设计不过度复杂且成本可行', '底座作为已选择的产品方向'], ['昂贵复杂底座已批准'], 'D6'),
            ref('D7', '提供声音提示帮助找到遗失的遥控器。', [317, 318, 324, 325], ['寻物蜂鸣／声音定位；可与底座合并'], ['声控操作全部电视功能'], 'D7-part-audio'),
            ref('D8', '采用小型普通LCD显示屏，为按键提供说明反馈。', [329, 333, 335, 338, 340, 342, 345, 348, 349],
                ['小LCD／普通信息屏；显示按键说明', '非昂贵触屏的简单信息显示'], ['已确定彩色触摸屏；最终完全取消屏幕'], 'D8'),
            ref('D9', '产品外观时尚。', [270, 301, 349], ['fancy／有吸引力／时尚设计'], ['高科技昂贵材料必选'], 'D9'),
            ref('D10', '产品容易学习使用。', [333, 349], ['易学／降低老年人学习门槛'], ['必须学习复杂滚轮操作'], 'D10'),
            ref('D11', '适配不同语言市场。', [385, 387, 388, 389, 392],
                ['面向不同市场的语言版本／本地化', '支持不同语言'], ['必须增加独立语言切换按钮'], 'D11'),
            ref('D12', '采用常规材料，例如塑料，保持成本合理。', [120, 352, 353], ['常规材料／普通塑料'], ['必须钛合金外壳'])],
        notes=['原D7同时提声音定位和老年人，后半与D2重复，不重复计参考。',
               '新增T3个人继续调查承诺及T4归档纪要；原T2趋势观察归属不够明确，允许合理拆并。',
               '40+硬范围与60至80重点人群兼容，不因进一步调研就断言定位完全未定。',
               '小LCD经过讨论取代昂贵触屏，原先底座与屏幕二选一并非最后状态。',
               '大字幕快捷键有主持人提议和支持，可作为有据额外方向，不能把它当正式分派给某人。',
               '充电底座、RSI、滚轮/摇杆、触屏成本调研最初多为建议或问题，须查后文承接，不能凭建议自动造任务。',
               '原文完整通读404段后冻结，未查看任何该会议模型输出。'])}


def main():
    for mid, data in DATA.items():
        out = BASE / mid
        assert not (out / 'model').exists() and not (out / 'state.sqlite').exists()
        original = out / 'reference-original.json'
        assert not original.exists(), 'Freeze once; revisions must be separately documented'
        original.write_bytes((out / 'reference.json').read_bytes())
        meeting = json.loads((out / 'input.json').read_text(encoding='utf8'))
        meeting['series'] = 'AMI-' + mid[:-1]
        write(out / 'input.json', meeting)
        for kind in ('actions', 'decisions'):
            for row in data[kind]:
                row['evidence_ids'] = [meeting['segments'][n-1]['id'] for n in row['evidence_turns']]
        write(out / 'reference.json', data)
        rubric = dict(
            task_scope='Source-supported future work or accepted personal commitment. Include items and can_add_task cards, deduplicate by record_id.',
            task_prediction_unit='A meaningful task identity. A bundled prediction may hit multiple reference actions without multiplying prediction TP.',
            decision_scope='Source-supported adopted business direction, communicated constraint, or agreed operational decision; separate routing overlap from false content.',
            decision_prediction_unit='Independent content claims, grouping semantically identical claims. Do not change atomization based on correctness.',
            acceptance='Accept semantic paraphrase, reasonable source-grounded implications, conditional adoption, and appropriate bundling. Do not infer owner, hard dates, execution scope or finality beyond evidence.',
            false_positive='Unsupported content, stale/reversed final state, material wrong entity/value/owner, or unaccepted proposal presented as commitment.',
            reference_scope='Human source-first reannotation with acceptable and unacceptable answers, frozen before inference. Original AMI labels preserved; report original coverage separately.',
            review='Primary assistant personally reads full input and each prediction with source context. Corpus/model labels are evidence, not automatic truth.',
            revisions='Any post-run reference correction must retain frozen reference and document source, reason, and effect on metrics in a separate file.',
            technical_retry_policy='Existing automatic recovery plus at most one explicit Service retry batch per meeting for technical failure. Preserve first-attempt outputs. No semantic reruns.',
            no_tuning='Identical v19 production code, prompts, model and inference to prior retest; two independent empty histories.')
        write(out / 'rubric-before-run.json', rubric)
        manifest = json.loads((out / 'manifest.json').read_text(encoding='utf8'))
        manifest.update(
            input_sha256=sha(out / 'input.json'), reference_sha256=sha(out / 'reference.json'),
            rubric_sha256=sha(out / 'rubric-before-run.json'),
            prior_exposure='No local experiment/document/model-output match before preparation. Only qmsum-tree.json raw filename metadata matched. Different participant groups from prior ES2002 and IB400x, same AMI remote-control scenario domain.',
            selection='First alphabetically in each IS and TS group with >=2 action and >=2 decision sentences, under 40 minutes, no local previous experiment. Selected before inference.',
            annotation_phase='Source-first full transcript read by primary assistant; acceptable answers frozen before inference.',
            limitations=['Two new local meetings in different participant groups, same AMI remote-control scenario domain.',
                         'Human reannotated references, with original AMI reference coverage reported separately.',
                         'Acceptable semantic answers explicitly listed; no multi-rater agreement measured.'])
        write(out / 'manifest.json', manifest)
    write(BASE / 'selection-audit.json', dict(
        meetings=list(DATA), selection='First qualifying unused IS and TS groups alphabetically; >=2 action and decision sentences, under40min.',
        prior_search='rg -l IS1000a|TS3003b across project excluding zip/sqlite/pyc and raw archive. Only data/generalization-v1/raw/qmsum-tree.json matched; filename metadata, not prior inference.',
        scope='Independent full meetings, different cohorts, same scenario domain; not cross-domain generalization.',
        annotation_timing='Both full transcripts read before model inference. Original references preserved and curated references frozen.'))
    print('Frozen IS1000a: 3 tasks/8 decisions; TS3003b: 4 tasks/12 decisions. No model calls.')


if __name__ == '__main__':
    main()
