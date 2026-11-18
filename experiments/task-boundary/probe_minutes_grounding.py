"""Frozen-candidate test for unsupported predicates and inherited quotation scope."""
from run_full_context_v5 import ROOT,read,write_json,digest
from meeting_eval.minutes_review import MinutesReviewer
from meeting_eval.model_client import ModelClient
import json
import argparse

GUIDANCE='''
先核对原文的陈述，再判断候选是否成立，不要把候选的改写当作原文重述。
动作核对：把复合候选拆成每个主语—谓语—宾语。每个谓语必须有原话表达或明确承接依据；并列名词、省略和“还有某材料”只证明提到材料，不能补成处理、整理、确认、发送等动作。一个子句无依据，整条 content 不能 supported，交给修正保留其余有依据的子句。
引用核对：识别“我听到他们说/有人曾问/举个例子”等外层框架。后续连续转述的问句继承该框架，直到原文明确回到本场发问或采用。语法上的问句、有人关心这个问题、本片段未提供答案，都不能作为 adoption_evidence。转述提问可以记为“某人曾询问”的事实；只有原文明确让本场处理这个问题才进入 unresolved。
reason 应指出原文提供的具体动作或外层引用框架，以及有无本场采用；禁止仅把候选换一种说法当作核验依据。归属核对同样逐分句进行，不把相邻发言人的内容并入一个人的主张。
'''


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--reasoned',action='store_true');args=parser.parse_args()
    base=ROOT/'runs/2026-11-16-context-v5-system-implementation'
    out=base/('minutes-reasoning-probe' if args.reasoned else 'minutes-grounding-probe');out.mkdir(exist_ok=False)
    (out/'guidance.txt').write_text(GUIDANCE,encoding='utf8')
    rows=[]
    for cid in ('C20','C24','P05a'):
        group='pairs' if cid.startswith('P') else 'corpus';src=base/'focus-v1/r1'/group/cid
        request=next(read(p) for p in src.rglob('request.json') if read(p.parent/'meta.json').get('stage')=='check_minutes')
        payload=json.loads(request['messages'][1]['content']);raw=dict(facts=[],unresolved=[])
        for c in payload['candidates']:
            raw['facts' if c['kind']=='fact' else 'unresolved'].append(dict(statement=c['statement'],evidence_ids=[payload['evidence_catalog'][q]['segment_id'] for q in c['evidence']]))
        folder=out/cid;folder.mkdir();client=ModelClient(ROOT.parent.parent/'meeting-agent/.env',folder/'model')
        inference={s:dict(thinking='enabled',reasoning_effort='high',max_tokens=16384) for s in ('check_minutes','check_minutes_repair')} if args.reasoned else {}
        reviewer=MinutesReviewer(client,folder,inference)
        if not args.reasoned:
            for s in ('check_minutes','check_minutes_repair'):reviewer.prompts[s]+=GUIDANCE
        reviewer.config['prompts']={s:digest(v) for s,v in reviewer.prompts.items()}
        write_json(folder/'input.json',dict(payload=payload,raw=raw,source=src.relative_to(ROOT).as_posix(),config=reviewer.config))
        result=reviewer.review(payload['meeting'],raw,payload['read_only_context']);write_json(folder/'result.json',result)
        row=dict(case_id=cid,status=result['trace']['status'],facts=result['facts'],unresolved=result['unresolved'],errors=result['errors'])
        rows.append(row);write_json(out/'progress.json',rows);print(cid,row['status'],flush=True)
    write_json(out/'summary.json',rows)


if __name__=='__main__':main()
