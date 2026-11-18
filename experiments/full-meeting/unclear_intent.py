"""Targeted dialogue-intent controls through the Service task branch."""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.extract import Extractor, resolve_calendar_dates
from meeting_eval.context_v3 import reduce_v3
from meeting_eval.inputs import normalize
from meeting_eval.stage_runner import atomic_json
from meeting_eval.service import Service
from meeting_eval.store import Store

AT = '2026-11-18T12:00:00+08:00'
SETTINGS = dict(interpret_work=dict(thinking='enabled',reasoning_effort='low',max_tokens=32768))


class TaskExtractor(Extractor):
    def extract(self, meeting, context, previous=None):
        result = self.evidence_extract(meeting,context,{'items','updates'},bool(previous))
        resolve_calendar_dates(result,meeting)
        return result


def controls():
    cases = {}
    def add(name, lines, expected):
        meeting = dict(meeting_id=name,case_id=name,series=name,started_at=AT,
                       audience=['host','alice'],writers=['host'],
                       roster={'host':'主持人','alice':'李宁'},speaker_map={'H':'host','A':'alice'},
                       account_map={'alice':'alice'},
                       segments=[dict(id=f's{i}',speaker=speaker,text=text)
                                 for i,(speaker,text) in enumerate(lines,1)])
        cases[name] = dict(meeting=meeting,expected=expected)
    add('spoken', [('H','大家对这个方案还有意见要补充吗？'),('A','我等会展示的时候口头补充两点。'),
                   ('H','好的，现在请下一位先展示。')],dict(items=0,clarifications=0,tasks=0))
    add('unclear', [('H','最后还有什么要安排的？'),('A','我之后再补一下。'),
                    ('H','先记下吧，具体补什么、怎么补还没说清楚。')],dict(items=0,clarifications=1,tasks=0))
    add('edit', [('H','谁把今天的结论补进演示稿？'),('A','我来修改演示稿，明早发到项目群。')],
        dict(items=1,clarifications=0,tasks=1))
    add('no_deadline', [('A','我想这份演示稿就由我来改。我会把今天确定的结论补进去。')],
        dict(items=1,clarifications=0,tasks=1))
    add('reference', [('H','这份客户演示稿少了刚才确定的费用表，谁把费用表加进去？'),
                      ('A','我来，稍后加上。')],dict(items=1,clarifications=0,tasks=1))
    add('conditional', [('A','如果预算获批，我就把获批的预算数补进演示稿。目前审批还没结束。')],
        dict(items=1,clarifications=0,tasks=0,conditional=1))
    add('elliptic', [('H','今天就先到这里，你还有什么要说的吗？'),('A','那个我回头再弄一下。'),
                     ('H','好。')],dict(items=0,clarifications=1,tasks=0))
    add('later_clear', [('H','大家还有什么补充？'),('A','我稍后补一下。'),
                        ('H','你是指修改哪份材料？'),
                        ('A','客户演示稿缺了费用表，我会把费用表加进去再发给你。')],
        dict(items=1,clarifications=0,tasks=1))
    prior = ROOT/'runs/2026-11-18-decision-action/ES2002b/input.json'
    meeting = json.loads(prior.read_text(encoding='utf8'))
    cases['R21'] = dict(meeting=meeting,expected=dict(items=4,clarifications_max=1,tasks=0))
    return cases


def run_case(name, case, out):
    folder=out/name
    folder.mkdir(parents=True,exist_ok=True)
    atomic_json(folder/'input.json',case)
    model=TaskExtractor(ROOT.parent.parent/'meeting-agent/.env',folder/'model','context-v5',
                        inference_config=SETTINGS)
    atomic_json(folder/'config.json',model.config)
    store=Store(folder/'state.sqlite')
    try:
        svc=Service(store,model)
        actor='evaluator'
        if name!='R21':
            actor='host'
        result=svc.process(case['meeting'],actor,AT)
        atomic_json(folder/'result.json',result)
        (folder/'minutes.md').write_text(svc.minutes(result['source_id'],actor),encoding='utf8')
        reviews=svc.requirements(result['source_id'],actor)
        tasks=store.tasks()
        trace=result['extraction'].get('_task_trace',{})
        items=result['extraction']['items']
        clarifications=[r for r in reviews if r['category']=='unclear_intent']
        expectations=case['expected']
        checks=dict(processed=result['status']=='processed',items=len(items)==expectations['items'],
                    tasks=len(tasks)==expectations['tasks'],
                    clarifications=len(clarifications)==expectations.get('clarifications',len(clarifications)),
                    no_permission=all(not r['can_add_task'] for r in clarifications))
        if 'clarifications_max' in expectations:
            checks['clarifications_bound']=len(clarifications)<=expectations['clarifications_max']
        if name=='R21':
            forbidden='ES2002b.A.dialog-act.dharshi.9'
            checks['no_R21_task']=all(forbidden not in i['evidence_ids'] for i in items)
            checks['reference_owners']=sorted(i['owner_ref'] for i in items)==sorted(['FEE005','MEE006','MEE007','MEE008'])
        if 'conditional' in expectations:
            checks['condition_preserved']=sum(r['category']=='conditional_work' for r in reviews)==expectations['conditional']
        # Repeat submission must be a durable read, without additional inference.
        with patch.object(model,'extract',side_effect=AssertionError('Duplicate inference')):
            assert svc.process(case['meeting'],actor,AT)==result
        sid=result['source_id']
        atomic_json(folder/'storage.json',dict(reviews=reviews,tasks=tasks))
        summary=dict(checks=checks,passed=all(checks.values()),items=items,reviews=reviews,
                     contexts=trace.get('context_records',[]),errors=result['extraction'].get('_errors',[]))
        atomic_json(folder/'summary.json',summary)
    finally:
        store.close()
    reopened=Store(folder/'state.sqlite')
    try:
        svc=Service(reopened)
        assert svc.result(sid)==result and svc.requirements(sid,actor)==reviews and reopened.tasks()==tasks
    finally:
        reopened.close()
    print(name,summary['passed'],checks,flush=True)
    return summary


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('out',type=Path)
    parser.add_argument('--cases',nargs='+')
    parser.add_argument('--check-disabled',action='store_true')
    parser.add_argument('--audit-saved',type=Path)
    args=parser.parse_args()
    if args.audit_saved:
        audit_saved(args.audit_saved,args.out)
        return
    if args.check_disabled:
        SETTINGS['check_work']=dict(thinking='disabled',temperature=0,max_tokens=16384)
    cases=controls()
    if args.cases:
        cases={name:cases[name] for name in args.cases}
    args.out.mkdir(parents=True,exist_ok=True)
    plan=dict(scope='Service task branch, fresh tracking/interpret/check, no facts/decisions/minutes model branches',
              settings=SETTINGS,cases=cases)
    manifest=args.out/'manifest.json'
    if manifest.exists():
        assert json.loads(manifest.read_text(encoding='utf8'))==plan
    else:
        atomic_json(manifest,plan)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs={name:pool.submit(run_case,name,case,args.out) for name,case in cases.items()}
        results={name:job.result() for name,job in jobs.items()}
    metas=[json.loads(p.read_text(encoding='utf8')) for p in args.out.rglob('meta.json')]
    atomic_json(args.out/'summary.json',dict(results=results,requests=len(metas),
        tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in metas)))
    if not all(r['passed'] for r in results.values()):
        raise SystemExit(1)


def audit_saved(source,out):
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf8'))
    checks={}
    for name,case in manifest['cases'].items():
        original=json.loads((source/name/'result.json').read_text(encoding='utf8'))
        extraction=copy.deepcopy(original['extraction'])
        trace=extraction['_task_trace']
        meeting=normalize(case['meeting'],'evaluator' if name=='R21' else 'host')
        pipeline=dict(checked_records=trace['checked_records'],checked_events=trace['checked_events'],
                      coverage_findings=trace.get('coverage_findings',[]),trace=trace)
        reduced=reduce_v3(pipeline,meeting,{'tasks':[]})
        assert reduced['items']==extraction['items']
        assert reduced['review_records']==trace['review_records']
        checks[name]=dict(final_reducer_matches=True)
        if name!='unclear':
            continue
        class Fixed:
            def extract(self,m,c):
                return copy.deepcopy(extraction)
        store=Store(out/'clarification.sqlite')
        try:
            svc=Service(store,Fixed())
            saved=svc.process(case['meeting'],'host',AT)
            sid=saved['source_id']
            rid=svc.requirements(sid,'host')[0]['record_id']
            decision=dict(decision='clarify_and_add_task',description='把费用表补进客户演示稿并发到项目群。',
                          owner_ref='alice')
            try:
                svc.resolve_requirement(sid,rid,'host',dict(decision,decision='add_task'),AT)
            except ValueError:
                pass
            else:
                raise AssertionError('Direct task creation must require clarification')
            resolved=svc.resolve_requirement(sid,rid,'host',decision,AT)
            assert svc.resolve_requirement(sid,rid,'host',decision,AT)==resolved
            assert len(store.tasks())==1
            atomic_json(out/'clarification.json',dict(resolution=resolved,tasks=store.tasks()))
            (out/'clarification.md').write_text(svc.minutes(sid,'host'),encoding='utf8')
        finally:
            store.close()
        reopened=Store(out/'clarification.sqlite')
        try:
            assert Service(reopened).resolve_requirement(sid,rid,'host',decision,AT)==resolved
            assert len(reopened.tasks())==1
        finally:
            reopened.close()
        checks[name]['clarification_created_once']=True
    atomic_json(out/'audit.json',checks)


if __name__=='__main__':
    main()
