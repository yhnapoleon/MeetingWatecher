"""Preserve supported new work while holding uncertain execution fields."""
import copy


def local_record_issues(event, record):
    """Only independently supported new-work content survives local field issues."""
    if not event or event['relation']['kind'] != 'new' or event['state']['kind'] != 'future_work':
        return False
    check = record['check']
    issues = set(check.get('issues', []))
    return (check['verdict'] in ('insufficient', 'contradicted') and bool(issues)
            and issues <= {'owner', 'commitment', 'time', 'question'}
            and all(event['checks'][key]['verdict'] == 'supported' for key in ('work', 'time', 'state', 'relation')))


def retain_relative_deadline(event, record):
    """A supported textual deadline need not be resolved to a calendar date."""
    time = event['time']
    if (event['relation']['kind'] == 'new' and event['state']['kind'] == 'future_work'
            and time.get('change') == 'set' and time['kind'] == 'deadline'
            and time.get('text') and time.get('date') is None
            and event['checks']['time']['verdict'] == 'supported'
            and (record['check']['verdict'] == 'supported' or local_record_issues(event, record))
            and 'time' not in record['check'].get('issues', []) and 'time' in record['missing_fields']):
        record['missing_fields'].remove('time')
        if not record['missing_fields']:
            record['question'] = None
        elif set(record['missing_fields']) <= {'owner', 'commitment'}:
            record['question'] = '这项工作是否已决定执行，若已决定由哪位负责人承接？'


def reduce_untracked_report(event, record):
    """A supported status report without a tracked task needs no new operation."""
    if (event['relation']['kind'] != 'new' or event['state']['kind'] not in ('completed','progress')
            or record['check']['verdict'] != 'supported' or record['missing_fields']
            or event['time'].get('change','keep') == 'uncertain'
            or any(event['checks'][k]['verdict'] != 'supported' for k in ('work','time','state','relation'))):
        return None
    evidence=list(dict.fromkeys(s['segment_id'] for field in ('work','owner','time','state') for s in event[field]['evidence']))
    result = dict(items=[],updates=[],pending=[],reports=[dict(target_guid=None,
        description=event['work']['description'],state=event['state']['kind'],evidence_ids=evidence,
        time=copy.deepcopy(event['time']))])
    # With no tracked task, time describes the report; there is no deadline to
    # update. Other explicit changes still need an operation we cannot perform.
    if event.get('other_changes'):
        result['pending'].append(dict(event_id=event['event_id'],reason='unsupported_task_change',evidence_ids=evidence))
        result['review_override']=dict(category='execution_blocked',missing_fields=[],question=None,
            execution_reason='工作进展已保存；当前没有关联的旧任务，无法执行所述其他字段变更。')
    return result


def reduce_new(event, record, meeting, history):
    """Return a candidate for a local hold; delegate other cases to existing policy.

    No semantic verdict is rewritten. In particular an unverified acceptance
    is not changed into an asserted assignment or a verified commitment.
    """
    if event['relation']['kind'] != 'new' or event['state']['kind'] != 'future_work':
        return None
    checks = event['checks']
    if any(checks[k]['verdict'] != 'supported' for k in ('work', 'time', 'state', 'relation')):
        return None
    conditional = (event['commitment']['kind']=='conditional' and checks['commitment']['verdict']=='supported'
                   and (record['check']['verdict']=='supported' or local_record_issues(event,record)))
    if event['commitment']['kind'] not in ('assigned', 'accepted', 'self_committed', 'decided') and not conditional:
        return None
    missing = set(record['missing_fields'])
    time_hold = 'time' in missing or event['time'].get('change') == 'uncertain'
    commitment_hold = conditional or 'commitment' in missing or checks['commitment']['verdict'] != 'supported'
    if not time_hold and not commitment_hold:
        return None
    evidence = list(dict.fromkeys(span['segment_id'] for field in
        ('work', 'owner', 'commitment', 'time', 'state', 'relation') for span in event[field]['evidence']))
    owner = event['owner']
    owner_supported = checks['owner']['verdict'] == 'supported' and 'owner' not in missing
    time = event['time']
    deadline = time['kind'] == 'deadline' and not time_hold
    item = dict(description=event['work']['description'], operation='candidate',
                owner_ref=owner.get('ref') if owner_supported else None,
                owner_kind={'person': 'corpus_person', 'group': 'group', 'speaker': 'speaker', 'unknown': None}[owner['kind']] if owner_supported else None,
                owner_label=owner.get('label') if owner_supported else None,
                due_text=time.get('text') if deadline else None, due_date=time.get('date') if deadline else None,
                action_anchor=event['work']['evidence'][0]['segment_id'], evidence_ids=evidence)
    holds = (['time'] if time_hold else []) + (['commitment'] if commitment_hold else [])
    pending = [dict(event_id=event['event_id'], reason='requirement_fields_unresolved', fields=holds,
                    item_index=0, evidence_ids=evidence, work_description=event['work']['description'])]
    if not owner_supported or owner['kind'] != 'person':
        pending.append(dict(event_id=event['event_id'], reason='owner_unverified' if not owner_supported else 'missing_personal_owner',
                            item_index=0, evidence_ids=evidence))
    return dict(items=[item], updates=[], pending=pending)
