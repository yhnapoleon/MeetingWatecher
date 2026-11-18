"""Freeze the reported failure and contrast cases before making new model calls."""
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest
from scripts.run_action_baseline import write_json

OUT=ROOT/'experiments/history-time'
SOURCE=ROOT/'runs/2026-11-14-context-prerequisites/guarded-replay/model/ea192c9e8826200bfd0592d6486eee459ff2ae55e1319eab204ac2707887762e'

def main():
    if (OUT/'fixtures.json').exists():raise ValueError('Frozen fixtures already exist')
    request=json.loads((SOURCE/'request.json').read_text(encoding='utf-8'))
    payload=json.loads(request['messages'][1]['content'])
    raw={**payload['meeting'],'audience':['host','chen'],'writers':['host'],
         'account_map':{'host':'host','chen':'chen'}}
    old=payload['history']['tasks'][0]
    task={k:v for k,v in old.items() if k!='owner_ref'}
    task.update(assignee='chen',series=raw['series'],readers=['host','chen'],writers=['host','chen'],origin='shared_tasklist')
    cases=[dict(id='M2',meeting=raw,tasks=[task],expected=dict(statuses={task['guid']:'done'},new_tasks=0,pending=True),
                meaning='本人完成旧工作，旧期限保持；范围调整仍待负责人')]
    def add(cid,turns,status='open',expected='open',duplicate=False,new_tasks=0,pending=False,new_due=None):
        meeting={**copy.deepcopy(raw),'case_id':cid,'meeting_id':cid,'source':'synthetic_history_time_contrast'}
        meeting['segments']=[dict(id=f'{cid}.{i}',speaker=raw['roster'][who],speaker_name=raw['roster'][who],
                                  person_ref=who,text=text) for i,(who,text) in enumerate(turns,1)]
        t={**copy.deepcopy(task),'status':status,'guid':'H-'+cid}
        ts=[t]
        if duplicate:ts.append({**copy.deepcopy(t),'guid':'H-'+cid+'-other'})
        cases.append(dict(id=cid,meeting=meeting,tasks=ts,expected=dict(statuses={t['guid']:expected for t in ts},
                    new_tasks=new_tasks,pending=pending,new_due=new_due),meaning=turns[-1][1]))
    add('HT02',[('chen','上周说的三个登录失败案例我已经整理好并发到研发群了。')],expected='done')
    add('HT03',[('chen','上周已完成的三个登录失败案例整理任务发现漏项，请重新打开，我继续补齐。')],status='done',expected='open')
    add('HT04',[('chen','上周说的那项登录失败案例整理任务，我已经做完并发群了。')],duplicate=True,pending=True)
    add('HT05',[('host','陈可的三个登录失败案例已经整理好发到研发群了，他今天不在。')],pending=True)
    add('HT06',[('chen','上周三个登录失败案例我已经发到研发群了。另外我会整理这次支付失败的两个案例，2026年11月20日下班前发到支付群。')],expected='done',new_tasks=1,new_due='2026-11-20')
    add('HT07',[('chen','三个登录失败案例还没整理完，截止时间改到2026年11月20日，我会在那天下班前发到研发群。')],pending=True)
    add('HT08',[('chen','上周三个登录失败案例还没整理好，也没有发到研发群，目前只完成了一个。')],pending=True)
    write_json(OUT/'fixtures.json',dict(annotation_status='agent_authored',is_blind=False,cases=cases))
    prompt=(ROOT/'prompts/interpret-work-context-v1.txt').read_text(encoding='utf-8')
    (OUT/'baseline.txt').write_text(prompt,encoding='utf-8')
    addition='''
历史任务与本次事件的时间分开：history.tasks 中的 due_date/due_text 是已保存的任务属性，不是本次发言的新证据。event.time 只记录本次会议明确说出的时间；不能把历史截止日期抄入 event.time，也不能将历史摘要里的“本周五”等相对词按本次会议日期重新计算。
汇报旧任务完成/重新打开时，历史截止日期由原任务保留，无需在事件中重填。本次未提时间就用 {"kind":"unspecified","text":null,"date":null,"evidence":[]}；本次只说完成发生在“今天早上”等时段，可用 work_window 并引用当前原话，不能将完成时刻当成截止日期。work.description 同样不要把历史期限写成本次的新要求。
如果本次明确提出期限或改期，必须保留本次的日期、原话和改变含义，不能用 unspecified 抹掉；任何 deadline 都必须有本次会议的逐字证据。旧任务关联仍需唯一依据，完成/重开仍需当前原话支持。
'''
    (OUT/'current-time.txt').write_text(prompt+addition,encoding='utf-8')
    source=dict(path=str(SOURCE.relative_to(ROOT)),request_hash=digest(request),
                response_hash=digest(json.loads((SOURCE/'response.json').read_text(encoding='utf-8'))),
                retry_response_hash=digest(json.loads((SOURCE/'retry-0001/response.json').read_text(encoding='utf-8'))))
    write_json(OUT/'manifest.json',dict(fixtures_hash=digest(json.loads((OUT/'fixtures.json').read_text(encoding='utf-8'))),
        prompts={v:digest((OUT/(v+'.txt')).read_text(encoding='utf-8')) for v in ('baseline','current-time')},source=source))
    print('Frozen 8 cases and 2 prompt variants')

if __name__=='__main__':main()
