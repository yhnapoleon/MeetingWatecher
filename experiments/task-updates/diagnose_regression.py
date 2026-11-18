"""Offline trace comparison and one-field interventions; not model re-evaluation."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.inputs import digest, normalize
from meeting_eval.context_state import reduce_context

OLD = ROOT/'runs/2026-11-14-context-prerequisites/guarded-regression'
NEW = ROOT/'runs/2026-11-14-task-updates/regression'
OUT = ROOT/'runs/2026-11-15-regression-diagnosis'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    inputs = {row['case_id']: row for row in map(json.loads, (NEW/'input.jsonl').read_text(encoding='utf-8').splitlines())}
    assert inputs == {row['case_id']: row for row in map(json.loads, (OLD/'input.jsonl').read_text(encoding='utf-8').splitlines())}
    comparison = []
    for cid in inputs:
        before, after = [read(folder/(cid+'.json'))['extraction'] for folder in (OLD, NEW)]
        assert before['_task_trace']['ledger'] == after['_task_trace']['ledger']
        comparison.append(dict(case_id=cid, same_input=True, same_ledger=True,
                               before_hash=digest(before), after_hash=digest(after),
                               before_items=before['items'], after_items=after['items'],
                               before_reviews=before['_task_trace']['review_records'],
                               after_reviews=after['_task_trace']['review_records']))
    probes = []

    def run(cid, label, mutate):
        extraction = read(NEW/(cid+'.json'))['extraction']
        trace = copy.deepcopy(extraction['_task_trace'])
        mutate(trace)
        result = reduce_context(trace['checked_events'], trace['uncovered_spans'], trace['checked_records'], normalize(inputs[cid], 'evaluator'), {'tasks': []})
        row = dict(case_id=cid, intervention=label, items=result['items'], pending=result['pending'], reviews=result['review_records'])
        probes.append(row)
        return row

    def assigned(trace):
        event = next(e for e in trace['checked_events'] if e['record_id'] == 'R2')
        event['commitment'] = dict(kind='assigned', evidence=copy.deepcopy(event['work']['evidence']))
        event['checks']['commitment'].update(verdict='supported', reason='Diagnostic intervention: retain explicit assignment, do not assert acceptance.')

    original = run('C03', 'unchanged', lambda trace: None)
    downgraded = run('C03', 'replace disputed acceptance with supported assignment only', assigned)
    assert len(original['items']) == 1 and len(downgraded['items']) == 2
    assert all(item['operation'] == 'candidate' for item in downgraded['items'])

    def optional_time(trace):
        trace['checked_records'][0]['missing_fields'] = []
        trace['checked_records'][0]['question'] = None

    original = run('C09', 'unchanged', lambda trace: None)
    relaxed = run('C09', 'remove date-resolution gap only; preserve deadline text and null date', optional_time)
    assert original['items'] == [] and len(relaxed['items']) == 1
    assert relaxed['items'][0]['due_text'] == 'before the next meeting' and relaxed['items'][0]['due_date'] is None

    def suggested(trace):
        event = trace['checked_events'][0]
        event['commitment']['kind'] = 'suggested'
        event['checks']['commitment'].update(verdict='supported', reason='Diagnostic intervention: classify wording as suggestion, not acceptance.')

    original = run('C26', 'unchanged', lambda trace: None)
    held = run('C26', 'change commitment interpretation to suggested only', suggested)
    assert len(original['items']) == 1 and held['items'] == []
    assert 'commitment' in held['reviews'][0]['missing_fields']
    output = dict(date='2026-11-15', kind='offline_counterfactual_diagnosis', model_calls=0,
                  production_modified=False, comparison=comparison, probes=probes,
                  caveats=['Interventions isolate program behavior; they do not validate model accuracy or constitute fixes.',
                           'C03 short acknowledgment is explicitly uncertain in frozen labels.',
                           'C09 clearing the time gap restores an incomplete work description; purpose remains unresolved.',
                           'Changed prompts and new model samples were both involved; semantic flips cannot be attributed to one prompt line.'])
    OUT.mkdir(exist_ok=True)
    (OUT/'diagnosis.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(cases_compared=len(comparison), identical_ledgers=len(comparison), probes=len(probes), passed=True, model_calls=0), indent=2))


if __name__ == '__main__':
    main()
