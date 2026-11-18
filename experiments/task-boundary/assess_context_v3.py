"""Observable focused contracts; semantic source review is recorded separately."""
import argparse
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'runs/2026-11-15-context-v3'


def read(p):return json.loads(p.read_text(encoding='utf8'))


def assess(folder):
    s=read(folder/'summary.json');name=s['case']
    items=s['items'] or [];reviews=s['reviews'] or [];updates=s['updates'] or []
    checks=dict(no_pipeline_error=not s['errors'],no_unresolved=not any(r['category']=='interpretation_unresolved' for r in reviews),
                no_finding=not s['findings'],repair_valid=s['repair']!='failed')
    expected={'M2':(0,0),'positive':(1,0),'C20':(1,1),'P07b':(1,0),'G-reference':(0,1),
              'G-manuscript':(2,2),'G-same-segment':(1,1),'C19':(1,1),'C23':(1,1),
              'HT04':(0,1),'CP01':(1,0),'CP05':(0,0),'CP06':(0,1),'CP07':(1,0)}
    checks['counts']=(len(items),len(reviews))==expected[name]
    if name in ('M2','positive','G-same-segment'):
        checks['old_task_done']=len(updates)==1 and (updates[0].get('status')=='done' or updates[0].get('changes',{}).get('status')=='done')
    else:checks['no_update']=not updates
    if name in ('positive','P07b','CP01','CP07'):
        checks['accepted_creation']=len(items)==1 and items[0]['operation']=='create'
    if name in ('C19','C23','C20','G-manuscript'):
        checks['only_owner_review']=all(r['missing_fields']==['owner'] for r in reviews)
        checks['candidate']=all(i['operation']=='candidate' for i in items)
    if name=='G-reference':
        checks['specific_choice']=len(reviews)==1 and bool(set(reviews[0]['missing_fields'])&{'reference','scope'})
    if name=='G-same-segment':
        checks['accepted_not_invented']=len(items)==1 and items[0]['operation']=='candidate' and len(reviews)==1 and reviews[0]['missing_fields']==['commitment']
    if name=='HT04':
        checks['only_relation_review']=len(reviews)==1 and reviews[0]['missing_fields']==['relation'] and not reviews[0]['can_add_task']
        checks['two_authorized_choices']=len(reviews)==1 and {r['guid'] for r in reviews[0].get('relation_options',[])}=={'H-HT04','H-HT04-other'}
    if name=='CP06':checks['implicit_need']=len(reviews)==1 and reviews[0]['category']=='implicit_need'
    return dict(case=name,checks=checks,observable_passed=all(checks.values()),
                source_summary=str((folder/'summary.json').relative_to(ROOT)).replace('\\','/'),
                semantic_review='pending',items=items,reviews=reviews,errors=s['errors'])


def main():
    p=argparse.ArgumentParser();p.add_argument('batches',nargs='+');args=p.parse_args()
    for batch in args.batches:
        folder=BASE/batch;rows=[assess(p.parent) for p in sorted(folder.glob('*/summary.json'))]
        result=dict(kind='observable_contracts_not_semantic_scores',cases=rows,total=len(rows),passed=sum(r['observable_passed'] for r in rows))
        (folder/'contract-review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        print(batch,result['passed'],'/',result['total'],[(r['case'],[k for k,v in r['checks'].items() if not v]) for r in rows if not r['observable_passed']])


if __name__=='__main__':main()
