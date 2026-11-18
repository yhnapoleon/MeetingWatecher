import unittest
from run_full_context_v5 import build_manifest


class CurrentPolicyTests(unittest.TestCase):
    def test_gate_schedules_each_scenario_once_and_rejects_unknown_selection(self):
        from run_context_v5_fixes import current_manifest, batches
        m=current_manifest();parts=batches(m,['C03','CTX_ES2002a_roles','M2-service'])
        self.assertEqual([p['name'] for p in parts],['gate','remaining'])
        self.assertEqual({j['id'] for j in parts[0]['jobs']},{'C03','CTX_ES2002a_roles'})
        self.assertEqual(parts[0]['chains'],['M2-service'])
        keys=[(j['group'],j['id']) for p in parts for j in p['jobs']]+[('chains',n) for p in parts for n in p['chains']]
        self.assertEqual(len(keys),95)
        self.assertEqual(len(set(keys)),95)
        with self.assertRaises(ValueError):batches(m,['missing'])

    def test_new_manifest_migrates_user_policy_without_changing_old_contract(self):
        from run_context_v5_fixes import current_manifest
        old=build_manifest();new=current_manifest()
        self.assertEqual(len(new['jobs']),93)
        for key in ('pairs/P03a','pairs/P12a'):
            self.assertEqual(new['rules'][key]['item_counts'],[1])
            self.assertEqual(new['rules'][key]['operations'],['candidate'])
            self.assertTrue(new['rules'][key]['only_owner'])
            self.assertTrue(new['rules'][key]['no_deadline'])
            self.assertNotEqual(old['rules'][key]['item_counts'],new['rules'][key]['item_counts'])
        self.assertEqual(build_manifest(),old)


if __name__=='__main__':unittest.main()
