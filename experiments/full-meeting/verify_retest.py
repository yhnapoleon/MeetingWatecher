"""Offline acceptance and usage accounting for the two saved full meetings."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import zipfile

spec=importlib.util.spec_from_file_location('full_run',Path(__file__).with_name('run.py'))
run=importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('out',type=Path)
    args=parser.parse_args()
    checks={}
    usage={}
    for mid in ('ES2002a','ES2002b'):
        folder=args.out/mid
        source=read(folder/'input.json')
        result=read(folder/'result.json')
        assert source==read(run.ROOT/f'runs/2026-11-17-full-meeting-{mid}-fresh-v17/input.json')
        assert result['status']=='processed' and not result['extraction']['_errors']
        trace=result['extraction']['_task_trace']
        tracking=trace['tracking']
        assert tracking['status']=='complete'
        assert tracking['completed_segments']==len(source['segments'])
        with zipfile.ZipFile(folder/'source.zip') as z:
            paths=[n for n in z.namelist() if n.startswith(('meeting_eval/','prompts/')) and not n.endswith('/')]
            assert all(z.read(n)==(run.ROOT/n).read_bytes() for n in paths)
        store=run.Store(folder/'state.sqlite')
        try:
            assert store.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            svc=run.Service(store)
            sid=result['source_id']
            frozen=json.loads(store.db.execute('SELECT body FROM extraction_context WHERE source_id=?',(sid,)).fetchone()[0])
            assert frozen['context']=={'tasks':[],'decisions':[]} and frozen['actor']==run.ACTOR
            with patch('urllib.request.urlopen',side_effect=AssertionError('Offline verification attempted HTTP')):
                assert svc.process(source,run.ACTOR,run.AT)==result
                assert svc.result(sid)==result
                assert svc.minutes(sid,run.ACTOR)==(folder/'minutes.md').read_text(encoding='utf8')
                assert svc.requirements(sid,run.ACTOR)==read(folder/'requirements.json')
                assert store.tasks()==read(folder/'tasks.json')
        finally:
            store.close()
        checks[mid]=dict(same_input_as_v17=True,source_snapshot_files=len(paths),
            source_unchanged=True,full_tracking_segments=tracking['completed_segments'],
            tracking_splits=len(tracking['splits']),final_errors=[],
            database_integrity=True,independent_empty_history=True,
            offline_repeat_and_reopen_consistent=True)
        if mid=='ES2002b':
            sample=next(r for r in trace['checked_records'] if r['record_id']=='R13')
            assert sample['kind']=='context_only' and sample['qualification']['work_basis']=='meeting_discourse'
            assert 'R13' not in trace['item_records']
            assert all(r['record_id']!='R13' for r in read(folder/'requirements.json'))
            checks[mid]['presentation_remark_no_task_or_review']=True
        paths=sorted((folder/'model').rglob('meta.json'))
        metas=[read(p) for p in paths]
        states=[read(p) for p in (folder/'model').rglob('state.json')]
        assert sum(len(s['attempts']) for s in states)==len(metas)
        usage[mid]=dict(requests=len(metas),known_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),
            requests_with_unknown_usage=sum(m.get('usage') is None for m in metas),
            attempts=[dict(path=str(p.relative_to(args.out)),stage=m['stage'],
                tokens=(m.get('usage') or {}).get('total_tokens'),outcome=m.get('outcome'),
                duration_seconds=m.get('duration_seconds')) for p,m in zip(paths,metas)])
    usage['total']=dict(requests=sum(v['requests'] for v in usage.values()),
        known_tokens=sum(v['known_tokens'] for v in usage.values()),
        requests_with_unknown_usage=sum(v['requests_with_unknown_usage'] for v in usage.values()))
    run.write(args.out/'acceptance.json',checks)
    run.write(args.out/'usage-audit.json',usage)
    run.write(args.out/'experiment-files.json',{str(p.relative_to(run.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__),Path(__file__).with_name('score_retest.py'),Path(__file__).with_name('retry_retest.py'),Path(__file__).with_name('run.py'))})
    print(json.dumps(dict(checks=checks,usage=usage['total']),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
