"""Export and validate source-backed semantic reviews; never calls a model."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from meeting_eval.inputs import digest

JUDGMENTS = ('content_supported', 'content_complete', 'owner_correct',
             'commitment_correct', 'time_correct', 'operation_correct')


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def index_cases(rows):
    result = {row['case_id']: row for row in rows}
    if len(result) != len(rows):
        raise ValueError('Duplicate case_id')
    return result


def export_review(inputs, labels, predictions):
    sources, supplied = index_cases(inputs), index_cases(predictions)
    if sources.keys() != supplied.keys():
        raise ValueError('Prediction case coverage differs from input')
    cases = []
    for cid, source in sources.items():
        guesses = supplied[cid]['items']
        if not isinstance(guesses, list):
            raise ValueError('Prediction items must be a list')
        cases.append(dict(case_id=cid, reviewed=False, segments=copy.deepcopy(source['segments']),
            references=copy.deepcopy([r for r in labels if r['case_id'] == cid]),
            predictions=copy.deepcopy(guesses), judgments=[dict(prediction_index=i,
                gold_event_id=None, **{k:None for k in JUDGMENTS}, reason='', evidence_ids=[])
                for i in range(len(guesses))]))
    return dict(version='action-semantics-v2', status='draft', reviewer='',
                hashes=dict(inputs=digest(inputs), labels=digest(labels), predictions=digest(predictions)),
                inputs=copy.deepcopy(inputs), cases=cases)


def validate_review(review, inputs, labels, predictions):
    expected = dict(inputs=digest(inputs), labels=digest(labels), predictions=digest(predictions))
    if review.get('hashes') != expected or digest(review.get('inputs')) != expected['inputs']:
        raise ValueError('Review hash mismatch; re-review changed data or predictions')
    if review.get('version') != 'action-semantics-v2' or review.get('status') not in ('agent_reviewed','human_reviewed') or not review.get('reviewer'):
        raise ValueError('Review is incomplete or unsupported')
    sources, supplied, cases = index_cases(inputs), index_cases(predictions), index_cases(review['cases'])
    if sources.keys() != supplied.keys() or sources.keys() != cases.keys():
        raise ValueError('Review case coverage mismatch')
    gold = {}
    for label in labels:
        if label['case_id'] not in sources:
            raise ValueError('Reference outside selected inputs')
        key = label['case_id'], label['event_id']
        if key in gold:
            raise ValueError('Duplicate reference event')
        gold[key] = label
    for cid, case in cases.items():
        guesses = supplied[cid]['items']
        references = [r for r in labels if r['case_id'] == cid]
        if case.get('reviewed') is not True or case.get('segments') != sources[cid]['segments'] or case.get('references') != references or case.get('predictions') != guesses:
            raise ValueError('Review source/reference/prediction snapshot mismatch or unreviewed case')
        judgments = case['judgments']
        indexes = [r['prediction_index'] for r in judgments]
        if len(indexes) != len(set(indexes)) or set(indexes) != set(range(len(guesses))):
            raise ValueError('Incomplete prediction review coverage')
        used = set()
        allowed = {s['id'] for s in sources[cid]['segments']}
        for row in judgments:
            if not all(type(row.get(k)) is bool for k in JUDGMENTS) or not isinstance(row.get('reason'), str) or not row['reason'].strip():
                raise ValueError('Missing semantic judgment or reason')
            evidence = row.get('evidence_ids')
            if not isinstance(evidence, list) or not set(evidence) <= allowed:
                raise ValueError('Review cites unknown evidence')
            target = row.get('gold_event_id')
            if target is not None:
                if (cid,target) not in gold or gold[cid,target]['operation'] not in ('create','candidate'):
                    raise ValueError('Invalid gold event match')
                if target in used:
                    raise ValueError('Semantic matches must be one-to-one')
                used.add(target)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs', type=Path, required=True)
    p.add_argument('--labels', type=Path, required=True)
    p.add_argument('--predictions', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    result = export_review(read_jsonl(a.inputs), read_jsonl(a.labels), read_jsonl(a.predictions))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Exported {len(result["cases"])} cases; review status is draft')


if __name__ == '__main__':
    main()
