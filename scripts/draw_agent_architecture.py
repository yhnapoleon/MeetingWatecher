"""Draw the implemented reasoning, orchestration, memory and tool relationships."""
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parts = []


def rect(x, y, w, h, fill, stroke='none', radius=16):
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')


def text(x, y, value, size=25, color='#34445c', weight=400):
    parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}">{escape(value)}</text>')


def line(path, color='#93a3b8', dashed=False, arrow=True):
    parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"'
                 + (' stroke-dasharray="7 6"' if dashed else '')
                 + (' marker-end="url(#arrow)"' if arrow else '') + '/>')


def badge(x, y, label, color, fill, width=68):
    rect(x, y, width, 28, fill, radius=7)
    text(x+10, y+20, label, 18, color, 650)


def node(x, y, w, title, detail, kind='LLM', color='#3560b3', fill='#edf3ff', code=None, height=88):
    rect(x, y, w, height, '#ffffff', '#d8e1ed', 12)
    rect(x, y+17, 4, height-34, color, radius=2)
    text(x+19, y+34, title, 27, '#172a46', 650)
    badge(x+w-83, y+15, kind, color, fill)
    text(x+19, y+65, detail, 22, '#526278')
    if code:
        text(x+19, y+height-17, code, 21, color)


def main():
    parts.clear()
    parts.append('''<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="1510" viewBox="0 0 1800 1510" role="img" aria-labelledby="title desc">
<title id="title">MeetingWatcher Agent 架构</title>
<desc id="desc">整会任务推理与决策核验工作流、会中 LangGraph 三节点编排，以及记忆、恢复和确认执行工具。</desc>
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10Z" fill="#93a3b8"/></marker></defs>
<style>text{font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif}</style>''')
    rect(0, 0, 1800, 1510, '#f3f6fb', radius=0)
    rect(0, 0, 1800, 145, '#14243d', radius=0)
    text(48, 64, 'MeetingWatcher', 42, '#ffffff', 700)
    text(428, 64, 'Agent 架构', 42, '#ffffff', 650)
    text(50, 108, '推理编排 · 证据核验 · 项目记忆 · 工具执行', 25, '#bdcee7')
    badge(1417, 48, 'LLM 推理', '#d7e7ff', '#2b466b', 132)
    badge(1565, 48, '程序节点', '#d4f3ed', '#28534f', 132)
    text(1420, 108, '实线：顺序　虚线：条件路径', 21, '#bdcee7')

    # Full-transcript reasoning workflow: code-native stages, not fictitious personas.
    rect(48, 177, 1008, 905, '#eaf0fa', '#d3deed', 22)
    badge(72, 200, '01', '#3560b3', '#dbe7fb', 50)
    text(138, 225, '整会抽取与核验工作流', 32, '#172a46', 700)
    text(74, 264, 'context-v5 v19  /  DecisionReview v2', 23, '#5b6d86')
    text(116, 311, '任务推理', 24, '#3560b3', 700)
    text(604, 311, '决策核验', 24, '#7555a2', 700)
    text(116, 342, '完整逐字稿 + 人员 + 可见旧任务', 21, '#64758d')
    text(604, 342, '完整逐字稿 + 历史决定', 21, '#64758d')

    ys = [364, 477, 590, 703, 816, 929]
    tasks = [
        ('上下文跟踪', '分块维护实体、线程与工作线索', 'LLM'),
        ('工作解释', '动作 / 对象 / 负责人 / 时间 / 承诺', 'LLM'),
        ('独立核验', '依据是否成立、工作是否遗漏', 'LLM'),
        ('局部修补', '只改指定记录，逐项处理缺口', 'LLM'),
        ('修补复检', '回查原话，关闭或保留异议', 'LLM'),
        ('工作状态归约', '新建 / 进展 / 完成 / 条件 / 待澄清', '程序'),
    ]
    decisions = [
        ('决策草稿', '提取选项、属性与采纳依据', 'LLM'),
        ('独立核验与补漏', '按议题查证，分段扫描遗漏', 'LLM'),
        ('采纳裁决', '对照草稿、独立结论与原话', 'LLM'),
        ('散会状态复核', '后文是否撤回、质疑或重开', 'LLM'),
        ('主张归并', '去重，区分包含与互补关系', 'LLM'),
        ('决定版本管理', 'reaffirms 重申 / supersedes 替代', '程序'),
    ]
    for rows, x, color, fill in [(tasks,116,'#3560b3','#edf3ff'), (decisions,604,'#7555a2','#f1ecfa')]:
        for i, ((title, detail, kind), y) in enumerate(zip(rows,ys)):
            if i:
                line(f'M{x+209} {ys[i-1]+88} V{y-3}', dashed=(rows is tasks and i==3))
            node(x,y,420,title,detail,kind,color,fill)
    # Successful first checks bypass both repair calls; bounded correction, no invented loop.
    line('M116 634 H86 V973 H112', dashed=True)
    rect(62, 762, 48, 86, '#eaf0fa', radius=0)
    text(74, 793, '通', 21, '#64758d')
    text(74, 824, '过', 21, '#64758d')
    text(348, 701, '有缺口', 18, '#64758d')
    text(116, 1054, '独立分支：事实 / 未决问题提取', 22, '#64758d')
    text(604, 1054, '各阶段保留原话、结论和错误记录', 22, '#64758d')

    # Actual StateGraph is retrieve -> generate -> persist.
    rect(1088, 177, 664, 905, '#eaf5f2', '#cfe3dc', 22)
    badge(1112, 200, '02', '#267663', '#d5ece4', 50)
    text(1178, 225, '会中助手 Agent', 32, '#172a46', 700)
    text(1114, 264, 'LangGraph StateGraph · retrieve → generate → persist', 22, '#52796e')
    rect(1114, 290, 612, 61, '#dbeee7', radius=12)
    text(1135, 329, '触发：新增稳定转写 / 用户文字请求', 26, '#246b59', 600)
    line('M1420 351 V373')

    node(1114,377,612,'retrieve · 构建上下文','自动：约 12 秒窗口 + 现有议题 + 任务',
         '混合','#267663','#e4f3ed',height=164)
    text(1133,474,'文字：模型调用 search_evidence 检索',23,'#526278')
    text(1133,510,'研究模式：search_sources → read_source',23,'#526278')
    line('M1420 541 V575')
    node(1114,579,612,'generate · 生成与校验','模型输出 Answer、summary_changes、work_changes',
         '混合','#267663','#e4f3ed',height=164)
    text(1133,676,'程序检查引用、人员、ID 和本轮新增依据',23,'#526278')
    text(1133,712,'增量 JSON 语法失败 → 一次格式修复',23,'#526278')
    line('M1420 743 V777')
    node(1114,781,612,'persist · 保存 Agent 产物','LiveSummary：同一议题原位补充、保留版本',
         '程序','#267663','#e4f3ed',height=164)
    text(1133,878,'WorkLedger：自动与文字入口共用候选',23,'#526278')
    text(1133,914,'Artifacts：比较表 / 清单 / 简报及修改版本',23,'#526278')
    rect(1114,967,612,89,'#ffffff','#cfe3dc',12)
    text(1133,1001,'运行状态  State',24,'#246b59',650)
    text(1133,1036,'context → result → artifact；AG-UI 发送步骤事件',22,'#526278')

    # Infrastructure is expressed in terms of agent memory and effectful tools.
    line('M552 1082 V1105')
    line('M1420 1082 V1105')
    text(70,1137,'工作流依赖：记忆读取、状态保存与确认执行',25,'#172a46',650)
    cards = [(48,552),(624,552),(1200,552)]
    for x,w in cards:
        rect(x,1160,w,281,'#ffffff','#d3deed',18)
    text(72,1208,'项目记忆与证据',29,'#172a46',700)
    text(72,1251,'Memory / Service / WorkLedger',24,'#3560b3',600)
    text(72,1294,'原话引用 · 人员 · 议题版本 · 历史决定',23)
    text(72,1334,'已确认任务 GUID · 进展与确认快照',23)
    text(72,1383,'按项目、会议、游标与可见范围读取',23,'#64758d')
    text(648,1208,'状态持久化与恢复',29,'#172a46',700)
    text(648,1251,'阶段执行器 / SqliteSaver',24,'#3560b3',600)
    text(648,1294,'整会：已接受阶段缓存 + 分块检查点',23)
    text(648,1334,'会中：作业 / 节点检查点 / 事件日志',23)
    text(648,1383,'恢复失败阶段，复用已验证的上游结果',23,'#64758d')
    text(1224,1208,'任务工具与人工确认',29,'#172a46',700)
    text(1224,1251,'会中候选 → 用户确认 → Service',24,'#267663',600)
    text(1224,1294,'创建任务 / 按原 GUID 更新 / 幂等确认',23)
    text(1224,1334,'写入本地任务模拟器，保存确认快照',23)
    text(1224,1383,'后续会议读取同一任务及其最新进展',23,'#64758d')
    text(48,1482,'代码对应  meeting_eval/context_v5.py · decision_review.py   |   meeting_copilot/jobs.py · live_summary.py · work.py',21,'#64758d')
    parts.append('</svg>')
    (ROOT/'docs/images/architecture.svg').write_text('\n'.join(parts),encoding='utf-8')


if __name__ == '__main__':
    main()
