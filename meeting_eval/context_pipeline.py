"""Incremental evidence ledger followed by full-context interpretation and checking."""
import copy
from pathlib import Path

from .inputs import digest
from .model_client import inference_parameters
from .task_pipeline import TaskPipeline, ROOT
from .task_events import canonical_events, canonical_checks
from .context_state import canonical_ledger, ledger_candidates, canonical_records, check_records
from .context_updates import validate_time_changes
from scripts.run_action_baseline import write_json


class ContextPipeline(TaskPipeline):
    checkpoint_size = 8
    repair_enabled = True

    def __init__(self,client,out,inference_config):
        self.client,self.out = client,Path(out)
        defaults = dict(thinking='enabled',reasoning_effort='high',temperature=1,max_tokens=16384)
        self.inference = {}
        stages = {'track_context':'track_context','interpret_work':'interpret_work','check_work':'check_work',
                  'repair_work':'interpret_work','check_repair':'check_work'}
        for stage,base in stages.items():
            overrides = inference_config.get(stage,inference_config.get(base,{}))
            settings = {**defaults,**overrides}
            if settings['thinking']=='disabled':
                settings.pop('reasoning_effort',None)
                settings['temperature']=overrides.get('temperature',0)
            inference_parameters(client.model,16384,settings)
            self.inference[stage]=settings
        self.prompts = {s:(ROOT/'prompts'/(base.replace('_','-')+'-context-v1.txt')).read_text(encoding='utf-8') for s,base in stages.items()}
        self.prompts['repair_work'] += '\n'+(ROOT/'prompts/repair-work-context-v1.txt').read_text(encoding='utf-8')
        self.prompts['check_repair'] += '\n这是一次修正后的独立核验。只核验输入 records/events；context_records 是其他已处理记录，仅供避免重复。uncovered_spans 固定为 []。根据原文判断，不以修改过就算正确。'
        self.config = dict(version=7,repair_enabled=self.repair_enabled,model=client.model,endpoint=client.endpoint,inference=self.inference,
            checkpoint_size=self.checkpoint_size,prompts={s:digest(p) for s,p in self.prompts.items()},
            code={n:digest((ROOT/'meeting_eval'/n).read_text(encoding='utf-8')) for n in
                  ('task_pipeline.py','task_events.py','context_pipeline.py','context_state.py','context_updates.py','context_new_work.py')})

    def run(self,meeting,history,*,resume=False):
        from .extract import model_input
        projected=model_input(meeting)
        folder=self.out/'context_pipeline'/digest([projected,history,self.config])
        result=dict(events=[],checked_events=[],checked_records=[],uncovered_spans=[],errors=[],trace={'checkpoints':[]})
        stage='track_context'
        try:
            ledger=None
            ends=list(range(self.checkpoint_size,len(meeting['segments']),self.checkpoint_size))+[len(meeting['segments'])]
            start=0
            for end in ends:
                prefix={**meeting,'segments':meeting['segments'][:end]}
                payload=dict(meeting=model_input(prefix),previous=ledger,new_segment_ids=[s['id'] for s in meeting['segments'][start:end]])
                ledger=self._stage(stage,payload,lambda raw:canonical_ledger(raw,prefix,ledger),folder,resume)
                result['trace']['checkpoints'].append(dict(through_segment=prefix['segments'][-1]['id'] if end else None,ledger=copy.deepcopy(ledger)))
                start=end
            candidates=ledger_candidates(ledger)
            result['trace'].update(ledger=ledger,candidates=candidates)
            stage='interpret_work'
            def interpret(raw,local_ledger=ledger,local_candidates=candidates):
                events,expanded=canonical_events(raw['events'],local_candidates,meeting,history)
                validate_time_changes(events)
                for event,original in zip(events,raw['events']):
                    if event['commitment']['kind']=='conditional' and not event['commitment']['evidence']:
                        raise ValueError('Conditional work requires condition evidence')
                    event['record_id']=original['record_id']
                    other=original['other_changes']
                    if not isinstance(other,list) or any(v not in ('content','owner','other') for v in other):
                        raise ValueError('Invalid other task changes')
                    event['other_changes']=other
                records=canonical_records(raw['records'],local_ledger,events,meeting)
                return dict(events=events,records=records,candidates=expanded)
            interpreted=self._stage(stage,dict(meeting=projected,ledger=ledger,candidates=candidates,history=history),interpret,folder,resume)
            result['events']=interpreted['events']
            result['trace'].update(interpreted)
            stage='check_work'
            evidence_catalog={f'Q{i}':dict(segment_id=s['id'],quote=s['text']) for i,s in enumerate(meeting['segments'],1) if s['text']}
            def check(raw,local_interpreted=None):
                local_interpreted = interpreted if local_interpreted is None else local_interpreted
                expanded=copy.deepcopy(raw)
                def expand(refs):
                    if not isinstance(refs,list) or any(not isinstance(ref,str) or ref not in evidence_catalog for ref in refs):
                        raise ValueError('Unknown check evidence reference')
                    return [evidence_catalog[ref] for ref in refs]
                for row in expanded['checks']:
                    for field in row['fields'].values():field['evidence']=expand(field['evidence'])
                for row in expanded['record_checks']:row['evidence']=expand(row['evidence'])
                expanded['uncovered_spans']=expand(expanded['uncovered_spans'])
                verified=canonical_checks(expanded,local_interpreted['events'],meeting)
                verified['checked_records']=check_records(expanded['record_checks'],local_interpreted['records'],meeting)
                return verified
            verified=self._stage(stage,dict(meeting=projected,ledger=ledger,**interpreted,history=history,evidence_catalog=evidence_catalog),check,folder,resume)
            result.update(verified)
            result['trace'].update(verified)
            targets={r['record_id'] for r in verified['checked_records'] if r['check']['verdict']!='supported'}
            targets.update(e['record_id'] for e in verified['checked_events'] if any(c['verdict']!='supported' for c in e['checks'].values()))
            if self.repair_enabled and targets:
                repair=dict(target_record_ids=sorted(targets),status='started',before=copy.deepcopy({**interpreted,**verified}))
                result['trace']['repair']=repair
                repair_stage='repair_work'
                try:
                    originals=[r for r in interpreted['records'] if r['record_id'] in targets]
                    tids={t for r in originals for t in r['thread_ids']}
                    subset_ledger={**ledger,'threads':[t for t in ledger['threads'] if t['thread_id'] in tids]}
                    original_threads={r['record_id']:r['thread_ids'] for r in originals}
                    original_event_ids={e['record_id']:e['event_id'] for e in interpreted['events']}
                    def validate_repair(raw):
                        if {r['record_id'] for r in raw['records']}!=targets or len(raw['records'])!=len(targets):
                            raise ValueError('Repair changed target record identities')
                        if any(r['thread_ids']!=original_threads[r['record_id']] for r in raw['records']):
                            raise ValueError('Repair changed requirement thread identities')
                        fixed=interpret(raw,subset_ledger,interpreted['candidates'])
                        next_id=max([int(e['event_id'][1:]) for e in interpreted['events']]+[0])+1
                        for event in fixed['events']:
                            rid=event['record_id']
                            if rid in original_event_ids:event['event_id']=original_event_ids[rid]
                            else:event['event_id']=f'E{next_id}';next_id+=1
                        return fixed
                    fixed=self._stage(repair_stage,dict(meeting=projected,ledger=subset_ledger,candidates=interpreted['candidates'],
                        history=history,target_record_ids=sorted(targets),original_records=originals,
                        original_events=[e for e in interpreted['events'] if e['record_id'] in targets],
                        record_checks=[r for r in verified['checked_records'] if r['record_id'] in targets],
                        event_checks=[e for e in verified['checked_events'] if e['record_id'] in targets],
                        context_records=[r for r in interpreted['records'] if r['record_id'] not in targets]),validate_repair,folder,resume)
                    repair['proposal']=copy.deepcopy(fixed)
                    repair_stage='check_repair'
                    def validate_recheck(raw):
                        checked=check(raw,fixed)
                        if checked['uncovered_spans']:raise ValueError('Repair check must only address target records')
                        return checked
                    rechecked=self._stage(repair_stage,dict(meeting=projected,ledger=subset_ledger,**fixed,history=history,
                        evidence_catalog=evidence_catalog,context_records=[r for r in interpreted['records'] if r['record_id'] not in targets]),
                        validate_recheck,folder,resume)
                    records_by_id={r['record_id']:r for r in fixed['records']}
                    checked_by_id={r['record_id']:r for r in rechecked['checked_records']}
                    interpreted['records']=[records_by_id.get(r['record_id'],r) for r in interpreted['records']]
                    interpreted['events']=[e for e in interpreted['events'] if e['record_id'] not in targets]+fixed['events']
                    interpreted['candidates']=fixed['candidates']
                    verified['checked_records']=[checked_by_id.get(r['record_id'],r) for r in verified['checked_records']]
                    verified['checked_events']=[e for e in verified['checked_events'] if e['record_id'] not in targets]+rechecked['checked_events']
                    result.update(events=interpreted['events'],**verified)
                    result['trace'].update(interpreted)
                    result['trace'].update(verified)
                    repair.update(status='checked',after=copy.deepcopy(rechecked))
                except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError) as exc:
                    repair.update(status='failed',stage=repair_stage,error=type(exc).__name__,detail=str(exc)[:500])
        except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError) as exc:
            result['errors']=[dict(stage=stage,error=type(exc).__name__,detail=str(exc)[:500])]
        result['trace']['errors']=result['errors']
        result['trace']['config']=self.config
        write_json(folder/'result.json',result)
        return result
