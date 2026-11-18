import copy
import importlib
import unittest


def meeting():
    return dict(case_id='M',segments=[dict(id='qm.X.587',text='甲甲Q1甲'),dict(id='qm.X.590',text='')])


class WireTests(unittest.TestCase):
    def module(self):return importlib.import_module('meeting_eval.context_wire')

    def test_projection_retains_source_once_and_exact_offsets(self):
        mod=self.module();m=meeting();span=dict(segment_id='qm.X.587',quote='甲',start=4,end=5)
        p=dict(meeting=m,ledger=dict(evidence=[span]),candidates=[dict(spans=[span])],
            evidence_catalog={'Q1':dict(segment_id='qm.X.587',quote='甲甲Q1甲')},
            coverage_review=dict(unrepresented_evidence=['Q1']),description='Q1')
        original=copy.deepcopy(p);wire=mod.wire_request(p)
        self.assertEqual(p,original);self.assertEqual(wire['meeting'],m)
        self.assertNotIn('evidence_catalog',wire)
        self.assertEqual(wire['ledger']['evidence'][0],dict(segment_id='qm.X.587',start=4,end=5))
        ref=wire['candidates'][0]['spans'][0]
        self.assertEqual(m['segments'][0]['text'][ref['start']:ref['end']],span['quote'])
        self.assertEqual(wire['coverage_review']['unrepresented_evidence'],['qm.X.587'])
        self.assertEqual(wire['description'],'Q1')

    def test_decode_all_evidence_fields_only_and_collect_unknowns(self):
        mod=self.module();m=meeting()
        raw=dict(case_id='M',description='Q587',qualification=dict(evidence=['qm.X.587'],adoption_evidence=['qm.X.587']))
        converted=mod.decode_output(raw,m)
        self.assertEqual(converted['qualification'],dict(evidence=['Q1'],adoption_evidence=['Q1']))
        self.assertEqual(converted['description'],'Q587')
        bad=dict(records=[dict(evidence=['Q587'])],events=[dict(work=dict(evidence=['missing']))])
        with self.assertRaises(ValueError) as failure:mod.decode_output(bad,m)
        self.assertIn('records',str(failure.exception));self.assertIn('events',str(failure.exception))
        self.assertIn('Q587',str(failure.exception))

    def test_schema_uses_source_examples_without_repeated_catalog_enum(self):
        mod=self.module();schema={'type':'string','example':'Q1','enum':['Q1']}
        wire=mod.wire_request(dict(meeting=meeting(),output_schema=schema,output_contract='证据Q1'))
        self.assertEqual(wire['output_schema']['example'],'qm.X.587')
        self.assertNotIn('enum',wire['output_schema'])
        self.assertNotIn('output_contract',wire)
        self.assertNotIn('Q1',mod.wire_prompt('使用Q编号，例如Q1。',meeting()))

    def test_invalid_span_offsets_are_not_silently_compacted(self):
        mod=self.module()
        p=dict(meeting=meeting(),ledger=dict(evidence=[dict(segment_id='qm.X.587',quote='甲',start=2,end=3)]))
        with self.assertRaises(ValueError):mod.wire_request(p)

    def test_repair_prompt_does_not_reintroduce_q_id_instruction(self):
        from pathlib import Path
        prompt=(Path(__file__).resolve().parents[1]/'prompts/repair-work-context-v4.txt').read_text(encoding='utf8')
        converted=self.module().wire_prompt(prompt,meeting())
        self.assertNotIn('Q ID',converted);self.assertNotIn('evidence_catalog',converted)


if __name__=='__main__':unittest.main()
