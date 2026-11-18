"""Offline counterfactual checks of saved failures; no model or production edits."""
import copy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from meeting_eval.context_protocol_v5 import expand_checks
from meeting_eval.context_state import canonical_ledger

BASE=ROOT/'runs/2026-11-16-context-v5-failure-analysis'
def read(p):return json.loads(p.read_text(encoding='utf8'))
def failure(call):
    try:call()
    except ValueError as e:return str(e)
    return None

def request_for(folder,stage,raw=None):
    for meta in (folder/'model').rglob('meta.json'):
        if read(meta).get('stage')!=stage or not meta.with_name('response.json').exists():continue
        response=read(meta.with_name('response.json'))
        try:value=json.loads(response['choices'][0]['message']['content'])
        except (KeyError,json.JSONDecodeError):continue
        if raw is not None and value!=raw:continue
        req=read(meta.with_name('request.json'))
        payload=json.loads(next(m['content'] for m in req['messages'] if m['role']=='user'))
        return payload,value,req['response_format'],str(meta.parent.relative_to(BASE))
    raise AssertionError('No matching model response: '+str(folder))

def main():
    results=[]
    for key in ['r1/probes/CP02','r1/updates/HT06','r2/updates/HT06']:
        folder=BASE/'cases'/key;payload,raw,fmt,path=request_for(folder,'check_repair')
        allowed=set(payload['output_schema']['properties']['record_checks']['properties'])
        extra=set(raw['record_checks'])-allowed
        # These three fields were added after the production binding was computed.
        binding_payload={k:v for k,v in payload.items() if k not in ('scope','output_schema','output_contract')}
        before=failure(lambda:expand_checks(raw,binding_payload,True));fixed=copy.deepcopy(raw)
        for rid in extra:del fixed['record_checks'][rid]
        after=failure(lambda:expand_checks(fixed,binding_payload,True))
        assert before and extra and after is None
        results.append(dict(case=key,stage='check_repair',before=before,after=after,
            allowed=sorted(allowed),context_record_ids=[r['record_id'] for r in payload['context_records']],
            extra=sorted(extra),response_format=fmt,request_path=path,
            isolated_change='Remove only checks for read-only record IDs in an in-memory copy.',
            limit='Only proves structural rejection cause. Does not validate semantics or fix missed task update.'))
    for key in ['r1/cancellation/PF02','r2/corpus/C14','r2/probes/CP07']:
        folder=BASE/'cases'/key
        vf=next(p for p in (folder/'model').rglob('validation-failure.json') if 'track_context' in p.parts)
        raw=read(vf)['previous_output'];payload,_,fmt,path=request_for(folder,'track_context',raw)
        meeting=payload['meeting'];previous=payload['previous'];fixed=copy.deepcopy(raw)
        before=failure(lambda:canonical_ledger(raw,meeting,previous));changes=[]
        texts={s['id']:s['text'] for s in meeting['segments']};positions={s['id']:i for i,s in enumerate(meeting['segments'])}
        if key.endswith('C14'):
            for thread in fixed['threads']:
                old=[positions[x['after_segment']] for x in thread['updates']]
                thread['updates'].sort(key=lambda x:positions[x['after_segment']])
                new=[positions[x['after_segment']] for x in thread['updates']]
                if old!=new:changes.append(dict(thread_id=thread['thread_id'],before=old,after=new))
        else:
            def visit(x):
                if isinstance(x,dict):
                    if 'quote' in x and 'segment_id' in x:
                        text=texts[x['segment_id']];quote=x['quote']
                        if 'start' in x and text[x['start']:x['end']]!=quote:
                            changes.append(dict(before=quote,after=text[x['start']:x['end']],segment_id=x['segment_id']))
                            x['quote']=text[x['start']:x['end']]
                        elif quote not in text:
                            changes.append(dict(before=quote,after=text,segment_id=x['segment_id'],matches=0))
                            x['quote']=text
                    for value in x.values():visit(value)
                elif isinstance(x,list):
                    for value in x:visit(value)
            visit(fixed)
        after=failure(lambda:canonical_ledger(fixed,meeting,previous))
        assert before and changes and after is None,(key,before,after)
        results.append(dict(case=key,stage='track_context',before=before,after=after,changes=changes,
            request_path=path,limit='In-memory diagnostic change passes ledger validation only; not a proposed permissive production fix or end-to-end pass.'))
    output=dict(network_calls=0,production_changes=0,original_artifacts_modified=False,checks=results)
    (BASE/'offline-boundary-checks.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(output,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
