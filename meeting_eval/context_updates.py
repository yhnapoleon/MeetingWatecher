"""Explicit date operations for existing context-v1 tasks; no platform permissions here."""
from datetime import date


def validate_time_changes(events):
    for event in events:
        time=event['time'];change=time.get('change')
        if change not in ('keep','set','clear','uncertain'):
            raise ValueError('Context time requires keep/set/clear/uncertain change')
        if change=='set' and (time['kind']!='deadline' or not time['evidence'] or not time.get('text')):
            raise ValueError('Setting a deadline requires current deadline evidence')
        if change=='clear' and (time['kind']!='unspecified' or time.get('date') is not None or not time.get('text') or not time['evidence']):
            raise ValueError('Clearing a deadline requires explicit cancellation evidence')


def validate_changes(update,source_ids):
    changes=update['changes']
    if not isinstance(changes,dict) or not changes or set(changes)-{'status','due_date','due_text'}:
        raise ValueError('Invalid task change fields')
    if 'status' in changes and changes['status'] not in ('open','done'):
        raise ValueError('Invalid proposed status')
    if 'status' in update and update['status']!=changes.get('status'):
        raise ValueError('Conflicting status change')
    has_time=bool(set(changes)&{'due_date','due_text'})
    required=set()
    if 'status' in changes:required.add('state')
    if has_time:
        if not {'due_date','due_text'}<=changes.keys():raise ValueError('Date and date text must change together')
        value,text=changes['due_date'],changes['due_text']
        if value is None:
            if text is not None:raise ValueError('Cleared date must clear text')
        else:
            if not isinstance(value,str) or not isinstance(text,str) or not text.strip():raise ValueError('Invalid changed deadline')
            date.fromisoformat(value)
        required.add('time')
    refs=update.get('field_evidence_ids')
    if not isinstance(refs,dict) or set(refs)!=required:
        raise ValueError('Changed fields require their own evidence')
    for values in refs.values():
        if not isinstance(values,list) or not values or not all(isinstance(v,str) for v in values) or not set(values)<=set(update['evidence_ids'])&source_ids:
            raise ValueError('Invalid field evidence')


def deadline_question(event,owner=False):
    time=event['time'];who='负责人是否确认' if owner else '是否确定'
    if time.get('change')=='clear':return who+'取消这项任务的截止日期？'
    if time.get('date'):return who+'将这项任务的截止日期改为'+time['date']+'？'
    return '这项任务的新截止日期具体是哪一天？'


def reduce_existing(event,record,meeting):
    """Return None for an unresolved relation, preserving the old refusal path."""
    if event['relation']['kind']!='existing':return None
    out=dict(items=[],updates=[],pending=[],reports=[])
    checks=event['checks'];time=event['time'];change=time.get('change','keep');state=event['state']['kind']
    ids=lambda spans:list(dict.fromkeys(s['segment_id'] for s in spans))
    evidence=ids([s for field in ('work','owner','commitment','time','state','relation') for s in event[field]['evidence']])
    def pending(reason,missing,question,*,capability=False):
        out['pending'].append(dict(event_id=event['event_id'],reason=reason,evidence_ids=evidence,work_description=event['work']['description']))
        out['review_override']=dict(category='execution_blocked' if capability else 'ambiguous',
            missing_fields=missing,question=question,
            execution_reason='当前仅支持完成、重新打开和截止日期变更；当前不支持这项其他字段修改，已保留但未执行。' if capability else None)
        return out
    bad=[k for k in ('work','time','state','relation') if checks[k]['verdict']!='supported']
    if bad:return pending('event_not_supported',bad,record['question'] or '请确认这次汇报对应的工作、状态或时间。')
    if change=='uncertain':return pending('deadline_change_unconfirmed',['time'],deadline_question(event))
    if change=='set' and not time.get('date'):
        return pending('deadline_date_unresolved',['time'],'这项任务的新截止日期具体是哪一天？')
    changes={};field_refs={}
    if state in ('completed','reopened'):
        changes['status']='done' if state=='completed' else 'open';field_refs['state']=ids(event['state']['evidence'])
    if change in ('set','clear'):
        source={s['id']:s for s in meeting['segments']}
        witnesses={source[s['segment_id']].get('person_ref') for s in time['evidence']}
        if (checks['commitment']['verdict']!='supported' or event['commitment']['kind'] not in ('accepted','self_committed')
                or 'commitment' in record['missing_fields'] or event['owner'].get('ref') not in witnesses):
            return pending('deadline_change_unconfirmed',['time'],deadline_question(event,True))
        changes.update(due_date=time['date'] if change=='set' else None,due_text=time['text'] if change=='set' else None)
        field_refs.update(time=ids(time['evidence']))
    if changes:
        if checks['owner']['verdict']!='supported' or event['owner']['kind']!='person' or 'owner' in record['missing_fields']:
            return pending('update_owner_unverified',['owner'],'这次任务变更是否由对应负责人确认？')
        out['updates'].append(dict(target_guid=event['relation']['target_guid'],description=event['work']['description'],
            owner_ref=event['owner']['ref'],effective_at=None,evidence_ids=evidence,changes=changes,field_evidence_ids=field_refs))
        if event.get('other_changes'):return pending('unsupported_task_change',[],None,capability=True)
        return out
    if event.get('other_changes'):return pending('unsupported_task_change',[],None,capability=True)
    if state in ('progress','future_work'):
        out['reports'].append(dict(target_guid=event['relation']['target_guid'],description=event['work']['description'],evidence_ids=evidence))
        return out
    return pending('unsupported_task_change',[],None,capability=True)
