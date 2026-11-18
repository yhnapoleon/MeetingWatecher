"""Isolated causal probes. Does not change production prompts, labels, or task state."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
import random
import statistics
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))
from meeting_eval.inputs import normalize,digest,dumps
from meeting_eval.extract import model_input,validate_partial,FIELDS
from scripts.run_action_baseline import credentials,read_jsonl,write_json
from scripts.score_mvp_actions import score

CASES=('C02','C03','C09','C20','C21','C26')
VARIANTS=('direct_t0','direct_t1','direct_thinking','events_t0')


def convert_events(raw,meeting):
    refs={s['id']:s['text'] for s in meeting['segments']}
    items,errors=[],[]
    allowed={'assignment','self_commitment','group_commitment','conditional_commitment','suggestion','completed','mention'}
    if not isinstance(raw.get('events'),list):
        return [],[{'error':'Missing events list'}]
    for index,event in enumerate(raw['events']):
        try:
            kind=event['event_kind']
            if kind not in allowed or event.get('accepted') not in (True,False,None):
                raise ValueError('Invalid event classification')
            groups={}
            for group in ('task_evidence','owner_evidence','acceptance_evidence','time_evidence'):
                spans=event[group]
                if not isinstance(spans,list):
                    raise ValueError('Missing evidence list')
                for span in spans:
                    if not span['quote'] or span['quote'] not in refs.get(span['segment_id'],''):
                        raise ValueError('Ungrounded quote in '+group)
                groups[group]=[span['segment_id'] for span in spans]
            if kind in ('suggestion','completed','mention'):
                continue
            if event['anchor'] not in groups['task_evidence']:
                raise ValueError('Anchor lacks task evidence')
            if event['accepted'] is True and kind=='assignment' and not groups['acceptance_evidence']:
                raise ValueError('Accepted assignment lacks acceptance evidence')
            known=event['owner_kind']=='corpus_person' and event.get('owner_ref') in meeting['roster']
            create=known and (kind=='self_commitment' or kind=='assignment' and event['accepted'] is True)
            item={k:event.get(k) for k in ('description','owner_kind','owner_ref','owner_label')}
            item.update(operation='create' if create else 'candidate',action_anchor=event['anchor'],
                evidence_ids=list(dict.fromkeys(e for ids in groups.values() for e in ids)),
                due_text=event.get('due_text') if event['time_kind']=='deadline' else None,
                due_date=event.get('due_date') if event['time_kind']=='deadline' else None)
            items.append(item)
        except (ValueError,KeyError,TypeError,AttributeError) as exc:
            errors.append({'event':index,'error':str(exc),'rejected':event})
    return items,errors


def run_one(case,variant,repeat,out,auth,prompts):
    key,model,endpoint=auth
    folder=out/f'{variant}-r{repeat}'/case['case_id']
    folder.mkdir(parents=True,exist_ok=True)
    meeting=normalize(case,'evaluator')
    thinking=variant=='direct_thinking'
    request=dict(model=model,temperature=1 if variant in ('direct_t1','direct_thinking') else 0,
        max_tokens=8192,response_format={'type':'json_object'},stream=False,
        thinking={'type':'enabled' if thinking else 'disabled'},
        messages=[{'role':'system','content':prompts['events' if variant=='events_t0' else 'direct']},
                  {'role':'user','content':dumps(model_input(meeting))}])
    if thinking:
        request['reasoning_effort']='high'
    path=folder/'request.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=request:
        raise ValueError('Changed request: use new output folder')
    write_json(path,request)
    response_path=folder/'response.json'
    errors=[]
    result={f:[] for f in FIELDS}
    meta={}
    try:
        if response_path.exists():
            response=json.loads(response_path.read_text(encoding='utf-8'))
            meta=json.loads((folder/'meta.json').read_text(encoding='utf-8'))
        else:
            start=time.perf_counter()
            req=urllib.request.Request(endpoint,data=dumps(request).encode('utf-8'),
                headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=120) as stream:
                response=json.load(stream)
            write_json(response_path,response)
            meta=dict(seconds=round(time.perf_counter()-start,3),usage=response.get('usage'),
                model=response.get('model'),fingerprint=response.get('system_fingerprint'),response_id=response.get('id'))
            write_json(folder/'meta.json',meta)
        choice=response['choices'][0]
        if choice['finish_reason']!='stop':
            raise ValueError('Incomplete response: '+choice['finish_reason'])
        raw=json.loads(choice['message']['content'])
        write_json(folder/'parsed.json',raw)
        if raw.get('case_id')!=case['case_id']:
            raise ValueError('Wrong case id')
        if variant=='events_t0':
            result['items'],errors=convert_events(raw,meeting)
        else:
            result['items']=raw.get('items')
        result=validate_partial(result,meeting,{'tasks':[],'decisions':[]},errors)
        errors=result['_errors']
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError) as exc:
        errors.append({'error':type(exc).__name__,'detail':str(exc)[:300]})
    value=dict(case_id=case['case_id'],items=result['items'],errors=errors,meta=meta)
    write_json(folder/'prediction.json',value)
    return variant,repeat,value


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--repeats',type=int,default=2)
    p.add_argument('--env-file',type=Path,default=ROOT.parent.parent/'meeting-agent/.env')
    a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    cases=[c for c in read_jsonl(ROOT/'data/mvp-v1/input.jsonl') if c['case_id'] in CASES]
    prompts={'direct':(ROOT/'prompts/extract-actions-v1.txt').read_text(encoding='utf-8'),
             'events':(ROOT/'experiments/action-architecture/events.txt').read_text(encoding='utf-8')}
    auth=credentials(a.env_file)
    labels=(ROOT/'data/mvp-v1/labels.jsonl').read_text(encoding='utf-8')
    config=dict(cases=cases,variants=VARIANTS,repeats=a.repeats,model=auth[1],endpoint=auth[2],
        prompt_hashes={k:digest(v) for k,v in prompts.items()},labels_hash=digest(labels),
        code_hash=digest(Path(__file__).read_text(encoding='utf-8')),max_tokens=8192,seed=20261114)
    config=json.loads(json.dumps(config))
    cf=a.out/'config.json'
    if cf.exists() and json.loads(cf.read_text(encoding='utf-8'))!=config:
        raise ValueError('Changed experiment configuration')
    write_json(cf,config)
    (a.out/'labels.snapshot.jsonl').write_text(labels,encoding='utf-8')
    for k,v in prompts.items():
        (a.out/(k+'.prompt.txt')).write_text(v,encoding='utf-8')
    jobs=[(c,v,r) for c in cases for v in VARIANTS for r in range(1,a.repeats+1)]
    random.Random(20261114).shuffle(jobs)
    grouped={}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(run_one,c,v,r,a.out,auth,prompts) for c,v,r in jobs]
        for future in as_completed(futures):
            variant,repeat,value=future.result()
            grouped.setdefault((variant,repeat),[]).append(value)
            print(variant,repeat,value['case_id'],'items',len(value['items']),'errors',len(value['errors']),flush=True)
    summary={}
    for variant in VARIANTS:
        rows=[]
        for repeat in range(1,a.repeats+1):
            predictions=sorted(grouped[variant,repeat],key=lambda x:x['case_id'])
            report=score(predictions,'dev',labels=read_jsonl(a.out/'labels.snapshot.jsonl'),inputs=cases,selected_ids=CASES)
            report['failed_cases']=[{'case_id':v['case_id'],'errors':v['errors']} for v in predictions if v['errors']]
            write_json(a.out/f'{variant}-r{repeat}'/'scores.json',report)
            rows.append(dict(anchors=report['action_anchors'],failed=len(report['failed_cases']),
                total_tokens=sum((v['meta'].get('usage') or {}).get('total_tokens',0) for v in predictions),
                mean_seconds=statistics.mean(v['meta'].get('seconds',0) for v in predictions)))
        summary[variant]={'trials':rows,'mean_f1':statistics.mean(r['anchors']['f1'] for r in rows)}
    write_json(a.out/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
