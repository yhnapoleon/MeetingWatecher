"""Portable context-v5 v19 Service entry point; --live is required for inference."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from meeting_eval.extract import Extractor
from meeting_eval.service import Service
from meeting_eval.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT / 'examples/m1.json')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--env', type=Path, default=ROOT / '.env')
    parser.add_argument('--config', type=Path, default=ROOT / 'config/context-v5-v19.json')
    parser.add_argument('--actor', default='host')
    parser.add_argument('--at', help='Import timestamp, ISO 8601 with timezone')
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    meeting = json.loads(args.input.read_text(encoding='utf8'))
    settings = json.loads(args.config.read_text(encoding='utf8'))
    if args.out.exists():
        parser.error('--out must name a new directory; preserve previous results')
    stamp = args.at or datetime.now().astimezone().isoformat()
    if datetime.fromisoformat(stamp).tzinfo is None:
        parser.error('--at must include a timezone')
    print(json.dumps({'mode': 'live' if args.live else 'preflight-only',
                      'input': str(args.input), 'segments': len(meeting['segments']),
                      'strategy': 'context-v5', 'review_decisions': True,
                      'out': str(args.out)}, ensure_ascii=False))
    if not args.live:
        return
    args.out.mkdir(parents=True)
    def save(name, value):
        (args.out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    save('input.json', meeting)
    save('inference.json', settings)
    extractor = Extractor(args.env if args.env.exists() else None, args.out / 'model', 'context-v5',
                          inference_config=settings, review_decisions=True)
    save('config.json', extractor.config)
    store = Store(args.out / 'state.sqlite')
    try:
        service = Service(store, extractor)
        result = service.process(meeting, args.actor, stamp)
        save('result.json', result)
        sid = result['source_id']
        (args.out / 'minutes.md').write_text(service.minutes(sid, args.actor), encoding='utf8')
        save('requirements.json', service.requirements(sid, args.actor))
        print(json.dumps({'status': result['status'], 'source_id': sid}, ensure_ascii=False))
    finally:
        store.close()


if __name__ == '__main__':
    main()
