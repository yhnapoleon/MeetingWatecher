"""Bounded model proposals; identity and coverage relations belong to the program."""
import copy
from . import context_protocol as base
from . import context_protocol_v3 as v3
from .inputs import digest


def closed_validate(value,schema):
    base.validate_schema(value,schema)
    def visit(v,s):
        if isinstance(v,dict):
            extra=set(v)-set(s['properties'])
            if extra:raise ValueError('Unexpected proposal fields: '+','.join(sorted(extra)))
            for k,item in v.items():visit(item,s['properties'][k])
        elif isinstance(v,list):
            for item in v:visit(item,s['items'])
    visit(value,schema)


CHECK=copy.deepcopy(v3.CHECK)
del CHECK['properties']['coverage_findings'];CHECK['required'].remove('coverage_findings')
NEW=base.obj(description=base.string('独立遗漏工作'),evidence=v3.Q)
UNCERTAIN=base.obj(description=base.string('无法可靠判断是否同一工作'),evidence=v3.Q,
                   related_record_ids=base.array(base.string('R1'),True))
CHECK['properties'].update(new_work_findings=base.array(NEW,True),uncertain_findings=base.array(UNCERTAIN,True))
CHECK['required']+=['new_work_findings','uncertain_findings']


def coverage_to_v3(raw):
    closed_validate(raw,CHECK)
    out=copy.deepcopy(raw)
    new=out.pop('new_work_findings');uncertain=out.pop('uncertain_findings')
    out['coverage_findings']=[dict(**f,relation='new_work',related_record_ids=[]) for f in new]
    out['coverage_findings'] += [dict(**f,relation='uncertain') for f in uncertain]
    return out


def mutable_schema(schema,excluded):
    out=copy.deepcopy(schema)
    for name in excluded:
        out['properties'].pop(name,None)
        if name in out['required']:out['required'].remove(name)
    return out


RECORD=mutable_schema(v3.RECORD,('record_id','thread_ids','introduced_by'))
EVENT=mutable_schema(v3.EVENT,('record_id','event_id'))
EVENT['example']=base.example(EVENT);EVENT['type']=['object','null']
BUNDLE=base.obj(record=RECORD,event=EVENT)


def repair_contract(payload):
    originals={r['record_id']:r for r in payload['original_records']}
    if set(originals)!=set(payload['target_record_ids']):raise ValueError('Invalid repair targets')
    slots={f'target_{i}':rid for i,rid in enumerate(sorted(originals),1)}
    findings={f['finding_id']:f for f in payload['coverage_findings']}
    scope=digest(dict(protocol='context-v4-patch-1',payload=payload))
    schema=base.obj(case_id=base.string(payload['meeting']['case_id']),scope=base.string(scope),
        targets=base.obj(**{slot:BUNDLE for slot in slots}),
        additions=base.obj(**{fid:base.array(BUNDLE,True) for fid in findings}),
        dispositions=copy.deepcopy(base.REPAIR['properties']['dispositions']))
    return schema,dict(scope=scope,slots=slots)


def expand_patch(raw,payload):
    schema,binding=repair_contract(payload);closed_validate(raw,schema)
    if raw['scope']!=binding['scope']:raise ValueError('Stale repair scope')
    if raw['case_id']!=payload['meeting']['case_id']:raise ValueError('Wrong case_id')
    original={r['record_id']:r for r in payload['original_records']}
    out=dict(case_id=raw['case_id'],records=[],events=[],dispositions=copy.deepcopy(raw['dispositions']))
    def add(bundle,rid,threads,finding=None):
        record=copy.deepcopy(bundle['record']);record.update(record_id=rid,thread_ids=copy.deepcopy(threads))
        if finding:record['introduced_by']=finding
        out['records'].append(record)
        if bundle['event'] is not None:
            event=copy.deepcopy(bundle['event']);event['record_id']=rid;out['events'].append(event)
    for slot,rid in binding['slots'].items():add(raw['targets'][slot],rid,original[rid]['thread_ids'])
    for fid,bundles in raw['additions'].items():
        for i,bundle in enumerate(bundles,1):add(bundle,f'R_{fid}_{i}',[],fid)
    return out
