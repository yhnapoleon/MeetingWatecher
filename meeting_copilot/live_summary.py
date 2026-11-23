"""Chronological, evidence-bounded topic updates. No pre-authored summary content."""
import copy
import json

INTERVAL_MS = 12000

OUTPUT_CONTRACT = '''输出必须是可解析的 JSON，不输出 type/json_object 包装字段。必需结构如下（示例只说明字段，不是会议事实）：
{"title":"会中增量纪要","summary":"","sections":[],"columns":[],"rows":[],"questions":[],"impact":null,"summary_changes":[{"id":null,"title":"议题标题","text":"截至新增发言的简明内容","kind":"fact","evidence_ids":["E1"],"category":"discussion","prior_topic_id":null,"relation":"new"}],"work_changes":[]}
没有议题变化时 summary_changes=[]。有工作变化时按上方 work_changes 字段定义填写。每个字段名必须用双引号，不能漏掉 title。正文变化只放 summary_changes，引用必须取自本轮给定的证据。
分类必须反映原话状态：主持人明确规定的产品要求/范围（要求包含什么、忽略什么、必须满足什么）用 decision，不用 discussion；还未确认的想法用 proposal。relation=reaffirmed 必须是上场已经记录的同一具体要求；只有话题相关不算重申，首次出现的限制或要求用 new，明确替换原定范围才用 changed。'''


def latest(storage, scope):
    from .jobs import is_visible
    with storage.connect() as db:
        jobs = [json.loads(r['body']) for r in db.execute(
            "SELECT body FROM jobs WHERE project=? AND status='completed'", (scope['project_id'],))]
    matches = [j for j in jobs if j.get('incremental') and j['kind'] == 'summary'
               and j['scope']['meeting_id'] == scope['meeting_id'] and is_visible(j['scope'], scope)]
    return max(matches, key=lambda j: j['scope']['cursor_ms'], default=None)


def plan(storage, memory, scope):
    prior = latest(storage, scope)
    after = prior['scope']['cursor_ms'] if prior else scope['meeting_start_ms']
    new = [e for e in memory.visible(scope) if e['meeting_id'] == scope['meeting_id'] and e['end_ms'] > after]
    # A slow model or a late-opened view must not collapse the backlog into one final summary.
    boundary = next((e['end_ms'] for e in new if e['end_ms'] >= after + INTERVAL_MS), None)
    meeting_end = next(m['end'] for m in memory.meetings if m['id'] == scope['meeting_id'])
    if boundary is None and new and (scope['cursor_ms'] >= after + INTERVAL_MS or scope['cursor_ms'] >= meeting_end - 1):
        boundary = new[-1]['end_ms']
    return {'ready': boundary is not None, 'cursor_ms': boundary, 'processed_until_ms': after}


def context(storage, memory, work, scope):
    prior = latest(storage, scope)
    previous = prior['result']['live_summary'] if prior else {'cards': []}
    after = prior['scope']['cursor_ms'] if prior else scope['meeting_start_ms']
    all_visible = memory.visible(scope)
    visible = [e for e in all_visible if e['meeting_id'] == scope['meeting_id']]
    new = [e for e in visible if e['end_ms'] > after]
    if not new:
        raise ValueError('暂无新的稳定转写')
    ledger = work.view(scope)
    prior_cards = []
    for archive in scope.get('archives', []):
        if archive['meeting_id'] == scope['meeting_id']:
            continue
        prior_scope = {**scope, 'meeting_id': archive['meeting_id'], 'cursor_ms': archive['cursor_ms']}
        prior_job = latest(storage, prior_scope)
        if prior_job:
            prior_cards.extend(prior_job['result']['live_summary']['cards'])
    # Keep cited history and a short lead-in; the new passage is explicit rather than buried in the full transcript.
    cited = {i for c in previous['cards'] for v in c['history'] for i in v['evidence_ids']}
    cited.update(i for p in ledger['proposals'] for i in p['change']['evidence_ids'])
    cited.update(e['id'] for task in ledger['tasks'] for e in task['evidence'])
    cited.update(i for c in prior_cards for i in c['evidence_ids'])
    lead_in = [e for e in visible if e['end_ms'] <= after][-2:]
    # Tasks shown to the model include their original evidence. Keep those visible
    # archive references in the same citation set as the new speech, so a progress
    # update can legitimately cite its original assignment as well as this report.
    evidence = list({e['id']: e for e in all_visible if e['id'] in cited}.values())
    evidence = list({e['id']: e for e in evidence + lead_in + new}.values())
    return {'evidence': evidence, 'new_evidence_ids': [e['id'] for e in new],
            'new_transcript': new,
            'previous_summary': previous,
            'previous_meeting_cards': [{k:v for k,v in c.items() if k!='history'} for c in prior_cards],
            'coverage': {'requested_start_ms': after, 'requested_end_ms': scope['cursor_ms'],
                         'stable_start_ms': new[0]['start_ms'], 'stable_end_ms': new[-1]['end_ms']},
            'business': {'tasks': ledger['tasks']}, 'meeting_work': ledger, 'roster': memory.roster}


def apply(job, answer, ctx):
    cards = copy.deepcopy(ctx['previous_summary']['cards'])
    known = {c['id']: c for c in cards}
    new_ids = set(ctx['new_evidence_ids'])
    changed = []
    ignored = []
    prior_by_id = {c['id']: c for c in ctx.get('previous_meeting_cards', [])}
    for index, patch in enumerate(answer['summary_changes']):
        cid = patch['id']
        if cid and cid not in known:
            raise ValueError('议题更新引用了不存在的卡片')
        if not new_ids.intersection(patch['evidence_ids']):
            if cid in known:
                # Rephrasing a known card adds no evidence. Keep that card as-is without
                # blocking independent, valid action items extracted from this passage.
                ignored.append({'id': cid, 'reason': 'no_new_evidence'})
                continue
            raise ValueError('议题更新必须引用本次新增发言')
        cid = cid or f"topic-{job['id']}-{index}"
        if cid in changed:
            raise ValueError('同一轮不能重复更新同一议题')
        old = known.get(cid)
        history = copy.deepcopy(old['history']) if old else []
        prior_id = patch.get('prior_topic_id')
        if prior_id and prior_id not in prior_by_id:
            raise ValueError('关联的上场议题不在可见归档中')
        if patch.get('relation', 'new') != 'new' and not prior_id:
            raise ValueError('上场变化必须关联可见的原议题')
        version = {k: patch[k] for k in ('title', 'text', 'kind', 'evidence_ids')}
        version.update(category=patch.get('category','discussion'),prior_topic_id=prior_id,relation=patch.get('relation','new'))
        version.update(cursor_ms=job['scope']['cursor_ms'], job_id=job['id'])
        history.append(version)
        card = {**version, 'id': cid, 'revision': len(history), 'history': history,
                'created_ms': old['created_ms'] if old else job['scope']['cursor_ms']}
        if old:
            cards[cards.index(old)] = card
        else:
            cards.append(card)
        known[cid] = card
        changed.append(cid)
    for change in answer['work_changes']:
        if not new_ids.intersection(change['evidence_ids']):
            raise ValueError('行动项更新必须引用本次新增发言')
    # The displayed prose is built from validated patches, not a second free-form full-page summary.
    active = known[changed[-1]] if changed else (cards[-1] if cards else None)
    answer.update(title=active['title'] if active else '正在听取讨论',
                  summary=active['text'] if active else '',
                  sections=[{k:c[k] for k in ('title','text','kind','evidence_ids')} for c in cards],
                  questions=[], columns=[], rows=[])
    return {'cards': cards, 'changed_ids': changed, 'processed_until_ms': job['scope']['cursor_ms'],
            'previous_meeting_cards': list(prior_by_id.values()),
            'generation': ctx['previous_summary'].get('generation', 0) + 1, 'ignored_changes': ignored}


INSTRUCTION = '''你正在维护随会议推进的议题卡。当前任务是阅读 new_transcript（本次新增发言），把其中新信息记录下来；previous_summary.cards 是已处理过的旧卡片，不要重新概括它们。
返回 summary_changes 数组，每项 {id,title,text,kind,evidence_ids}。只有 previous_summary.cards 中的本场议题可用其完整 id 更新；本场尚未记录的议题必须 id=null，哪怕它重申了上场内容。previous_summary.cards=[] 时所有变化的 id 必须为 null。
每项还含 category（discussion=研究/讨论，decision=明确要求或决定，proposal=方案提议尚未采纳，question=未决问题）、prior_topic_id（previous_meeting_cards 中实际相关的上场卡片完整ID，否则null）、relation（new=本场新增，reaffirmed=重申上场，changed=本场明确改变原范围/要求，questioned=与原记录有差异待核对）。relation=changed仅用于本场明确替换、否定或收窄上场范围，复述同一内容用reaffirmed。STT歧义或内容疑似矛盾而未经澄清时用questioned，category用question，不能替参会者选定一种解释。关联上场不代表本场已经采纳；提议用proposal，不把“可以考虑”写成决定。
previous_meeting_cards 是只读的上场归档，仅用于关联和比较，不能复制它的 id 到更新目标 id，不能把上场全文重新粘贴到本场 text。本场 text 只写本次确认、变化或差异，最多160字。先对照上场判断本场的重申或变化。把不同范围的要求、研究发现和方案提议分开；不能用一张通用汇报卡吞下后来的所有内容。听到研究结论或新方案时必须在 summary_changes 中记录；不能只写到 sections 或 summary，前端不会显示它们。
对同一个方案的提问、理由和后续倾向属于同一张卡，不能按发言人或时间拆卡。但是提出另一种方案时，必须建立独立的 proposal 卡（id=null），不能更新研究汇报卡或旧方案卡。修订时保留仍有效的已有信息，纠正被推翻的内容。
是否重复以已有卡片为准。即使发言人说 recap/重申，若目标人群、价格、功能等具体信息尚未出现在已有卡片，也应首次记录，不能漏掉首次听到的内容。
text 是这张卡截至本次发言的完整简明内容，最多160字；title 不超过16字。每次更新必须引用新增发言，并保留支撑旧事实的引用。
刚提出问题就只记问题；理由尚未出现不能预填；表达倾向不能写为正式决定。仅嗯啊/重复/寒暄时 summary_changes=[]，不能硬凑卡片。
本轮最多3项变化，不重发未变化的卡。普通 sections/columns/rows/questions 留空，summary 留空，title="会中增量纪要"。
如果本次新增发言已转到功能、目标人群等新话题，应创建对应新卡，不能继续复述旧的供电议题。返回前逐条核对：每个变化的 evidence_ids 至少含一个 new_evidence_ids，只有旧证据的卡片不得输出。
主持人安排汇报顺序属于会议议程；成员随后介绍市场研究、用户界面、组件研究等实质内容时，分别进入对应研究议题，不能把研究方法和发现不断拼接到“演示顺序”卡片。同一研究议题内部继续更新原卡。
研究发现也应补充已有任务的进展候选，不让任务详情永远停在“具体发现待后续”这样的过期描述。只要新增发言已经提供事实，就更新对应判断；未明确分工不新建任务。新的方案提议单独成为proposal卡，后续反对理由/风险补入该卡，不埋在某人的研究汇报中。
输出前检查：如果新增发言提出一个具体方案，而已有卡只有研究过程/约束汇报，summary_changes 必须新增一张 category=proposal、id=null 的方案卡。它的 text 只写新方案、当前态度和已出现的顾虑，不复述此前整段研究。
不要把尚未发生的结论、未来目录或归档内容当本场新变化。'''
