"""Verify the recorded final run against current sources, without model calls."""
import hashlib
import json
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.inputs import digest, normalize
from meeting_eval.context_state import reduce_context

BASE = ROOT / 'runs/2026-11-14-task-updates'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    verified = []
    for path in list((BASE/'final').glob('*/result.json')) + [BASE/'replay-final/m1-result.json', BASE/'replay-final/m2-result.json']:
        config = read(path)['extraction']['_task_trace']['config']
        assert config['version'] == 4
        for name, value in config['code'].items():
            assert digest((ROOT/'meeting_eval'/name).read_text(encoding='utf-8')) == value, (path, name)
        for stage, value in config['prompts'].items():
            assert digest((ROOT/'prompts'/(stage.replace('_', '-')+'-context-v1.txt')).read_text(encoding='utf-8')) == value
        verified.append(str(path.relative_to(ROOT)))
    assert len(verified) == 15
    regression = []
    for name in ('regression', 'context'):
        for line in (BASE/name/'input.jsonl').read_text(encoding='utf-8').splitlines():
            source = json.loads(line)
            result = read(BASE/name/(source['case_id']+'.json'))
            trace = result['extraction']['_task_trace']
            reduced = reduce_context(trace['checked_events'], trace['uncovered_spans'], trace['checked_records'], normalize(source, 'evaluator'), {'tasks': []})
            assert all(reduced[key] == result['extraction'][key] for key in ('items', 'updates'))
            regression.append(source['case_id'])
    with zipfile.ZipFile(BASE/'before.zip') as archive:
        assert archive.read('meeting_eval/task_events.py').decode('utf-8').replace('\r\n', '\n') == (ROOT/'meeting_eval/task_events.py').read_text(encoding='utf-8')
    comparisons = read(ROOT/'runs/2026-11-14-evidence-implementation/comparison-summary.json')['final_policy_audit']['comparisons']
    assert len(comparisons) == 37 and all(row['identical_items_updates'] for row in comparisons)
    connection = sqlite3.connect('file:'+str(BASE/'replay-final/state.sqlite')+'?mode=ro', uri=True)
    rows = [json.loads(row[0]) for row in connection.execute('select body from task_events order by seq')]
    connection.close()
    originals = {task['guid'] for task in rows if task['status'] == 'open' and task.get('due_date') == '2026-11-13'}
    done = [task for task in rows if task['guid'] in originals and task['status'] == 'done']
    assert len(done) == 1 and done[0]['due_date'] == '2026-11-13'
    acceptance = read(BASE/'replay-final/acceptance.json')
    assert len(acceptance['checks']) == 12 and all(acceptance['checks'].values())
    assert not (BASE/'replay-final/first-pass').exists()
    summary = read(BASE/'summary.json')
    groups = list(summary['variants'].values()) + list(summary['regression'].values()) + list(summary['replays'].values())
    assert sum(group['new_calls'] for group in groups) == 87
    assert sum(group['new_tokens'] for group in groups) == 371783
    log = (BASE/'final-tests.log').read_bytes()
    log = log.decode('utf-16') if log.startswith(b'\xff\xfe') else log.decode('utf-8-sig')
    assert 'Ran 111 tests' in log and log.rstrip().endswith('OK')
    report = dict(date='2026-11-15', tests=111, evidence_policy_comparisons=37, task_events_unchanged=True,
                  final_runtime_code_and_prompt_matches=verified, regression_items_updates_unchanged_with_final_code=regression,
                  final_directed_cached_pass='13/13', final_fresh_replay_first_pass='12/12',
                  completed_task_retains_due_date='2026-11-13', new_calls=87, new_tokens=371783,
                  default_strategy='split-v3', overall_semantic_quality_accepted=False,
                  limitations=summary['limitations'], model_runs_pending=0)
    target = BASE/'final-verification.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    files = [ROOT/'README.md']
    for folder in ('meeting_eval', 'prompts', 'tests', 'scripts', 'docs', 'experiments/task-updates'):
        files.extend(path for path in (ROOT/folder).rglob('*') if path.is_file() and '__pycache__' not in path.parts)
    with zipfile.ZipFile(BASE/'final.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    report['final_zip_sha256'] = hashlib.sha256((BASE/'final.zip').read_bytes()).hexdigest()
    links = 0
    for name in ('docs/task-updates-results.md', 'docs/task-updates-design.md', 'docs/HANDOVER.md', 'docs/context-workflow.md', 'docs/superpowers/plans/2026-11-14-task-updates.md'):
        path = ROOT/name
        for link in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            if '://' not in link:
                assert (path.parent/link.split('#')[0]).exists(), (name, link)
                links += 1
    report['local_links_verified'] = links
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
