import unittest

from meeting_eval.extract import decision_output


class DecisionEvidenceTests(unittest.TestCase):
    meeting = {"segments": [{"id": "proposal"}, {"id": "agreement"}, {"id": "recap"}]}
    row = dict(attribute="范围", statement="仅会员", supersedes=None, final_status="effective", basis="newly_adopted",
               choice_ids=["proposal"], adoption_ids=["agreement"], later_ids=["recap"])

    def test_separate_speakers_and_shared_declaration_keep_usable_evidence(self):
        output = decision_output({"decisions": [self.row]}, self.meeting)[0]
        self.assertEqual(output, dict(attribute="范围", statement="仅会员", supersedes=None,
                                      evidence_ids=["proposal", "agreement", "recap"]))
        declared = dict(self.row, basis="communicated_rule", adoption_ids=["proposal"], later_ids=[])
        self.assertEqual(decision_output({"decisions": [declared]}, self.meeting)[0]["evidence_ids"], ["proposal"])

    def test_missing_adoption_or_unknown_later_reference_cannot_enter_decisions(self):
        for invalid in (dict(adoption_ids=[]), dict(choice_ids=[]), dict(later_ids=["fabricated"]),
                        dict(adoption_ids=[{"id": "agreement"}]), dict(basis="proposed")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                decision_output({"decisions": [dict(self.row, **invalid)]}, self.meeting)

    def test_only_effective_values_reach_the_decision_store(self):
        rows = [dict(self.row, final_status=status, basis=None, adoption_ids=[])
                for status in ("open", "withdrawn", "superseded")]
        self.assertEqual(decision_output({"decisions": rows + [self.row]}, self.meeting),
                         decision_output({"decisions": [self.row]}, self.meeting))
        with self.assertRaises(ValueError):
            decision_output({"decisions": [dict(self.row, final_status="probably")]}, self.meeting)
