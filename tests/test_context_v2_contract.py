"""Behavior tests for the proposed record-level contract; no model mocks."""
import copy
import unittest

from meeting_eval.context_coverage import plan_repair, apply_repair, route_record, validate_check_alignment


def record(rid='R1',kind='work',verdict='supported',introduced_by=None):
    r=dict(record_id=rid,kind=kind,description='将测试结果发给客服',thread_ids=['T1'],evidence=['Q1'],
           check={'verdict':verdict},gap_checks=[],clarification=dict(status='not_needed',fields=[],question=None,basis='原文明确',evidence=['Q1']))
    if introduced_by:r.update(introduced_by=introduced_by,thread_ids=[])
    return r


def finding(relation='new_work',related=None):
    return dict(description='将合同发给法务',evidence=['Q1'],relation=relation,related_record_ids=related or [])


def disposition(fid='O1',action='added',ids=None):
    return dict(finding_id=fid,disposition=action,record_ids=['R_O1_1'] if ids is None else ids,evidence=['Q1'])


def verified(d,verdict='supported'):
    return {**d,'verdict':verdict}


class CoverageTests(unittest.TestCase):
    def plan(self,records=None,findings=None):
        return plan_repair(records if records is not None else [record()], findings if findings is not None else [finding()], ['Q1','Q2'], 'source-v1/check-v1')

    def test_omission_alone_triggers_repair_even_without_failed_records(self):
        p=self.plan()
        self.assertTrue(p['needs_repair']);self.assertEqual(p['target_record_ids'],[])

    def test_new_work_in_same_segment_is_added_not_deduplicated(self):
        p=self.plan();d=disposition();new=record('R_O1_1',introduced_by='O1')
        new['description']='将合同发给法务'
        result=apply_repair(p,[new],[d],[verified(d)])
        self.assertEqual([r['record_id'] for r in result['records']],['R1','R_O1_1'])
        self.assertEqual(result['unresolved_findings'],[])

    def test_verified_duplicate_can_close_without_deleting_context(self):
        original=record(kind='context_only');p=self.plan([original],[finding('same_work',['R1'])])
        d=disposition(action='covered',ids=['R1'])
        result=apply_repair(p,[original],[d],[verified(d)])
        self.assertEqual(result['records'],[original]);self.assertEqual(result['unresolved_findings'],[])

    def test_rejected_omission_closes_only_after_supported_recheck(self):
        p=self.plan();d=disposition(action='rejected',ids=[])
        self.assertEqual(apply_repair(p,[],[d],[verified(d)])['unresolved_findings'],[])
        result=apply_repair(p,[],[d],[verified(d,'contradicted')])
        self.assertEqual([f['finding_id'] for f in result['unresolved_findings']],['O1'])

    def test_failed_new_record_cannot_close_finding_or_become_work(self):
        p=self.plan();d=disposition();new=record('R_O1_1',verdict='contradicted',introduced_by='O1')
        result=apply_repair(p,[new],[d],[verified(d)])
        self.assertEqual(result['records'],p['records']);self.assertEqual(len(result['unresolved_findings']),1)

    def test_initially_supported_target_degradation_preserves_original_and_finding(self):
        original=record();p=self.plan([original],[finding('same_work',['R1'])]);bad=record(verdict='contradicted')
        d=disposition(action='covered',ids=['R1'])
        result=apply_repair(p,[bad],[d],[verified(d)])
        self.assertEqual(result['records'],[original]);self.assertEqual(len(result['unresolved_findings']),1)

    def test_rejected_disposition_cannot_close_finding_depending_on_degraded_target(self):
        original=record();p=self.plan([original],[finding('same_work',['R1'])])
        d=disposition(action='rejected',ids=[])
        result=apply_repair(p,[record(verdict='contradicted')],[d],[verified(d)])
        self.assertEqual(result['records'],[original])
        self.assertEqual([f['finding_id'] for f in result['unresolved_findings']],['O1'])

    def test_unselected_record_change_invalidates_whole_batch(self):
        p=self.plan();changed=record();changed['description']='错误改写'
        result=apply_repair(p,[changed],[disposition()],[verified(disposition())])
        self.assertEqual(result['status'],'invalid');self.assertEqual(result['records'],p['records'])

    def test_missing_disposition_preserves_first_snapshot(self):
        p=self.plan();result=apply_repair(p,[],[],[])
        self.assertEqual(result['status'],'invalid');self.assertEqual(result['records'],p['records'])
        self.assertEqual(len(result['unresolved_findings']),1)

    def test_added_cannot_point_to_existing_same_segment_record(self):
        p=self.plan();d=disposition(ids=['R1'])
        result=apply_repair(p,[],[d],[verified(d)])
        self.assertEqual(result['status'],'invalid');self.assertEqual(len(result['unresolved_findings']),1)

    def test_changed_disposition_in_recheck_does_not_close(self):
        p=self.plan();d=disposition(action='rejected',ids=[]);v=verified(disposition(action='covered',ids=['R1']))
        result=apply_repair(p,[],[d],[v])
        self.assertEqual(len(result['unresolved_findings']),1)

    def test_distinct_findings_with_shared_evidence_keep_distinct_ids(self):
        second=finding();second['description']='通知合规'
        p=self.plan(findings=[finding(),second]);d1=disposition(action='rejected',ids=[]);d2=disposition('O2','unresolved',[])
        result=apply_repair(p,[],[d1,d2],[verified(d1),verified(d2)])
        self.assertEqual([f['finding_id'] for f in result['unresolved_findings']],['O2'])

    def test_related_supported_record_is_targeted_and_unrelated_is_preserved(self):
        original=record();other=record('R2');p=self.plan([original,other],[finding('same_work',['R1'])])
        self.assertEqual(p['target_record_ids'],['R1'])
        fixed=copy.deepcopy(original);fixed['description']='发测试结果并补完整附件'
        d=disposition(action='covered',ids=['R1']);r=apply_repair(p,[fixed],[d],[verified(d)])
        self.assertEqual(r['records'],[fixed,other])

    def test_wrong_thread_or_new_id_namespace_preserves_snapshot(self):
        p=self.plan([record(verdict='contradicted')]);fixed=record();fixed['thread_ids']=['T9']
        d=disposition(action='rejected',ids=[])
        self.assertEqual(apply_repair(p,[fixed],[d],[verified(d)])['status'],'invalid')
        new=record('R_NEW',introduced_by='O1')
        self.assertEqual(apply_repair(self.plan(),[new],[d],[verified(d)])['status'],'invalid')

    def test_unknown_evidence_and_invalid_relation_fail_at_boundary(self):
        f=finding();f['evidence']=['Q99']
        with self.assertRaises(ValueError):self.plan(findings=[f])
        with self.assertRaises(ValueError):self.plan(findings=[finding('new_work',['R1'])])


class RoutingTests(unittest.TestCase):
    def gap(self,field,blocking):
        r=record();r['gap_checks']=[dict(field=field,verdict='supported',blocking_for=blocking,reason='原文待决定',evidence=['Q1'])]
        r['clarification'].update(status='needed',fields=[field],question='请确认具体对象' if field=='reference' else '由谁负责？')
        return r

    def test_true_competing_reference_blocks_content(self):
        self.assertEqual(route_record(self.gap('reference','content'),{'Q1':{'segment_id':'s1','quote':'原话'}})['route'],'content_review')

    def test_normal_ellipsis_without_supported_gap_remains_work(self):
        r=record();r['description']='小林会后细化这个场景'
        self.assertEqual(route_record(r,{'Q1':{'segment_id':'s1','quote':'原话'}})['route'],'normal')

    def test_owner_gap_keeps_candidate_and_specific_question(self):
        result=route_record(self.gap('owner','operation'),{'Q1':{'segment_id':'s1','quote':'原话'}})
        self.assertEqual(result,dict(route='candidate_review',fields=['owner'],question='由谁负责？'))

    def test_classification_dispute_never_asks_owner_of_unestablished_task(self):
        r=self.gap('owner','operation');r['check']['verdict']='contradicted'
        self.assertEqual(route_record(r,{'Q1':{'segment_id':'s1','quote':'原话'}}),dict(route='unresolved',fields=[],question=None))

    def test_not_needed_cannot_hide_supported_content_gap(self):
        r=self.gap('reference','content');r['clarification'].update(status='not_needed',fields=[],question=None)
        with self.assertRaises(ValueError):route_record(r,{'Q1':{'segment_id':'s1','quote':'原话'}})

    def test_unresolved_does_not_count_as_normal_even_with_no_gap(self):
        r=record();r['clarification']['status']='unresolved'
        self.assertEqual(route_record(r,{'Q1':{'segment_id':'s1','quote':'原话'}})['route'],'unresolved')

    def test_supported_record_check_cannot_silently_reject_original_gap(self):
        original=record();original['missing_fields']=['reference']
        check=dict(record_id='R1',verdict='supported',issues=[],proposed_kind=None,
            gap_checks=[dict(field='reference',verdict='unsupported',blocking_for='none')])
        with self.assertRaises(ValueError):validate_check_alignment([original],[check])

    def test_original_gap_rejection_must_target_record_for_repair(self):
        original=record();original['missing_fields']=['reference']
        check=dict(record_id='R1',verdict='contradicted',issues=['reference','question'],proposed_kind=None,
            gap_checks=[dict(field='reference',verdict='unsupported',blocking_for='none')])
        validate_check_alignment([original],[check])

    def test_kind_change_cannot_be_marked_supported_without_repair(self):
        original=record();original['missing_fields']=[]
        check=dict(record_id='R1',verdict='supported',issues=[],proposed_kind='context_only',gap_checks=[])
        with self.assertRaises(ValueError):validate_check_alignment([original],[check])

    def test_nonblocking_supported_gap_cannot_leave_old_blocking_record_supported(self):
        original=record();original.update(missing_fields=['reference'],question='具体指哪个场景？')
        check=dict(record_id='R1',verdict='supported',issues=[],proposed_kind=None,
            gap_checks=[dict(field='reference',verdict='supported',blocking_for='none')],
            clarification=dict(status='not_needed',fields=[],question=None))
        with self.assertRaises(ValueError):validate_check_alignment([original],[check])

    def test_cleared_question_without_old_gap_still_requires_repair(self):
        original=record();original.update(missing_fields=[],question='需要另行安排吗？')
        check=dict(record_id='R1',verdict='supported',issues=[],proposed_kind=None,gap_checks=[],
            clarification=dict(status='not_needed',fields=[],question=None))
        with self.assertRaises(ValueError):validate_check_alignment([original],[check])


if __name__=='__main__': unittest.main()
