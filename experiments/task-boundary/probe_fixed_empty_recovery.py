"""One frozen C20 recheck to verify the provider's fixed-empty-object adapter."""
import json
from run_full_context_v5 import ROOT,read,write_json
from meeting_eval.model_client import ModelClient
from meeting_eval.context_protocol_v4 import closed_validate


def main():
    base=ROOT/'runs/2026-11-16-context-v5-system-implementation'
    src=next(p.parent for p in (base/'focused-strict/r1/corpus/C20').rglob('meta.json') if read(p).get('http_status')==400)
    request=read(src/'request.json');payload=json.loads(request['messages'][1]['content'])
    out=base/'fixed-empty-recovery';out.mkdir(exist_ok=False)
    write_json(out/'source.json',dict(path=src.relative_to(ROOT).as_posix(),payload=payload))
    client=ModelClient(ROOT.parent.parent/'meeting-agent/.env',out/'model')
    raw=client.call(request['messages'][0]['content'].split('\n本次通过 submit_result')[0],payload,'check_repair',
        inference={'thinking':'disabled','max_tokens':16384},strict_schema=payload['output_schema'],deadline_seconds=300)
    write_json(out/'value.json',raw);closed_validate(raw,payload['output_schema'])
    assert raw['case_id']==payload['meeting']['case_id'] and raw['scope']==payload['scope']
    write_json(out/'summary.json',dict(full_wire_contract_valid=True,fixed_checks=raw['checks'],semantic_review='pending'))
    print('C20 fixed-empty recovery satisfies original closed schema and identity',flush=True)


if __name__=='__main__':main()
