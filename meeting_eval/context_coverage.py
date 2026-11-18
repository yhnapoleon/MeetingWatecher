"""Pure repair planning, checked merge and clarification contracts for context-v2.

Callers supply canonical records with record+event checks already aggregated in
check.verdict. Model semantic correspondence is a trusted input to this contract;
Q membership is validated, but shared evidence never proves shared work.
"""
import copy
import re
from .context_protocol import validate_records


def by_id(rows, key):
    result={}
    if not isinstance(rows,list):raise ValueError('Expected list')
    for row in rows:
        identity=row[key]
        if not isinstance(identity,str) or not identity or identity in result:raise ValueError('Invalid identity')
        result[identity]=row
    return result


def refs(values,catalog):
    if not isinstance(values,list) or not values or any(v not in catalog for v in values):
        raise ValueError('Missing or unknown evidence')


def supported(record):
    verdict=record['check']['verdict']
    if verdict not in ('supported','insufficient','contradicted'):raise ValueError('Invalid record check')
    return (verdict=='supported' and record.get('event_supported',True)
            and record.get('clarification',{}).get('status')!='unresolved')


def plan_repair(records,findings,catalog,scope):
    """Freeze identities once per source-version/first-check snapshot."""
    original=by_id(records,'record_id')
    targets={rid for rid,r in original.items() if not supported(r)}
    frozen=[]
    for i,f in enumerate(findings,1):
        refs(f['evidence'],catalog)
        if not isinstance(f['description'],str) or not f['description'].strip():raise ValueError('Missing finding description')
        relation=f['relation'];related=f['related_record_ids']
        if relation not in ('new_work','same_work','uncertain'):raise ValueError('Invalid finding relation')
        if not isinstance(related,list) or len(set(related))!=len(related) or set(related)-original.keys():raise ValueError('Invalid related records')
        if relation=='new_work' and related or relation=='same_work' and not related:raise ValueError('Contradictory finding relation')
        targets.update(related)
        frozen.append({**copy.deepcopy(f),'finding_id':f'O{i}'})
    return dict(scope=scope,records=copy.deepcopy(records),findings=frozen,catalog=list(catalog),
                target_record_ids=sorted(targets),needs_repair=bool(targets or frozen))


def apply_repair(plan,proposals,dispositions,finding_checks):
    """One atomic structural validation; conservative per-record semantic merge."""
    original=by_id(plan['records'],'record_id');findings=by_id(plan['findings'],'finding_id')
    baseline=dict(records=copy.deepcopy(plan['records']),unresolved_findings=copy.deepcopy(plan['findings']))
    try:
        proposed=by_id(proposals,'record_id');ds=by_id(dispositions,'finding_id');checks=by_id(finding_checks,'finding_id')
        if ds.keys()!=findings.keys() or checks.keys()!=findings.keys():raise ValueError('Incomplete finding dispositions/checks')
        targets=set(plan['target_record_ids'])
        if set(proposed)&original.keys()!=targets:raise ValueError('Missing target or changed unselected record')
        new=set(proposed)-original.keys()
        for rid,r in proposed.items():
            # Record evidence has already been aligned to source spans by the pipeline.
            supported(r)
            if rid in targets:
                if r['thread_ids']!=original[rid]['thread_ids']:raise ValueError('Changed original thread identity')
            else:
                fid=r['introduced_by']
                if fid not in findings or not re.fullmatch(re.escape('R_'+fid+'_')+r'[1-9][0-9]*',rid) or r['thread_ids']:
                    raise ValueError('Invalid added record namespace')
        referenced_new=set()
        for fid,d in ds.items():
            action=d['disposition'];ids=d['record_ids'];refs(d['evidence'],plan['catalog'])
            if action not in ('covered','added','rejected','unresolved'):raise ValueError('Invalid disposition')
            if not isinstance(ids,list) or len(set(ids))!=len(ids):raise ValueError('Invalid disposition record IDs')
            if action in ('covered','added') and (not ids or set(ids)-(original.keys()|new)):raise ValueError('Unknown covered records')
            if action in ('rejected','unresolved') and ids:raise ValueError('Unexpected disposition references')
            if action=='added':
                if not set(ids)<=new or any(proposed[r]['introduced_by']!=fid or proposed[r]['kind']!='work' for r in ids):
                    raise ValueError('Added disposition requires own new work records')
                referenced_new.update(ids)
            if action=='covered' and not set(ids)<=original.keys():raise ValueError('Covered disposition must use existing records')
            check=checks[fid];refs(check['evidence'],plan['catalog'])
            if check['verdict'] not in ('supported','insufficient','contradicted'):raise ValueError('Invalid finding check verdict')
            if check['disposition'] not in ('covered','added','rejected','unresolved') or not isinstance(check['record_ids'],list):
                raise ValueError('Invalid checked disposition')
        if referenced_new!=new:raise ValueError('Unaccounted new record')
        merged=copy.deepcopy(original);degraded=set()
        for rid in targets:
            if supported(original[rid]) and not supported(proposed[rid]):degraded.add(rid)
            else:merged[rid]=copy.deepcopy(proposed[rid])
        # A valid record must also have verified correspondence to the finding.
        unresolved=[]
        for fid,d in ds.items():
            check=checks[fid];ids=d['record_ids'];action=d['disposition']
            correspondence=(check['verdict']=='supported' and check['disposition']==action and check['record_ids']==ids)
            mapped=all(rid not in degraded and supported(proposed.get(rid,merged.get(rid))) for rid in ids)
            dependent_degradation=bool(set(findings[fid]['related_record_ids']) & degraded)
            close=correspondence and mapped and not dependent_degradation and action!='unresolved'
            if close and action=='added':
                for rid in ids:merged[rid]=copy.deepcopy(proposed[rid])
            if not close:unresolved.append(copy.deepcopy(findings[fid]))
        return dict(status='checked',records=list(merged.values()),unresolved_findings=unresolved)
    except (ValueError,KeyError,TypeError) as exc:
        return dict(status='invalid',detail=str(exc),**baseline)


def route_record(record,catalog):
    """Routing proposal only; normal does not bypass existing event permissions."""
    validate_records({'records':[record]},catalog)
    c=record['clarification']
    if not supported(record) or c['status']=='unresolved':return dict(route='unresolved',fields=[],question=None)
    if c['status']=='not_needed':return dict(route='normal',fields=[],question=None)
    content=any(g['verdict']=='supported' and g['blocking_for']=='content' for g in record['gap_checks'])
    return dict(route='content_review' if content else 'candidate_review',fields=c['fields'],question=c['question'])


def validate_check_alignment(original_records,checks):
    """Reject checks that accept a record while proposing a change to it."""
    original=by_id(original_records,'record_id');checked=by_id(checks,'record_id')
    if original.keys()!=checked.keys():raise ValueError('Incomplete record checks')
    for rid,r in original.items():
        c=checked[rid];gaps=by_id(c['gap_checks'],'field')
        if set(r['missing_fields'])-gaps.keys():raise ValueError('Unchecked original gap')
        removed={f for f in r['missing_fields'] if gaps[f]['verdict']=='unsupported' or gaps[f]['blocking_for']=='none'}
        changed_kind=c['proposed_kind'] is not None and c['proposed_kind']!=r['kind']
        cleared_question=r.get('question') is not None and c.get('clarification',{}).get('status')=='not_needed'
        if (removed or changed_kind or cleared_question) and c['verdict']=='supported':
            raise ValueError('Supported check contradicts proposed record correction')
        if removed and not (removed & set(c['issues']) or 'question' in c['issues']):
            raise ValueError('Rejected gap requires targeted repair issue')
        if changed_kind and 'classification' not in c['issues']:
            raise ValueError('Kind correction requires classification issue')
        if cleared_question and 'question' not in c['issues']:
            raise ValueError('Cleared question requires question repair issue')
