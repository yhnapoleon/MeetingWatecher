import json
from datetime import datetime, timezone

from .inputs import normalize, digest, dumps, instant
from .store import Simulator
from .extract import validate,failed_fields,merge_retry
from .decision_history import exact_reaffirmation, project_versions


class Service:
    def __init__(self, store, extractor=None):
        self.store = store
        self.sim = Simulator(store)
        self.extractor = extractor
        with store.db:
            store.db.execute('CREATE TABLE IF NOT EXISTS extraction_context (source_id TEXT PRIMARY KEY, body TEXT)')
            store.db.execute('CREATE TABLE IF NOT EXISTS requirement_decisions (source_id TEXT, record_id TEXT, body TEXT, PRIMARY KEY(source_id,record_id))')
            store.db.execute('CREATE TABLE IF NOT EXISTS extraction_retry_grants (source_id TEXT, node_id TEXT, retry_id TEXT, observed_at TEXT, PRIMARY KEY(source_id,node_id))')
        if extractor is not None and hasattr(extractor,'config'):
            with store.db:
                store.db.execute('CREATE TABLE IF NOT EXISTS extraction_config (id INTEGER PRIMARY KEY, body TEXT)')
                row = store.db.execute('SELECT body FROM extraction_config WHERE id=1').fetchone()
                config = dumps(extractor.config)
                from .stage_runner import semantic_config
                old_config=json.loads(row['body']) if row else None
                budget_only=row and old_config.get('strategy')=='context-v5' and extractor.config.get('strategy')=='context-v5' and semantic_config(old_config)==semantic_config(extractor.config)
                if row and row['body'] != config and not budget_only:
                    raise ValueError('Extractor configuration changed; use a new database')
                if not row:
                    if store.db.execute('SELECT count(*) FROM sources').fetchone()[0]:
                        raise ValueError('Legacy database has no extraction configuration; use a new database')
                    store.db.execute('INSERT INTO extraction_config VALUES (1,?)',(config,))

    def current_source(self, source_id):
        row = self.store.db.execute('SELECT body FROM sources WHERE id=?',(source_id,)).fetchone()
        if not row:
            return None
        src = json.loads(row['body'])
        # Most recently imported version defines current source authorization.
        latest = self.store.db.execute('SELECT body FROM sources WHERE tenant=? AND source_key=? '
            'ORDER BY observed_at DESC,rowid DESC LIMIT 1',(src['tenant'],src['source_key'])).fetchone()
        return json.loads(latest['body'])

    def source_readable(self, source_id, viewer):
        row = self.store.db.execute('SELECT body FROM sources WHERE id=?',(source_id,)).fetchone()
        if not row:
            return False
        original = json.loads(row['body'])
        current = self.current_source(source_id)
        # Cached derived output may contain history authorized for the original audience.
        return viewer in original['audience'] and viewer in current['audience']

    def task_projection(self, task, viewers):
        current = self.store.task(task['guid'])
        if not all(v in current['readers'] for v in viewers):
            return None
        out = {k:v for k,v in task.items() if k not in ('readers','writers','source_readers','token')}
        allowed = all(v in current.get('source_readers',current['readers']) for v in viewers)
        if current.get('source_id'):
            allowed = allowed and all(self.source_readable(current['source_id'],v) for v in viewers)
        if not allowed:
            for key in ('source_id','evidence','origin','meeting_id'):
                out.pop(key,None)
        return out

    def context(self, series, viewer, as_of, tenant='local', audience=None):
        viewers = list(set([viewer]+(audience or [])))
        tasks = []
        for task in self.store.tasks(as_of):
            if task['tenant'] == tenant and task['series'] == series:
                visible = self.task_projection(task,viewers)
                if visible:
                    tasks.append(visible)
        decisions = self.decision_projection(series,viewers,as_of,False,tenant,None)
        return dict(tasks=tasks,decisions=decisions)

    def recap(self, series, viewer, as_of, tenant='local'):
        return [t for t in self.context(series,viewer,as_of,tenant)['tasks'] if t['status'] != 'done']

    def decisions(self, series, viewer, as_of, history=False, tenant='local', attribute=None):
        return self.decision_projection(series,[viewer],as_of,history,tenant,attribute)

    def decision_projection(self, series, viewers, as_of, history, tenant, attribute):
        cutoff = instant(as_of)
        rows = self.store.db.execute('SELECT body FROM decisions WHERE observed_at<=? ORDER BY observed_at,rowid',
                                    (cutoff,))
        eligible = [d for row in rows if (d := json.loads(row['body']))['tenant'] == tenant
                    and d['series'] == series and (attribute is None or d['attribute'] == attribute)
                    and (not d.get('effective_at') or instant(d['effective_at']) <= cutoff)]
        readable = {d['id'] for d in eligible if all(self.source_readable(d['source_id'],v) for v in viewers)}
        return project_versions(eligible,readable,history)

    def process(self, raw, actor, observed_at,*,_retry_source_id=None):
        at = instant(observed_at)
        tenant = raw.get('tenant','local')
        roster = {}
        viewers = set(raw.get('audience',[actor])) | {actor}
        for row in self.store.db.execute('SELECT id,body FROM sources WHERE tenant=? AND observed_at<=?',(tenant,at)):
            old = json.loads(row['body'])
            if old['series'] == raw.get('series',raw['meeting_id']) and all(self.source_readable(row['id'],v) for v in viewers):
                roster.update(old['roster'])
        m = normalize(raw,actor,roster)
        sid = _retry_source_id or digest([m['tenant'],m['source_key'],m['version']])
        existing = self.store.db.execute('SELECT * FROM sources WHERE id=?',(sid,)).fetchone()
        if _retry_source_id and not existing:raise ValueError('Retry source missing')
        if existing:
            if not self.source_readable(sid,actor):
                raise PermissionError('Source access revoked')
            previous = json.loads(existing['result'])
            if previous['status'] != 'partial':
                self.recover(actor=actor,observed_at=at)
                return self.result(sid)
            m = json.loads(existing['body'])
            ctx = self.retry_context(sid,m,actor)
            retry = getattr(self.extractor,'retry',None)
            from .stage_runner import recovery_scope
            grants={r['node_id']:r['retry_id'] for r in self.store.db.execute(
                'SELECT node_id,retry_id FROM extraction_retry_grants WHERE source_id=?',(sid,))}
            with recovery_scope(grants):
                extracted = retry(m,ctx,previous['extraction']) if retry else self.extractor.extract(m,ctx)
            result = validate(merge_retry(previous['extraction'],extracted),m,ctx)
        else:
            ctx = self.context(m['series'],actor,at,m['tenant'],m['audience'])
            result = validate(self.extractor.extract(m,ctx),m,ctx)
        prior = self.store.db.execute('SELECT id FROM sources WHERE tenant=? AND source_key=?',
                                     (m['tenant'],m['source_key'])).fetchone() if not existing else None
        output = dict(source_id=sid,meeting_id=m['meeting_id'],status='revision_pending' if prior else 'processed',
                      extraction=result,pending=[],decision_ids=[],intent_ids=[])
        output['recovery']=list({e['recovery']['node_id']:e['recovery'] for e in result.get('_errors',[]) if e.get('recovery')}.values())
        output['collected_issues']=self.collect_issues(sid,result)
        if result.get('_errors') and not prior:
            output['status'] = 'partial'
        with self.store.db:
            if not existing:
                self.store.db.execute('INSERT INTO sources VALUES (?,?,?,?,?,?,?)',
                    (sid,m['tenant'],m['source_key'],m['version'],at,dumps(m),dumps(output)))
                self.store.db.execute('INSERT INTO extraction_context VALUES (?,?)',
                    (sid,dumps({'actor':actor,'context':ctx})))
            if not prior:
                self.plan_operations(m,sid,actor,at,result,ctx,output)
            else:
                output['pending'].append({'reason':'source_revision_requires_reconciliation','prior_source':prior['id']})
            self.store.db.execute('UPDATE sources SET result=? WHERE id=?',(dumps(output),sid))
        self.recover(actor=actor,observed_at=at)
        return self.result(sid)

    def retry_context(self,sid,meeting,actor):
        if not self.source_readable(sid,actor):raise PermissionError('Source access revoked')
        if self.current_source(sid)['version']!=meeting['version']:raise PermissionError('Retry source version changed')
        saved=self.store.db.execute('SELECT body FROM extraction_context WHERE source_id=?',(sid,)).fetchone()
        if not saved:raise ValueError('Partial result has no frozen context; use a new database')
        frozen=json.loads(saved['body']);ctx=frozen['context']
        viewers=list(set(meeting['audience']+[actor]))
        permitted=(all(self.task_projection(t,viewers)==t for t in ctx['tasks']) and
            all(self.source_readable(d['source_id'],v) for d in ctx['decisions'] for v in viewers))
        linked = {d[key] for d in ctx['decisions'] for key in ('reaffirms','supersedes') if d.get(key)}
        # A frozen relation may point to a separately revoked source.
        for did in linked:
            row = self.store.db.execute('SELECT body FROM decisions WHERE id=?',(did,)).fetchone()
            target_source = json.loads(row['body'])['source_id'] if row else None
            if not target_source or not all(self.source_readable(target_source,v) for v in viewers):
                raise PermissionError('Retry context authorization changed')
        if actor!=frozen['actor'] or not permitted:raise PermissionError('Retry context authorization changed')
        return ctx

    def retry_extraction(self,sid,actor,retry_id,observed_at):
        """Grant each exhausted node one durable batch; retries of this API are idempotent."""
        if not isinstance(retry_id,str) or not retry_id.strip():raise ValueError('retry_id is required')
        at=instant(observed_at)
        row=self.store.db.execute('SELECT body,result FROM sources WHERE id=?',(sid,)).fetchone()
        if not row or not self.source_readable(sid,actor):raise PermissionError('Source access revoked')
        meeting=json.loads(row['body']);self.retry_context(sid,meeting,actor)
        # BEGIN IMMEDIATE protects read/insert against another process submitting the same ID.
        with self.store.db:
            self.store.db.execute('BEGIN IMMEDIATE')
            duplicate=self.store.db.execute('SELECT 1 FROM extraction_retry_grants WHERE source_id=? AND retry_id=?',(sid,retry_id)).fetchone()
            current=self.result(sid)
            if duplicate:return current
            nodes=[r['node_id'] for r in current.get('recovery',[]) if r['status']=='recovery_required' and not r.get('manual_grant_used')]
            inserted=0
            for node in nodes:
                inserted+=self.store.db.execute('INSERT OR IGNORE INTO extraction_retry_grants VALUES (?,?,?,?)',(sid,node,retry_id,at)).rowcount
        if not inserted:return current
        return self.process(meeting,actor,at,_retry_source_id=sid)

    @staticmethod
    def collect_issues(sid,result):
        if result.get('_minutes_review',{}).get('status')!='accepted' or 'unresolved' in failed_fields(result):return []
        issues={}
        for row in result['unresolved']:
            statement=row['statement'].strip();evidence=sorted(row['evidence_ids'])
            if not statement:continue
            identity='I-'+digest([sid,statement,evidence])[:20]
            issues[identity]=dict(issue_id=identity,source_id=sid,statement=statement,evidence_ids=evidence,
                retention_state='collected',resolution_state='open',can_add_task=False)
        return list(issues.values())

    def collected_issues(self,sid,viewer):
        if not self.source_readable(sid,viewer):raise PermissionError('Collected issues read denied')
        return self.result(sid).get('collected_issues',[])

    def plan_operations(self,m,sid,actor,at,result,ctx,output):
        refs = {s['id']:s for s in m['segments']}
        incomplete = failed_fields(result)
        blocked = set(incomplete)
        if ctx['tasks'] and incomplete & {'items','updates'}:
            blocked.update(('items','updates'))
        conflicts_i,conflicts_u = set(),set()
        task_pending = result.get('_task_trace',{}).get('pending',[])
        output['pending'].extend(p for p in task_pending if 'item_index' not in p)
        for i,item in enumerate(result['items']):
            for j,update in enumerate(result['updates']):
                if getattr(self.extractor,'strategy',None) in ('evidence-v1','context-v1','context-v2','context-v3','context-v4','context-v5'):
                    # One checked event has one relation; distinct work in one turn is allowed.
                    continue
                same_owner = item['owner_ref'] == update.get('owner_ref')
                shared_evidence = set(item['evidence_ids']) & set(update['evidence_ids'])
                # Different wording is normal across independently generated branches.
                # Shared owner/evidence is a potential collision, never proof of two tasks.
                if same_owner and shared_evidence:
                    conflicts_i.add(i)
                    conflicts_u.add(j)
                    output['pending'].append({'item':item,'update':update,'reason':'create_update_conflict'})

        def propose(index, operation, payload, evidence):
            iid = digest([sid,operation,index])
            intent = dict(id=iid,source_id=sid,operation=operation,actor=actor,observed_at=at,
                          payload=payload,evidence_ids=evidence,policy='v0.1_owner_report_can_complete')
            inserted = self.store.db.execute('INSERT OR IGNORE INTO intents VALUES (?,?,?,NULL)',(iid,dumps(intent),'pending'))
            if inserted.rowcount:
                self.store.log('proposed',intent)
            output['intent_ids'].append(iid)

        for i,item in enumerate(result['items']):
            if i in conflicts_i:
                continue
            if 'items' in blocked:
                output['pending'].append({'item':item,'reason':'extraction_incomplete'})
                continue
            owner = m['account_map'].get(item['owner_ref'])
            if item['operation'] != 'create' or not owner or actor not in m['writers']:
                reason = next((p['reason'] for p in task_pending if p.get('item_index')==i),
                              'candidate_or_account_or_write_permission') if item['operation']!='create' else 'candidate_or_account_or_write_permission'
                pending = {'item':item,'reason':reason}
                record_ids = result.get('_task_trace',{}).get('item_records',[])
                if i < len(record_ids):pending['record_id']=record_ids[i]
                output['pending'].append(pending)
                continue
            payload = dict(summary=item['description'],assignee=owner,due_date=item['due_date'],due_text=item['due_text'],
                           readers=m['audience'],writers=list(set(m['writers']+[owner])),tenant=m['tenant'],
                           series=m['series'],source_id=sid,origin=m['meeting_id'],source_readers=m['audience'],
                           evidence=[refs[e] for e in item['evidence_ids']])
            propose(i,'create',payload,item['evidence_ids'])

        for i,u in enumerate(result['updates']):
            if i in conflicts_u:
                continue
            if 'updates' in blocked:
                output['pending'].append({'update':u,'reason':'extraction_incomplete'})
                continue
            owner_account = m['account_map'].get(u.get('owner_ref'))
            changes = u['changes'] if 'changes' in u else {'status':u['status']}
            targets = [t for t in ctx['tasks'] if t['guid'] == u.get('target_guid')] if u.get('target_guid') else [
                t for t in ctx['tasks'] if t['summary'] == u.get('description') and t.get('assignee') == owner_account]
            reason = None
            if len(targets) != 1:
                reason = 'ambiguous_target'
            else:
                t = self.sim.get(targets[0]['guid'],actor)
                duplicates = [x for x in ctx['tasks'] if x['summary'] == t['summary'] and x.get('assignee') == t.get('assignee')]
                explicit_guid = any(t['guid'] in refs[e]['text'] for e in u['evidence_ids'])
                speakers = {m['account_map'].get(refs[e]['person_ref']) for e in u['evidence_ids']}
                field_speakers = [{m['account_map'].get(refs[e]['person_ref']) for e in values}
                                  for field,values in u.get('field_evidence_ids',{}).items() if field in ('time','state')]
                if len(duplicates) > 1 and not explicit_guid:
                    reason = 'ambiguous_target'
                elif (not isinstance(t.get('assignee'),str) or t['assignee'] != owner_account or t['assignee'] not in speakers
                      or any(t['assignee'] not in people for people in field_speakers)):
                    reason = 'not_single_owner_report'
                elif actor not in t['writers']:
                    reason = 'write_denied'
                elif not set(t['readers']) <= set(m['audience']):
                    reason = 'target_audience_exceeds_source'
                elif 'changes' in u and any(t.get(k)!=targets[0].get(k) for k in set(changes)|{'assignee'}):
                    reason = 'task_changed_since_meeting'
            if reason:
                output['pending'].append({'update':u,'reason':reason})
            else:
                payload=dict(guid=t['guid'],changes=changes,effective_at=u.get('effective_at'))
                if 'changes' in u:payload['expected']={k:t.get(k) for k in set(changes)|{'assignee'}}
                propose(i,'update',payload,u['evidence_ids'])

        for i,d in enumerate(result['decisions']):
            if 'decisions' in blocked:
                output['pending'].append({'decision':d,'reason':'extraction_incomplete'})
                continue
            if d.get('supersedes'):
                old = next(x for x in ctx['decisions'] if x['id'] == d['supersedes'])
                if old['attribute'] != d['attribute']:
                    output['pending'].append({'decision':d,'reason':'replacement_attribute_mismatch'})
                    continue
            did = 'D-'+digest([sid,i])[:16]
            decision = {**d,'id':did,'source_id':sid,'tenant':m['tenant'],'series':m['series'],
                        'observed_at':at,'effective_at':m['started_at'],'evidence':[refs[e] for e in d['evidence_ids']]}
            if not d.get('supersedes') and not d.get('reaffirms'):
                decision['reaffirms'] = exact_reaffirmation(d,ctx['decisions'],sid)
            self.store.db.execute('INSERT OR IGNORE INTO decisions VALUES (?,?,?)',(did,at,dumps(decision)))
            output['decision_ids'].append(did)

    def recover(self, actor=None, observed_at=None):
        recovered_at = instant(observed_at or datetime.now(timezone.utc).isoformat())
        for row in self.store.db.execute("SELECT * FROM intents WHERE status!='confirmed'").fetchall():
            intent = json.loads(row['body'])
            if actor and intent['actor'] != actor:
                continue
            iid, who, at, payload = intent['id'],intent['actor'],recovered_at,intent['payload']
            try:
                # A receipt lookup is a read; do not require permission to send a new write
                # if this intent already succeeded on the platform.
                task = None
                if intent['operation'] == 'create':
                    token = self.store.db.execute('SELECT * FROM tokens WHERE token=?',(iid,)).fetchone()
                    if token and token['actor'] == who:
                        task = self.sim.get(token['guid'],who)
                else:
                    current_task = self.sim.get(payload['guid'],who)
                    if all(current_task.get(k) == v for k,v in payload['changes'].items()):
                        task = current_task
                if task is None and intent.get('source_id'):
                    current = self.current_source(intent['source_id'])
                    if intent.get('policy')=='explicit_user_requirement_confirmation' and current['version']!=intent['source_version']:
                        raise PermissionError('Manually confirmed source version changed')
                    if not self.source_readable(intent['source_id'],who) or who not in current['writers']:
                        raise PermissionError('Source read/write access revoked')
                    audience = payload['readers'] if intent['operation'] == 'create' else self.sim.get(payload['guid'],who)['readers']
                    if not set(audience) <= set(current['audience']):
                        raise PermissionError('Target audience exceeds current source audience')
                if task is None:
                    if intent['operation']=='update' and 'expected' in payload:
                        current_task=self.sim.get(payload['guid'],who)
                        if any(current_task.get(k)!=v for k,v in payload['expected'].items()):
                            raise PermissionError('Task changed since update was proposed')
                    with self.store.db:
                        self.store.log('sent',{'intent_id':iid,'operation':intent['operation'],'observed_at':at})
                    if intent['operation'] == 'create':
                        task = self.sim.create(payload,who,iid,at)
                    else:
                        task = self.sim.update(payload['guid'],payload['changes'],who,at,payload.get('effective_at'))
                readback = self.sim.get(task['guid'],who)
                with self.store.db:
                    self.store.db.execute('UPDATE intents SET status=?,guid=? WHERE id=?',('confirmed',readback['guid'],iid))
                    self.store.log('confirmed',{'intent_id':iid,'guid':readback['guid'],'readback':readback,'observed_at':at})
            except (PermissionError,LookupError,OSError) as exc:
                with self.store.db:
                    self.store.db.execute('UPDATE intents SET status=? WHERE id=?',('unknown',iid))
                    self.store.log('unconfirmed',{'intent_id':iid,'error':type(exc).__name__})

    def result(self,sid):
        out = json.loads(self.store.db.execute('SELECT result FROM sources WHERE id=?',(sid,)).fetchone()['result'])
        out['bindings'] = {iid:self.store.binding(iid) for iid in out['intent_ids']}
        return out

    def requirements(self,sid,viewer):
        from .requirement_review import requirements
        return requirements(self,sid,viewer)

    def resolve_requirement(self,sid,rid,actor,decision,observed_at):
        from .requirement_review import resolve_requirement
        return resolve_requirement(self,sid,rid,actor,decision,observed_at)

    def minutes(self,sid,viewer):
        if not self.source_readable(sid,viewer):
            raise PermissionError('Minutes read denied')
        out = self.result(sid)
        result = out['extraction']
        reviews = self.requirements(sid,viewer)
        resolutions = {r['record_id']:r['resolution'] for r in reviews if r['resolution']}
        item_records = result.get('_task_trace',{}).get('item_records',[])
        collected={(r['statement'],tuple(sorted(r['evidence_ids']))):r for r in out.get('collected_issues',[])}
        lines = ['# '+out['meeting_id']+' 会议纪要','']
        if result.get('_errors'):
            lines.extend(['本次处理未完整完成，以下保留已通过校验的内容；错误详情见结果 JSON。',''])
        for title,field in [('关键事实','facts'),('行动项','items'),('已决事项','decisions'),('未决问题','unresolved'),('任务更新提议','updates')]:
            lines.extend(['## '+title,''])
            shown_issues=set()
            for index,item in enumerate(result[field]):
                text = item.get('statement') or item.get('description') or ''
                if field=='unresolved':
                    issue=collected.get((text.strip(),tuple(sorted(item['evidence_ids']))))
                    if issue:
                        if issue['issue_id'] in shown_issues:continue
                        shown_issues.add(issue['issue_id'])
                        text=f"[{issue['issue_id']}] {text}；已收录·待确定"
                if field == 'items':
                    label = '待办' if item['operation'] == 'create' else '待确认'
                    resolved = resolutions.get(item_records[index]) if index < len(item_records) else None
                    if resolved:
                        label = '用户已忽略' if resolved['decision']=='dismiss' else '等待询问' if resolved['decision']=='ask_issuer' else '任务已创建' if resolved.get('intent_status')=='confirmed' else '用户已确认，写入尚未确认'
                    text += f"；负责人：{item.get('owner_label') or '待确认'}；期限：{item.get('due_date') or item.get('due_text') or '未知'}；{label}"
                if field=='updates' and 'changes' in item:
                    changes=item['changes']
                    if 'due_date' in changes:text+='；截止日期：'+(changes['due_date'] or '已提出取消')
                    if 'status' in changes:text+='；状态：'+('完成' if changes['status']=='done' else '重新打开')
                lines.append('- '+text+' ['+', '.join(item['evidence_ids'])+']')
            if not result[field]:
                lines.append('无。')
            lines.append('')
        source = json.loads(self.store.db.execute('SELECT body FROM sources WHERE id=?',(sid,)).fetchone()['body'])
        cited = {e for field in ('items','facts','unresolved','decisions','updates')
                 for item in result[field] for e in item.get('evidence_ids',[])}
        reports=result.get('_task_trace',{}).get('reports',[])
        if reports:
            lines.extend(['## 工作进展与完成汇报',''])
            for report in reports:
                cited.update(report['evidence_ids'])
                state={'completed':'已完成：','progress':'进行中：'}.get(report.get('state'),'')
                lines.append('- '+state+report['description']+' ['+', '.join(report['evidence_ids'])+']')
            lines.append('')
        deferred=result.get('_task_trace',{}).get('deferred_topics',[])
        reviewed=result.get('_minutes_review',{})
        if reviewed.get('status')=='accepted' and reviewed.get('deferred_context_hash')==digest(deferred):
            hidden=set(reviewed.get('covered_deferred_record_ids',[]))
            deferred=[r for r in deferred if r['record_id'] not in hidden]
        if deferred:
            lines.extend(['## 待定事项（仅收集）',''])
            for topic in deferred:
                cited.update(topic['evidence_ids'])
                lines.append('- '+topic['description']+' ['+', '.join(topic['evidence_ids'])+']')
            lines.append('')
        contexts=result.get('_task_trace',{}).get('context_records',[])
        if contexts:
            lines.extend(['## 会议上下文',''])
            for record in contexts:
                cited.update(record['evidence_ids'])
                lines.append('- '+record['description']+' ['+', '.join(record['evidence_ids'])+']')
            lines.append('')
        diagnostics=[r for r in reviews if r['category']=='interpretation_unresolved']
        actionable=[r for r in reviews if r['category']!='interpretation_unresolved']
        if diagnostics:
            lines.extend(['## 系统核验诊断',''])
            for record in diagnostics:
                cited.update(record['evidence_ids'])
                lines.append(f"- [{record['record_id']}] 工作解释尚未确定：{record['description']} [{', '.join(record['evidence_ids'])}]；{record['question']}")
            lines.append('')
        for heading, group in (
                ('待澄清意向', [r for r in actionable if r.get('requires_clarification')]),
                ('待澄清需求', [r for r in actionable if r.get('requires_adoption') and r['category']=='implicit_need']),
                ('待采纳方案', [r for r in actionable if r.get('requires_adoption') and r['category']=='proposal']),
                ('需要确认的需求与工作', [r for r in actionable if not r.get('requires_adoption') and not r.get('requires_clarification')])):
            if not group:
                continue
            lines.extend(['## '+heading,''])
            for record in group:
                cited.update(record['evidence_ids'])
                category = {'unclear_intent':'意向待澄清','implicit_need':'隐式需求（推测）','execution_blocked':'已明确但尚未执行',
                            'interpretation_unresolved':'原话含义尚未解决','proposal':'工作提议（待采纳）','conditional_work':'条件性工作'}.get(record['category'],'模糊工作（待确认）')
                if (record['category']=='ambiguous' and record['missing_fields']==['owner']
                        and record['description_status']=='supported_interpretation'):
                    category='已明确工作（待分配）'
                status = '；含义尚未核实' if record['description_status']=='unverified_hypothesis' else ''
                lines.append(f"- [{record['record_id']}] {category}{status}：{record['description']}")
                if record.get('commitment_kind')=='conditional':
                    lines.append('  条件原话：'+'；'.join(record['commitment_quotes']))
                if record['resolution']:
                    resolved = record['resolution']
                    status = {'add_task':'任务已创建' if resolved.get('intent_status')=='confirmed' else '用户已确认，写入尚未确认',
                              'adopt_and_add_task':'已采纳，任务已创建' if resolved.get('intent_status')=='confirmed' else '已采纳，写入尚未确认',
                              'clarify_and_add_task':'已澄清，任务已创建' if resolved.get('intent_status')=='confirmed' else '已澄清，写入尚未确认',
                              'dismiss':'用户已忽略','ask_issuer':'待向提出方询问，尚未发送'}[resolved['decision']]
                    lines.append('  处理结果：'+status)
                if record['category']=='execution_blocked':
                    lines.append('  未执行原因：'+record['execution_reason'])
                elif record['category']=='interpretation_unresolved':
                    lines.append('  处理状态：'+record['question'])
                elif not record['resolution'] or record['resolution']['decision']=='ask_issuer':
                    lines.append('  确认问题：'+record['question'])
                    issuer = source['roster'].get(record['issuer_ref']) or '任务提出方'
                    lines.append('  建议向'+issuer+'确认。原话：'+', '.join(record['evidence_ids']))
            lines.append('')
        if result.get('_task_trace') and out['pending']:
            labels = {'event_not_supported':'内容或判断尚无充分依据','ambiguous_task_relation':'无法确定关联哪项工作',
                'update_owner_unverified':'尚不能确认这是负责人汇报','no_supported_state_change':'未形成可执行的任务变更',
                'commitment_suggested':'这是建议，尚未承接','commitment_conditional':'条件尚未确认成立',
                'commitment_unknown':'承接关系不明确','commitment_declined':'该项工作被拒绝',
                'owner_unverified':'负责人尚未确认','unaccepted_assignment':'分派尚未承接',
                'personal_acceptance_unverified':'尚无对应负责人的承接证据','missing_personal_owner':'团队已承诺，个人负责人待确认',
                'time_unverified':'时间含义待确认','possible_missed_work':'可能遗漏的工作，需要核对原话',
                'deadline_change_unconfirmed':'截止日期变更尚未确定','deadline_date_unresolved':'新截止日期尚不明确',
                'unsupported_task_change':'当前尚不支持这类任务字段变更','not_single_owner_report':'尚无对应负责人对本次变更的确认',
                'task_changed_since_meeting':'任务已发生后续修改，本次变更未覆盖新值',
                'write_denied':'当前没有修改这项任务的权限','target_audience_exceeds_source':'任务可见范围超出本次会议授权范围',
                'candidate_or_account_or_write_permission':'执行身份或写入条件尚未满足','extraction_incomplete':'本次提取未完整完成'}
            lines.extend(['## 待核对工作',''])
            reviewed_ids = {r['record_id'] for r in reviews}
            reviewed_events = {e['event_id'] for e in result.get('_task_trace',{}).get('checked_events',[]) if e.get('record_id') in reviewed_ids}
            for pending in out['pending']:
                if pending.get('record_id') in reviewed_ids or pending.get('event_id') in reviewed_events:
                    continue
                refs = pending.get('evidence_ids',pending.get('item',pending.get('update',{})).get('evidence_ids',[]))
                cited.update(refs)
                text = labels.get(pending['reason'],'需要进一步核对')
                if pending.get('work_description'):
                    text += '：'+pending['work_description']
                elif pending.get('quote'):
                    text += '：'+pending['quote']
                lines.append('- '+text+' ['+', '.join(refs)+']')
            lines.append('')
        lines.extend(['## 原话证据',''])
        for s in source['segments']:
            if s['id'] in cited:
                lines.append(f"- [{s['id']}] {s['speaker_name']}（{s['speaker']}）：{s['text']}")
        return '\n'.join(lines)+'\n'
