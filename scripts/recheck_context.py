"""Ablate only checking on one frozen context request; no regeneration upstream."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from meeting_eval.model_client import ModelClient
from meeting_eval.inputs import digest,normalize
from meeting_eval.task_events import canonical_checks
from meeting_eval.context_state import check_records,reduce_context
from scripts.run_action_baseline import write_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-run',type=Path,required=True)
    p.add_argument('--case',required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--env-file',type=Path,default=ROOT.parent.parent/'meeting-agent/.env')
    p.add_argument('--thinking',choices=('enabled','disabled'),required=True)
    p.add_argument('--prompt-file',type=Path,help='Optional isolated prompt ablation; upstream payload stays frozen')
    p.add_argument('--attempt',choices=('first','last'),help='Explicitly select a saved check request when the run includes retries')
    a=p.parse_args();matches=[]
    for path in (a.source_run/'model').rglob('request.json'):
        meta=path.with_name('meta.json')
        if not meta.exists() or json.loads(meta.read_text(encoding='utf-8')).get('stage')!='check_work':continue
        request=json.loads(path.read_text(encoding='utf-8'));payload=json.loads(request['messages'][1]['content'])
        if payload['meeting']['case_id']==a.case:matches.append((path,request,payload))
    if len(matches)!=1:
        if not matches or not a.attempt:raise ValueError('Select a run with exactly one check request or name --attempt')
        matches.sort(key=lambda x:x[0].as_posix())
        matches=[matches[0] if a.attempt=='first' else matches[-1]]
    path,request,payload=matches[0]
    a.out.mkdir(parents=True,exist_ok=True)
    prompt=a.prompt_file.read_text(encoding='utf-8') if a.prompt_file else request['messages'][0]['content']
    config=dict(source_request=str(path.resolve()),source_hash=digest(request),thinking=a.thinking,max_tokens=request['max_tokens'],prompt_hash=digest(prompt))
    config_path=a.out/'config.json'
    if config_path.exists() and json.loads(config_path.read_text(encoding='utf-8'))!=config:raise ValueError('Use a new output directory')
    write_json(config_path,config)
    settings=dict(thinking=a.thinking,temperature=0 if a.thinking=='disabled' else 1,max_tokens=request['max_tokens'])
    if a.thinking=='enabled':settings['reasoning_effort']=request.get('reasoning_effort','high')
    client=ModelClient(a.env_file,a.out/'model')
    raw=client.call(prompt,payload,'check_work',inference=settings)
    write_json(a.out/'check.raw.json',raw)
    catalog=payload['evidence_catalog']
    def expand(refs):
        if not isinstance(refs,list) or any(not isinstance(ref,str) or ref not in catalog for ref in refs):raise ValueError('Unknown evidence')
        return [catalog[ref] for ref in refs]
    for row in raw['checks']:
        for field in row['fields'].values():field['evidence']=expand(field['evidence'])
    for row in raw['record_checks']:row['evidence']=expand(row['evidence'])
    raw['uncovered_spans']=expand(raw['uncovered_spans'])
    m=normalize(payload['meeting'],'evaluator')
    checked=canonical_checks(raw,payload['events'],m)
    records=check_records(raw['record_checks'],payload['records'],m)
    result=reduce_context(checked['checked_events'],checked['uncovered_spans'],records,m,payload['history'])
    write_json(a.out/'result.json',dict(**checked,checked_records=records,proposals=result))
    print(json.dumps(dict(items=result['items'],review_records=result['review_records']),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
