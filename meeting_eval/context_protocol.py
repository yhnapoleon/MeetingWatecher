"""Versioned context-v2 output contract (standard-library JSON Schema subset).

The schemas below use only type, properties, required, items, enum and minimum.
Examples are generated from those same definitions; semantic validation follows.
"""
import copy
import json
from .context_state import KINDS, MISSING, ISSUES, rows_by_id
from .task_events import EVENT_FIELDS


def string(example='依据',values=None,nullable=False):
    return dict(type=['string','null'] if nullable else 'string',example=example,**({'enum':values} if values else {}))


def obj(**properties):return dict(type='object',properties=properties,required=list(properties))
def array(items,empty=False):return dict(type='array',items=items,**({'example':[]} if empty else {}))
def enum(*values):return string(values[0],list(values))
Q=array(string('Q1'))
SPAN=obj(segment_id=string('原段ID'),quote=string('原文逐字子串'))
SPAN['properties'].update(occurrence=dict(type='integer',minimum=1),start=dict(type='integer',minimum=0),end=dict(type='integer',minimum=1))
SPANS=array(SPAN,True)
RECORD=obj(record_id=string('R1'),thread_ids=array(string('T1')),kind=enum(*sorted(KINDS)),
    content_basis=enum('explicit','contextual','inferred','unknown'),description=string('完整工作或上下文含义'),
    evidence=SPANS,missing_fields=array(enum(*sorted(MISSING)),True),question=string(None,nullable=True),issuer_ref=string(None,nullable=True))
RECORD['properties']['kind']['example']='work'
RECORD['properties']['introduced_by']=string('O1')
EVENT=obj(record_id=string('R1'),candidate_ids=array(string('C1')),work=obj(description=string('动作与对象'),evidence=SPANS),
    owner=obj(kind=enum('unknown','person','group','speaker'),ref=string(None,nullable=True),label=string(None,nullable=True),evidence=SPANS),
    commitment=obj(kind=enum('unknown','accepted','self_committed','assigned','decided','suggested','declined','conditional'),evidence=SPANS),
    time=obj(kind=enum('unspecified','deadline','work_window'),text=string(None,nullable=True),date=string(None,nullable=True),evidence=SPANS,change=enum('keep','set','clear','uncertain')),
    state=obj(kind=enum('future_work','progress','completed','reopened','revised','unknown'),evidence=SPANS),
    relation=obj(kind=enum('new','existing','ambiguous','unknown'),target_guid=string(None,nullable=True),evidence=SPANS),
    other_changes=array(enum('content','owner','other'),True))
GAP=obj(field=enum(*sorted(MISSING)),verdict=enum('unsupported','supported'),blocking_for=enum('none','content','operation'),reason=string(),evidence=Q)
CLARIFICATION=obj(status=enum('not_needed','needed','unresolved'),basis=string(),fields=array(enum(*sorted(MISSING)),True),question=string(None,nullable=True),evidence=Q)
CHECK_FIELD=obj(verdict=enum('supported','insufficient','contradicted'),reason=string(),evidence=Q)
RECORD_CHECK=obj(record_id=string('R1'),verdict=enum('supported','insufficient','contradicted'),issues=array(enum(*sorted(ISSUES)),True),reason=string(),evidence=Q,
    proposed_kind=string(None,sorted(KINDS)+[None],True),gap_checks=array(GAP,True),clarification=CLARIFICATION)
FINDING=obj(description=string('遗漏的独立工作或已有工作缺失内容'),evidence=Q,relation=enum('new_work','same_work','uncertain'),related_record_ids=array(string('R1'),True))
DISPOSITION=obj(finding_id=string('O1'),disposition=enum('rejected','covered','added','unresolved'),record_ids=array(string('R_O1_1'),True),evidence=Q)
DISPOSITION_CHECK=copy.deepcopy(DISPOSITION)
DISPOSITION_CHECK['properties'].update(verdict=enum('supported','insufficient','contradicted'),reason=string())
DISPOSITION_CHECK['required']+=['verdict','reason']
INTERPRET=obj(case_id=string('输入case_id'),records=array(RECORD),events=array(EVENT))
REPAIR=copy.deepcopy(INTERPRET);REPAIR['properties']['dispositions']=array(DISPOSITION);REPAIR['required']+=['dispositions']
CHECK=obj(case_id=string('输入case_id'),record_checks=array(RECORD_CHECK),checks=array(obj(event_id=string('E1'),fields=obj(**{f:CHECK_FIELD for f in EVENT_FIELDS}))),coverage_findings=array(FINDING,True))
RECHECK=copy.deepcopy(CHECK);del RECHECK['properties']['coverage_findings'];RECHECK['required'].remove('coverage_findings')
RECHECK['properties']['disposition_checks']=array(DISPOSITION_CHECK);RECHECK['required']+=['disposition_checks']


def example(schema):
    if 'example' in schema:return copy.deepcopy(schema['example'])
    if schema['type']=='object':return {k:example(schema['properties'][k]) for k in schema['required']}
    if schema['type']=='array':return [example(schema['items'])]
    return 1


def validate_schema(value,schema,path='$'):
    """Validate all required structure before quote alignment; report all misses."""
    errors=[]
    def visit(v,s,p):
        typ=s['type'];types=typ if isinstance(typ,list) else [typ]
        valid=any((t=='null' and v is None) or (t=='string' and isinstance(v,str)) or
            (t=='integer' and type(v) is int) or (t=='array' and isinstance(v,list)) or
            (t=='object' and isinstance(v,dict)) for t in types)
        if not valid:errors.append(p+': expected '+str(typ));return
        if 'enum' in s and v not in s['enum']:errors.append(p+': invalid enum')
        if 'minimum' in s and v<s['minimum']:errors.append(p+': below minimum')
        if isinstance(v,dict):
            for k in s['required']:
                if k not in v:errors.append(p+'.'+k+': required')
            for k,item in s['properties'].items():
                if k in v:visit(v[k],item,p+'.'+k)
        if isinstance(v,list):
            for i,item in enumerate(v):visit(item,s['items'],p+f'[{i}]')
    visit(value,schema,path)
    if errors:raise ValueError('; '.join(errors))


def prompt_schema(schema):
    sample=example(schema);validate_schema(sample,schema)
    return '\n仅输出符合以下完整结构的 JSON（数组按实际情况可为空，示例不是答案）：\n'+json.dumps(sample,ensure_ascii=False)


def expand_refs(refs,catalog,required=False):
    if not isinstance(refs,list) or any(not isinstance(q,str) or q not in catalog for q in refs) or required and not refs:
        raise ValueError('Missing or unknown evidence reference')
    return [catalog[q] for q in refs]


def validate_clarification(record,catalog):
    c=record['clarification'];gaps=rows_by_id(record['gap_checks'],'field');blocking=set()
    for g in gaps.values():
        expand_refs(g['evidence'],catalog,True)
        if not g['reason'].strip():raise ValueError('Gap needs reason')
        if g['verdict']=='unsupported' and g['blocking_for']!='none':raise ValueError('Unsupported blocking gap')
        if g['verdict']=='supported' and g['blocking_for']!='none':blocking.add(g['field'])
    expand_refs(c['evidence'],catalog,True)
    if not c['basis'].strip() or len(set(c['fields']))!=len(c['fields']):raise ValueError('Invalid clarification basis/fields')
    if c['status']=='needed' and (set(c['fields'])!=blocking or not blocking or not c['question'] or not c['question'].strip()):
        raise ValueError('Unsupported clarification')
    if c['status']=='not_needed' and (blocking or c['fields'] or c['question'] is not None):raise ValueError('Contradictory not_needed')
    if c['status']=='unresolved' and (c['fields'] or c['question'] is not None):raise ValueError('System uncertainty cannot fabricate a user question')


def validate_records(raw,catalog):
    # Used by the pure routing contract after schema validation at model boundary.
    for r in raw['records']:
        validate_schema(r['clarification'],CLARIFICATION)
        for gap in r['gap_checks']:validate_schema(gap,GAP)
        validate_clarification(r,catalog)
    return raw['records']
