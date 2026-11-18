"""Run the existing full replay with an isolated interpretation prompt variant."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.extract import Extractor
from meeting_eval.inputs import digest
from scripts import replay_mvp
from scripts.run_action_baseline import write_json

class ExperimentExtractor(Extractor):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        prompt=(ROOT/'experiments/history-time/current-time.txt').read_text(encoding='utf-8')
        manifest=json.loads((ROOT/'experiments/history-time/manifest.json').read_text(encoding='utf-8'))
        assert digest(prompt)==manifest['prompts']['current-time']
        self.task_pipeline.prompts['interpret_work']=prompt
        self.task_pipeline.config['prompts']['interpret_work']=digest(prompt)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():raise ValueError('Use a new output directory; keep first-pass outputs')
    replay_mvp.Extractor=ExperimentExtractor
    report=replay_mvp.replay(args.out,ROOT.parent.parent/'meeting-agent/.env','context-v1',
        inference_config=json.loads((ROOT/'experiments/action-context/compact-check.json').read_text(encoding='utf-8')))
    metas=[json.loads(p.read_text(encoding='utf-8')) for p in (args.out/'model').rglob('meta.json')]
    write_json(args.out/'cost.json',dict(calls=len(metas),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),
        request_seconds=sum(m['duration_seconds'] for m in metas),mode='fresh_full_replay_no_imported_cache'))
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['passed']:raise SystemExit(1)

if __name__=='__main__':main()
