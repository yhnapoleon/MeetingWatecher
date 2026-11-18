"""Read-only verification of authored data, provenance and behavior references."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.inputs import digest, normalize
from scripts.review_action_semantics import read_jsonl

HERE = Path(__file__).resolve().parent
inputs = read_jsonl(HERE/'input.jsonl')
labels = read_jsonl(HERE/'labels.jsonl')
behavior = json.loads((HERE/'behavior.json').read_text(encoding='utf-8'))
manifest = json.loads((HERE/'manifest.json').read_text(encoding='utf-8'))
assert manifest['status'] == 'frozen'
assert manifest['input_hash'] == behavior['input_hash'] == digest(inputs)
assert manifest['labels_hash'] == behavior['labels_hash'] == digest(labels)
assert manifest['behavior_hash'] == digest(behavior)
assert manifest['evaluation_role'] == 'synthetic_mechanism_check' and manifest['is_blind'] is False
assert len(inputs) == len({c['case_id'] for c in inputs}) == 8
assert len(labels) == len({r['event_id'] for r in labels}) == 9
assert sum(r['operation'] in ('create', 'candidate') for r in labels) == 6
sources = {c['case_id']: normalize(c, 'evaluator') for c in inputs}
for row in labels:
    src = sources[row['case_id']]
    text = {s['id']:s['text'] for s in src['segments']}
    assert set(row['evidence_ids']) <= text.keys()
    assert row['owner_ref'] is None or row['owner_ref'] in src['roster']
    for values in row['field_evidence'].values():
        for span in values:
            assert text[span['segment_id']][span['start']:span['end']] == span['quote']
contract = json.loads((ROOT/'experiments/action-context/behavior-contract.json').read_text(encoding='utf-8'))
corpus_sources = {}
for view in contract['source_views'].values():
    folder = ROOT/view['path']
    rows = read_jsonl(folder/'input.jsonl')
    refs = read_jsonl(folder/'labels.jsonl')
    assert view['input_hash'] == digest(rows)
    assert view['labels_hash'] == digest(refs)
    corpus_sources.update({c['case_id']: c for c in rows if c['case_id'] in view['selected_cases']})
for collection, cases in ((behavior, sources), (contract, corpus_sources)):
    assert {c['case_id'] for c in collection['cases']} == cases.keys()
    for row in collection['cases']:
        ids = {s['id'] for s in cases[row['case_id']]['segments']}
        assert len(row['criteria']) == len({c['id'] for c in row['criteria']})
        for criterion in row['criteria']:
            assert set(criterion['evidence_ids']) <= ids
            if 'checkpoint_after_segment' in criterion:
                assert criterion['checkpoint_after_segment'] in ids
print(json.dumps(dict(status='verified', synthetic_cases=8, reference_actions=6,
                      known_case_contracts=len(contract['cases']),
                      synthetic_criteria=sum(len(c['criteria']) for c in behavior['cases']),
                      known_case_criteria=sum(len(c['criteria']) for c in contract['cases'])), ensure_ascii=False))
