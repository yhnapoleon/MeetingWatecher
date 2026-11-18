"""Isolated provider strict-tool experiment; no production acceptance shortcut."""
import json
import time
import urllib.request
import urllib.error
from urllib.parse import urlsplit,urlunsplit
from run_full_context_v5 import ROOT,read,write_json
from meeting_eval.model_client import ModelClient,read_response
from probe_system_recovery import SOURCES


def tool_schema(node):
    keep={'type','properties','required','additionalProperties','items','enum','anyOf','description'}
    out={k:v for k,v in node.items() if k in keep}
    if 'properties' in out:
        out['properties']={k:tool_schema(v) for k,v in out['properties'].items()}
        out['required']=list(out['properties']);out['additionalProperties']=False
    if 'items' in out:out['items']=tool_schema(out['items'])
    if 'anyOf' in out:out['anyOf']=[tool_schema(v) for v in out['anyOf']]
    return out


def main():
    base=ROOT/'runs/2026-11-16-context-v5-system-implementation';out=base/'strict-recovery-probe';out.mkdir(exist_ok=False)
    sources={'C14':SOURCES['C14']}
    for c in ('C11','C09'):
        sources[c]=next(p.parent/'attempt-1' for p in (base/'focus-v1/r1/corpus'/c).rglob('state.json') if read(p)['attempts'][0]['status']=='syntax_invalid')
    rows=[]
    for cid,src in sources.items():
        folder=out/cid;folder.mkdir();client=ModelClient(ROOT.parent.parent/'meeting-agent/.env',folder/'unused-cache')
        req=read(src/'request.json');payload=json.loads(req['messages'][1]['content']);parts=urlsplit(client.endpoint)
        endpoint=urlunsplit((parts.scheme,parts.netloc,'/beta/chat/completions','',''))
        req.pop('response_format',None);req.pop('reasoning_effort',None)
        req.update(thinking={'type':'disabled'},temperature=0,
            tools=[dict(type='function',function=dict(name='submit_result',description='Submit the complete validated stage result.',strict=True,parameters=tool_schema(payload['output_schema'])))],
            tool_choice=dict(type='function',function={'name':'submit_result'}))
        req['messages'][0]['content']+='\n本次通过 submit_result 工具提交相同完整结构，不在普通 content 返回 JSON。'
        write_json(folder/'request.json',req);write_json(folder/'source.json',dict(source=src.relative_to(ROOT).as_posix(),endpoint=endpoint))
        started=time.perf_counter();meta=dict(stage='strict_probe',case_id=cid,usage_unknown=True)
        try:
            request=urllib.request.Request(endpoint,data=json.dumps(req,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+client.key,'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=90) as stream:response=read_response(stream,time.monotonic()+180)
            write_json(folder/'response.json',response);meta.update(usage=response.get('usage'),usage_unknown=response.get('usage') is None)
            choice=response['choices'][0];calls=choice['message'].get('tool_calls',[]);meta['finish_reason']=choice['finish_reason']
            assert choice['finish_reason']=='tool_calls' and len(calls)==1 and calls[0]['function']['name']=='submit_result'
            value=json.loads(calls[0]['function']['arguments']);write_json(folder/'value.json',value);meta['parsed']=True
        except urllib.error.HTTPError as exc:
            meta.update(http_status=exc.code,error=exc.read(2500).decode('utf8',errors='replace').replace(client.key,'[redacted]'),parsed=False)
        except Exception as exc:meta.update(error=type(exc).__name__+': '+str(exc),parsed=False)
        meta['seconds']=round(time.perf_counter()-started,3);write_json(folder/'meta.json',meta);rows.append(meta);write_json(out/'progress.json',rows)
        print(cid,meta['parsed'],meta.get('http_status'),meta.get('error','')[:200],flush=True)
        if meta.get('http_status') in (402,429):break
    write_json(out/'summary.json',rows)


if __name__=='__main__':main()
