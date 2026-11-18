"""Replay recorded validation failure; counterfactual edits are diagnostic only."""
import copy
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import normalize,digest
from meeting_eval.task_events import canonical_events
from scripts.run_action_baseline import write_json

def main():
    manifest=json.loads((ROOT/'experiments/history-time/manifest.json').read_text(encoding='utf-8'))
    folder=ROOT/manifest['source']['path']
    request=json.loads((folder/'request.json').read_text(encoding='utf-8'))
    assert digest(request)==manifest['source']['request_hash']
    payload=json.loads(request['messages'][1]['content']);meeting=normalize(payload['meeting'],'host');results=[]
    for name,path,key in [('first',folder,'response_hash'),('recovery',folder/'retry-0001','retry_response_hash')]:
        response=json.loads((path/'response.json').read_text(encoding='utf-8'))
        assert digest(response)==manifest['source'][key]
        raw=json.loads(response['choices'][0]['message']['content'])
        try:canonical_events(raw['events'],payload['candidates'],meeting,payload['history']);error=None
        except ValueError as exc:error=str(exc)
        assert error=='Deadline requires explicit text and evidence',error
        edited=copy.deepcopy(raw['events']);changes=[]
        for index,event in enumerate(edited):
            if event['time']['kind']=='deadline' and not event['time']['evidence']:
                changes.append(dict(index=index,before=event['time']))
                event['time']=dict(kind='unspecified',text=None,date=None,evidence=[])
        canonical_events(edited,payload['candidates'],meeting,payload['history'])
        results.append(dict(attempt=name,error=error,response_hash=digest(response),
            diagnostic_only_counterfactual=dict(changes=changes,validation_passed=True),
            note='Not a generated output or a quality score; no saved model response or production validation was edited'))
    out=ROOT/'runs/2026-11-14-history-time';out.mkdir(parents=True,exist_ok=True)
    write_json(out/'reproduction.json',results)
    print(json.dumps(results,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
