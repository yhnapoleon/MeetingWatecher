"""Source spans and task events. Validation is distinct from semantic support."""
import copy
from datetime import date
from typing import TypedDict


class EvidenceSpan(TypedDict):
    segment_id: str
    start: int
    end: int
    quote: str


class WorkCandidate(TypedDict):
    candidate_id: str
    spans: list[EvidenceSpan]


class TaskEvent(TypedDict):
    event_id: str
    candidate_ids: list[str]
    work: dict
    owner: dict
    commitment: dict
    time: dict
    state: dict
    relation: dict


class CheckedEvent(TaskEvent):
    checks: dict


EVENT_FIELDS = ('work','owner','commitment','time','state','relation')
KINDS = {
    'owner':{'person','group','speaker','unknown'},
    'commitment':{'suggested','assigned','self_committed','accepted','decided','declined','conditional','unknown'},
    'time':{'deadline','work_window','unspecified'},
    'state':{'future_work','progress','completed','reopened','revised','unknown'},
    'relation':{'new','existing','ambiguous','unknown'},
}


def validate_spans(spans, meeting):
    source = {s['id']:s['text'] for s in meeting['segments']}
    if not isinstance(spans,list):
        raise ValueError('Evidence must be a list')
    for span in spans:
        text = source.get(span['segment_id'])
        start,end = span['start'],span['end']
        if (text is None or type(start) is not int or type(end) is not int or
                not 0 <= start < end <= len(text) or text[start:end] != span['quote']):
            raise ValueError('Invalid evidence span')


def align_spans(raw_spans, meeting):
    """Locate exact quotes in source; never invent offsets or accept fuzzy text."""
    source = {s['id']:s['text'] for s in meeting['segments']}
    if not isinstance(raw_spans,list):
        raise ValueError('Evidence must be a list')
    result = []
    for raw in raw_spans:
        sid,quote = raw['segment_id'],raw['quote']
        if sid not in source or not isinstance(quote,str) or not quote:
            raise ValueError('Invalid quote source')
        if 'start' in raw or 'end' in raw:
            span = {k:raw[k] for k in ('segment_id','start','end','quote')}
        else:
            positions = []
            at = source[sid].find(quote)
            while at >= 0:
                positions.append(at)
                at = source[sid].find(quote,at+1)
            occurrence = raw.get('occurrence')
            if len(positions)==1 and occurrence is None:
                occurrence = 1
            if type(occurrence) is not int or not 1 <= occurrence <= len(positions):
                raise ValueError('Missing or ambiguous exact quote; provide occurrence')
            start = positions[occurrence-1]
            span = dict(segment_id=sid,start=start,end=start+len(quote),quote=quote)
        validate_spans([span],meeting)
        if span not in result:
            result.append(span)
    return result


def validate_events(events, candidates, meeting, history):
    if not isinstance(events,list):
        raise ValueError('Missing events list')
    ids = {c['candidate_id'] for c in candidates}
    targets = {t['guid'] for t in history['tasks']}
    seen = set()
    for event in events:
        eid = event['event_id']
        if not isinstance(eid,str) or not eid or eid in seen:
            raise ValueError('Invalid event identity')
        seen.add(eid)
        refs = event['candidate_ids']
        if not isinstance(refs,list) or not refs or len(set(refs))!=len(refs) or not set(refs)<=ids:
            raise ValueError('Event lacks known candidate provenance')
        for field in EVENT_FIELDS:
            value = event[field]
            validate_spans(value['evidence'],meeting)
            if field in KINDS and value['kind'] not in KINDS[field]:
                raise ValueError('Invalid event kind: '+field)
        work = event['work']
        if not isinstance(work.get('description'),str) or not work['description'].strip() or not work['evidence']:
            raise ValueError('Work requires description and evidence')
        owner = event['owner']
        if owner['kind']=='person':
            if owner.get('ref') not in meeting['roster'] or not owner['evidence']:
                raise ValueError('Unknown or unsupported person reference')
        elif owner.get('ref') is not None:
            raise ValueError('Non-person owner cannot carry a person reference')
        if owner.get('label') is not None and not isinstance(owner['label'],str):
            raise ValueError('Invalid owner label')
        commitment = event['commitment']
        if commitment['kind'] in ('accepted','self_committed','decided') and not commitment['evidence']:
            raise ValueError('Commitment requires evidence')
        temporal = event['time']
        for field in ('text','date'):
            if temporal.get(field) is not None and not isinstance(temporal[field],str):
                raise ValueError('Invalid time field')
        if temporal.get('date'):
            date.fromisoformat(temporal['date'])
        if temporal['kind']=='deadline' and (not temporal.get('text') or not temporal['evidence']):
            raise ValueError('Deadline requires explicit text and evidence')
        relation = event['relation']
        target = relation.get('target_guid')
        if relation['kind']=='existing':
            if target not in targets:
                raise ValueError('Task target outside authorized history')
        elif target is not None:
            raise ValueError('Unresolved relation cannot name one task target')


def canonical_events(raw_events, candidates, meeting, history):
    if not isinstance(raw_events,list):
        raise ValueError('Missing events list')
    events = []
    expanded = copy.deepcopy(candidates)
    for i,raw in enumerate(raw_events,1):
        event = dict(event_id=f'E{i}',candidate_ids=raw['candidate_ids'])
        for field in EVENT_FIELDS:
            event[field] = copy.deepcopy(raw[field])
            event[field]['evidence'] = align_spans(raw[field]['evidence'],meeting)
        if event['candidate_ids']==[] and event['work']['evidence']:
            cid = f'C{len(expanded)+1}'
            expanded.append(dict(candidate_id=cid,spans=copy.deepcopy(event['work']['evidence']),origin='interpret_work'))
            event['candidate_ids'] = [cid]
        events.append(event)
    validate_events(events,expanded,meeting,history)
    return events,expanded


def canonical_checks(raw, events, meeting):
    rows = raw['checks']
    if not isinstance(rows,list):
        raise ValueError('Missing checks list')
    by_id = {r['event_id']:r for r in rows}
    expected={e['event_id'] for e in events}
    if len(by_id)!=len(rows) or set(by_id)!=expected:
        duplicates=sorted({r['event_id'] for r in rows if sum(x['event_id']==r['event_id'] for x in rows)>1})
        raise ValueError('Event check identity mismatch: missing='+str(sorted(expected-set(by_id)))+
                         ', extra='+str(sorted(set(by_id)-expected))+', duplicate='+str(duplicates))
    checked = []
    for event in events:
        checks = by_id[event['event_id']]['fields']
        if not isinstance(checks,dict) or set(checks)!=set(EVENT_FIELDS):
            raise ValueError('Incomplete field checks')
        clean = {}
        for field,value in checks.items():
            if value['verdict'] not in ('supported','contradicted','insufficient') or not isinstance(value.get('reason'),str) or not value['reason'].strip():
                raise ValueError('Invalid semantic verdict')
            clean[field] = dict(verdict=value['verdict'],reason=value['reason'],evidence=align_spans(value['evidence'],meeting))
            if field=='work' and value['verdict']=='supported' and not clean[field]['evidence']:
                raise ValueError('Supported work requires a citation')
        checked.append({**copy.deepcopy(event),'checks':clean})
    return dict(checked_events=checked,uncovered_spans=align_spans(raw['uncovered_spans'],meeting))


def reduce_task_events(checked_events, uncovered_spans, meeting, history):
    """Generate proposals only. Service remains responsible for actual writes."""
    result = dict(items=[],updates=[],pending=[])
    source = {s['id']:s for s in meeting['segments']}
    for event in checked_events:
        evidence = list(dict.fromkeys(s['segment_id'] for field in EVENT_FIELDS for s in event[field]['evidence']))
        def pending(reason, **extra):
            if all(event['checks'][k]['verdict']=='supported' for k in ('work','time')):
                extra['work_description'] = event['work']['description']
            result['pending'].append(dict(event_id=event['event_id'],reason=reason,evidence_ids=evidence,**extra))
        checks = event['checks']
        # A rejected time claim may also be embedded in the task title. Clearing
        # due fields alone cannot make that title safe to write.
        state,relation = event['state']['kind'],event['relation']['kind']
        required = ['work','time','state','relation']
        # Reporting an existing task's state is not a fresh promise to do work.
        # Creation still requires a supported commitment below.
        if not (state in ('completed','reopened') and relation=='existing'):
            required.append('commitment')
        unsupported = [k for k in required if checks[k]['verdict']!='supported']
        if unsupported:
            pending('event_not_supported',fields=unsupported,details={k:checks[k]['reason'] for k in unsupported})
            continue
        if relation in ('ambiguous','unknown'):
            pending('ambiguous_task_relation')
            continue
        owner = event['owner']
        owner_supported = checks['owner']['verdict']=='supported'
        if state in ('completed','reopened') and relation=='existing':
            if owner_supported and owner['kind']=='person':
                result['updates'].append(dict(target_guid=event['relation']['target_guid'],
                    description=event['work']['description'],owner_ref=owner['ref'],
                    status='done' if state=='completed' else 'open',effective_at=None,evidence_ids=evidence))
            else:
                pending('update_owner_unverified')
            continue
        if state!='future_work' or relation!='new':
            pending('no_supported_state_change')
            continue
        commitment = event['commitment']['kind']
        if commitment not in ('assigned','accepted','self_committed','decided'):
            pending('commitment_'+commitment)
            continue
        owner_ref = owner.get('ref') if owner_supported else None
        owner_kind = {'person':'corpus_person','group':'group','speaker':'speaker','unknown':None}[owner['kind']] if owner_supported else None
        witnesses = {source[s['segment_id']].get('person_ref') for s in event['commitment']['evidence']}
        accepted = commitment in ('accepted','self_committed') and owner_ref is not None and owner_ref in witnesses
        operation = 'create' if accepted and owner_kind=='corpus_person' else 'candidate'
        time = event['time']
        deadline = time['kind']=='deadline' and checks['time']['verdict']=='supported'
        item = dict(description=event['work']['description'],operation=operation,owner_kind=owner_kind,
            owner_ref=owner_ref,owner_label=owner.get('label') if owner_supported else None,
            due_text=time.get('text') if deadline else None,due_date=time.get('date') if deadline else None,
            action_anchor=event['work']['evidence'][0]['segment_id'],evidence_ids=evidence)
        result['items'].append(item)
        if operation=='candidate':
            reason = 'owner_unverified' if not owner_supported else 'unaccepted_assignment' if commitment=='assigned' else 'personal_acceptance_unverified' if owner_kind=='corpus_person' else 'missing_personal_owner'
            pending(reason,item_index=len(result['items'])-1)
    for span in uncovered_spans:
        result['pending'].append(dict(reason='possible_missed_work',evidence_ids=[span['segment_id']],quote=span['quote']))
    return result
