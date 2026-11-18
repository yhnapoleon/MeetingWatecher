"""Recheck the saved architecture probes offline; never calls the model."""
import copy
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from meeting_eval.inputs import digest
from scripts.score_mvp_actions import score

RUN = ROOT / 'runs/2026-11-14-action-architecture'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]


def main():
    config = read(RUN / 'config.json')
    labels_text = (RUN / 'labels.snapshot.jsonl').read_text(encoding='utf-8')
    assert digest(labels_text) == config['labels_hash']
    assert labels_text == (ROOT / 'data/mvp-v1/labels.jsonl').read_text(encoding='utf-8')
    assert digest((ROOT / 'scripts/diagnose_action_architecture.py').read_text(encoding='utf-8')) == config['code_hash']
    for name, expected in config['prompt_hashes'].items():
        assert digest((RUN / (name + '.prompt.txt')).read_text(encoding='utf-8')) == expected

    predictions = sorted(RUN.glob('*-r*/C*/prediction.json'))
    context_predictions = sorted((RUN / 'context-probe').glob('*-r*/C*/prediction.json'))
    assert len(predictions) == 48 and len(context_predictions) == 4
    for path in predictions + context_predictions:
        value = read(path)
        choice = read(path.with_name('response.json'))['choices'][0]
        assert not value['errors'], path
        assert choice['finish_reason'] == 'stop', path
        assert json.loads(choice['message']['content']) == read(path.with_name('parsed.json')), path

    variants = {}
    summary = read(RUN / 'summary.json')
    labels = lines(RUN / 'labels.snapshot.jsonl')
    case_ids = [case['case_id'] for case in config['cases']]
    for variant in config['variants']:
        rows, times, tokens, examples = [], [], [], {}
        for repeat in range(1, config['repeats'] + 1):
            folder = RUN / f'{variant}-r{repeat}'
            values = [read(folder / cid / 'prediction.json') for cid in case_ids]
            actual = score(values, 'dev', labels=labels, inputs=config['cases'], selected_ids=case_ids)
            saved = read(folder / 'scores.json')
            assert not saved.pop('failed_cases')
            assert actual == saved
            rows.append(actual['action_anchors']['f1'])
            tokens.append(sum(v['meta']['usage']['total_tokens'] for v in values))
            times.extend(v['meta']['seconds'] for v in values)
            for v in values:
                examples.setdefault(v['case_id'], []).append({
                    'repeat': repeat, 'items': v['items']})
        assert statistics.mean(rows) == summary[variant]['mean_f1']
        variants[variant] = dict(mean_anchor_f1=statistics.mean(rows),
                                 mean_tokens_per_six_cases=statistics.mean(tokens),
                                 mean_seconds_per_call=statistics.mean(times), cases=examples)

    context = []
    probe_config = read(RUN / 'context-probe/config.json')
    for path in context_predictions:
        request = read(path.with_name('request.json'))
        original = read(RUN / path.parents[1].name / 'C03/request.json')
        before, after = copy.deepcopy(original), copy.deepcopy(request)
        before['messages'][1]['content'] = after['messages'][1]['content'] = '<input>'
        assert before == after
        items = read(path)['items']
        context.append(dict(variant_repeat=path.parents[1].name,
                            targets=[dict(anchor=a, found=any(i['action_anchor'] == a for i in items))
                                     for a in probe_config['target_anchors']]))

    baseline = lines(ROOT / 'runs/2026-11-14-repair-final-dev/split-v3-r1/predictions.jsonl')
    corrupted = copy.deepcopy(baseline)
    for row in corrupted:
        for item in row['items']:
            item['description'] = '采购二百台服务器并立即付款'
    original_report, corrupted_report = score(baseline, 'dev'), score(corrupted, 'dev')
    assert original_report == corrupted_report
    assert original_report['action_anchors'] == read(RUN / 'metric-blindspot.json')['original_score']

    report = dict(saved_calls_checked=len(predictions) + len(context_predictions),
                  failed_calls=0, hashes_match=True, score_reports_reproduced=8,
                  unrelated_descriptions_leave_entire_score_unchanged=True,
                  context_probe=context, variants=variants)
    (RUN / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('variants', 'context_probe')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
