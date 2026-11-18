"""One explicitly requested structural recovery in copies, with new usage only."""
import argparse
import json
import shutil
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(Path(__file__).parent)]
from run_context_v3 import BASE,ENV,INFERENCE,snapshot,read,write_json
from meeting_eval.context_v3 import ContextV3Pipeline,reduce_v3
from meeting_eval.model_client import ModelClient


def main():
    p=argparse.ArgumentParser();p.add_argument('--batches',nargs='+',required=True);p.add_argument('--name',required=True);args=p.parse_args()
    if Path(args.name).name!=args.name or any(Path(b).name!=b for b in args.batches):raise ValueError('Single directory names required')
    out=BASE/args.name;out.mkdir(exist_ok=False);snapshot(out);rows=[]
    for batch in args.batches:
        for source in sorted((BASE/batch).glob('*/summary.json')):
            previous=read(source)
            if not previous['errors']:continue
            folder=out/batch/source.parent.name;shutil.copytree(source.parent,folder)
            prior={p.relative_to(folder).as_posix() for p in folder.rglob('meta.json')}
            data=read(folder/'input.json');client=ModelClient(ENV,folder/'model');pipe=ContextV3Pipeline(client,folder,INFERENCE)
            if pipe.config!=read(folder/'pipeline.json')['trace']['config']:raise ValueError('Recovery configuration changed')
            result=pipe.run(data['meeting'],data['history'],resume=True);write_json(folder/'pipeline.json',result)
            reduced=reduce_v3(result,data['meeting'],data['history']) if not result['errors'] else None
            write_json(folder/'reduced.json',reduced)
            repair=result['trace'].get('repair',{})
            summary=dict(case=previous['case'],errors=result['errors'],items=reduced['items'] if reduced else None,
                reviews=reduced['review_records'] if reduced else None,updates=reduced['updates'] if reduced else None,
                findings=result['coverage_findings'],repair=repair.get('status'),repair_error=repair.get('detail'),first_pass=previous)
            write_json(folder/'summary.json',summary)
            added=[read(p) for p in folder.rglob('meta.json') if p.relative_to(folder).as_posix() not in prior]
            row=dict(batch=batch,case=previous['case'],errors=result['errors'],calls=len(added),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in added))
            rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    write_json(out/'summary.json',dict(results=rows,calls=sum(r['calls'] for r in rows),tokens=sum(r['tokens'] for r in rows),new_usage_only=True))


if __name__=='__main__':main()
