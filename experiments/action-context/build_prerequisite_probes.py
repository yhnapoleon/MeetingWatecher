"""Freeze two authored cancellation contrasts before running the model."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest


def main():
    out=ROOT/'data/context-prerequisites-v1'
    if out.exists():raise ValueError('Frozen data already exists')
    out.mkdir()
    roster=[dict(speaker=s,speaker_name=n,person_ref=p) for s,n,p in
            [('P','主持人','probe_pm'),('L','小林','probe_lin'),('Z','小周','probe_zhou')]]
    specs=[('PF01',[
        ('P','小林，请整理展会报名名单。'),('L','好，我来整理展会报名名单。'),
        ('P','展会取消，报名名单不用整理了。'),('L','收到，不整理名单了。'),
        ('P','小周，取消后需要通知已经报名的人。'),('Z','我来通知这些报名者展会取消。')],
        '通知已报名人员展会取消','probe_zhou','小周',[5,6],
        '报名名单撤回且不追问；取消后的通知工作仍由小周承接，只保留这一任务。'),
        ('PF02',[
        ('P','今天分别安排春季展会和秋季展会的准备工作。'),
        ('L','我会整理春季展会的报名名单。'),('Z','我会整理秋季展会的报名名单。'),
        ('P','春季展会取消，春季的名单不用整理；秋季展会不受影响。'),
        ('L','收到，春季名单不整理了。'),('Z','秋季的名单仍由我整理。')],
        '整理秋季展会报名名单','probe_zhou','小周',[3,4,6],
        '只撤回春季展会工作，秋季同名名单工作由小周继续执行；不得因同名或取消另一活动而关闭。')]
    inputs=[];labels=[];cases=[]
    for cid,turns,desc,owner,name,refs,criterion in specs:
        segments=[dict(id=f'{cid}.s{i}',text=t,**next(p for p in roster if p['speaker']==s)) for i,(s,t) in enumerate(turns,1)]
        inputs.append(dict(case_id=cid,meeting_id=cid,series='synthetic-prerequisite-'+cid,language='zh',
                           source='synthetic_mechanism_check',meeting_date='2026-11-14',participants=roster,segments=segments))
        evidence=[f'{cid}.s{i}' for i in refs]
        labels.append(dict(case_id=cid,event_id=cid+'.1',operation='create',description=desc,owner_ref=owner,
                           owner_kind='corpus_person',owner_label=name,due_text=None,due_date=None,
                           action_anchor=evidence[0],evidence_ids=evidence,required_content=[desc],
                           annotation_status='agent_authored',reason=criterion))
        cases.append(dict(case_id=cid,criteria=[dict(id='selective_cancellation',description=criterion,
                                                    evidence_ids=[s['id'] for s in segments])]))
    for name,rows in [('input',inputs),('labels',labels)]:
        (out/(name+'.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
    manifest=dict(status='frozen',annotation_status='agent_authored',is_blind=False,
                  input_hash=digest(inputs),labels_hash=digest(labels),purpose='Negative controls for over-broad cancellation')
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'behavior.json').write_text(json.dumps(dict(**manifest,version='context-prerequisite-contrast-v1',cases=cases),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Frozen two cancellation contrasts, two expected tasks')


if __name__=='__main__':main()
