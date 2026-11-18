"""Print source and user-visible outcomes for manual audit; never score them."""
import argparse
import json
from pathlib import Path


def read(p):
    return json.loads(p.read_text(encoding='utf8'))


def output(result):
    extraction=result.get('extraction',{})
    trace=extraction.get('_task_trace',{})
    return dict(status=result.get('status'),errors=extraction.get('_errors',result.get('errors',[])),
        items=[{k:v for k,v in i.items() if k not in ('evidence_ids','action_anchor')} for i in extraction.get('items',[])],
        reviews=[{k:r.get(k) for k in ('category','description','missing_fields','question')} for r in trace.get('review_records',[])],
        reports=trace.get('reports',[]),deferred=trace.get('deferred_topics',[]),
        updates=extraction.get('updates',[]),unresolved=extraction.get('unresolved',[]),
        context=[r['description'] for r in trace.get('context_records',[])],
        pending=[{k:v for k,v in p.items() if k!='item'} for p in result.get('pending',[])])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--round',type=int,default=1)
    parser.add_argument('--ids',nargs='*')
    parser.add_argument('--group')
    parser.add_argument('--no-source',action='store_true')
    args=parser.parse_args()
    manifest=read(args.out/'manifest.json')
    rows=read(args.out/f'r{args.round}/progress.json')
    jobs={(j['group'],j['id']):j for j in manifest['jobs']}
    for row in sorted(rows,key=lambda r:(r['group'],r['case_id'])):
        if args.ids and row['case_id'] not in args.ids:continue
        if args.group and row['group']!=args.group:continue
        folder=args.out/f'r{args.round}'/row['group']/row['case_id']
        print('\n'+f"r{args.round}/{row['group']}/{row['case_id']} AUTO {row['passed']} {row['failed']}")
        job=jobs.get((row['group'],row['case_id']))
        if job and not args.no_source:
            meeting=job['meeting']
            print('ROSTER',json.dumps(meeting.get('participants',[]),ensure_ascii=False))
            print('SOURCE',json.dumps([(s.get('speaker'),s.get('speaker_ref'),s['text']) for s in meeting['segments']],ensure_ascii=False))
            if job.get('tasks'):print('OLD',json.dumps(job['tasks'],ensure_ascii=False))
        for name in ('result.json','m1-result.json','m2-result.json','failure.json','error.json'):
            if (folder/name).exists():
                result=read(folder/name)
                print(name,json.dumps(output(result) if 'extraction' in result else result,ensure_ascii=False))
        if (folder/'tasks.json').exists():
            print('TASKS',json.dumps([{k:t.get(k) for k in ('guid','title','summary','owner_ref','due_date','status')} for t in read(folder/'tasks.json')],ensure_ascii=False))


if __name__=='__main__':main()
