"""Model-facing v3 contract; deterministic adapter to the existing checked state."""
import copy
from . import context_protocol as v2
from .context_state import KINDS, MISSING, rows_by_id

Q = v2.array(v2.string('Q1'), True)
INTERPRET = copy.deepcopy(v2.INTERPRET)
RECORD = INTERPRET['properties']['records']['items']
RECORD['properties']['evidence'] = Q
RECORD['properties']['need_basis'] = v2.obj(goal=v2.string(None, nullable=True), evidence=Q)
RECORD['required'].append('need_basis')
EVENT = INTERPRET['properties']['events']['items']
for field in ('work','owner','commitment','time','state','relation'):
    EVENT['properties'][field]['properties']['evidence'] = Q
del EVENT['properties']['work']['properties']['description']
EVENT['properties']['work']['required'].remove('description')
EVENT['properties']['relation']['properties']['candidate_guids']=v2.array(v2.string('历史任务GUID'),True)
EVENT['properties']['relation']['required'].append('candidate_guids')
REPAIR = copy.deepcopy(INTERPRET)
REPAIR['properties']['dispositions'] = copy.deepcopy(v2.REPAIR['properties']['dispositions'])
REPAIR['required'].append('dispositions')
GAP = v2.obj(field=v2.enum(*sorted(MISSING)), status=v2.enum('not_needed','needed'),
             reason=v2.string(), evidence=v2.Q, question=v2.string(None,nullable=True))
CONTENT = v2.obj(verdict=v2.enum('supported','insufficient','contradicted'), reason=v2.string(),
                 evidence=v2.Q, missing_details=v2.array(v2.obj(description=v2.string('原话应保留的必要目的或范围'),evidence=v2.Q), True))
CHECK = copy.deepcopy(v2.CHECK)
CHECK['properties']['record_checks'] = v2.array(v2.obj(record_id=v2.string('R1'),kind=v2.enum(*sorted(KINDS)),
    reason=v2.string(),evidence=v2.Q,content=CONTENT,gap_checks=v2.array(GAP,True)))
CHECK['properties']['record_checks']['items']['properties']['kind']['example']='work'
RECHECK = copy.deepcopy(CHECK)
del RECHECK['properties']['coverage_findings'];RECHECK['required'].remove('coverage_findings')
RECHECK['properties']['disposition_checks']=copy.deepcopy(v2.RECHECK['properties']['disposition_checks'])
RECHECK['required'].append('disposition_checks')


def prompt_schema(schema):
    text=v2.prompt_schema(schema)
    import json
    def elements(node,path):
        nonlocal text
        if node['type']=='array':
            if node.get('example')==[] and node['items']['type']=='object':
                text+='\n非空 '+path+' 的每个元素必须完整包含：'+json.dumps(v2.example(node['items']),ensure_ascii=False)
            elements(node['items'],path+'[]')
        elif node['type']=='object':
            for key,value in node['properties'].items():elements(value,path+'.'+key)
    elements(schema,'$')
    text+='\n数组为空只是示例值，不表示可以省略非空元素的字段。每个输入 record_id/event_id 恰好核验一次，不重复输出相同 ID。'
    return text


def evidence_catalog(meeting):
    return {f'Q{i}':dict(segment_id=s['id'],quote=s['text'])
            for i,s in enumerate(meeting['segments'],1) if s['text']}


def adapt_interpret(raw, meeting, history, repair=False):
    v2.validate_schema(raw, REPAIR if repair else INTERPRET)
    out=copy.deepcopy(raw);catalog=evidence_catalog(meeting)
    records=rows_by_id(out['records'],'record_id')
    for r in records.values():
        r['evidence']=v2.expand_refs(r['evidence'],catalog,True)
        goal=r['need_basis'];v2.expand_refs(goal['evidence'],catalog)
        if r['kind']=='implicit_need' and (not goal['goal'] or not goal['goal'].strip() or not goal['evidence']):
            raise ValueError('Implicit need requires a source-backed goal')
        if r['kind']!='implicit_need' and (goal['goal'] is not None or goal['evidence']):
            raise ValueError('Only implicit_need carries a need goal')
    for e in out['events']:
        if e['record_id'] not in records:raise ValueError('Event references unknown record')
        if 'description' in e['work']:raise ValueError('Duplicate work description is not allowed')
        e['work']['description']=records[e['record_id']]['description']
        relation=e['relation'];choices=relation['candidate_guids']
        if len(set(choices))!=len(choices) or set(choices)-{t['guid'] for t in history['tasks']}:
            raise ValueError('Unknown or duplicate relation choices')
        if relation['kind']=='ambiguous' and len(choices)<2:raise ValueError('Ambiguous relation requires competing history choices')
        if relation['kind']!='ambiguous' and choices:raise ValueError('Only ambiguous relation has choices')
        for field in ('work','owner','commitment','time','state','relation'):
            e[field]['evidence']=v2.expand_refs(e[field]['evidence'],catalog,field=='work')
    return out


def adapt_check(raw, interpreted, catalog, recheck=False):
    v2.validate_schema(raw, RECHECK if recheck else CHECK)
    out=copy.deepcopy(raw);original=rows_by_id(interpreted['records'],'record_id')
    rows=rows_by_id(out['record_checks'],'record_id')
    if rows.keys()!=original.keys():raise ValueError('Incomplete record checks')
    for rid,row in rows.items():
        if any(k in row for k in ('verdict','issues','clarification','proposed_kind')):
            raise ValueError('Mixed record check protocol versions')
        r=original[rid];content=row['content'];v2.expand_refs(content['evidence'],catalog,True)
        if not content['reason'].strip():raise ValueError('Content check requires reason')
        for missing in content['missing_details']:
            if not missing['description'].strip():raise ValueError('Missing content needs description')
            v2.expand_refs(missing['evidence'],catalog,True)
        issues=[]
        if row['kind']!=r['kind']:issues.append('classification')
        if content['verdict']!='supported' or content['missing_details']:issues.append('work')
        gaps=rows_by_id(row['gap_checks'],'field')
        if set(r['missing_fields'])-gaps.keys():raise ValueError('Unchecked original gap')
        needed=[];questions=[]
        for gap in gaps.values():
            if 'verdict' in gap or 'blocking_for' in gap:raise ValueError('Mixed gap protocol versions')
            status=gap.pop('status');question=gap.pop('question')
            if status=='needed':
                if not isinstance(question,str) or not question.strip():raise ValueError('Needed gap requires a specific question')
                needed.append(gap['field']);questions.append(question)
            elif question is not None:raise ValueError('Closed gap cannot ask a question')
            gap.update(verdict='supported' if status=='needed' else 'unsupported',
                blocking_for=('content' if gap['field'] in ('work','reference','scope') else 'operation') if status=='needed' else 'none')
        removed=set(r['missing_fields'])-set(needed)
        issues.extend(sorted(removed))
        if r['question'] is not None and not needed:issues.append('question')
        issues=list(dict.fromkeys(issues))
        reason=row['reason']+'；'+content['reason']
        if content['missing_details']:reason+='；遗漏：'+'；'.join(m['description'] for m in content['missing_details'])
        row.update(verdict=('contradicted' if content['verdict']=='contradicted' else 'insufficient') if issues else 'supported',
            issues=issues,reason=reason,proposed_kind=row['kind'] if row['kind']!=r['kind'] else None,
            clarification=dict(status='needed' if needed else 'not_needed',basis=row['reason'],fields=needed,
                question='；'.join(dict.fromkeys(questions)) if questions else None,evidence=row['evidence']))
    return out
