"""Semantic tracking proposals; identifiers and source positions belong to code."""
import copy

from . import context_protocol as base
from .context_protocol_v4 import closed_validate
from .context_protocol_v5 import closed_schema
from .context_state import KINDS, canonical_ledger, rows_by_id


def source_catalog(meeting):
    return {s['id']:dict(segment_id=s['id'],quote=s['text']) for s in meeting['segments'] if s['text']}


def tracking_schema(payload):
    catalog=source_catalog(payload['meeting'])
    refs=base.array(base.string(next(iter(catalog),''),values=list(catalog)))
    update=base.obj(kind=base.enum(*sorted(KINDS)),description=base.string('本次原话表达的具体含义'),evidence_ids=refs)
    update['properties']['kind']['example']='work'
    thread=base.obj(entity_labels=base.array(base.string('对象名称'),True),updates=base.array(update))
    tids=[t['thread_id'] for t in (payload['previous'] or {}).get('threads',[])]
    change=base.obj(thread_id=base.string(tids[0] if tids else '',values=tids),
        entity_labels=base.array(base.string('关联对象名称'),True),updates=base.array(update))
    return closed_schema(base.obj(case_id=base.string(payload['meeting']['case_id']),
        entities=base.array(base.obj(label=base.string('仅提及的对象'),evidence_ids=refs),True),
        new_threads=base.array(thread,True),thread_updates=base.array(change,True)))


def expand_tracking(raw,payload):
    closed_validate(raw,tracking_schema(payload))
    meeting=payload['meeting'];previous=payload['previous']
    if raw['case_id']!=meeting['case_id']:raise ValueError('Wrong case_id')
    catalog=source_catalog(meeting);positions={s['id']:i for i,s in enumerate(meeting['segments'])}
    new_ids=set(payload['new_segment_ids'])
    ledger=copy.deepcopy(previous) if previous else dict(entities=[],links=[],threads=[])
    entities=rows_by_id(ledger['entities'],'entity_id');threads=rows_by_id(ledger['threads'],'thread_id')
    labels={e['label']:e for e in entities.values()}

    def allocate(prefix,used):
        i=len(used)+1
        while prefix+str(i) in used:i+=1
        return prefix+str(i)

    def spans(ids):
        if not ids or not all(i in catalog for i in ids):
            raise ValueError('Evidence must use nonempty original segment_id values from evidence_catalog')
        return [copy.deepcopy(catalog[i]) for i in dict.fromkeys(ids)]

    def entity(label,evidence):
        if not label.strip():raise ValueError('Empty entity label')
        if label not in labels:
            e=dict(entity_id=allocate('N',entities),label=label,mentions=[])
            entities[e['entity_id']]=e;labels[label]=e;ledger['entities'].append(e)
        e=labels[label]
        for span in evidence:
            if not any(s['segment_id']==span['segment_id'] and s['quote']==span['quote'] for s in e['mentions']):
                e['mentions'].append(copy.deepcopy(span))
        return e['entity_id']

    def updates(values):
        if not values:raise ValueError('Thread requires at least one grounded update')
        result=[]
        for value in values:
            evidence=spans(value['evidence_ids'])
            if not set(value['evidence_ids']) & new_ids:
                raise ValueError('An update must cite at least one new_segment_id; history is read-only')
            if not value['description'].strip():raise ValueError('Empty update description')
            latest=max(value['evidence_ids'],key=positions.__getitem__)
            result.append(dict(after_segment=latest,kind=value['kind'],description=value['description'],evidence=evidence))
        return sorted(result,key=lambda u:positions[u['after_segment']])

    for mention in raw['entities']:
        entity(mention['label'],spans(mention['evidence_ids']))
    # Validate every reference before adding new threads: output cannot reference
    # a program ID that the model predicts we might allocate in this response.
    for change in raw['thread_updates']:
        if change['thread_id'] not in threads:
            raise ValueError('Unknown existing thread; choose one of '+repr(sorted(threads))+' or use new_threads')
    additions={}
    for change in raw['thread_updates']:
        tid=change['thread_id'];fresh=updates(change['updates'])
        additions.setdefault(tid,[]).extend(fresh)
        for label in change['entity_labels']:
            eid=entity(label,[s for u in fresh for s in u['evidence']])
            if eid not in threads[tid]['entity_ids']:threads[tid]['entity_ids'].append(eid)
    for tid,fresh in additions.items():
        threads[tid]['updates'].extend(sorted(fresh,key=lambda u:positions[u['after_segment']]))
    for proposal in raw['new_threads']:
        fresh=updates(proposal['updates']);tid=allocate('T',threads)
        eids=list(dict.fromkeys(entity(label,[s for u in fresh for s in u['evidence']]) for label in proposal['entity_labels']))
        thread=dict(thread_id=tid,entity_ids=eids,updates=fresh)
        threads[tid]=thread;ledger['threads'].append(thread)
    return canonical_ledger(ledger,meeting,previous)
