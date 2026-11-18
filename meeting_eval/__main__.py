import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .extract import Extractor, DEFAULT_STRATEGY, STRATEGIES
from .store import Store
from .service import Service


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='离线会议纪要、任务与决策查询')
    parser.add_argument('--db',type=Path,default=Path('runs/local/state.sqlite'))
    sub = parser.add_subparsers(dest='command',required=True)
    ingest = sub.add_parser('ingest')
    ingest.add_argument('input',type=Path)
    ingest.add_argument('--actor',required=True)
    ingest.add_argument('--observed-at',default=None)
    ingest.add_argument('--env-file',type=Path,default=Path('../../meeting-agent/.env'))
    ingest.add_argument('--out',type=Path,default=Path('runs/local'))
    ingest.add_argument('--strategy',choices=STRATEGIES,default=DEFAULT_STRATEGY)
    ingest.add_argument('--inference-config',type=Path)
    for name in ('recap','decisions'):
        p = sub.add_parser(name)
        p.add_argument('--series',required=True)
        p.add_argument('--viewer',required=True)
        p.add_argument('--as-of',required=True)
        p.add_argument('--tenant',default='local')
        if name == 'decisions':
            p.add_argument('--history',action='store_true')
            p.add_argument('--attribute')
    p = sub.add_parser('minutes')
    p.add_argument('source_id')
    p.add_argument('--viewer',required=True)
    p = sub.add_parser('recover')
    p.add_argument('--actor',required=True)
    p = sub.add_parser('requirements',help='查看隐式需求和模糊工作及确认问题')
    p.add_argument('source_id')
    p.add_argument('--viewer',required=True)
    p = sub.add_parser('resolve-requirement',help='人工确认加入任务、忽略或标记待向提出方询问')
    p.add_argument('source_id')
    p.add_argument('record_id')
    p.add_argument('--actor',required=True)
    p.add_argument('--input',type=Path,required=True,help='JSON 决定；待采纳卡用 adopt_and_add_task，待澄清意向用 clarify_and_add_task；建任务均需最终 description 和 owner_ref')
    p.add_argument('--observed-at',default=None)
    args = parser.parse_args()
    store = Store(args.db)
    svc = Service(store)
    try:
        if args.command == 'ingest':
            inference = json.loads(args.inference_config.read_text(encoding='utf-8')) if args.inference_config else None
            svc = Service(store,Extractor(args.env_file,args.out/'model',args.strategy,inference_config=inference))
            raw = json.loads(args.input.read_text(encoding='utf-8-sig'))
            result = svc.process(raw,args.actor,args.observed_at or datetime.now(timezone.utc).isoformat())
            args.out.mkdir(parents=True,exist_ok=True)
            (args.out/(result['source_id']+'.md')).write_text(svc.minutes(result['source_id'],args.actor),encoding='utf-8')
        elif args.command == 'recap':
            result = svc.recap(args.series,args.viewer,args.as_of,args.tenant)
        elif args.command == 'decisions':
            result = svc.decisions(args.series,args.viewer,args.as_of,args.history,args.tenant,args.attribute)
        elif args.command == 'minutes':
            print(svc.minutes(args.source_id,args.viewer))
            return
        elif args.command == 'requirements':
            result = svc.requirements(args.source_id,args.viewer)
        elif args.command == 'resolve-requirement':
            decision = json.loads(args.input.read_text(encoding='utf-8-sig'))
            result = svc.resolve_requirement(args.source_id,args.record_id,args.actor,decision,args.observed_at or datetime.now(timezone.utc).isoformat())
        else:
            svc.recover(args.actor)
            result = {'intents':[dict(r) for r in store.db.execute('SELECT id,status,guid FROM intents')]}
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if args.command=='ingest' and result['status']=='partial':
            raise SystemExit(1)
    finally:
        store.close()


if __name__ == '__main__':
    main()
