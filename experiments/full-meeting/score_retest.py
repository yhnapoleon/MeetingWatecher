"""Export full-Service predictions and total a separately reviewed, frozen-rubric audit.

No model calls. Labels must be supplied in OUT/annotations.json after reading sources.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def inventory(folder):
    result = read(folder/'result.json')
    extraction = result['extraction']
    trace = extraction['_task_trace']
    reviews = read(folder/'requirements.json')
    source = read(folder/'input.json')
    segments = {s['id']: s for s in source['segments']}
    records = {r['record_id']: r for r in trace.get('checked_records', [])}
    assert len(trace['item_records']) == len(extraction['items'])
    tasks = {}
    for rid, item in zip(trace['item_records'], extraction['items']):
        assert rid not in tasks
        tasks[rid] = dict(record_id=rid, in_items=True, in_review=False, item=item,
                          description=item['description'], evidence_ids=item['evidence_ids'])
    for review in reviews:
        if not review['can_add_task']:
            continue
        rid = review['record_id']
        task = tasks.setdefault(rid, dict(record_id=rid, in_items=False,
            description=review['description'], evidence_ids=review['evidence_ids']))
        task.update(in_review=True, review=review)
    for rid, task in tasks.items():
        task['checked_record'] = records.get(rid)
        task['source'] = [segments[sid] for sid in task['evidence_ids']]
    decisions = [dict(index=i, output=d, source=[segments[sid] for sid in d['evidence_ids']])
                 for i, d in enumerate(extraction['decisions'], 1)]
    return dict(status=result['status'], tasks=list(tasks.values()), decisions=decisions,
        review_counts=dict(Counter(r['category'] for r in reviews)),
        non_task_reviews=[r for r in reviews if not r['can_add_task']],
        context_records=trace.get('context_records', []),
        input_sha256=hashlib.sha256((folder/'input.json').read_bytes()).hexdigest(),
        result_sha256=hashlib.sha256((folder/'result.json').read_bytes()).hexdigest())


def metrics(tp, fp, hits, reference):
    return dict(tp=tp, fp=fp, predictions=tp+fp, reference_hits=hits,
        reference=reference, fn=reference-hits,
        precision=tp/(tp+fp) if tp+fp else None, reference_recall=hits/reference)


def score(inv, labels, task_reference, decision_reference):
    assert labels['result_sha256']==inv['result_sha256'], 'Labels belong to another final result'
    task_labels = {a['record_id']: a for a in labels['tasks']}
    assert len(task_labels) == len(labels['tasks'])
    assert set(task_labels) == {t['record_id'] for t in inv['tasks']}, 'Every task must be reviewed'
    assert all(a['verdict'] in ('TP', 'FP') and a['reason'] for a in task_labels.values())
    hits = [a['reference'] for a in task_labels.values() if a.get('reference')]
    assert all(a['verdict']=='TP' for a in task_labels.values() if a.get('reference'))
    assert len(set(hits)) == len(hits)
    assert set(hits) <= {f'T{i}' for i in range(1, task_reference+1)}
    tp = sum(a['verdict']=='TP' for a in task_labels.values())
    item_labels = [task_labels[t['record_id']] for t in inv['tasks'] if t['in_items']]
    item_tp = sum(a['verdict']=='TP' for a in item_labels)
    decision_labels = {a['index']: a for a in labels['decisions']}
    assert len(decision_labels) == len(labels['decisions'])
    assert set(decision_labels) == {d['index'] for d in inv['decisions']}, 'Every decision row must be reviewed'
    # A frozen semantic unit can span complementary rows (e.g. one button set).
    # Explicitly named units are counted once; all contributing rows remain audited.
    claim_groups = {}
    for a in decision_labels.values():
        for i, c in enumerate(a['claims']):
            unit = c.get('unit', f"row-{a['index']}-claim-{i}")
            if unit in claim_groups:
                prior = claim_groups[unit]
                assert (prior['name'],prior['verdict']) == (c['name'],c['verdict'])
                assert a.get('grouping_reason'), 'Cross-row grouping must be explained'
            else:
                claim_groups[unit] = c
    claims = list(claim_groups.values())
    assert all(c['verdict'] in ('TP','FP') and c['reason'] and c['name'] for c in claims)
    assert all(a['claims'] for a in decision_labels.values())
    dhits = {h for a in decision_labels.values() for h in a.get('reference_hits', [])}
    assert dhits <= {f'D{i}' for i in range(1, decision_reference+1)}
    dtp = sum(c['verdict']=='TP' for c in claims)
    return dict(status=inv['status'], tasks=metrics(tp,len(task_labels)-tp,len(hits),task_reference),
        items_only=metrics(item_tp,len(item_labels)-item_tp,
            len({a['reference'] for a in item_labels if a.get('reference')}),task_reference),
        decisions=metrics(dtp,len(claims)-dtp,len(dhits),decision_reference),
        decision_rows=len(decision_labels), review_counts=inv['review_counts'],
        input_sha256=inv['input_sha256'], result_sha256=inv['result_sha256'])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('out',type=Path)
    args=parser.parse_args()
    inventories={}
    for mid in ('ES2002a','ES2002b'):
        folder=args.out/mid
        if (folder/'result.json').exists():
            inventories[mid]=inventory(folder)
            write(folder/'audit-inventory.json',inventories[mid])
    if not (args.out/'annotations.json').exists():
        print('Inventories exported; annotations.json is required for scoring.')
        return
    assert set(inventories)=={'ES2002a','ES2002b'}
    labels=read(args.out/'annotations.json')
    scored={mid:score(inventories[mid],labels[mid],3 if mid=='ES2002a' else 4,
                     3 if mid=='ES2002a' else 8) for mid in inventories}
    for mid, values in scored.items():
        summary=read(args.out/mid/'summary.json')
        values['initial_status']=summary.get('initial_status',summary['status'])
        values['explicit_recovery_calls']=summary.get('recovery_calls',0)
    total={}
    for kind in ('tasks','items_only','decisions'):
        rows=[m[kind] for m in scored.values()]
        total[kind]=metrics(*(sum(r[k] for r in rows) for k in ('tp','fp','reference_hits','reference')))
    value=dict(meetings=scored,total=total,
        rubric_sha256=hashlib.sha256((args.out/'rubric-before-run.json').read_bytes()).hexdigest(),
        limitations=['Two previously exposed development meetings; fresh full runs, plus one explicit technical recovery for ES2002a.',
            'Reference recall is not exhaustive full-transcript recall.',
            'Precision is human adjudication of task identity / independent decision claims, not field accuracy.',
            'Task check inference differs from the previous full v17 run.'])
    write(args.out/'evaluation.json',value)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
