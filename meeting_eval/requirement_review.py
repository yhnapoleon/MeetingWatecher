"""Explicit user decisions on review records; never impersonate meeting acceptance."""
import json
from datetime import date

from .inputs import digest, dumps, instant


def requirements(service,sid,viewer):
    if not service.source_readable(sid,viewer):
        raise PermissionError('Requirement read denied')
    records=service.result(sid)['extraction'].get('_task_trace',{}).get('review_records',[])
    result=[]
    for record in records:
        row=service.store.db.execute('SELECT body FROM requirement_decisions WHERE source_id=? AND record_id=?',
                                    (sid,record['record_id'])).fetchone()
        resolution=json.loads(row['body']) if row else None
        if resolution and resolution.get('intent_id'):
            resolution['task_guid']=service.store.binding(resolution['intent_id'])
            intent=service.store.db.execute('SELECT status FROM intents WHERE id=?',(resolution['intent_id'],)).fetchone()
            resolution['intent_status']=intent['status'] if intent else 'missing'
        result.append({**record,'resolution':resolution})
    return result


def resolve_requirement(service,sid,rid,actor,decision,observed_at):
    records=requirements(service,sid,actor)
    current=service.current_source(sid)
    if actor not in current['writers']:
        raise PermissionError('Requirement decision requires source write access')
    row=service.store.db.execute('SELECT body FROM sources WHERE id=?',(sid,)).fetchone()
    source=json.loads(row['body'])
    if current['version']!=source['version']:
        raise ValueError('Source changed; review the current version')
    record=next((r for r in records if r['record_id']==rid),None)
    if record is None:
        raise ValueError('Unknown review record')
    if not isinstance(decision,dict) or decision.get('decision') not in ('add_task','adopt_and_add_task','clarify_and_add_task','dismiss','ask_issuer'):
        raise ValueError('Invalid review decision')
    kind=decision['decision']
    if record['category']=='execution_blocked' and kind!='dismiss':
        raise ValueError('This is an unsupported operation, not a missing user decision')
    creates_task = kind in ('add_task', 'adopt_and_add_task', 'clarify_and_add_task')
    allowed={'decision','description','owner_ref','due_date','due_text'} if creates_task else {'decision'}
    if set(decision)-allowed:
        raise ValueError('Unexpected decision fields')
    clean={'decision':kind}
    if creates_task:
        if kind == 'clarify_and_add_task':
            if not record.get('requires_clarification') or not record.get('can_clarify_as_new_task'):
                raise ValueError('This record cannot be clarified as a new task')
        elif record.get('requires_clarification'):
            raise ValueError('Explicit clarification required before creating a task')
        elif kind == 'adopt_and_add_task':
            if not record.get('requires_adoption'):
                raise ValueError('This record is not awaiting adoption')
        elif record.get('requires_adoption'):
            raise ValueError('Explicit adoption required before creating a task')
        elif not record['can_add_task']:
            raise ValueError('Resolve existing task relation before creating a task')
        description=decision.get('description')
        owner=source['account_map'].get(decision.get('owner_ref'))
        if not isinstance(description,str) or not description.strip() or not owner or owner not in current['audience']:
            raise ValueError('Provide final description and an authorized mapped owner')
        clean.update(description=description.strip(),owner_ref=decision['owner_ref'])
        for key in ('due_date','due_text'):
            value=decision.get(key)
            if value is not None and (not isinstance(value,str) or not value.strip()):
                raise ValueError('Invalid confirmed time')
            clean[key]=value
        if clean['due_date']:date.fromisoformat(clean['due_date'])
    previous=record['resolution']
    if previous and previous['decision'] in ('add_task','adopt_and_add_task','clarify_and_add_task','dismiss'):
        if previous['input']!=clean:
            raise ValueError('Review record already resolved with a different decision')
        service.recover(actor=actor,observed_at=observed_at)
        return next(r['resolution'] for r in requirements(service,sid,actor) if r['record_id']==rid)
    at=instant(observed_at)
    resolution=dict(source_id=sid,record_id=rid,actor=actor,observed_at=at,decision=kind,input=clean,intent_id=None)
    if kind=='ask_issuer':
        resolution.update(question=record['question'],issuer_ref=record['issuer_ref'],delivery='not_sent')
    output=service.result(sid)
    with service.store.db:
        if creates_task:
            iid=digest([sid,'manual_requirement',rid])
            resolution['intent_id']=iid
            refs={s['id']:s for s in source['segments']}
            payload=dict(summary=clean['description'],assignee=owner,due_date=clean['due_date'],due_text=clean['due_text'],
                readers=current['audience'],writers=list(set(current['writers']+[owner])),tenant=source['tenant'],series=source['series'],
                source_id=sid,origin=source['meeting_id'],source_readers=current['audience'],
                evidence=[refs[e] for e in record['evidence_ids']],manual_decision=dict(actor=actor,record_id=rid,observed_at=at))
            intent=dict(id=iid,source_id=sid,operation='create',actor=actor,observed_at=at,payload=payload,
                        evidence_ids=record['evidence_ids'],policy='explicit_user_requirement_confirmation',source_version=source['version'])
            service.store.db.execute('INSERT OR IGNORE INTO intents VALUES (?,?,?,NULL)',(iid,dumps(intent),'pending'))
            service.store.log('proposed',intent)
            if iid not in output['intent_ids']:output['intent_ids'].append(iid)
            service.store.db.execute('UPDATE sources SET result=? WHERE id=?',(dumps(output),sid))
        service.store.db.execute('INSERT OR REPLACE INTO requirement_decisions VALUES (?,?,?)',(sid,rid,dumps(resolution)))
        service.store.log('requirement_decision',resolution)
    service.recover(actor=actor,observed_at=at)
    return next(r['resolution'] for r in requirements(service,sid,actor) if r['record_id']==rid)
