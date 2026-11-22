"""Recount published judgments and verify frozen files; no model or SQLite needed."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def main():
    base = ROOT / 'runs/2026-11-18-two-unseen-v19'
    totals = dict(task_tp=0, task_predictions=0, task_hits=0, task_reference=0,
                  decision_tp=0, decision_predictions=0, decision_hits=0, decision_reference=0)
    for mid in ('IS1000a', 'TS3003b'):
        folder = base / mid
        manifest = read(folder / 'manifest.json')
        for file, key in [('input.json', 'input_sha256'), ('reference.json', 'reference_sha256'),
                          ('rubric-before-run.json', 'rubric_sha256')]:
            if hashlib.sha256((folder / file).read_bytes()).hexdigest() != manifest[key]:
                raise ValueError(f'{mid}/{file}: frozen hash mismatch')
        labels, reference, metrics = (read(folder / name) for name in
                                      ('annotations.json', 'reference.json', 'evaluation.json'))
        if labels['result_sha256'] != metrics['result_sha256']:
            raise ValueError(f'{mid}: judgment/result identity mismatch')
        for kind, ref_key, prefix in [('tasks', 'actions', 'task'), ('decisions', 'decisions', 'decision')]:
            rows = labels[kind]
            claims = rows if kind == 'tasks' else [c for row in rows for c in row['claims']]
            tp = sum(c['verdict'] == 'TP' for c in claims)
            hits = {h for row in rows for h in row['reference_hits']}
            values = dict(tp=tp, predictions=len(claims), reference_hits=len(hits), reference=len(reference[ref_key]))
            for key, value in values.items():
                if metrics[kind][key] != value:
                    raise ValueError(f'{mid}/{kind}/{key}: recount mismatch')
            totals[prefix + '_tp'] += tp
            totals[prefix + '_predictions'] += len(claims)
            totals[prefix + '_hits'] += len(hits)
            totals[prefix + '_reference'] += len(reference[ref_key])
        print(mid + ': frozen hashes and judgment counts passed')
    print(json.dumps(totals, ensure_ascii=False))
    print('Scope: published judgments only; original result/model/database replay is separate.')


if __name__ == '__main__':
    main()
