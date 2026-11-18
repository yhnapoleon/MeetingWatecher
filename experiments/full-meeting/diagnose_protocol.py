"""Offline causal probes of the saved ES2002a protocol failure. No model client."""
import copy
import hashlib
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.context_wire import decode_output,reference_field,reference_issues
from meeting_eval.context_protocol_v3 import INTERPRET
from meeting_eval.context_protocol_v4 import closed_validate
from meeting_eval.context_v5 import ContextV5Pipeline
from meeting_eval.reference_repair import ReferenceRepair
from meeting_eval.inputs import normalize,digest,dumps
from meeting_eval.model_client import supports_strict_recovery

SOURCE=ROOT/'runs/2026-11-17-full-meeting-ES2002a'
OUT=ROOT/'runs/2026-11-17-evidence-protocol-diagnosis'


def read(p):return json.loads(p.read_text(encoding='utf8'))
def size(v):return len(dumps(v).encode('utf8'))
def fingerprint(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def map_references(value,convert):
    if isinstance(value,list):return [map_references(v,convert) for v in value]
    if isinstance(value,dict):return {k:convert(v) if reference_field(k) else map_references(v,convert) for k,v in value.items()}
    return copy.deepcopy(value)


def trial(fn):
    try:
        result=fn()
        return dict(passed=True),result
    except (ValueError,TypeError,KeyError,AttributeError,IndexError) as exc:
        return dict(passed=False,error=type(exc).__name__+': '+str(exc)[:500]),None


class NoClient:
    model='deepseek-flash'
    endpoint='https://api.deepseek.com/chat/completions'
    def call(self,*args,**kwargs):raise AssertionError('No model calls allowed')


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    meeting=normalize(read(SOURCE/'input.json'),'evaluator')
    texts={s['id']:s['text'] for s in meeting['segments']}
    extraction=read(SOURCE/'result.json')['extraction'];trace=extraction['_task_trace']
    pipe=ContextV5Pipeline(NoClient(),OUT,read(SOURCE/'inference.json'))
    report=dict(scope='Offline diagnosis only; no accepted output generated; raw artifacts unchanged',attempts=[],requests=[],working_comparisons=[])
    for p in sorted((SOURCE/'model').rglob('interpret_work/*/attempt-*/raw.json')):
        raw=read(p);before=digest(raw);req=read(p.with_name('request.json'));payload=json.loads(req['messages'][-1]['content'])
        issues=reference_issues(raw,meeting);refs=[r for i in issues for r in i['invalid'] if isinstance(r,dict)]
        row=dict(path=p.relative_to(ROOT).as_posix(),sha256=fingerprint(p),slots=len(issues),reference_objects=len(refs),
            all_ids_exist=all(r.get('segment_id') in texts for r in refs),
            valid_nonempty_offsets=sum(type(r.get('start')) is int and type(r.get('end')) is int and
                0<=r['start']<r['end']<=len(texts[r['segment_id']]) for r in refs),
            single_character_spans=sum(r.get('end',0)-r.get('start',0)==1 for r in refs),
            has_output_schema='output_schema' in payload,patch_current_eligible=ReferenceRepair().prepare(raw,payload) is not None,
            strict_provider_available=supports_strict_recovery(req['model'],NoClient.endpoint))
        row['unchanged_decode'],_=trial(lambda:decode_output(raw,meeting))
        # Diagnostic counterfactual only: discard spans, preserve declared segment IDs.
        # This changes evidence granularity and is NOT production acceptance or a repair recommendation.
        ids_only=map_references(raw,lambda values:[r['segment_id'] if isinstance(r,dict) else r for r in values])
        row['ids_only_structure'],_=trial(lambda:closed_validate(ids_only,INTERPRET))
        row['ids_only_interpret'],interpreted=trial(lambda:pipe.interpret(decode_output(ids_only,meeting),
            trace['ledger'],trace['candidates'],meeting,{'tasks':[]}))
        row['non_evidence_fields_unchanged']=map_references(raw,lambda _:[])==map_references(ids_only,lambda _:[])
        row['draft_work']=[dict(record_id=r['record_id'],description=r['description']) for r in raw['records'] if r['kind']=='work']
        if interpreted:row['interpreted_event_count']=len(interpreted['events'])
        assert digest(raw)==before
        report['attempts'].append(row)
    for p in sorted((SOURCE/'model').rglob('request.json')):
        req=read(p);payload=json.loads(req['messages'][-1]['content']);meta=read(p.with_name('meta.json'))
        row=dict(path=p.relative_to(ROOT).as_posix(),stage=meta['stage'],prompt_tokens=meta['usage']['prompt_tokens'],
            system_utf8_bytes=len(req['messages'][0]['content'].encode('utf8')),user_utf8_bytes=len(req['messages'][-1]['content'].encode('utf8')),
            top_level_utf8_bytes={k:size(v) for k,v in payload.items()},schema_present='output_schema' in payload,
            strict_tool=bool(req.get('tools')),feedback=payload.get('validation_feedback'))
        row['feedback_contains_expected_type']='array of strings' in str(row['feedback']) or '字符串' in str(row['feedback'])
        report['requests'].append(row)
    for cid in ('GN25','GN29'):
        folder=ROOT/'runs/2026-11-17-interpret-budget-low/natural'/cid
        for p in folder.rglob('interpret_work/*/attempt-*/raw.json'):
            req=read(p.with_name('request.json'));raw=read(p);payload=json.loads(req['messages'][-1]['content'])
            state=read(p.parent.parent/'state.json')
            report['working_comparisons'].append(dict(case=cid,path=p.relative_to(ROOT).as_posix(),node_status=state['status'],
                has_conflicting_span_sentence='证据对象的 start/end' in req['messages'][0]['content'],has_output_schema='output_schema' in payload,
                evidence_issues=len(reference_issues(raw,payload['meeting']))))
    # Show why changing only interpretation invalidates the existing tracking parent folder.
    original_config=copy.deepcopy(pipe.config);original_cache=pipe.cache_config()
    pipe.config['prompts']['interpret_work']='diagnostic-placeholder'
    report['cache_probe']=dict(changed_only_interpret_prompt_hash=True,parent_cache_config_changed=pipe.cache_config()!=original_cache)
    pipe.config=original_config
    report['source_hashes']={str(p.relative_to(ROOT)):fingerprint(p) for p in sorted((ROOT/'meeting_eval').glob('*.py'))}
    (OUT/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('requests','source_hashes')},ensure_ascii=False,indent=2))
    print('Request byte breakdown:')
    for row in report['requests']:
        print(row['stage'],row['prompt_tokens'],sorted(row['top_level_utf8_bytes'].items(),key=lambda x:-x[1])[:4])


if __name__=='__main__':
    with patch.object(socket,'socket',side_effect=AssertionError('Network forbidden in offline diagnosis')):
        main()
