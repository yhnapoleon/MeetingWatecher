"""Evidence-backed meeting work, confirmed through the existing local Service.

Model proposals and operator confirmations remain separate. Scoped snapshots
preserve the task identity and make earlier meeting views independent of later updates.
"""
import json
import uuid
from datetime import datetime, timezone

from meeting_eval.store import Store
from meeting_eval.service import Service
from .storage import dumps


class WorkLedger:
    def __init__(self, storage):
        self.storage = storage
        with storage.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS work_proposals(id TEXT PRIMARY KEY, body TEXT);
                CREATE TABLE IF NOT EXISTS work_snapshots(seq INTEGER PRIMARY KEY AUTOINCREMENT, proposal TEXT UNIQUE, guid TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS work_proposal_versions(seq INTEGER PRIMARY KEY AUTOINCREMENT, proposal TEXT, job TEXT, body TEXT, UNIQUE(proposal,job));
            ''')

    def view(self, scope):
        from .jobs import is_visible
        with self.storage.connect() as db:
            proposals = [json.loads(r['body']) for r in db.execute('SELECT body FROM work_proposals ORDER BY rowid')]
            snapshots = [json.loads(r['body']) for r in db.execute('SELECT body FROM work_snapshots ORDER BY seq')]
            versions = [json.loads(r['body']) for r in db.execute('SELECT body FROM work_proposal_versions ORDER BY seq')]
        by_id = {p['id']: p for p in proposals if is_visible(p['scope'], scope)}
        for p in versions:
            if is_visible(p['scope'], scope):
                by_id[p['id']] = p
        visible = [s for s in snapshots if is_visible(s['scope'], scope) and scope['actor'] in s['readers']]
        latest = {}
        for s in visible:
            latest[s['guid']] = s
        accepted = {s['proposal_id'] for s in visible}
        return {'tasks': list(latest.values()), 'history': visible,
                'proposals': [p for p in by_id.values() if p['id'] not in accepted]}

    def propose(self, job, result, context):
        from .jobs import is_visible
        known = {t['guid']: t for t in context.get('meeting_work', {}).get('tasks', [])}
        pending = {p['id']: p for p in context.get('meeting_work', {}).get('proposals', [])}
        lookup = {e['id']: e for e in result['evidence']}
        proposals, revisions, ids = [], [], []
        for index, change in enumerate(result['answer']['work_changes']):
            target = change['target_guid']
            if target and target not in known:
                raise ValueError('任务更新没有对应的可见历史任务')
            if target and known[target]['owner'] != change['owner']:
                raise ValueError('不能把其他负责人的汇报写入此任务')
            refs = [lookup[i] for i in change['evidence_ids']]
            if not any(e['meeting_id'] == job['scope']['meeting_id'] for e in refs):
                raise ValueError('行动项必须有本场依据')
            if not target and change['state'] != 'open':
                raise ValueError('阶段汇报不能作为新任务创建')
            existing = change.get('existing_proposal_id')
            if not existing and target:
                # A confirmed task has one pending progress update. Models may omit
                # existing_proposal_id when another small speech window adds detail.
                # The exact target GUID makes this association unambiguous.
                existing = next((pid for pid, p in pending.items()
                                 if p['change']['target_guid'] == target
                                 and p['change']['owner'] == change['owner']), None)
            if existing:
                prior = pending.get(existing)
                if not prior or prior['change']['owner'] != change['owner'] or prior['change']['target_guid'] != target:
                    raise ValueError('待确认事项关联不匹配')
                ids.append(existing)
                if job.get('incremental'):
                    # Preserve the original candidate at earlier cursors; enrich the same card now.
                    revisions.append({**prior, 'scope': job['scope'], 'job_id': job['id'],
                                      'change': change, 'evidence': refs})
                continue
            p = {'id': job['id'] + '-' + str(index), 'scope': job['scope'], 'job_id': job['id'],
                 'origin': 'automatic' if job['kind']=='summary' else 'text',
                 'change': change, 'evidence': refs, 'expected_revision': known[target]['revision'] if target else None}
            proposals.append(p)
            ids.append(p['id'])
        with self.storage.connect() as db:
            for p in proposals:
                db.execute('INSERT OR IGNORE INTO work_proposals VALUES (?,?)', (p['id'], dumps(p)))
            for p in revisions:
                db.execute('INSERT OR IGNORE INTO work_proposal_versions(proposal,job,body) VALUES (?,?,?)',
                           (p['id'], job['id'], dumps(p)))
        return ids

    def confirm(self, pid, scope, body):
        from .jobs import is_visible
        with self.storage.connect() as db:
            row = db.execute('SELECT body FROM work_proposals WHERE id=?', (pid,)).fetchone()
            duplicate = db.execute('SELECT body FROM work_snapshots WHERE proposal=?', (pid,)).fetchone()
        if not row:
            raise LookupError('候选事项不存在')
        p = json.loads(row['body'])
        if not is_visible(p['scope'], scope):
            raise PermissionError('事项不在当前可见范围')
        if duplicate:
            saved = json.loads(duplicate['body'])
            if not is_visible(saved['scope'], scope):
                raise PermissionError('该确认发生在当前游标之后')
            return saved
        p = next((candidate for candidate in self.view(scope)['proposals'] if candidate['id'] == pid), p)
        c = p['change']; guid = c['target_guid']
        old = next((t for t in self.view(scope)['tasks'] if t['guid'] == guid), None) if guid else None
        if guid and (not old or old['revision'] != p['expected_revision']):
            raise ValueError('原任务已变化，请重新读取本场进展')
        state = body.state or c['state']
        due = body.due_text if body.due_text is not None else (old['due_text'] if old else c['due_text'])
        actor = scope['actor']; at = datetime.now(timezone.utc).isoformat()
        store = Store(self.storage.root / 'actions.sqlite')
        try:
            service = Service(store)
            if guid:
                # Do not allow an earlier-scope confirmation to overwrite a later revision.
                with self.storage.connect() as db:
                    latest = db.execute('SELECT body FROM work_snapshots WHERE guid=? ORDER BY seq DESC LIMIT 1', (guid,)).fetchone()
                if latest and json.loads(latest['body'])['revision'] != old['revision']:
                    raise ValueError('任务已有更晚进展，不能从旧时间点覆盖')
                payload = {'guid': guid, 'changes': {'status': 'done' if state == 'done' else 'open', 'due_text': due}}
                operation = 'update'
            else:
                payload = {'summary': c['title'], 'assignee': c['owner'], 'due_date': None, 'due_text': due,
                           'readers': [actor], 'writers': [actor], 'tenant': 'local', 'series': scope['project_id'],
                           'origin': 'meeting_work_operator_confirmation', 'evidence': c['evidence_ids']}
                operation = 'create'
            store.put_intent({'id': pid, 'actor': actor, 'source_id': None, 'operation': operation,
                              'payload': payload, 'policy': 'meeting_work_explicit_confirmation', 'observed_at': at})
            service.recover(actor=actor, observed_at=at)
            guid = store.binding(pid)
            if not guid:
                raise ValueError('本地任务写入未确认')
            platform = service.sim.get(guid, actor)
        finally:
            store.close()
        event = {'proposal_id': pid, 'scope': scope, 'guid': guid, 'owner': c['owner'],
                 'title': old['title'] if old else c['title'], 'due_text': due,
                 'object_text': old.get('object_text') if old else c.get('object_text'),
                 'deadline_text': old.get('deadline_text') if old else c.get('deadline_text'),
                 'origin': p.get('origin','text'),
                 'created_origin': old.get('created_origin','text') if old else p.get('origin','text'),
                 'state': state, 'platform_status': platform['status'], 'detail': c['detail'],
                 'model_state': c['state'], 'note': body.note, 'user_due_text': body.due_text,
                 'evidence': p['evidence'], 'readers': [actor], 'at': at,
                 'revision': pid, 'previous_revision': old['revision'] if old else None,
                 'created_scope': old['created_scope'] if old else scope}
        with self.storage.connect() as db:
            db.execute('INSERT INTO work_snapshots(proposal,guid,body) VALUES (?,?,?)', (pid, guid, dumps(event)))
        return event
