"""Run the decision/assignment and history controls through the local Service."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.extract import Extractor
from meeting_eval.service import Service
from meeting_eval.store import Store
from meeting_eval.stage_runner import atomic_json


def run(out):
    source = ROOT/'runs/2026-11-18-decision-action/paired-control'
    first = json.loads((source/'input.json').read_text(encoding='utf8'))
    first.update(started_at='2026-11-18T08:00:00+08:00',account_map={'li':'li'})
    second = dict(first,case_id='annual-fee-change',meeting_id='annual-fee-change',
                  started_at='2026-11-19T08:00:00+08:00',
                  segments=[dict(id='f1',speaker='A',text='沿用首批报名只面向会员的规定。对昨天确定的年费作一项变更，年费从九十九元改为八十九元，即日起按新价执行。')])
    out.mkdir(parents=True,exist_ok=True)
    model = Extractor(ROOT.parent.parent/'meeting-agent/.env',out/'model','context-v5',review_decisions=True)
    store = Store(out/'state.sqlite')
    first_at = '2026-11-18T09:00:00+08:00'
    last_at = '2026-11-19T09:00:00+08:00'
    try:
        svc = Service(store,model)
        for name,meeting,at in [('initial',first,first_at), ('replacement',second,last_at)]:
            result = svc.process(meeting,'evaluator',at)
            atomic_json(out/(name+'.json'),result)
            (out/(name+'.md')).write_text(svc.minutes(result['source_id'],'evaluator'),encoding='utf8')
            requests = len(list((out/'model').rglob('meta.json')))
            before = svc.decisions('control','evaluator',at,history=True)
            again = svc.process(meeting,'evaluator',at)
            assert again['source_id']==result['source_id'] and len(list((out/'model').rglob('meta.json')))==requests
            assert before == svc.decisions('control','evaluator',at,history=True)
            assert result['status']=='processed',result['extraction']['_errors']
        active = svc.decisions('control','evaluator',at)
        history = svc.decisions('control','evaluator',at,history=True)
        tasks = store.tasks()
        atomic_json(out/'storage.json',dict(active=active,history=history,tasks=tasks))
        check_control(svc.decisions('control','evaluator',first_at),active,history,tasks)
    finally:
        store.close()
    reopened = Store(out/'state.sqlite')
    try:
        svc = Service(reopened)
        assert svc.decisions('control','evaluator',last_at) == active
        assert svc.decisions('control','evaluator',last_at,history=True) == history
        assert reopened.tasks() == tasks
    finally:
        reopened.close()


def check_control(initial, active, history, tasks):
    assert len(initial)==len(active)==2 and len(history)==4
    assert len(tasks)==1 and tasks[0]['assignee']=='li'
    rules = [d for d in active if d.get('reaffirms')]
    prices = [d for d in active if d.get('supersedes')]
    assert len(rules)==len(prices)==1
    rule,price = rules[0],prices[0]
    old = {d['id']:d for d in initial}
    assert set(old)=={rule['reaffirms'],price['supersedes']}
    assert all('会员' in d['statement'] and '首批' in d['statement'] for d in (rule,old[rule['reaffirms']]))
    assert any(value in price['statement'] for value in ('89','八十九'))
    assert any(value in old[price['supersedes']]['statement'] for value in ('99','九十九'))
    assert rule['source_id']!=old[rule['reaffirms']]['source_id']
    assert rule['evidence_ids']==price['evidence_ids']==['f1']
    assert {d['id'] for d in history} == set(old) | {rule['id'],price['id']}


def stored_control(out, previous):
    with tempfile.TemporaryDirectory() as temp:
        store = Store(Path(temp)/'copy.sqlite')
        original = sqlite3.connect((previous/'state.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
        try:
            original.backup(store.db)
            svc = Service(store)
            first = svc.decisions('control','evaluator','2026-11-18T09:00:00+08:00')
            at = '2026-11-19T09:00:00+08:00'
            active = svc.decisions('control','evaluator',at)
            history = svc.decisions('control','evaluator',at,history=True)
            tasks = store.tasks()
            atomic_json(out/'storage.json',dict(active=active,history=history,tasks=tasks))
            check_control(first,active,history,tasks)
        finally:
            original.close()
            store.close()


def relation_control(out):
    """Isolate a paraphrase and a similar rule for a different cohort at the reviewed node."""
    model = Extractor(ROOT.parent.parent/'meeting-agent/.env',out/'model','context-v5',review_decisions=True)
    history = [dict(id='prior-eligibility',attribute='报名对象',statement='第一轮申请只接受在籍会员。')]
    turns = [[1,'主持人','第一轮沿用上次的报名办法：没有会员身份的人这一轮不能报。'],
             [2,'主持人','另外，现在确定第二轮也只接受会员申请。两轮分开登记。']]
    topics = [dict(topic='第一轮报名资格',refs=[1]),dict(topic='第二轮报名资格',refs=[2])]
    atomic_json(out/'input.json',dict(turns=turns,topics=topics,history=history))
    claims = model.decision_reviewer.reconcile(turns,topics,[],[],history)
    atomic_json(out/'claims.json',claims)
    assert len(claims)==2
    by_anchor = {r['anchor']:r for r in claims}
    assert by_anchor[1].get('reaffirms')=='prior-eligibility' and not by_anchor[1]['supersedes']
    assert not by_anchor[2].get('reaffirms') and not by_anchor[2]['supersedes']


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('out',type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--relation-only',action='store_true')
    mode.add_argument('--stored',type=Path,metavar='PREVIOUS_RUN')
    args = parser.parse_args()
    if args.stored:
        stored_control(args.out,args.stored)
    elif args.relation_only:
        relation_control(args.out)
    else:
        run(args.out)

