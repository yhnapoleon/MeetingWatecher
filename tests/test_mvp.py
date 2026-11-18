import copy
import json
from pathlib import Path
import tempfile
import unittest

from meeting_eval.inputs import normalize
from meeting_eval.store import Store, Simulator
from meeting_eval.service import Service
from meeting_eval.extract import validate

T0 = '2026-11-09T10:00:00+08:00'
T1 = '2026-11-16T09:59:59+08:00'
T2 = '2026-11-16T10:01:00+08:00'
ROOT = Path(__file__).resolve().parents[1]


class FixedExtractor:
    def __init__(self, result):
        self.result = result

    def extract(self, meeting, context):
        return copy.deepcopy(self.result)


def action(description='整理案例', **changes):
    return dict(description=description, operation='create', owner_kind='corpus_person',
                owner_ref='chen', owner_label='陈可', due_text='这周五下班前',
                due_date='2026-11-13', action_anchor='M1.1',
                evidence_ids=['M1.1', 'M1.2'], **changes)


def extraction(items=None):
    return dict(items=items or [], facts=[], unresolved=[], decisions=[], updates=[])


class MVPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'state.sqlite'
        self.db = Store(self.path)
        self.sim = Simulator(self.db)
        self.raw = json.loads((ROOT / 'examples/m1.json').read_text(encoding='utf-8'))

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def seed(self, guid='X', **kw):
        task = dict(guid=guid, summary='同名任务', status='open', readers=['host','guest'],
                    writers=['host'], assignee='chen', tenant='local', series='登录改版')
        task.update(kw)
        self.sim.seed(task, T0)

    def service(self, result):
        return Service(self.db, FixedExtractor(result))

    def test_identity_preserves_original_and_unknown_time(self):
        m = normalize(self.raw, 'host')
        self.assertEqual(m['segments'][1]['speaker'], '说话人 2')
        self.assertEqual(m['segments'][1]['person_ref'], 'chen')
        raw = dict(meeting_id='AMI', meeting_date='13-12-04', segments=[], series='A')
        self.assertIsNone(normalize(raw, 'host')['started_at'])

    def test_history_uses_observation_time_and_current_acl(self):
        self.seed()
        self.sim.update('X', {'status':'done'}, 'host', T2, effective_at=T0)
        svc = self.service(extraction())
        self.assertEqual([t['guid'] for t in svc.recap('登录改版','guest',T1)], ['X'])
        self.assertEqual(svc.recap('登录改版','guest',T2), [])
        self.sim.update('X', {'readers':['host']}, 'host', T2)
        self.assertEqual(svc.recap('登录改版','guest',T1), [])

    def test_read_only_update_is_denied(self):
        self.seed()
        with self.assertRaises(PermissionError):
            self.sim.update('X', {'status':'done'}, 'guest', T2)
        self.assertEqual(self.sim.get('X','host')['status'], 'open')

    def test_same_version_restart_and_two_deliveries_in_one_segment(self):
        result = extraction([action(), action('发送测试报告')])
        first = self.service(result).process(self.raw,'host',T0)
        self.db.close()
        self.db = Store(self.path)
        second = self.service(result).process(self.raw,'host',T0)
        self.assertEqual(first['bindings'], second['bindings'])
        self.assertEqual(len(self.service(result).recap('登录改版','host',T1)), 2)

    def test_receipt_loss_recovers_same_guid_after_restart(self):
        intent = dict(id='intent-1', operation='create', actor='host', observed_at=T0,
                      payload=dict(summary='交付', readers=['host'], writers=['host'],
                                   tenant='local', series='登录改版', assignee='chen'))
        self.db.put_intent(intent)
        guid = self.sim.create(intent['payload'], 'host', 'intent-1', T0)['guid']
        self.db.close()
        self.db = Store(self.path)
        self.service(extraction()).recover()
        self.assertEqual(self.db.binding('intent-1'), guid)
        self.assertEqual(len(self.service(extraction()).recap('登录改版','host',T1)), 1)

    def test_invalid_evidence_rejected_before_writing(self):
        bad = action()
        bad['evidence_ids'] = ['invented']
        with self.assertRaises(ValueError):
            self.service(extraction([bad])).process(self.raw,'host',T0)
        self.assertEqual(self.service(extraction()).recap('登录改版','host',T1), [])

    def test_revision_is_preserved_without_duplicate_creation(self):
        svc = self.service(extraction([action()]))
        svc.process(self.raw,'host',T0)
        self.raw['segments'][1]['text'] += ' 改下周交。'
        result = svc.process(self.raw,'host',T2)
        self.assertEqual(result['status'], 'revision_pending')
        self.assertEqual(len(svc.recap('登录改版','host',T2)), 1)

    def test_ambiguous_update_and_joint_ownership_stay_pending(self):
        self.seed('X')
        self.seed('Y')
        upd = dict(target_guid=None, description='同名任务', owner_ref='chen',
                   status='done', evidence_ids=['M1.2'], effective_at=None)
        result = self.service({**extraction(), 'updates':[upd]}).process(self.raw,'host',T2)
        self.assertEqual(result['pending'][0]['reason'], 'ambiguous_target')
        self.assertEqual(self.sim.get('X','host')['status'], 'open')

    def test_decision_replacement_keeps_history_and_other_projects(self):
        d = dict(attribute='首批范围', statement='只限员工', supersedes=None, evidence_ids=['M1.4'])
        svc = self.service({**extraction(), 'decisions':[d]})
        r = svc.process(self.raw,'host',T0)
        did = r['decision_ids'][0]
        raw = copy.deepcopy(self.raw)
        raw['meeting_id'] = 'Next'
        d2 = {**d, 'statement':'员工与客户', 'supersedes':did}
        self.service({**extraction(), 'decisions':[d2]}).process(raw,'host',T2)
        self.assertEqual(svc.decisions('登录改版','host',T1)[0]['statement'], '只限员工')
        self.assertEqual(svc.decisions('登录改版','host',T2)[0]['statement'], '员工与客户')
        self.assertEqual(len(svc.decisions('登录改版','host',T2,history=True)), 2)
        self.assertEqual(svc.decisions('另一个项目','host',T2), [])

    def test_context_filters_source_and_tenant_before_model(self):
        self.seed('X', source_readers=['host'], evidence=[{'text':'私有原话'}])
        self.seed('Y', tenant='other')
        svc = self.service(extraction())
        ctx = svc.context('登录改版','guest',T1)
        self.assertEqual([t['guid'] for t in ctx['tasks']], ['X'])
        self.assertNotIn('私有原话', json.dumps(ctx, ensure_ascii=False))
        self.assertEqual(svc.decisions('登录改版','guest',T1), [])

    def test_mapped_account_can_complete_original_task(self):
        self.raw['account_map'] = {'chen':'ou_chen','host':'ou_host'}
        svc = self.service(extraction([action()]))
        first = svc.process(self.raw,'host',T0)
        guid = next(iter(first['bindings'].values()))
        self.assertEqual(self.sim.get(guid,'host')['assignee'],'ou_chen')
        raw = copy.deepcopy(self.raw)
        raw['meeting_id'] = 'M-next'
        upd = dict(target_guid=guid, description='整理案例',owner_ref='chen',status='done',
                   evidence_ids=['M1.2'],effective_at=None)
        self.service({**extraction(),'updates':[upd]}).process(raw,'host',T2)
        self.assertEqual(self.sim.get(guid,'host')['status'],'done')

    def test_joint_owner_report_cannot_complete_whole_task(self):
        self.seed('J',assignee=['chen','host'],readers=['host','chen'])
        upd = dict(target_guid='J',description='同名任务',owner_ref='chen',status='done',
                   evidence_ids=['M1.2'],effective_at=None)
        r = self.service({**extraction(),'updates':[upd]}).process(self.raw,'host',T2)
        self.assertEqual(r['pending'][0]['reason'],'not_single_owner_report')
        self.assertEqual(self.sim.get('J','host')['status'],'open')

    def test_effective_time_gates_future_task_and_decision_changes(self):
        self.seed()
        self.sim.update('X',{'status':'done'},'host',T0,effective_at=T2)
        svc = self.service(extraction())
        self.assertEqual([t['guid'] for t in svc.recap('登录改版','host',T1)],['X'])
        d = dict(attribute='范围',statement='员工',supersedes=None,evidence_ids=['M1.4'])
        self.raw['started_at'] = T2
        self.service({**extraction(),'decisions':[d]}).process(self.raw,'host',T0)
        self.assertEqual(svc.decisions('登录改版','host',T1),[])

    def test_expanded_source_audience_does_not_publish_old_derived_minutes(self):
        svc = self.service(extraction([action()]))
        first = svc.process(self.raw,'host',T0)
        self.raw['audience'].append('guest')
        svc.process(self.raw,'host',T2)
        with self.assertRaises(PermissionError):
            svc.minutes(first['source_id'],'guest')

    def test_inherited_private_roster_not_sent_to_expanded_audience(self):
        self.raw['roster']['secret'] = '私有参会者'
        self.service(extraction()).process(self.raw,'host',T0)
        raw = dict(meeting_id='new',series='登录改版',audience=['host','guest'],segments=[])
        class CheckExtractor:
            def extract(inner,meeting,context):
                self.assertNotIn('secret',meeting['roster'])
                return extraction()
        Service(self.db,CheckExtractor()).process(raw,'host',T2)

    def test_recovery_rechecks_current_source_writers(self):
        svc = self.service(extraction())
        original = svc.process(self.raw,'host',T0)
        self.db.put_intent(dict(id='late',source_id=original['source_id'],operation='create',actor='host',
            observed_at=T0,payload=dict(summary='延迟创建',readers=['host','chen'],writers=['host'],
                                        tenant='local',series='登录改版',assignee='chen')))
        self.raw['writers'] = ['chen']
        svc.process(self.raw,'host',T2)
        self.assertIsNone(self.db.binding('late'))
        self.assertEqual(svc.recap('登录改版','host',T2),[])

    def test_late_recovery_does_not_rewrite_earlier_recap(self):
        self.db.put_intent(dict(id='late',operation='create',actor='host',observed_at=T0,
            payload=dict(summary='延迟创建',readers=['host'],writers=['host'],
                         tenant='local',series='登录改版',assignee='chen')))
        svc = self.service(extraction())
        svc.recover(observed_at=T2)
        self.assertEqual(svc.recap('登录改版','host',T1),[])
        self.assertEqual(len(svc.recap('登录改版','host',T2)),1)

    def test_lost_receipt_can_be_confirmed_after_write_revocation(self):
        svc = self.service(extraction())
        source = svc.process(self.raw,'host',T0)
        payload = dict(summary='已创建',readers=['host','chen'],writers=['host'],
                       tenant='local',series='登录改版',assignee='chen')
        self.db.put_intent(dict(id='sent',operation='create',actor='host',observed_at=T0,
                               source_id=source['source_id'],payload=payload))
        guid = self.sim.create(payload,'host','sent',T0)['guid']
        self.raw['writers'] = ['chen']
        svc.process(self.raw,'host',T2)
        self.assertEqual(self.db.binding('sent'),guid)
        self.assertEqual(len(svc.recap('登录改版','host',T2)),1)

    def test_invalid_update_time_is_rejected_before_intent_persisted(self):
        self.seed('X',readers=['host','chen'])
        upd = dict(target_guid='X',description='同名任务',owner_ref='chen',status='done',
                   evidence_ids=['M1.2'],effective_at='tomorrow')
        with self.assertRaises(ValueError):
            self.service({**extraction(),'updates':[upd]}).process(self.raw,'host',T2)
        self.assertEqual(self.db.db.execute('SELECT count(*) FROM intents').fetchone()[0],0)

    def test_model_selected_guid_does_not_resolve_identical_task_ambiguity(self):
        self.seed('X',readers=['host','chen'])
        self.seed('Y',readers=['host','chen'])
        upd = dict(target_guid='X',description='同名任务',owner_ref='chen',status='done',
                   evidence_ids=['M1.2'],effective_at=None)
        r = self.service({**extraction(),'updates':[upd]}).process(self.raw,'host',T2)
        self.assertEqual(r['pending'][0]['reason'],'ambiguous_target')
        self.assertEqual(self.sim.get('X','host')['status'],'open')


if __name__ == '__main__':
    unittest.main()
