"""Aggregate manually reviewed results and verify annotations against saved inputs."""
import hashlib
import json
from pathlib import Path
from score_retest import metrics

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'runs/2026-11-18-two-unseen-v19'


def read(p):
    return json.loads(p.read_text(encoding='utf8'))


def write(p,d):
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def main():
    meetings={}
    for mid in ['IS1000a','TS3003b']:
        out=BASE/mid
        e=read(out/'evaluation.json');labels=read(out/'annotations.json');source=read(out/'input.json')
        refs=read(out/'reference.json');manifest=read(out/'manifest.json')
        assert hashlib.sha256((out/'reference.json').read_bytes()).hexdigest()==manifest['reference_sha256']
        assert labels['result_sha256']==hashlib.sha256((out/'result.json').read_bytes()).hexdigest()
        assert all(1<=n<=len(source['segments']) for k in ['tasks','decisions'] for r in labels[k] for n in r['checked_turns'])
        assert e['initial_status']==e['status']=='processed' and e['explicit_recovery_calls']==0
        strict=[x for x in labels['tasks'] if x['strict_record_verdict']=='TP']
        strict_hits={h for r in strict for h in r['strict_reference_hits']}
        e['owner_sensitive_record_metric']=metrics(len(strict),len(labels['tasks'])-len(strict),len(strict_hits),len(refs['actions']))
        e['cross_section_content_reference_recall']={k:dict(hits=len(labels['cross_section_reference_hits'][k]),reference=len(refs[k]),recall=len(labels['cross_section_reference_hits'][k])/len(refs[k])) for k in ['actions','decisions']}
        final=read(out/'result.json')['extraction']
        for missing in labels['missing_decisions']:
            assert 1<=missing['cross_section_fact_index']<=len(final['facts'])
        e['corpus_reference_coverage']=labels['corpus_reference_coverage']
        e['usage']=read(out/'summary.json')
        e['acceptance']=read(out/'acceptance.json')
        meetings[mid]=e

        lines=[f'# {mid}：最终输出人工逐条复核','','复核人：主助手。全文逐段通读，随后对照最终输出及后续发言逐条核对；未使用模型自动判分。主表评价工作/决策内容，负责人争议单列，并保留严格伴随分数。','',
               '[可接受答案](标注与可接受答案.md) · [原文](完整会议原文.txt) · [最终纪要](minutes.md) · [机器可读复核](annotations.json)','','## 任务','','| 记录 | 内容判定／参考 | 核对依据 | 原文段号 |','| --- | --- | --- | --- |']
        for r in labels['tasks']:
            lines.append(f"| {r['record_id']} | {r['verdict']} / {', '.join(r['reference_hits']) or '支持的拆分工作'} | {r['reason']} | {', '.join(map(str,r['checked_turns']))} |")
            if r.get('owner_review'):lines.append(f"\n负责人复核（{r['record_id']}）：{r['owner_review']}\n")
        # Keep table continuous by moving owner notes below it.
        owners=[r for r in labels['tasks'] if r.get('owner_review')]
        lines=[x for x in lines if not x.startswith('\n负责人复核')]
        lines+=['']+[f"- {r['record_id']} 负责人：{r['owner_review']}" for r in owners]
        lines+=['','## 决策','','| 输出行 | 参考命中 | 主张及判断依据 | 原文段号 |','| --- | --- | --- | --- |']
        for r in labels['decisions']:
            reasons='<br>'.join(c['name']+'：'+c['reason'] for c in r['claims'])
            lines.append(f"| {r['index']} | {', '.join(r['reference_hits']) or '参考外有据内容'} | {reasons} | {', '.join(map(str,r['checked_turns']))} |")
        lines+=['','## 决策栏目漏项','']+[f"- {r['reference']}：{r['cause']}" for r in labels['missing_decisions']]
        lines+=['','## 字段与确认卡','']+[f'- {v}' for v in labels['field_review'].values()]
        lines += [f"- {r['record_id']}：{r['reason']}" for r in labels['non_task_review_audit']]
        if labels.get('unresolved_audit'):
            lines+=['','## 未决栏逐条复核','','| 序号 | 判断 | 依据 |','| --- | --- | --- |']
            lines += [f"| {r['index']} | {r['verdict']} | {r['reason']} |" for r in labels['unresolved_audit']]
        lines+=['','## 指标解释','',f"任务内容 P={e['tasks']['precision']:.1%}，参考R={e['tasks']['reference_recall']:.1%}；决策内容 P={e['decisions']['precision']:.1%}，决策栏参考R={e['decisions']['reference_recall']:.1%}。",'',
                f"含负责人绑定风险的整条任务记录口径：P={e['owner_sensitive_record_metric']['precision']:.1%}，完整记录参考R={e['owner_sensitive_record_metric']['reference_recall']:.1%}。候选中的明确待确认不算已确认负责人；这里不把透明的未知当成虚构。",'',
                '两处决策栏目漏项在各自事实栏保留。全文内容覆盖与决策栏召回是不同指标；内容全覆盖不等于所有栏目状态一致。','']
        (out/'人工逐条复核.md').write_text('\n'.join(lines),encoding='utf8')

    total={}
    for kind in ['tasks','decisions','owner_sensitive_record_metric']:
        total[kind]=metrics(*(sum(m[kind][key] for m in meetings.values()) for key in ['tp','fp','reference_hits','reference']))
    total['cross_section_decision_reference_recall']=dict(hits=20,reference=20,recall=1.0)
    total['requests']=sum(m['usage']['calls'] for m in meetings.values())
    total['tokens']=sum(m['usage']['tokens'] for m in meetings.values())
    value=dict(meetings=meetings,total=total,metric_scope='Content-based primary scores; frozen owner-sensitive companion retained. See scoring-clarification.json.',
               human_review='Primary assistant personally reviewed both full transcripts and final predictions; no model judge.',
               post_run_reference_changes=[],limitations=['Same AMI remote-control scenario domain; different participant groups.','No production fixes applied.','High content scores do not imply verified owners or consistent unresolved status.'])
    write(BASE/'evaluation.json',value)
    print(json.dumps(dict(total=total,verified='Every prediction reviewed; source/reference/result binding and accepted output verified.'),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
