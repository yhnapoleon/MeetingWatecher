"""Evidence-backed context snapshots and reviewable requirements, not task permissions."""
import copy

from .inputs import digest
from .task_events import align_spans, reduce_task_events
from .context_new_work import retain_relative_deadline, reduce_new, local_record_issues, reduce_untracked_report
from .context_updates import reduce_existing, deadline_question

KINDS = {'work','implicit_need','ambiguous','entity_only','context_only','deferred_topic','withdrawn','resolved'}
MISSING = {'work','reference','owner','commitment','time','scope','relation'}
ISSUES = MISSING | {'classification','state','question'}


def rows_by_id(rows, key):
    if not isinstance(rows,list):
        raise ValueError('Missing list: '+key)
    result = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity,str) or not identity or identity in result:
            raise ValueError('Invalid identity: '+key)
        result[identity] = row
    return result


def nonempty(value):
    return isinstance(value,str) and bool(value.strip())


def canonical_ledger(raw, meeting, previous):
    ledger = {k:copy.deepcopy(raw[k]) for k in ('entities','links','threads')}
    entities = rows_by_id(ledger['entities'],'entity_id')
    threads = rows_by_id(ledger['threads'],'thread_id')
    positions = {s['id']:i for i,s in enumerate(meeting['segments'])}
    for entity in entities.values():
        entity['mentions'] = align_spans(entity['mentions'],meeting)
        if not nonempty(entity.get('label')) or not entity['mentions']:
            raise ValueError('Entity requires label and mentions')
    if not isinstance(ledger['links'],list):
        raise ValueError('Missing links')
    for link in ledger['links']:
        if (link['source'] not in entities or link['target'] not in entities or
                link['relation'] not in ('same_as','related','distinct','uncertain')):
            raise ValueError('Invalid entity link')
        link['evidence'] = align_spans(link['evidence'],meeting)
        if not link['evidence']:
            raise ValueError('Entity link requires evidence')
    for thread in threads.values():
        if not isinstance(thread['entity_ids'],list) or not set(thread['entity_ids']) <= entities.keys():
            raise ValueError('Unknown thread entity')
        if not isinstance(thread['updates'],list) or not thread['updates']:
            raise ValueError('Thread requires updates')
        last = -1
        for update in thread['updates']:
            end = positions.get(update['after_segment'],-1)
            update['evidence'] = align_spans(update['evidence'],meeting)
            if end >= 0 and update['evidence']:
                end = max(end,max(positions[s['segment_id']] for s in update['evidence']))
                update['after_segment'] = meeting['segments'][end]['id']
            if (end < last or end < 0 or update['kind'] not in KINDS or
                    not nonempty(update.get('description')) or not update['evidence'] or
                    any(positions[s['segment_id']] > end for s in update['evidence'])):
                raise ValueError('Invalid or future thread update')
            last = end
    if previous:
        for old in previous['entities']:
            new = entities.get(old['entity_id'])
            if not new or old['label'] != new['label'] or any(s not in new['mentions'] for s in old['mentions']):
                raise ValueError('Entity history changed')
        if any(link not in ledger['links'] for link in previous['links']):
            raise ValueError('Link history changed')
        for old in previous['threads']:
            new = threads.get(old['thread_id'])
            if (not new or new['updates'][:len(old['updates'])] != old['updates'] or
                    not set(old['entity_ids']) <= set(new['entity_ids'])):
                raise ValueError('Thread history changed')
    return ledger


def ledger_candidates(ledger):
    candidates = []
    for thread in ledger['threads']:
        spans = []
        for update in thread['updates']:
            for span in update['evidence']:
                if span not in spans:
                    spans.append(span)
        candidates.append(dict(candidate_id='C'+str(len(candidates)+1),thread_id=thread['thread_id'],spans=spans))
    return candidates


def canonical_records(raw, ledger, events, meeting):
    records = copy.deepcopy(raw)
    by_id = rows_by_id(records,'record_id')
    tids = {t['thread_id'] for t in ledger['threads']}
    covered = set()
    for record in records:
        refs = record['thread_ids']
        if not isinstance(refs,list) or not set(refs) <= tids:
            raise ValueError('Unknown requirement thread')
        covered.update(refs)
        if record['kind'] not in KINDS or record['content_basis'] not in ('explicit','contextual','inferred','unknown'):
            raise ValueError('Invalid requirement classification')
        if not nonempty(record.get('description')):
            raise ValueError('Requirement lacks description')
        record['evidence'] = align_spans(record['evidence'],meeting)
        if not record['evidence']:
            raise ValueError('Requirement lacks evidence')
        if not isinstance(record['missing_fields'],list) or not set(record['missing_fields']) <= MISSING:
            raise ValueError('Invalid missing fields')
        if record['question'] is not None and not nonempty(record['question']):
            raise ValueError('Invalid clarification question')
        if record['issuer_ref'] is not None and record['issuer_ref'] not in meeting['roster']:
            raise ValueError('Unknown issuer')
        if record['kind'] in ('implicit_need','ambiguous') and not nonempty(record['question']):
            raise ValueError('Unclear requirement needs a question')
        if record['kind'] in ('context_only','deferred_topic') and (record['missing_fields'] or record['question'] is not None):
            raise ValueError('Context-only record cannot require task clarification')
    if covered != tids:
        raise ValueError('Requirement thread coverage incomplete')
    used = set()
    for event in events:
        rid = event['record_id']
        if rid not in by_id or rid in used:
            raise ValueError('Event requires a unique requirement record')
        if by_id[rid]['kind'] in ('entity_only','context_only','deferred_topic','withdrawn','resolved'):
            raise ValueError('Closed record cannot carry an event; separate the remaining work')
        used.add(rid)
    if any(r['kind']=='work' and r['record_id'] not in used for r in records):
        raise ValueError('Work record requires an event')
    return records


def check_records(raw, records, meeting):
    rows = rows_by_id(raw,'record_id')
    if set(rows) != {r['record_id'] for r in records}:
        raise ValueError('Incomplete requirement checks')
    checked = []
    for record in records:
        row = rows[record['record_id']]
        if row['verdict'] not in ('supported','insufficient','contradicted') or not nonempty(row['reason']):
            raise ValueError('Invalid requirement check')
        evidence = align_spans(row['evidence'],meeting)
        if row['verdict']=='supported' and not evidence:
            raise ValueError('Supported requirement requires evidence')
        issues = row.get('issues',[])
        if (not isinstance(issues,list) or not set(issues) <= ISSUES or
                (row['verdict']=='supported' and issues) or
                (row['verdict']!='supported' and not issues)):
            raise ValueError('Requirement check needs specific valid issues')
        checked.append({**record,'check':dict(verdict=row['verdict'],reason=row['reason'],evidence=evidence,issues=issues)})
    return checked


def record_content_supported(record):
    check = record['check']
    # A local failure does not disprove content, but must still block the
    # corresponding execution field below. Contradictions never pass here.
    issues = set(check.get('issues',[]))
    return check['verdict']=='supported' or (check['verdict']=='insufficient' and
        bool(issues) and issues <= {'owner','commitment','question'})


def reduce_context(checked_events, uncovered_spans, records, meeting, history):
    records = copy.deepcopy(records)
    event_map = {e['record_id']:e for e in checked_events}
    for record in records:
        # v2+ gap checks distinguish an incorrect old claim from an actual gap.
        # Only legacy records need to derive gaps from check issues.
        if 'gap_checks' not in record:
            record['missing_fields'] = list(dict.fromkeys(record['missing_fields'] +
                [f for f in record['check'].get('issues',[]) if f in MISSING]))
        if any(e['record_id']==record['record_id'] and e['relation']['kind']=='new' and e['time'].get('change')=='uncertain' for e in checked_events):
            if 'time' not in record['missing_fields']:record['missing_fields'].append('time')
        if record['record_id'] in event_map:
            retain_relative_deadline(event_map[record['record_id']],record)
    allowed = {r['record_id'] for r in records if r['kind']=='work' and
               r['content_basis'] in ('explicit','contextual') and
               (record_content_supported(r) or local_record_issues(event_map.get(r['record_id']),r)) and
               not set(r['missing_fields']) & {'work','reference','scope','relation'} and
               ('time' not in r['missing_fields'] or event_map.get(r['record_id'],{}).get('relation',{}).get('kind')=='new')}
    events = [e for e in checked_events if e['record_id'] in allowed]
    result = reduce_task_events([],uncovered_spans,meeting,history)
    result['item_records'] = []
    result['reports'] = []
    result['deferred_topics'] = [dict(record_id=r['record_id'],description=r['description'],
        evidence_ids=list(dict.fromkeys(s['segment_id'] for s in r['evidence'])))
        for r in records if r['kind']=='deferred_topic' and r['check']['verdict']=='supported']
    result['context_records'] = [dict(record_id=r['record_id'],description=r['description'],
        evidence_ids=list(dict.fromkeys(s['segment_id'] for s in r['evidence'])))
        for r in records if r['kind']=='context_only' and r['check']['verdict']=='supported']
    by_id = {r['record_id']:r for r in records}
    reduced = {}
    for event in events:
        event=copy.deepcopy(event)
        record=by_id[event['record_id']]
        time=event['time']
        if (event['relation']['kind']=='new' and event['state']['kind']=='future_work'
                and time['kind']=='work_window' and time.get('text')
                and time.get('change')!='uncertain' and 'time' not in record['missing_fields']
                and all(event['checks'][f]['verdict']=='supported' for f in ('work','time'))
                and time['text'] not in record['description']):
            record['description']+='（工作时段：'+time['text']+'）'
            event['work']['description']=record['description']
        single = reduce_existing(event,by_id[event['record_id']],meeting)
        if single is None:single = reduce_untracked_report(event,by_id[event['record_id']])
        if single is None:single = reduce_new(event,by_id[event['record_id']],meeting,history)
        if single is None:single = reduce_task_events([event],[],meeting,history)
        missing = set(by_id[event['record_id']]['missing_fields'])
        for i,item in enumerate(single['items']):
            if missing & {'owner','commitment'}:
                item['operation']='candidate'
                if 'owner' in missing:item.update(owner_ref=None,owner_kind=None,owner_label=None)
                single['pending'].append(dict(event_id=event['event_id'],reason='requirement_fields_unresolved',item_index=i,evidence_ids=item['evidence_ids']))
        if single['updates'] and 'owner' in missing:
            single['updates']=[]
            single['pending'].append(dict(event_id=event['event_id'],reason='update_owner_unverified',evidence_ids=[s['segment_id'] for s in event['work']['evidence']]))
        reduced[event['record_id']]=single
        offset=len(result['items'])
        result['pending'].extend({**p,**({'item_index':p['item_index']+offset} if 'item_index' in p else {})} for p in single['pending'])
        result['items'].extend(single['items'])
        result['updates'].extend(single['updates'])
        result['reports'].extend(single.get('reports',[]))
        result['item_records'].extend([event['record_id']] * len(single['items']))
    event_map = {e['record_id']:e for e in checked_events}
    reviews = []
    for record in records:
        if record['kind'] in ('entity_only','context_only','deferred_topic','withdrawn','resolved') and record['check']['verdict']=='supported':
            continue
        event = event_map.get(record['record_id'])
        single = reduced.get(record['record_id'])
        if single and not single['pending']:
            continue
        category = 'implicit_need' if record['kind']=='implicit_need' or record['content_basis']=='inferred' else 'ambiguous'
        missing = list(record['missing_fields'])
        if event:
            existing=event['relation']['kind']=='existing'
            report=(event['state']['kind'] in ('progress','completed','reopened') and
                    event['checks']['commitment']['verdict']=='supported')
            for field in ('work','owner','commitment','time','state','relation'):
                if (existing or report) and field=='commitment':continue
                if event['checks'][field]['verdict']!='supported' and field not in missing:
                    missing.append(field)
            if not existing and not report and event['commitment']['kind'] not in ('self_committed','accepted','decided') and 'commitment' not in missing:
                missing.append('commitment')
            if (event['relation']['kind']=='ambiguous' and event['checks']['relation']['verdict']=='supported'
                    and 'relation' not in missing):
                missing.append('relation')
        if single:
            reasons={p['reason'] for p in single['pending']}
            if reasons & {'missing_personal_owner','owner_unverified','update_owner_unverified'} and 'owner' not in missing:
                missing.append('owner')
        questions = dict(work='具体要做什么？',reference='这里指的是哪个对象？',
            owner='这项已明确的工作由哪位具体负责人执行？',commitment='这项工作是否已决定执行或由对应负责人承接？',
            time='这项工作的时间安排是什么？',scope='尚未确定的工作范围是什么？',relation='这项工作对应哪条已有任务？',state='这项工作的当前状态是什么？')
        question = record['question'] or '；'.join(questions[f] for f in missing)
        if record['question'] and 'relation' in missing and 'relation' not in record['missing_fields']:
            question+='；'+questions['relation']
        if set(missing)=={'owner'}:
            question='这项已明确的工作由哪位具体负责人执行？'
        elif set(missing)=={'commitment'}:
            question=('这项分派是否已由对应负责人承接？' if event and event['commitment']['kind']=='assigned'
                      else '这项工作是否已经由对应负责人承接，还是尚待决定？')
        if event and set(missing)=={'time'} and not record['question']:
            question=deadline_question(event)
        commitment_details={}
        if (event and record['kind']=='work' and (record_content_supported(record) or local_record_issues(event,record))
                and event['relation']['kind']=='new' and event['state']['kind']=='future_work'
                and event['checks']['commitment']['verdict']=='supported'
                and event['checks']['work']['verdict']=='supported'):
            commitment=event['commitment']['kind']
            if commitment in ('suggested','conditional'):
                commitment_details=dict(commitment_kind=commitment,
                    commitment_quotes=list(dict.fromkeys(s['quote'] for s in event['commitment']['evidence'])))
                category='proposal' if commitment=='suggested' else 'conditional_work'
                if set(missing) <= {'owner','commitment'}:
                    question=('是否采纳这项提议？采纳后可再明确负责人。' if commitment=='suggested'
                              else '这项工作所附的条件是否成立，是否据此继续执行？')
        override=single.get('review_override',{}) if single else {}
        category=override.get('category',category)
        missing=override.get('missing_fields',missing)
        question=override.get('question',question)
        refs = list(dict.fromkeys(s['segment_id'] for s in record['evidence']))
        description_ok = (record_content_supported(record) or local_record_issues(event,record)) and (not event or all(
            event['checks'][k]['verdict']=='supported' for k in ('work','time')))
        # New relation means no tracked task; it does not establish future work.
        can_add = (not history['tasks'] if not event else
            event['relation']['kind']=='new' and event['checks']['relation']['verdict']=='supported'
            and event['state']['kind']=='future_work' and event['checks']['state']['verdict']=='supported')
        needs_adoption = bool(record.get('qualification') and can_add
                              and category in ('implicit_need', 'proposal'))
        qualification = record.get('qualification', {})
        unclear = (record['kind'] in ('work','ambiguous') and bool(qualification)
                   and (qualification.get('work_basis')=='unclear_intent'
                        or bool(set(missing) & {'work','reference','scope'})))
        clarification_details = {}
        if unclear:
            category = 'unclear_intent'
            current = qualification.get('speech_scope')=='current' or bool(qualification.get('adoption_evidence'))
            clarification_details = dict(requires_clarification=True,
                                         can_clarify_as_new_task=bool(can_add and current and 'relation' not in missing))
            can_add = False
        if needs_adoption:
            can_add = False
        if event and not can_add and not question and not override.get('execution_reason'):
            missing=list(dict.fromkeys(missing+['state']))
            question='这次记录是工作进展、已有任务变更，还是另有未来工作？请复核其状态与任务关系。'
        reviews.append(dict(record_id=record['record_id'],category=category,description=record['description'],
            content_basis=record['content_basis'],description_status='supported_interpretation' if description_ok else 'unverified_hypothesis',
            missing_fields=missing,question=question,issuer_ref=record['issuer_ref'],evidence_ids=refs,
            check_reason=record['check']['reason'],can_add_task=can_add,
            **({'requires_adoption': True} if needs_adoption else {}),
            **clarification_details,
            **commitment_details,
            **({'execution_reason':override['execution_reason']} if override.get('execution_reason') else {})))
    # Preserve one user-facing review identity; legacy pending still serves raw audit.
    for span in uncovered_spans:
        rid='U-'+digest(span)[:16]
        reviews.append(dict(record_id=rid,category='ambiguous',description='核验发现可能遗漏的原话：'+span['quote'],
            content_basis='unknown',description_status='unverified_hypothesis',missing_fields=['work','owner','commitment'],
            question='这段原话是否包含遗漏的工作？请确认具体内容、负责人及是否执行。',issuer_ref=None,
            evidence_ids=[span['segment_id']],check_reason='核验指出遗漏，尚未形成完整工作解释',can_add_task=not history['tasks']))
    result['review_records'] = reviews
    return result
