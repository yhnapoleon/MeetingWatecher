"""Visible STT windows and optional archived Service records. Never reads scenario events."""
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from contextlib import closing

from meeting_eval.store import Store
from meeting_eval.service import Service


class Memory:
    def __init__(self, scenario_path, root, history_db=None):
        scenario = json.loads(Path(scenario_path).read_text(encoding='utf-8'))
        self.meetings = scenario['meetings']
        self.clips = scenario['clips']
        self.names = {p['id']: p['name'] for p in scenario['people']}
        self.roster = [{'name': p['name'], 'role': p['role']} for p in scenario['people']]
        self.history = Path(root) / 'business.sqlite'
        if history_db and not self.history.exists():
            # SQLite backup also includes committed WAL pages, without touching the original.
            with closing(sqlite3.connect(f'{Path(history_db).resolve().as_uri()}?mode=ro', uri=True)) as src:
                with closing(sqlite3.connect(self.history)) as dst:
                    src.backup(dst)
        self.evidence = []
        group = []
        for i, word in enumerate(scenario['captionWords']):
            clip = next(c for c in self.clips if c['at'] <= word['start'] < c['end'])
            word = {**word, 'index': i, 'clip': clip}
            if group and (word['speaker'] != group[-1]['speaker'] or clip != group[-1]['clip']
                          or word['start'] - group[0]['start'] > 10000):
                self.evidence.append(self.window(group))
                group = []
            group.append(word)
        if group:
            self.evidence.append(self.window(group))

    def window(self, words):
        c = words[0]['clip']
        return {'id': f"stt:{words[0]['index']}-{words[-1]['index']}:v1",
                'meeting_id': c['meetingId'], 'speaker': self.names[words[0]['speaker']],
                'start_ms': words[0]['start'], 'end_ms': min(words[-1]['end'], c['end']),
                'source_start_ms': c['sourceStart'] + words[0]['start'] - c['at'],
                'source_end_ms': c['sourceStart'] + min(words[-1]['end'], c['end']) - c['at'],
                'quote': ''.join(w['text'] for w in words).strip(), 'provenance': 'stt_replay'}

    def scope(self, body):
        if body.project_id != 'remote':
            raise ValueError('此项目尚未绑定会议资料，请使用遥控器产品设计项目')
        meeting = self.meetings[body.meeting]
        if not meeting['at'] <= body.cursor_ms <= meeting['end']:
            raise ValueError('会议游标不在当前会议范围内')
        completed = []
        for a in body.archives:
            if (a.meeting == body.meeting and a.cursor_ms > body.cursor_ms) or a.meeting > body.meeting or not self.meetings[a.meeting]['at'] <= a.cursor_ms <= self.meetings[a.meeting]['end']:
                raise ValueError('归档范围无效')
            completed.append({'meeting_id': self.meetings[a.meeting]['id'], 'cursor_ms': a.cursor_ms,
                              'full': a.cursor_ms >= self.meetings[a.meeting]['end'] - 1})
        return {'project_id': body.project_id, 'actor': 'evaluator', 'meeting_id': meeting['id'],
                'meeting_start_ms': meeting['at'], 'cursor_ms': body.cursor_ms,
                'archives': completed, 'provenance': 'stt_replay'}

    def visible(self, scope):
        limits = {a['meeting_id']: a['cursor_ms'] for a in scope['archives']}
        limits[scope['meeting_id']] = scope['cursor_ms']
        return [e for e in self.evidence if e['end_ms'] <= limits.get(e['meeting_id'], -1)]

    def history_context(self, scope):
        result = {'tasks': [], 'decisions': [], 'candidates': [], 'evidence': []}
        permitted = {a['meeting_id'] for a in scope['archives'] if a['full']}
        if not permitted or not self.history.exists():
            return result
        store = Store(self.history)
        try:
            service = Service(store)
            rows = list(store.db.execute('SELECT * FROM sources ORDER BY observed_at,rowid'))
            selected = [r for r in rows if json.loads(r['body'])['meeting_id'] in permitted
                        and service.source_readable(r['id'], scope['actor'])]
            if not selected:
                return result
            ids = {r['id'] for r in selected}
            last = selected[-1]
            source = json.loads(last['body'])
            context = service.context(source['series'], scope['actor'], last['observed_at'], source['tenant'])
            result['tasks'] = [t for t in context['tasks'] if t.get('source_id') in ids]
            result['decisions'] = [d for d in service.decisions(source['series'], scope['actor'], last['observed_at'],
                                                              history=True, tenant=source['tenant']) if d.get('source_id') in ids]
            for row in selected:
                src = json.loads(row['body'])
                result['candidates'].extend(json.loads(row['result']).get('pending', []))
                for s in src['segments']:
                    result['evidence'].append({'id': s['id'], 'meeting_id': src['meeting_id'],
                        'speaker': self.names.get(s['speaker'], s['speaker']), 'quote': s['text'],
                        'source_start_ms': s['start_ms'], 'source_end_ms': s['end_ms'],
                        'start_ms': None, 'end_ms': None, 'provenance': 'corpus_transcript'})
            return result
        finally:
            store.close()

    def retrieve(self, scope, query='', recent_ms=None):
        visible = self.visible(scope)
        history = self.history_context(scope)
        if recent_ms is not None:
            start = max(scope['meeting_start_ms'], scope['cursor_ms'] - recent_ms)
            # Include only whole stable windows. The coverage explicitly reports their bounds.
            evidence = [e for e in visible if e['meeting_id'] == scope['meeting_id'] and e['start_ms'] >= start]
            coverage = {'requested_start_ms': start, 'requested_end_ms': scope['cursor_ms'],
                        'stable_start_ms': min((e['start_ms'] for e in evidence), default=start),
                        'stable_end_ms': max((e['end_ms'] for e in evidence), default=start)}
        else:
            terms = re.findall(r'[A-Za-z0-9]+', query)
            aliases = {'电池': 'battery batteries power kinetic', '供电': 'battery batteries power kinetic',
                       '体积': 'size component components', '成本': 'cost price', '任务': 'work next responsibility',
                       '分工': 'work instructions lunch', '验证': 'test evaluate', '动能': 'kinetic battery',
                       '决定': 'decided decision agreed', '方案': 'design concept'}
            for k, v in aliases.items():
                if k in query:
                    terms.extend(v.split())
            # Retrieval questions include meta words ('meeting', 'reason', 'rejected')
            # which otherwise outrank the actual design issue across a full archive.
            noise = {'meeting','previous','last','reason','reasons','decision','decisions','rejected','adopted','not','why','remote','control','the','was','were','and','for','of','in','to'}
            terms = [t.lower() for t in terms if t.lower() not in noise]
            if set(terms).intersection({'charging','charge','recharge','rechargeable','dock','cradle'}):
                terms.extend(['charging','charge','rechargeable','cradle','complexity','battery'])
            terms = list(dict.fromkeys(terms))[:24]
            ranked = []
            if terms:
                # Each query owns its SQLite connection; the shared corpus is immutable.
                db = sqlite3.connect(':memory:')
                try:
                    db.execute('CREATE VIRTUAL TABLE e USING fts5(id UNINDEXED,text)')
                    all_rows = visible + history['evidence']
                    db.executemany('INSERT INTO e VALUES (?,?)', [(e['id'], e['quote']) for e in all_rows])
                    hits = [r[0] for r in db.execute('SELECT id FROM e WHERE e MATCH ? ORDER BY bm25(e) LIMIT 16',
                                                   (' OR '.join('"'+t+'"' for t in terms),))]
                    lookup = {e['id']: e for e in all_rows}
                    ranked = [lookup[i] for i in hits]
                finally:
                    db.close()
            if ranked:
                ids = {e['id'] for e in ranked}
                for pool in [visible, history['evidence']]:
                    for i, e in enumerate(pool):
                        if e['id'] in ids:
                            ranked.extend(pool[max(0, i-1):i+2])
                evidence = list({e['id']: e for e in ranked}.values())[:40]
            else:
                evidence = visible[-45:]
            coverage = {'cursor_ms': scope['cursor_ms'], 'selection': 'retrieved_windows'}
        lookup = {e['id']: e for e in history['evidence']}
        def referenced(value):
            if isinstance(value, str):
                return [value] if value in lookup else []
            if isinstance(value, list):
                return [i for v in value for i in referenced(v)]
            if isinstance(value, dict):
                return [i for v in value.values() for i in referenced(v)]
            return []
        aliases = {}
        business = {k:v for k,v in history.items() if k!='evidence'}
        for row in history['decisions']+history['tasks']:
            key = row.get('id') or row.get('guid')
            if key: aliases[key] = list(dict.fromkeys(referenced(row)))
        # Business records already expose their evidence IDs to the model. Return the actual
        # source rows too, so citations to those records can be opened and verified.
        evidence = list({e['id']: e for e in evidence + [lookup[i] for i in referenced(business)]}.values())
        return {'evidence': evidence, 'coverage': coverage, 'citation_aliases': aliases,
                'business': {k: v for k, v in history.items() if k != 'evidence'},
                'boundary': '当前内容为 STT 词轴回放；归档历史若有导入则使用人工逐字稿与 Service 状态。候选分工未确认。'}
