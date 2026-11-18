"""Bind final experiments to current code and preserve a source snapshot."""
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest

BASE=ROOT/'runs/2026-11-15-field-preservation'


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    log=(BASE/'final-tests.log').read_bytes()
    text=log.decode('utf-16') if log.startswith(b'\xff\xfe') else log.decode('utf-8-sig')
    assert 'Ran 119 tests' in text and text.rstrip().endswith('OK')
    paths=list((BASE/'repaired').glob('*/result.json'))+[BASE/'replay-final/m1-result.json',BASE/'replay-final/m2-result.json']
    assert len(paths)==10
    verified=[]
    for path in paths:
        config=read(path)['extraction']['_task_trace']['config']
        assert config['version']==5
        for name,value in config['code'].items():
            assert digest((ROOT/'meeting_eval'/name).read_text(encoding='utf-8'))==value,(path,name)
        for stage,value in config['prompts'].items():
            assert digest((ROOT/'prompts'/(stage.replace('_','-')+'-context-v1.txt')).read_text(encoding='utf-8'))==value
        verified.append(str(path.relative_to(ROOT)))
    with zipfile.ZipFile(BASE/'before.zip') as archive:
        assert archive.read('meeting_eval/task_events.py').decode('utf-8').replace('\r\n','\n')==(ROOT/'meeting_eval/task_events.py').read_text(encoding='utf-8')
    old=read(ROOT/'runs/2026-11-14-evidence-implementation/comparison-summary.json')['final_policy_audit']['comparisons']
    assert len(old)==37 and all(row['identical_items_updates'] for row in old)
    for name in ('regression','context'):
        assert (BASE/name/'labels.snapshot.jsonl').read_text(encoding='utf-8')==(ROOT/'runs/2026-11-14-task-updates'/name/'labels.snapshot.jsonl').read_text(encoding='utf-8')
    summary=read(BASE/'summary.json')
    assert summary['probes']['baseline']['passed']==6 and summary['probes']['repaired']['passed']==8
    assert summary['total_cost']['new_calls']==87 and summary['total_cost']['new_tokens']==369056
    assert not (BASE/'replay-final/first-pass').exists()
    record=dict(date='2026-11-15',tests=119,final_runtime_code_prompt_matches=verified,
                old_policy_outputs_unchanged=37,old_task_events_unchanged=True,old_labels_unchanged=True,
                semantic_quality_accepted_for_default=False,default_strategy='split-v3',automatic_repair_deployed=False,
                directed_mechanical_checks='8/8',fresh_replay_first_pass='12/12',old_update_trace_replays='13/13',
                code_review_important_findings=2,important_findings_fixed=2,model_runs_pending=0,
                new_calls=87,new_tokens=369056,limitations=summary['limitations'])
    target=BASE/'final-verification.json'
    target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    links=0
    for name in ('docs/HANDOVER.md','docs/field-preservation-design.md','docs/field-preservation-results.md','docs/context-workflow.md','docs/superpowers/plans/2026-11-15-field-preservation.md'):
        path=ROOT/name
        for link in re.findall(r'\]\(([^)]+)\)',path.read_text(encoding='utf-8')):
            if '://' not in link:
                assert (path.parent/link.split('#')[0]).exists(),(name,link)
                links+=1
    with zipfile.ZipFile(BASE/'final.zip','w',zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT/'README.md','README.md')
        for folder in ('meeting_eval','prompts','tests','scripts','docs','experiments/field-preservation'):
            for path in (ROOT/folder).rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts:
                    archive.write(path,path.relative_to(ROOT).as_posix())
    record.update(final_snapshot_sha256=hashlib.sha256((BASE/'final.zip').read_bytes()).hexdigest(),local_links_verified=links)
    target.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
