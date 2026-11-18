import json
import tempfile
import unittest
from pathlib import Path

from meeting_eval.decision_review import project_claims
from meeting_eval.extract import validate_partial
from meeting_eval.service import Service
from meeting_eval.store import Store
from test_mvp import FixedExtractor, extraction


class DecisionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Store(Path(self.temp.name) / 'history.sqlite')
        self.addCleanup(self.db.close)
        self.model = FixedExtractor(extraction())
        self.svc = Service(self.db, self.model)

    def at(self, day):
        return f'2026-11-{day:02}T12:00:00+00:00'

    def meeting(self, day, statement, audience=('host', 'guest'), **relation):
        decision = dict(attribute='资格', statement=statement, supersedes=None, evidence_ids=['s'])
        decision.update(relation)
        self.model.result = dict(extraction(), decisions=[decision])
        raw = dict(meeting_id=str(day), series='报名', audience=list(audience), started_at=self.at(day),
                   segments=[dict(id='s', speaker='主持人', text=statement)])
        result = self.svc.process(raw, 'host', self.at(day))
        self.assertEqual(result['status'], 'processed')
        return result['decision_ids'][0]

    def rows(self, day, **kwargs):
        return self.svc.decisions('报名', 'host', self.at(day), **kwargs)

    def test_version_replacement_and_return_to_original(self):
        first = self.meeting(1, '首批仅限会员')
        repeat = self.meeting(2, '首批仅限会员')
        self.assertEqual(self.rows(2, history=True)[1]['reaffirms'], first)
        self.assertEqual([d['id'] for d in self.rows(2)], [repeat])
        self.assertEqual(self.meeting(2, '首批仅限会员'), repeat)
        other = self.meeting(3, '第二批仅限会员')
        changed = self.meeting(4, '首批对所有人开放', supersedes=repeat)
        restored = self.meeting(5, '首批仅限会员', supersedes=changed)
        self.assertEqual({d['id'] for d in self.rows(4)}, {other, changed})
        self.assertEqual({d['id'] for d in self.rows(5)}, {other, restored})
        self.assertEqual(len(self.rows(5, history=True)), 5)
        self.assertEqual([d['id'] for d in self.rows(1)], [first])

    def test_paraphrase_and_audience_projection(self):
        first = self.meeting(1, '首批仅限会员')
        private = self.meeting(2, '会员才可参与首批', audience=['host'], reaffirms=first)
        self.assertEqual([d['id'] for d in self.rows(2)], [private])
        ctx = self.svc.context('报名', 'host', self.at(2), audience=['guest'])
        self.assertEqual([d['id'] for d in ctx['decisions']], [first])
        changed = self.meeting(3, '首批也对访客开放', audience=['host'], supersedes=private)
        self.assertEqual([d['id'] for d in self.rows(3)], [changed])
        self.assertEqual([d['id'] for d in self.svc.decisions('报名','guest',self.at(3))], [first])

    def test_revoked_source_hides_reference_and_preserves_visible_reaffirmation(self):
        first = self.meeting(1, '首批仅限会员')
        repeat = self.meeting(2, '会员才可参与首批', reaffirms=first)
        self.meeting(3, '第二批另定')
        with_context = self.rows(3)[-1]['source_id']
        sid = self.rows(1)[0]['source_id']
        source = json.loads(self.db.db.execute('SELECT body FROM sources WHERE id=?',(sid,)).fetchone()[0])
        source['audience'] = ['host']
        with self.db.db:
            self.db.db.execute('UPDATE sources SET body=? WHERE id=?',(json.dumps(source),sid))
        rows = self.svc.context('报名','host',self.at(2),audience=['guest'])['decisions']
        self.assertEqual([r['id'] for r in rows], [repeat])
        self.assertNotIn(first, json.dumps(rows))
        with self.assertRaisesRegex(PermissionError, 'authorization changed'):
            self.svc.retry_context(with_context, self.svc.current_source(with_context), 'host')

    def test_legacy_equivalent_rows_are_readable_without_database_migration(self):
        first = self.meeting(1, '首批仅限会员')
        repeat = self.meeting(2, '首批仅限会员')
        changed = self.meeting(3, '首批对所有人开放', supersedes=repeat)
        with self.db.db:
            for row in self.db.db.execute('SELECT id,body FROM decisions').fetchall():
                body = json.loads(row['body'])
                body.pop('reaffirms', None)
                if body['id'] == changed:
                    body['supersedes'] = first
                self.db.db.execute('UPDATE decisions SET body=? WHERE id=?',(json.dumps(body),row['id']))
        self.assertEqual([d['id'] for d in self.rows(2)], [repeat])
        self.assertEqual([d['id'] for d in self.rows(3)], [changed])
        self.assertEqual(len(self.rows(3, history=True)), 3)

    def test_review_relation_survives_validation_and_rejects_invalid_targets(self):
        meeting = dict(segments=[dict(id='s')], roster={})
        history = dict(tasks=[], decisions=[dict(id='old', attribute='资格')])
        claim = dict(attribute='资格', statement='仅会员', supersedes=None, reaffirms='old', refs=[1])
        decisions = project_claims(meeting, [claim])
        raw = dict(extraction(), decisions=decisions)
        self.assertEqual(validate_partial(raw,meeting,history)['decisions'][0]['reaffirms'], 'old')
        for change in (dict(reaffirms='unknown'), dict(reaffirms=[]), dict(attribute='年费'),
                       dict(supersedes='old')):
            raw['decisions'] = [dict(decisions[0], **change)]
            self.assertEqual(validate_partial(raw,meeting,history)['decisions'], [])

    def test_late_reaffirmation_of_retired_version_stays_in_history(self):
        from meeting_eval.decision_history import project_versions
        # Two meetings used the same earlier context; the changed value was saved first.
        base = dict(attribute='资格', statement='首批仅限会员', source_id='m1', id='d1')
        changed = dict(base,id='d2',source_id='m2',statement='首批开放',supersedes='d1')
        late = dict(base,id='d3',source_id='m3',reaffirms='d1')
        rows = [base,changed,late]
        readable = {'d1','d2','d3'}
        self.assertEqual(project_versions(rows,readable,False), [changed])
        self.assertEqual(project_versions(rows,readable,True), rows)
