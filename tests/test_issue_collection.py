import copy
import json
from pathlib import Path
import tempfile
import unittest

from meeting_eval.service import Service
from meeting_eval.store import Store

FIXTURE=json.loads((Path(__file__).parent/'fixtures/sv05_verified_issue.json').read_text(encoding='utf8'))
AT='2026-11-17T10:01:00+08:00'


class RecordedExtractor:
    strategy='context-v5'
    def __init__(self):self.calls=0;self.output=copy.deepcopy(FIXTURE['extraction'])
    def extract(self,*args):self.calls+=1;return copy.deepcopy(self.output)


class IssueCollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'state.sqlite';self.store=Store(self.db);self.addCleanup(lambda:self.store.close())
        self.extractor=RecordedExtractor();self.svc=Service(self.store,self.extractor)
        self.raw=copy.deepcopy(FIXTURE['input']['meeting']);self.actor=FIXTURE['input']['actor']

    def test_sv05_is_durable_and_diagnostic_is_separate(self):
        out=self.svc.process(self.raw,self.actor,AT);sid=out['source_id']
        issues=self.svc.collected_issues(sid,self.actor)
        self.assertEqual(len(issues),1);self.assertIn('讲义',issues[0]['statement']);self.assertNotIn('教室',issues[0]['statement'])
        self.assertEqual(issues[0]['retention_state'],'collected');self.assertEqual(issues[0]['resolution_state'],'open')
        self.assertEqual(self.store.tasks(),[])
        minutes=self.svc.minutes(sid,self.actor)
        self.assertEqual(minutes.count(issues[0]['issue_id']),1)
        self.assertIn('已收录·待确定',minutes);self.assertIn('系统核验诊断',minutes)
        self.assertEqual(out['extraction']['_task_trace'],FIXTURE['extraction']['_task_trace'])
        self.svc.process(self.raw,self.actor,AT);self.assertEqual(self.extractor.calls,1)
        self.store.close();self.store=Store(self.db);self.svc=Service(self.store,self.extractor)
        self.assertEqual(self.svc.collected_issues(sid,self.actor),issues)
        with self.assertRaises(PermissionError):self.svc.collected_issues(sid,'outsider')
        # A later source ACL revocation also gates older cached issues.
        row=self.store.db.execute('SELECT body FROM sources WHERE id=?',(sid,)).fetchone()
        source=json.loads(row['body']);source['audience']=[]
        with self.store.db:self.store.db.execute('UPDATE sources SET body=? WHERE id=?',(json.dumps(source),sid))
        with self.assertRaises(PermissionError):self.svc.collected_issues(sid,self.actor)

    def test_unverified_minutes_do_not_create_collected_issues(self):
        self.extractor.output['_minutes_review']['status']='failed'
        out=self.svc.process(self.raw,self.actor,AT)
        self.assertEqual(self.svc.collected_issues(out['source_id'],self.actor),[])

    def test_new_source_version_has_distinct_issue_identity(self):
        first=self.svc.process(self.raw,self.actor,AT)
        self.raw['segments'][0]['text']+=' 请记录。'
        second=self.svc.process(self.raw,self.actor,'2026-11-17T10:02:00+08:00')
        self.assertNotEqual(first['collected_issues'][0]['issue_id'],second['collected_issues'][0]['issue_id'])


if __name__=='__main__':unittest.main()
