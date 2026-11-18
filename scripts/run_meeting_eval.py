"""Evaluate the full meeting extractor through the normal import/service path."""
import argparse
import csv
import json
from pathlib import Path
import sys
import statistics
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))
from meeting_eval.extract import Extractor, DEFAULT_STRATEGY, STRATEGIES, validate_partial
from meeting_eval.inputs import digest
from meeting_eval.service import Service
from meeting_eval.store import Store
from scripts.run_action_baseline import read_jsonl,write_json
from scripts.score_mvp_actions import score
from scripts.replay_mvp import audit
from scripts.review_action_semantics import export_review


def save_review(path, draft):
    if path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if saved['hashes'] == draft['hashes']:
            return
        write_json(path.with_name('semantic-review.previous-'+digest(saved)+'.json'),saved)
    write_json(path,draft)


class BaselineExtractor(Extractor):
    """Evaluation control: same v1 prompt and raw corpus input, within normal service."""
    def __init__(self,env_file,out):
        super().__init__(env_file,out,'actions')
        self.config['strategy'] = 'baseline_raw'
        self.raw = None

    def retry(self,meeting,context,previous):
        return self.extract(meeting,context,previous)

    def extract(self,meeting,context,previous=None):
        raw = self.stage('actions',self.raw,fresh=bool(previous))
        value = {k:[] for k in ('items','facts','unresolved','decisions','updates')}
        value.update(items=raw.get('items'))
        return validate_partial(value,meeting,context,raw.get('_errors'))


def evaluate(out,env_file,strategy=DEFAULT_STRATEGY,split='dev',only=None,*,inference_config=None,data_dir=None,review_decisions=False):
    out.mkdir(parents=True,exist_ok=True)
    data = Path(data_dir) if data_dir is not None else ROOT/'data/mvp-v1'
    if data_dir is None:
        with (data/'splits.csv').open(encoding='utf-8-sig',newline='') as f:
            ids = {r['case_id'] for r in csv.DictReader(f) if r['split']==split}
    else:
        manifest = json.loads((data/'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('status')!='frozen' or manifest.get('input_hash')!=digest(read_jsonl(data/'input.jsonl')) or manifest.get('labels_hash')!=digest(read_jsonl(data/'labels.jsonl')):
            raise ValueError('Semantic dataset is not frozen or hashes changed')
        ids = {c['case_id'] for c in read_jsonl(data/'input.jsonl')}
    if only:
        if not set(only) <= ids:
            raise ValueError('Requested cases outside selected split')
        ids &= set(only)
    cases = [c for c in read_jsonl(data/'input.jsonl') if c['case_id'] in ids]
    if strategy=='baseline' and inference_config:
        raise ValueError('Use actions strategy for configured inference comparisons')
    kwargs = {'inference_config':inference_config} if inference_config is not None else {}
    if review_decisions:
        if strategy!='context-v5':
            raise ValueError('--review-decisions requires --strategy context-v5')
        kwargs['review_decisions'] = True
    model = BaselineExtractor(env_file,out/'model') if strategy=='baseline' else Extractor(env_file,out/'model',strategy,**kwargs)
    code_paths = ['meeting_eval/inputs.py','meeting_eval/extract.py','meeting_eval/model_client.py','meeting_eval/service.py',
                  'scripts/run_meeting_eval.py','scripts/score_mvp_actions.py']
    if strategy in ('evidence-v1','context-v1'):
        code_paths.extend(['meeting_eval/task_pipeline.py','meeting_eval/task_events.py'])
    if strategy=='context-v1':
        code_paths.extend(['meeting_eval/context_pipeline.py','meeting_eval/context_state.py','meeting_eval/requirement_review.py'])
    if data_dir is not None:
        code_paths.extend(['scripts/review_action_semantics.py','scripts/score_action_semantics.py'])
    labels = (data/'labels.jsonl').read_text(encoding='utf-8')
    if data_dir is not None:
        labels = ''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in read_jsonl(data/'labels.jsonl') if r['case_id'] in ids)
    config = dict(input_hash=digest(cases),labels_hash=digest(labels),split=split,cases=sorted(ids),extractor=model.config,
                  code_hashes={f:digest((ROOT/f).read_text(encoding='utf-8')) for f in code_paths})
    if data_dir is not None:
        config['dataset_manifest_hash'] = digest(manifest)
    config_path = out/'config.json'
    if config_path.exists() and json.loads(config_path.read_text(encoding='utf-8')) != config:
        raise ValueError('Changed input/prompt/model/code: choose a new output directory')
    write_json(config_path,config)
    snapshot = out/'labels.snapshot.jsonl'
    if snapshot.exists() and snapshot.read_text(encoding='utf-8') != labels:
        raise ValueError('Reference snapshot changed: choose a new output directory')
    if not snapshot.exists():
        snapshot.write_text(labels,encoding='utf-8')
    (out/'input.jsonl').write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in cases),encoding='utf-8')
    store = Store(out/'state.sqlite')
    svc = Service(store,model)
    predictions,errors,timings = [],[],[]
    timing_path = out/'timings.json'
    previous_timings = {t['case_id']:t for t in json.loads(timing_path.read_text(encoding='utf-8'))} if timing_path.exists() else {}
    try:
        for i,c in enumerate(cases,1):
            started = time.perf_counter()
            try:
                if strategy=='baseline':
                    model.raw = c
                # Isolate excerpts without changing the semantic project name in the model input.
                raw = {**c,'tenant':'eval-'+c['case_id']}
                result = svc.process(raw,'evaluator','2026-11-14T00:00:00+08:00')
                status = result['status']
                prediction = {'case_id':c['case_id'],'items':result['extraction']['items'],'status':status,
                              'pending':result['pending'],'errors':result['extraction'].get('_errors',[])}
                if result['extraction'].get('_errors'):
                    errors.append({'case_id':c['case_id'],'errors':result['extraction']['_errors']})
                write_json(out/(c['case_id']+'.json'),result)
                (out/(c['case_id']+'.md')).write_text(svc.minutes(result['source_id'],'evaluator'),encoding='utf-8')
            except Exception as exc:
                status = 'failed'
                error = dict(case_id=c['case_id'],error_type=type(exc).__name__,message=str(exc))
                errors.append(error)
                # Empty is only the scorer adapter. Explicit status/error prevents interpreting it as no tasks.
                prediction = {'case_id':c['case_id'],'items':[],'status':'failed','error':error}
            elapsed = round(time.perf_counter()-started,3)
            old = previous_timings.get(c['case_id'])
            if old:
                timing = {**old,'status':status,'last_resume_seconds':elapsed}
                if old['status'] in ('partial','failed'):
                    timing['seconds'] += elapsed
            else:
                timing = {'case_id':c['case_id'],'seconds':elapsed,'status':status}
            timings.append(timing)
            write_json(timing_path,timings+ [v for k,v in previous_timings.items() if k not in {x['case_id'] for x in timings}])
            predictions.append(prediction)
            print(f'{out.name} {i}/{len(cases)} {c["case_id"]}: {status}',flush=True)
        (out/'predictions.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in predictions),encoding='utf-8')
        write_json(out/'errors.json',errors)
        write_json(out/'timings.json',timings)
        if data_dir is None:
            report = score(predictions,split,labels=read_jsonl(snapshot),inputs=cases,selected_ids=ids)
        else:
            selected_labels = [r for r in read_jsonl(snapshot) if r['case_id'] in ids]
            review_path = out/'semantic-review.json'
            draft = export_review(cases,selected_labels,predictions)
            save_review(review_path,draft)
            report = dict(view=data.name,excerpts=len(cases),semantic_review_status='requires_review')
        if only:
            report['subset'] = sorted(ids)
        report.update(failed_cases=errors,annotation_status='agent_labeled')
        write_json(out/'scores.json',report)
        # Frozen references are consumed only by scoring; never passed to the model.
        audit(store,out/'operations.jsonl')
        meta = [json.loads(f.read_text(encoding='utf-8')) for f in (out/'model').rglob('meta.json')]
        summary = dict(excerpts=len(cases),successful=len(cases)-len(errors),calls=len(meta),
                       request_seconds=round(sum(m['duration_seconds'] for m in meta),3),
                       wall_seconds=round(sum(t['seconds'] for t in timings),3),
                       median_case_seconds=statistics.median(t['seconds'] for t in timings),
                       total_tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in meta),
                       action_anchors=report.get('action_anchors'))
        write_json(out/'summary.json',summary)
        return summary
    finally:
        store.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--env-file',type=Path,default=ROOT.parent.parent/'meeting-agent/.env')
    p.add_argument('--strategy',choices=('baseline',)+STRATEGIES,default=DEFAULT_STRATEGY)
    p.add_argument('--review-decisions',action='store_true',help='Review decision evidence, later changes and missing topics (context-v5)')
    p.add_argument('--split',choices=('dev','holdout'),default='dev')
    p.add_argument('--cases',nargs='+')
    p.add_argument('--inference-config',type=Path)
    p.add_argument('--data-dir',type=Path,help='Frozen semantic evaluation view directory')
    args = p.parse_args()
    inference = json.loads(args.inference_config.read_text(encoding='utf-8')) if args.inference_config else None
    summary = evaluate(args.out,args.env_file,args.strategy,args.split,args.cases,inference_config=inference,data_dir=args.data_dir,
                       review_decisions=args.review_decisions)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if summary['successful'] != summary['excerpts']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

