"""Check only program-selected identities; discoveries use coverage findings."""
import copy
from . import context_protocol as base
from . import context_protocol_v3 as v3
from .context_protocol_v4 import closed_validate, mutable_schema
from .context_state import rows_by_id
from .inputs import digest


def review_issues(records, events):
    """Freeze actual objections, not merely target identities, for rechecking."""
    issues=[]
    for record in records:
        for field in record['check'].get('issues',[]):
            issues.append(dict(issue_id=record['record_id']+':'+field,record_id=record['record_id'],
                field=field,reason=record['check']['reason'],evidence=record['check']['evidence']))
    for event in events:
        for field,check in event['checks'].items():
            if check['verdict']!='supported':
                issues.append(dict(issue_id=event['event_id']+':'+field,record_id=event['record_id'],
                    field=field,reason=check['reason'],evidence=check['evidence']))
    return issues


def closed_schema(schema):
    """Expose the same no-extra-fields rule that closed_validate enforces."""
    out=copy.deepcopy(schema)
    def visit(node):
        if 'properties' in node:
            node['additionalProperties']=False
            for child in node['properties'].values():visit(child)
        if 'items' in node:visit(node['items'])
    visit(out)
    return out


def check_contract(payload, recheck=False):
    records=rows_by_id(payload['records'],'record_id')
    events=rows_by_id(payload['events'],'event_id')
    source=v3.RECHECK if recheck else v3.CHECK
    record=mutable_schema(source['properties']['record_checks']['items'], ('record_id',))
    refs=base.array(base.string('Q1',values=list(v3.evidence_catalog(payload['meeting']))))
    record['properties']['qualification']=base.obj(
        speech_scope=base.enum('current','quoted','historical','uncertain'),
        work_basis=base.enum('action','work_report','goal_need','option','entity_mention','none','uncertain',
                             'meeting_discourse','unclear_intent'),
        evidence=refs,adoption_evidence={**copy.deepcopy(refs),'example':[]},reason=base.string())
    record['required'].append('qualification')
    fields=source['properties']['checks']['items']['properties']['fields']
    scope=digest(dict(protocol='context-v5-check-2-flat',payload=payload,recheck=recheck))
    schema=base.obj(case_id=base.string(payload['meeting']['case_id']),scope=base.string(scope),
        record_checks=base.obj(**{rid:copy.deepcopy(record) for rid in records}),
        checks=base.obj(**{eid+'.'+field:copy.deepcopy(value)
                          for eid in events for field,value in fields['properties'].items()}))
    remaining='disposition_checks' if recheck else 'coverage_findings'
    schema['properties'][remaining]=copy.deepcopy(source['properties'][remaining])
    schema['required'].append(remaining)
    if recheck:
        issue=base.obj(status=base.enum('resolved','overturned','unresolved'),reason=base.string(),
            evidence=base.array(base.string('Q1',values=list(v3.evidence_catalog(payload['meeting'])))))
        schema['properties']['issue_checks']=base.obj(**{i['issue_id']:copy.deepcopy(issue) for i in payload.get('review_issues',[])})
        schema['required'].append('issue_checks')
    return closed_schema(schema),dict(scope=scope)


def expand_checks(raw,payload,recheck=False):
    schema,binding=check_contract(payload,recheck)
    closed_validate(raw,schema)
    if raw['case_id']!=payload['meeting']['case_id']:raise ValueError('Wrong case_id')
    if raw['scope']!=binding['scope']:raise ValueError('Stale check scope')
    out=copy.deepcopy(raw);del out['scope']
    out['record_checks']=[dict(record_id=rid,**row) for rid,row in raw['record_checks'].items()]
    records={r['record_id']:r for r in out['record_checks']}
    for row in records.values():
        q=row['qualification']
        if not q['evidence'] or not q['reason'].strip():raise ValueError('Work qualification requires evidence and reason')
        current=q['speech_scope']=='current' or bool(q['adoption_evidence'])
        basis=q['work_basis'];kind=row['kind']
        conflict=(kind in ('work','implicit_need','ambiguous') and (not current or basis in ('option','entity_mention','none','uncertain')))
        conflict=conflict or (kind=='work' and basis=='goal_need') or (kind=='implicit_need' and basis!='goal_need')
        conflict=conflict or (kind in ('context_only','entity_only') and current and basis in ('action','work_report'))
        conflict=conflict or (basis=='meeting_discourse' and kind!='context_only')
        content_question = any(g['field'] in ('work','reference','scope') and g['status']=='needed'
                               and isinstance(g['question'],str) and g['question'].strip()
                               for g in row['gap_checks'])
        conflict=conflict or (basis=='unclear_intent' and (kind!='ambiguous' or not content_question))
        if conflict:
            row['content']['verdict']='insufficient'
            row['content']['reason']+='；工作资格与分类不一致，须回原话解决，不能预设工作再向用户追问。'
    if recheck:
        for issue in payload.get('review_issues',[]):
            check=out['issue_checks'][issue['issue_id']]
            if not check['reason'].strip() or not check['evidence']:
                raise ValueError('Issue disposition requires reason and evidence')
            if check['status']=='unresolved':
                content=records[issue['record_id']]['content']
                content['verdict']='insufficient'
                content['reason']+='；未解决的首检异议：'+check['reason']
    fields=base.CHECK['properties']['checks']['items']['properties']['fields']['properties']
    out['checks']=[dict(event_id=e['event_id'],fields={field:copy.deepcopy(raw['checks'][e['event_id']+'.'+field])
                   for field in fields}) for e in payload['events']]
    return out
