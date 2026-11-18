"""Replay frozen successful focus calls through final code, with network impossible."""
import json
from pathlib import Path
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[2]),str(Path(__file__).parent)]
from run_context_v2 import BASE,INFERENCE,read,write_json
from meeting_eval.context_v2 import ContextV2Pipeline,reduce_v2
from meeting_eval.inputs import digest


class RecordedClient:
    def __init__(self,folder):
        cfg=read(folder/'pipeline.json')['trace']['config'];self.model=cfg['model'];self.endpoint=cfg['endpoint'];self.responses={};self.calls=0
        for p in (folder/'model').rglob('request.json'):
            req=read(p);resp=read(p.with_name('response.json'))
            if resp['choices'][0]['finish_reason']!='stop':raise ValueError('Recorded response incomplete')
            key=digest([req['messages'][0]['content'],json.loads(req['messages'][1]['content'])])
            self.responses[key]=json.loads(resp['choices'][0]['message']['content'])

    def call(self,prompt,payload,stage,**kwargs):
        self.calls+=1
        return json.loads(json.dumps(self.responses[digest([prompt,payload])]))


def main():
    out=BASE/'offline-final';out.mkdir(exist_ok=False);rows=[]
    for batch in ('revision1-r1','revision1-r2'):
        for p in sorted((BASE/batch).glob('*/pipeline.json')):
            old=read(p);folder=p.parent;data=read(folder/'input.json');client=RecordedClient(folder)
            result=ContextV2Pipeline(client,out/batch/folder.name,INFERENCE).run(data['meeting'],data['history'])
            assert not result['errors'],(batch,folder.name,result['errors'])
            reduced=reduce_v2(result,data['meeting'],data['history'])
            assert reduced==read(folder/'reduced.json'),(batch,folder.name,'changed observable result')
            assert not result['coverage_findings']
            assert not any(r['category']=='interpretation_unresolved' for r in reduced['review_records'])
            write_json(out/batch/folder.name/'reduced.json',reduced)
            rows.append(dict(batch=batch,case=folder.name,matching_output=True,replayed_calls=client.calls))
    write_json(out/'summary.json',dict(network_calls=0,cases=rows,passed=len(rows)))
    print('Matched',len(rows),'case outputs; 0 network calls')


if __name__=='__main__':main()
