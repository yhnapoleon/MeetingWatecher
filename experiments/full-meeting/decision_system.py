"""Stage ablations on frozen proposals. Use a new experiment directory per revision."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.decision_review import DecisionReview, review_input, project_claims
from meeting_eval.extract import Extractor, model_input
from meeting_eval.inputs import normalize
from meeting_eval.stage_runner import atomic_json


def run(name, out, phase):
    prior = ROOT / 'runs/2026-11-18-decision-adoption'
    source = ROOT / ('runs/2026-11-17-full-meeting-'+name+'-fresh-v17') if name.startswith('ES') else (out if name=='IB4003' else prior/name)
    if name=='paired-control':
        source=ROOT/'runs/2026-11-18-decision-action/paired-control'
    read = lambda p: json.loads(p.read_text(encoding='utf8'))
    meeting = model_input(normalize(read(source/'input.json'),'evaluator'))
    baseline = out/'baseline/result.json' if name=='IB4003' else prior/'final'/name/'result.json'
    previous = read(baseline)['decisions']
    transcript, topics = review_input(meeting, previous)
    extractor = Extractor(ROOT.parent.parent/'meeting-agent/.env',out/'model','context-v5')
    reviewer = DecisionReview(extractor.client,out/'model/independent',{'thinking':'disabled','max_tokens':10000})
    if phase=='review':
        result = reviewer.review(meeting,previous,[])
        atomic_json(out/'review.json',result)
        return
    if phase in ('local','oracle'):
        nearby = {i for t in topics for anchor in t['refs'] for i in range(anchor-4,anchor+5)}
        if phase=='oracle':
            # Diagnostic ceiling: human-selected counterevidence, never used by the production path.
            fragments = {'ES2002a':['D.181','B.216'], 'ES2002b':['B.290','A.69','B.129','C.83']}
            for short in fragments[name]:
                speaker, end = short.split('.')
                i = next(i for i,s in enumerate(meeting['segments'],1)
                         if s['id']==f'{name}.{speaker}.dialog-act.dharshi.{end}')
                nearby.update(range(i-5,i+7))
        transcript = [row for row in transcript if row[0] in nearby]
    if phase=='coverage':
        additions = reviewer.scan(transcript)
        atomic_json(out/'discovered.json',additions)
        topics += additions
    findings = reviewer.verify(transcript,topics,[])
    atomic_json(out/(phase+'.json'),project_claims(meeting,findings))
    if phase=='coverage':
        atomic_json(out/'merged.json',project_claims(meeting,reviewer.merge(findings)))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('name')
    parser.add_argument('out',type=Path)
    parser.add_argument('phase',choices=['local','oracle','timeline','coverage','review'])
    args=parser.parse_args()
    run(args.name,args.out,args.phase)

