"""Audited replay of the four JSON-keyword HTTP 400 failures, preserving ancestors.

This is a one-off experiment across a code fix, not a production configuration
migration. The original run is immutable; only the copied DB config is rebound.
"""
import argparse
import hashlib
import shutil
import time
from pathlib import Path

from run_incomplete_recovery import ROOT,read,write_json,digest,accounting,verify,configure,Extractor,Service,Store


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();manifest=read(args.source/'manifest.json')
    if {j['id'] for j in manifest['jobs']}!={'C14','SV17','SV05','SV10'}:raise ValueError('Unexpected replay scope')
    # Verify the exact deterministic provider contract error before any new call.
    for job in manifest['jobs']:
        folder=args.source/job['id'];result=read(folder/'result.json')
        if result['status']!='partial' or {e.get('field') for e in result['extraction']['_errors']}!={'items','updates'}:
            raise ValueError('Replay requires only the work dependency group to have failed')
        failures=[read(p) for p in folder.rglob('meta.json') if read(p).get('outcome')=='terminal_error']
        if len(failures)!=1 or failures[0]['stage']!='track_context' or failures[0].get('http_status')!=400 or "Prompt must contain the word 'json'" not in failures[0].get('provider_error',''):
            raise ValueError('Unexpected terminal failure')
    args.out.mkdir(parents=True,exist_ok=False)
    write_json(args.out/'manifest.json',{**manifest,'replay_source':str(args.source),'reason':'JSON mode keyword removed with redundant output_contract; fixed at ModelClient wire boundary',
        'reuse':'accepted facts, decisions and minutes; rerun only failed work group in copied database',
        'code_hash':hashlib.sha256((ROOT/'meeting_eval/model_client.py').read_bytes()).hexdigest()})
    rows=[];start=time.perf_counter()
    for job in manifest['jobs']:
        old=args.source/job['id'];folder=args.out/job['id'];shutil.copytree(old,folder)
        before=accounting(folder);original=read(old/'result.json')
        extractor=Extractor(ROOT.parent.parent/'meeting-agent/.env',folder/'model','context-v5',inference_config=manifest['inference'])
        configure(extractor,'b',None,'none');store=Store(folder/'state.sqlite')
        try:
            old_config=read(folder/'config.json')
            if not old_config['task_pipeline']['code']['model_client.py']!=extractor.config['task_pipeline']['code']['model_client.py']:
                raise ValueError('No audited code correction to replay')
            write_json(folder/'replay-provenance.json',dict(source=str(old),source_result_hash=digest(original),
                previous_config_hash=digest(old_config),new_config_hash=digest(extractor.config),baseline_accounting=before))
            # Explicit in an experimental copy only; production Service still refuses changed configs.
            with store.db:store.db.execute('UPDATE extraction_config SET body=? WHERE id=1',(__import__('json').dumps(extractor.config,ensure_ascii=False,sort_keys=True),))
            write_json(folder/'config.json',extractor.config)
            svc=Service(store,extractor)
            result=svc.process(job['meeting'],job['actor'],'2026-11-17T10:04:00+08:00')
            for field in ('facts','decisions','unresolved','_minutes_review'):
                if result['extraction'][field]!=original['extraction'][field]:raise AssertionError('Successful ancestor changed: '+field)
            write_json(folder/'result.json',result);write_json(folder/'tasks.json',store.tasks())
        finally:store.close()
        row=verify(job,folder,manifest['inference'],manifest['c14_rule'])
        row.update(new_requests=row['requests']-before['requests'],new_tokens=row['tokens']-before['tokens'],
            inherited_terminal_errors=before['terminal_error'],successful_ancestors_unchanged=True)
        rows.append(row);write_json(folder/'acceptance.json',row);write_json(args.out/'progress.json',rows)
        print(job['id'],row,flush=True)
    write_json(args.out/'summary.json',dict(rows=rows,passed=sum(r['passed'] for r in rows),total=len(rows),
        new_requests=sum(r['new_requests'] for r in rows),new_tokens=sum(r['new_tokens'] for r in rows),
        seconds=round(time.perf_counter()-start,3),**accounting(args.out)))


if __name__=='__main__':main()
