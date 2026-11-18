"""One structural recovery on a copied case, leaving first-pass outputs intact."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.extract import Extractor
from meeting_eval.service import Service
from meeting_eval.store import Store
from scripts.run_action_baseline import write_json

BASE=ROOT/'runs/2026-11-15-full-validation'

def read(p):return json.loads(p.read_text(encoding='utf-8'))

def main():
    p=argparse.ArgumentParser();p.add_argument('group');p.add_argument('case');a=p.parse_args()
    job=next(j for j in read(BASE/'manifest.json')['jobs'] if j['group']==a.group and j['id']==a.case)
    source=BASE/a.group/a.case
    assert read(source/'result.json')['status']=='partial'
    target=BASE/'recovery'/a.group/a.case
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(source,target)
    before={str(p.relative_to(target)) for p in (target/'model').rglob('meta.json')}
    ex=Extractor(ROOT.parent.parent/'meeting-agent/.env',target/'model','context-v1',
        inference_config=read(ROOT/'experiments/action-context/compact-check.json'))
    assert ex.config==read(source/'config.json')
    store=Store(target/'state.sqlite')
    try:
        svc=Service(store,ex)
        r=svc.process(job['meeting'],job['actor'],'2026-11-16T10:02:00+08:00')
        write_json(target/'result.json',r);write_json(target/'tasks.json',store.tasks())
        (target/'minutes.md').write_text(svc.minutes(r['source_id'],job['actor']),encoding='utf-8')
        fresh=[read(p) for p in (target/'model').rglob('meta.json') if str(p.relative_to(target)) not in before]
        summary=dict(group=a.group,case_id=a.case,status=r['status'],items=r['extraction']['items'],
                     errors=r['extraction'].get('_errors'),new_calls=len(fresh),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in fresh))
        write_json(target/'recovery-summary.json',summary)
        print(json.dumps(summary,ensure_ascii=False))
    finally:store.close()

if __name__=='__main__':main()
