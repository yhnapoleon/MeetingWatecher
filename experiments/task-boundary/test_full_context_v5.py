import copy
import json
from pathlib import Path
import unittest
from run_full_context_v5 import build_manifest, assess_result

ROOT=Path(__file__).resolve().parents[2]


class FullContracts(unittest.TestCase):
    def test_frozen_scope_and_changed_labels(self):
        m=build_manifest()
        self.assertEqual(len(m['jobs']),93)
        self.assertEqual(len({(j['group'],j['id']) for j in m['jobs']}),93)
        c23=next(r for r in m['labels']['corpus'] if r['case_id']=='C23')
        self.assertNotIn('未听清',c23['description'])
        self.assertEqual(m['rules']['updates/M2']['item_counts'],[1])

    def test_m2_requires_visible_time_and_only_owner_question(self):
        m=build_manifest();rule=m['rules']['updates/M2']
        p=ROOT/'runs/2026-11-16-user-solutions/live-v3/r1/M2-service/m2-result.json'
        result=json.loads(p.read_text(encoding='utf8'))
        # Fixture has a separately generated prior task; assess semantic portion here.
        rule=copy.deepcopy(rule);rule.pop('update_expected')
        score=assess_result(result,[],rule)
        self.assertTrue(score['passed'],score)
        bad=copy.deepcopy(result);bad['extraction']['items'][0].update(description='调整范围，内部员工和试点客户开放。',due_text=None,due_date=None)
        self.assertFalse(assess_result(bad,[],rule)['checks']['today_visible'])
        bad=copy.deepcopy(result);bad['extraction']['_task_trace']['review_records'][0]['missing_fields']=['owner','commitment']
        self.assertFalse(assess_result(bad,[],rule)['passed'])

    def test_repair_failure_cannot_pass_as_no_tasks(self):
        result=dict(status='processed',extraction=dict(items=[],updates=[],_errors=[],_task_trace=dict(review_records=[],repair=dict(status='failed'))))
        self.assertFalse(assess_result(result,[],dict(item_counts=[0],no_review=True))['passed'])


if __name__=='__main__':unittest.main()
