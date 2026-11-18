"""Recorded locate/interpret/check calls with successful upstream stages frozen."""
import copy
import json
from pathlib import Path

from .inputs import digest
from .model_client import inference_parameters
from .task_events import align_spans, canonical_events, canonical_checks
from scripts.run_action_baseline import write_json

ROOT = Path(__file__).resolve().parents[1]
STAGES = ('locate_work','interpret_work','check_work')
DEFAULT_INFERENCE = {
    'locate_work':{'thinking':'disabled','temperature':0,'max_tokens':8192},
    'interpret_work':{'thinking':'enabled','reasoning_effort':'high','temperature':1,'max_tokens':8192},
    'check_work':{'thinking':'disabled','temperature':0,'max_tokens':8192},
}


class TaskPipeline:
    def __init__(self,client,out,inference_config):
        self.client,self.out = client,Path(out)
        self.inference = {}
        for stage in STAGES:
            defaults = dict(DEFAULT_INFERENCE[stage])
            overrides = inference_config.get(stage,{})
            if 'thinking' in overrides and overrides['thinking']!=defaults['thinking']:
                defaults.pop('reasoning_effort',None)
                defaults['temperature'] = 1 if overrides['thinking']=='enabled' else 0
            self.inference[stage] = {**defaults,**overrides}
        self.prompts = {s:(ROOT/'prompts'/(s.replace('_','-')+'-v1.txt')).read_text(encoding='utf-8') for s in STAGES}
        for settings in self.inference.values():
            inference_parameters(client.model,8192,settings)
        self.config = dict(version=2,model=client.model,endpoint=client.endpoint,inference=self.inference,
            prompts={s:digest(p) for s,p in self.prompts.items()},
            code={name:digest((ROOT/'meeting_eval'/name).read_text(encoding='utf-8')) for name in ('task_pipeline.py','task_events.py')})

    def _stage(self,stage,payload,validate,folder,resume):
        path = folder/stage/digest([payload,self.config])
        path.mkdir(parents=True,exist_ok=True)
        accepted = path/'validated.json'
        if accepted.exists():
            return json.loads(accepted.read_text(encoding='utf-8'))
        status = path/'state.json'
        fresh = resume and status.exists()
        try:
            raw = self.client.call(self.prompts[stage],payload,stage,inference=self.inference[stage],fresh=fresh)
            if raw.get('case_id') != payload['meeting']['case_id']:
                raise ValueError('Wrong case_id')
            result = validate(raw)
            write_json(accepted,result)
            write_json(status,{'status':'complete'})
            return result
        except Exception:
            write_json(status,{'status':'failed'})
            raise

    def run(self,meeting,history,*,resume=False):
        from .extract import model_input
        projected = model_input(meeting)
        folder = self.out/'task_pipeline'/digest([projected,history,self.config])
        result = dict(events=[],checked_events=[],uncovered_spans=[],errors=[],trace={})
        stage = STAGES[0]
        try:
            def locate(raw):
                if not isinstance(raw.get('candidates'),list):
                    raise ValueError('Missing candidates list')
                values = []
                for i,item in enumerate(raw['candidates'],1):
                    spans = align_spans(item['spans'],meeting)
                    if not spans:
                        raise ValueError('Candidate lacks evidence')
                    values.append(dict(candidate_id=f'C{i}',spans=spans))
                return values
            candidates = self._stage(stage,{'meeting':projected},locate,folder,resume)
            result['trace']['candidates'] = candidates
            stage = STAGES[1]
            def interpret(raw):
                events,expanded = canonical_events(raw.get('events'),candidates,meeting,history)
                discarded = raw['discarded_candidates']
                if not isinstance(discarded,list):
                    raise ValueError('Missing candidate disposition')
                used = {ref for event in events for ref in event['candidate_ids']}
                rejected = set()
                for item in discarded:
                    cid = item['candidate_id']
                    if cid in rejected or cid in used or not isinstance(item.get('reason'),str) or not item['reason'].strip():
                        raise ValueError('Invalid discarded candidate explanation')
                    rejected.add(cid)
                if used | rejected != {c['candidate_id'] for c in expanded}:
                    raise ValueError('Candidate coverage incomplete')
                return dict(events=events,candidates=expanded,discarded_candidates=discarded)
            interpreted = self._stage(stage,{'meeting':projected,'candidates':candidates,'history':history},interpret,folder,resume)
            result['events'] = interpreted['events']
            result['trace'].update(interpreted)
            stage = STAGES[2]
            def check(raw):
                return canonical_checks(raw,interpreted['events'],meeting)
            verified = self._stage(stage,{'meeting':projected,'candidates':candidates,**interpreted,'history':history},check,folder,resume)
            result.update(verified)
            result['trace'].update(verified)
        except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError) as exc:
            result['errors'] = [dict(stage=stage,error=type(exc).__name__,detail=str(exc)[:500])]
        result['trace']['errors'] = result['errors']
        result['trace']['config'] = self.config
        write_json(folder/'result.json',result)
        return result
