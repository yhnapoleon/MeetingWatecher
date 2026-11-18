"""Append-only tracking with program-owned verbatim evidence and source order."""
import copy

from . import context_protocol as base
from .context_protocol_v3 import evidence_catalog
from .context_protocol_v4 import closed_validate
from .context_protocol_v5 import closed_schema
from .context_state import KINDS, canonical_ledger, rows_by_id


def delta_schema(payload):
    refs = base.array(base.string('Q1', values=list(evidence_catalog(payload['meeting']))))
    update = base.obj(thread_id=base.string('T1'), kind=base.enum(*sorted(KINDS)),
        description=base.string('截至本段的具体含义'), evidence=refs)
    update['properties']['kind']['example'] = 'work'
    return closed_schema(base.obj(case_id=base.string(payload['meeting']['case_id']),
        new_entities=base.array(base.obj(entity_id=base.string('N1'), label=base.string('对象名称'), mentions=refs), True),
        entity_mentions=base.array(base.obj(entity_id=base.string('已有N编号'), mentions=refs), True),
        links=base.array(base.obj(source=base.string('N1'), target=base.string('N2'),
            relation=base.enum('same_as','related','distinct','uncertain'), evidence=refs), True),
        new_threads=base.array(base.obj(thread_id=base.string('T1'), entity_ids=base.array(base.string('N1'), True)), True),
        thread_entities=base.array(base.obj(thread_id=base.string('已有T编号'), entity_ids=base.array(base.string('N1'))), True),
        updates_by_segment=base.obj(**{sid:base.array(update, True) for sid in payload['new_segment_ids']})))


def expand_delta(raw, payload):
    closed_validate(raw, delta_schema(payload))
    meeting = payload['meeting']; previous = payload['previous']
    if raw['case_id'] != meeting['case_id']:
        raise ValueError('Wrong case_id')
    ledger = copy.deepcopy(previous) if previous else dict(entities=[], links=[], threads=[])
    entities = rows_by_id(ledger['entities'], 'entity_id')
    threads = rows_by_id(ledger['threads'], 'thread_id')
    catalog = evidence_catalog(meeting)
    positions = {s['id']:i for i,s in enumerate(meeting['segments'])}
    new_ids = set(payload['new_segment_ids'])

    def spans(refs):
        return copy.deepcopy(base.expand_refs(refs, catalog, True))

    for entity in rows_by_id(raw['new_entities'], 'entity_id').values():
        identity = entity['entity_id']
        if identity in entities:
            raise ValueError('Cannot replace existing entity')
        entity = dict(entity, mentions=spans(entity['mentions']))
        entities[identity] = entity; ledger['entities'].append(entity)
    for addition in rows_by_id(raw['entity_mentions'], 'entity_id').values():
        if addition['entity_id'] not in entities:
            raise ValueError('Unknown entity for mentions')
        entities[addition['entity_id']]['mentions'].extend(spans(addition['mentions']))
    for link in raw['links']:
        ledger['links'].append(dict(link, evidence=spans(link['evidence'])))
    for thread in rows_by_id(raw['new_threads'], 'thread_id').values():
        identity = thread['thread_id']
        if identity in threads:
            raise ValueError('Cannot replace existing thread')
        thread = dict(copy.deepcopy(thread), updates=[])
        threads[identity] = thread; ledger['threads'].append(thread)
    for addition in rows_by_id(raw['thread_entities'], 'thread_id').values():
        if addition['thread_id'] not in threads:
            raise ValueError('Unknown thread for entities')
        target = threads[addition['thread_id']]['entity_ids']
        target.extend(e for e in addition['entity_ids'] if e not in target)
    # Object key order carries no semantics. Walk only the supplied new source
    # segments; previous updates are never sorted, rewritten or removed.
    for segment in meeting['segments']:
        sid = segment['id']
        if sid not in new_ids:
            continue
        for update in raw['updates_by_segment'][sid]:
            if update['thread_id'] not in threads:
                raise ValueError('Unknown thread update')
            evidence = spans(update['evidence'])
            if any(positions[s['segment_id']] > positions[sid] for s in evidence):
                raise ValueError('Future update evidence')
            threads[update['thread_id']]['updates'].append(dict(after_segment=sid,
                kind=update['kind'], description=update['description'], evidence=evidence))
    return canonical_ledger(ledger, meeting, previous)
