import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


class Storage:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, body TEXT);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project TEXT, status TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT, body TEXT);
                CREATE INDEX IF NOT EXISTS job_events ON events(job,seq);
                CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, project TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, project TEXT, body TEXT);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / 'copilot.sqlite', timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute('SELECT body FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            raise LookupError('任务不存在')
        return json.loads(row['body'])

    def save_job(self, job):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)',
                       (job['id'], job['scope']['project_id'], job['status'], dumps(job)))

    def event(self, job_id, event):
        body = event.model_dump(mode='json', by_alias=True, exclude_none=True)
        with self.connect() as db:
            db.execute('INSERT INTO events(job,body) VALUES (?,?)', (job_id, dumps(body)))

    def finish(self, job, event):
        body=event.model_dump(mode='json',by_alias=True,exclude_none=True)
        with self.connect() as db:
            db.execute('UPDATE jobs SET status=?,body=? WHERE id=?',(job['status'],dumps(job),job['id']))
            db.execute('INSERT INTO events(job,body) VALUES (?,?)',(job['id'],dumps(body)))

    def events(self, job_id, after=0):
        with self.connect() as db:
            return [(r['seq'], json.loads(r['body'])) for r in db.execute(
                'SELECT seq,body FROM events WHERE job=? AND seq>? ORDER BY seq', (job_id, after))]
