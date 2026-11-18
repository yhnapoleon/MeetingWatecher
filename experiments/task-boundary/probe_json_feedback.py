"""Compare actionable delimiter diagnostics on saved failures; never patch accepted JSON."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
from pathlib import Path
from run_full_context_v5 import ROOT,read,write_json
from meeting_eval.model_client import ModelClient
from probe_system_recovery import SOURCES


def delimiter_hint(text):
    stack=[];quoted=False;escaped=False
    for i,c in enumerate(text):
        if quoted:
            if escaped:escaped=False
            elif c=='\\':escaped=True
            elif c=='"':quoted=False
            continue
        if c=='"':quoted=True
        elif c in '{[':stack.append((c,i))
        elif c in '}]':
            expected={'}':'{',']':'['}[c]
            if not stack:return f'Unexpected closing {c} at position {i}.'
            if stack[-1][0]!=expected:return f'At position {i}, closing {c} conflicts with opener {stack[-1][0]} at {stack[-1][1]}; close that container with '+({'{':'}','[':']'}[stack[-1][0]])+' first.'
            stack.pop()
    if stack:return 'Unclosed containers at end: '+repr(stack)+'. Close each object/array separately in reverse nesting order.'
    return 'Check commas, keys and string escaping against the full output schema.'


def main():
    out=ROOT/'runs/2026-11-16-context-v5-system-implementation/json-feedback-probes';out.mkdir(exist_ok=False)
    sources={'C14':SOURCES['C14']}
    candidates=list((ROOT/'runs/2026-11-16-context-v5-system-implementation/focus-v1/r1/corpus/C11').rglob('state.json'))
    sources['C11']=next(p.parent/'attempt-1' for p in candidates if read(p)['attempts'][0]['status']=='syntax_invalid')
    def one(cid,include_old):
        src=sources[cid];req=read(src/'request.json');response=read(src/'response.json');content=response['choices'][0]['message']['content']
        payload=json.loads(req['messages'][1]['content']);payload['validation_feedback']=dict(error=delimiter_hint(content),instruction='重新生成完整 JSON。逐层关闭每一个 object 和 array；不要复制之前的缺失分隔符。保持原文含义，完整满足 output_schema。')
        if include_old:payload['validation_feedback']['previous_output']={'raw_text':content,'finish_reason':'stop'}
        folder=out/(cid+('-with-raw' if include_old else '-without-raw'));folder.mkdir()
        inference={k:req[k] for k in ('temperature','max_tokens','reasoning_effort') if k in req};inference['thinking']=req['thinking']['type']
        client=ModelClient(ROOT.parent.parent/'meeting-agent/.env',folder/'model')
        write_json(folder/'source.json',dict(source=src.relative_to(ROOT).as_posix(),diagnostic=payload['validation_feedback']))
        try:
            value=client.call(req['messages'][0]['content'],payload,'format_probe',inference=inference,deadline_seconds=300)
            write_json(folder/'value.json',value);row=dict(case=cid,include_old=include_old,parsed=True)
        except Exception as exc:row=dict(case=cid,include_old=include_old,parsed=False,error=str(exc))
        write_json(folder/'summary.json',row);print(row,flush=True);return row
    with ThreadPoolExecutor(max_workers=4) as pool:rows=[f.result() for f in as_completed([pool.submit(one,c,b) for c in sources for b in (True,False)])]
    write_json(out/'summary.json',rows)


if __name__=='__main__':main()
