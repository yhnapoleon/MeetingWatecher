"""Score reviewed action meaning, independently from source-anchor identity."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.review_action_semantics import JUDGMENTS, index_cases, read_jsonl, validate_review


def prf(hits, expected, predicted):
    return dict(hits=hits, expected=expected, predicted=predicted,
                precision=hits/predicted if predicted else None,
                recall=hits/expected if expected else None,
                f1=2*hits/(expected+predicted) if expected+predicted else None)


def score_semantics(predictions, labels, review):
    validate_review(review, review['inputs'], labels, predictions)
    supplied = index_cases(predictions)
    gold = [r for r in labels if r['operation'] in ('create','candidate')]
    hits = full = unsupported = unsafe = executable_hits = 0
    fields = Counter()
    predicted = sum(len(r['items']) for r in predictions)
    errors = []
    matched = set()
    for case in review['cases']:
        cid = case['case_id']
        for row in case['judgments']:
            item = supplied[cid]['items'][row['prediction_index']]
            content = row['gold_event_id'] is not None and row['content_supported'] and row['content_complete']
            correct = content and all(row[k] for k in JUDGMENTS)
            hits += int(content)
            full += int(correct)
            unsupported += int(not row['content_supported'])
            unsafe += int(item['operation'] == 'create' and not correct)
            executable_hits += int(item['operation'] == 'create' and correct)
            if content:
                matched.add((cid,row['gold_event_id']))
            wrong = [k for k in JUDGMENTS if not row[k]]
            fields.update(wrong)
            if not correct:
                errors.append(dict(case_id=cid, prediction_index=row['prediction_index'],
                                   gold_event_id=row['gold_event_id'], wrong=wrong, reason=row['reason']))
    return dict(version='action-semantics-v2', review_status=review['status'], reviewer=review['reviewer'],
        content=prf(hits,len(gold),predicted), fully_correct=prf(full,len(gold),predicted),
        correct_create=prf(executable_hits,sum(g['operation']=='create' for g in gold),
                           sum(i['operation']=='create' for r in predictions for i in r['items'])),
        unsupported_predictions=unsupported, unsupported_rate=unsupported/predicted if predicted else None,
        unsafe_create_proposals=unsafe, field_errors=dict(fields),
        candidate_predictions=sum(i['operation']=='candidate' for r in predictions for i in r['items']),
        pending_count=sum(len(r.get('pending',[])) for r in predictions),
        failed_cases=[r['case_id'] for r in predictions if r.get('status') in ('failed','partial') or r.get('errors')],
        uncertain_references=[g['event_id'] for g in gold if g.get('uncertainty')],
        missed_content=[g['event_id'] for g in gold if (g['case_id'],g['event_id']) not in matched], errors=errors)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--predictions', type=Path, required=True)
    p.add_argument('--labels', type=Path, required=True)
    p.add_argument('--review', type=Path, required=True)
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    result = score_semantics(read_jsonl(a.predictions),read_jsonl(a.labels),json.loads(a.review.read_text(encoding='utf-8')))
    text = json.dumps(result, ensure_ascii=False, indent=2)+'\n'
    if a.out:
        a.out.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
