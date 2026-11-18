import json
import sqlite3
import uuid
from pathlib import Path

from .inputs import dumps, instant


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY, tenant TEXT, source_key TEXT, version TEXT,
                observed_at TEXT, body TEXT, result TEXT,
                UNIQUE(tenant, source_key, version));
            CREATE TABLE IF NOT EXISTS intents (
                id TEXT PRIMARY KEY, body TEXT, status TEXT, guid TEXT);
            CREATE TABLE IF NOT EXISTS task_events (
                seq INTEGER PRIMARY KEY, guid TEXT, observed_at TEXT, effective_at TEXT, body TEXT);
            CREATE INDEX IF NOT EXISTS task_time ON task_events(guid, observed_at);
            CREATE TABLE IF NOT EXISTS tokens (token TEXT PRIMARY KEY, actor TEXT, guid TEXT);
            CREATE TABLE IF NOT EXISTS decisions (id TEXT PRIMARY KEY, observed_at TEXT, body TEXT);
            CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY, kind TEXT, body TEXT);
        ''')

    def close(self):
        self.db.close()

    def log(self, kind, body):
        self.db.execute('INSERT INTO audit(kind,body) VALUES (?,?)', (kind,dumps(body)))

    def put_intent(self, intent):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO intents VALUES (?,?,?,NULL)',
                            (intent['id'],dumps(intent),'pending'))
            self.log('proposed', intent)

    def binding(self, intent_id):
        row = self.db.execute('SELECT guid FROM intents WHERE id=?',(intent_id,)).fetchone()
        return row['guid'] if row else None

    def task(self, guid, as_of=None):
        sql = 'SELECT body FROM task_events WHERE guid=?'
        args = [guid]
        if as_of:
            sql += ' AND observed_at<=? AND effective_at<=?'
            args.extend([instant(as_of),instant(as_of)])
        row = self.db.execute(sql+' ORDER BY observed_at DESC,seq DESC LIMIT 1',args).fetchone()
        return json.loads(row['body']) if row else None

    def tasks(self, as_of=None):
        ids = self.db.execute('SELECT DISTINCT guid FROM task_events').fetchall()
        return [t for row in ids if (t := self.task(row['guid'],as_of)) is not None]

    def append_task(self, task, observed_at, effective_at=None):
        self.db.execute('INSERT INTO task_events(guid,observed_at,effective_at,body) VALUES (?,?,?,?)',
                        (task['guid'],instant(observed_at),instant(effective_at or observed_at),dumps(task)))


class Simulator:
    """Durable offline platform. Tokens are permanent here, unlike Feishu's time window."""
    def __init__(self, store):
        self.store = store

    def seed(self, task, at):
        if self.store.task(task['guid']):
            return
        task = {**task, 'writers':task.get('writers', ['host']),
                'tenant':task.get('tenant','local')}
        with self.store.db:
            self.store.append_task(task, at)
            self.store.log('platform_seed',task)

    def get(self, guid, actor):
        task = self.store.task(guid)
        if task is None:
            raise LookupError('Task not found')
        if actor not in task['readers']:
            raise PermissionError('Task read denied')
        return task

    def create(self, payload, actor, token, at):
        if actor not in payload['writers'] or actor not in payload['readers']:
            raise PermissionError('Task create denied')
        with self.store.db:
            row = self.store.db.execute('SELECT * FROM tokens WHERE token=?',(token,)).fetchone()
            if row:
                if row['actor'] != actor:
                    raise PermissionError('Token belongs to another caller')
                return self.get(row['guid'],actor)
            task = {**payload, 'guid':'SIM-'+uuid.uuid4().hex[:12], 'status':'open'}
            self.store.append_task(task,at)
            self.store.db.execute('INSERT INTO tokens VALUES (?,?,?)',(token,actor,task['guid']))
            self.store.log('platform_create',{'token':token,'actor':actor,'guid':task['guid']})
        return task

    def update(self, guid, changes, actor, at, effective_at=None):
        task = self.get(guid,actor)
        if actor not in task['writers']:
            raise PermissionError('Task update denied')
        if not set(changes) <= {'status','due_date','due_text','readers','summary'}:
            raise ValueError('Unsupported update fields')
        if 'status' in changes and changes['status'] not in ('open','done'):
            raise ValueError('Invalid task status')
        task = {**task, **changes}
        with self.store.db:
            self.store.append_task(task,at,effective_at)
            self.store.log('platform_update',{'guid':guid,'actor':actor,'changes':changes,'at':at})
        return task
