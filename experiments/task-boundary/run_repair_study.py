"""Frozen stage experiments; no production mutation, no automatic retries."""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.extract import model_input
from meeting_eval.inputs import digest
from meeting_eval.model_client import ModelClient
from scripts.run_action_baseline import write_json

HERE = Path(__file__).parent
OUT = ROOT/'runs/2026-11-15-m2-repair-study'
CONFIG = dict(thinking='disabled', temperature=0, max_tokens=16384)
KINDS = {'work','implicit_need','ambiguous','entity_only','context_only','withdrawn','resolved'}
FIELDS = {'work','reference','scope','owner','commitment','time','relation'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def validate_records(raw, catalog):
    records = raw['records']
    if not isinstance(records, list) or not records:
        raise ValueError('Expected nonempty semantic records')
    ids = set()
    def refs(value):
        if not isinstance(value, list) or not value or any(q not in catalog for q in value):
            raise ValueError('Missing or unknown evidence ID')
    for r in records:
        rid = r['record_id']
        if not isinstance(rid,str) or not rid or rid in ids: raise ValueError('Duplicate/invalid ID')
        ids.add(rid)
        if r['kind'] not in KINDS or not isinstance(r['description'],str) or not r['description'].strip():
            raise ValueError('Invalid semantic record')
        refs(r['evidence'])
        if not isinstance(r['gap_checks'],list): raise ValueError('Invalid gaps')
        gaps = set(); blocking = set()
        for g in r['gap_checks']:
            f = g['field']
            if f not in FIELDS or f in gaps: raise ValueError('Duplicate/invalid gap')
            gaps.add(f)
            if g['verdict'] not in ('supported','unsupported') or g['blocking_for'] not in ('content','operation','none'):
                raise ValueError('Invalid gap check')
            if g['verdict']=='unsupported' and g['blocking_for']!='none': raise ValueError('Unsupported blocking gap')
            if not isinstance(g['reason'],str) or not g['reason'].strip(): raise ValueError('Missing gap reason')
            refs(g['evidence'])
            if g['verdict']=='supported' and g['blocking_for']!='none': blocking.add(f)
        c = r['clarification']; refs(c['evidence'])
        if not isinstance(c['basis'],str) or not c['basis'].strip(): raise ValueError('Missing clarification basis')
        if c['status'] not in ('needed','not_needed','unresolved'): raise ValueError('Invalid clarification')
        if not isinstance(c['fields'],list) or len(set(c['fields']))!=len(c['fields']) or set(c['fields'])-FIELDS:
            raise ValueError('Invalid clarification fields')
        if c['status']=='needed':
            if set(c['fields'])!=blocking or not blocking or not isinstance(c['question'],str) or not c['question'].strip():
                raise ValueError('Unsupported clarification')
        elif c['status']=='not_needed' and (c['fields'] or c['question'] is not None or blocking):
            raise ValueError('Contradictory not_needed')
    return records


def freeze():
    OUT.mkdir(exist_ok=False)
    cases = read(ROOT/'runs/2026-11-15-m2-system-diagnosis/evidence.json')
    frozen = {}
    for name,key in [('M2','cross_bad'),('positive','positive'),('C20','C20'),('P07b','P07b')]:
        c=cases[key]; t=c['extraction']['_task_trace']; first=t.get('repair',{}).get('before',t)
        frozen[name] = dict(meeting=model_input(c['meeting']),history=c['history'],
            evidence_catalog={f'Q{i}':dict(segment_id=s['id'],quote=s['text']) for i,s in enumerate(c['meeting']['segments'],1)},
            upstream={k:copy.deepcopy(t['ledger'] if k=='ledger' else first[k]) for k in ('ledger','records','events')})
    write_json(OUT/'inputs.json',frozen)
    prompt=(HERE/'classify-v1.txt').read_text(encoding='utf8')
    (OUT/'classify-v1.txt').write_text(prompt,encoding='utf8')
    write_json(OUT/'plan.json',dict(config=CONFIG,input_hash=digest(frozen),prompt_hash=digest(prompt),
        cases=list(frozen),rounds=2,arms=['visible','blind'],expected_calls=16,
        rubric={'M2':'Q1 completed work retained; Q2 non-work, no gap/question/unresolved for scope',
        'positive':'Q1 completed work; Q2 scope non-work; Q3+Q4 gray-config/testing work, Chen accepted today, no gap/question/unresolved',
        'C20':'Video editing+confirmation work retained; owner operation gap allowed; no manuscript action/question/unresolved',
        'P07b':'Scene refinement work with Lin acceptance retained; no reference/scope gap or question/unresolved'},
        promotion='blind M2+positive both rounds pass; no C20/P07b regression; each round blind >= visible; at least one strict advantage; structural/unresolved fail; no extra sampling'))
    with zipfile.ZipFile(OUT/'before.zip','w',zipfile.ZIP_DEFLATED) as z:
        for folder in ('meeting_eval','prompts','tests','experiments/task-boundary'):
            for p in (ROOT/folder).rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts: z.write(p,p.relative_to(ROOT))
    return frozen,prompt


def call_one(name, case, arm, round_, prompt):
    folder=OUT/'c3'/f'{name}-{arm}-r{round_}'
    folder.mkdir(parents=True,exist_ok=False)
    payload=copy.deepcopy(case)
    if arm=='blind': payload.pop('upstream')
    write_json(folder/'input.json',payload)
    result=dict(case=name,arm=arm,round=round_,status='failed')
    try:
        client=ModelClient(ROOT.parent.parent/'meeting-agent/.env',folder/'model')
        raw=client.call(prompt,payload,'classify',inference=CONFIG)
        write_json(folder/'raw.json',raw)
        validate_records(raw,payload['evidence_catalog'])
        result.update(status='valid',unresolved=any(r['clarification']['status']=='unresolved' for r in raw['records']))
    except Exception as exc:
        result.update(error=type(exc).__name__,detail=str(exc)[:300])
    write_json(folder/'result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);args=parser.parse_args()
    frozen,prompt=freeze();results=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs=[pool.submit(call_one,n,c,a,r,prompt) for r in (1,2) for n,c in frozen.items() for a in ('visible','blind')]
        for future in as_completed(jobs):
            result=future.result();results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
    metas=[read(p) for p in (OUT/'c3').rglob('meta.json')]
    write_json(OUT/'c3-summary.json',dict(results=results,calls=len(metas),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),
        call_seconds=sum(m['duration_seconds'] for m in metas),semantic_scoring='pending manual review'))


if __name__=='__main__': main()
