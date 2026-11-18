from contextvars import copy_context
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from scripts.run_action_baseline import write_json
from .model_client import ModelClient, inference_parameters
from .inputs import digest, dumps, instant

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('items','facts','unresolved','decisions','updates')
DEFAULT_STRATEGY = 'split-v3'
STRATEGIES = ('actions','combined','split','legacy','actions-v2','split-v2','split-v3','evidence-v1','context-v1','context-v2','context-v3','context-v4','context-v5')
STAGE_FIELDS = {'actions':('items',),'facts':('facts','unresolved'),
                'decisions':('decisions',),'updates':('updates',),'combined':FIELDS,'legacy':FIELDS}
ALLOWED_FIELDS = {
    'items':('description','operation','owner_kind','owner_label','owner_ref','due_text','due_date','action_anchor','evidence_ids'),
    'facts':('statement','evidence_ids'), 'unresolved':('statement','evidence_ids'),
    'decisions':('attribute','statement','supersedes','reaffirms','evidence_ids'),
    'updates':('target_guid','description','owner_ref','status','effective_at','evidence_ids','changes','field_evidence_ids')}


def failed_fields(result):
    fields = set()
    for error in result.get('_errors',[]):
        if error.get('field') in FIELDS:
            fields.add(error['field'])
        else:
            fields.update(STAGE_FIELDS.get(error.get('stage'),FIELDS))
    return fields


def merge_retry(previous,current):
    retry = failed_fields(previous)
    errors = []
    for error in current.get('_errors',[]):
        affected = {error['field']} if error.get('field') in FIELDS else set(STAGE_FIELDS.get(error.get('stage'),FIELDS))
        errors.extend({**error,'field':field} for field in sorted(retry & affected))
    result = {**current,**{f:previous[f] for f in FIELDS if f not in retry},'_errors':errors}
    if '_task_trace' in previous and not retry & {'items','updates'}:
        result['_task_trace'] = previous['_task_trace']
    if '_minutes_review' in previous and not retry & {'facts','unresolved'}:
        result['_minutes_review'] = previous['_minutes_review']
    return result


def resolve_calendar_dates(result,meeting):
    """Resolve only a cited explicit Chinese calendar-week deadline with a known date."""
    day = meeting.get('meeting_date')
    if not isinstance(day,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day):
        return result
    reference = date.fromisoformat(day)
    evidence = {s['id']:s['text'] for s in meeting['segments']}
    resolutions = []
    for item in result['items']:
        phrase = item.get('due_text') or ''
        matches = list(re.finditer(r'(本|这|下)周([一二三四五六日天])',phrase))
        if len(matches)!=1 or not any(phrase in evidence[e] for e in item['evidence_ids']):
            continue
        match = matches[0]
        weekday = '一二三四五六日'.find(match[2].replace('天','日'))
        shift = 7 if match[1]=='下' else 0
        resolved = (reference+timedelta(days=shift+weekday-reference.weekday())).isoformat()
        if resolved!=item['due_date']:
            resolutions.append(dict(action_anchor=item['action_anchor'],field='due_date',
                **{'from':item['due_date'],'to':resolved},rule='explicit_calendar_week',reference_date=day))
            item['due_date'] = resolved
    if resolutions:
        result['_date_resolutions'] = resolutions
    return result


def decision_output(raw, meeting):
    """Validate the evidence roles before projecting onto the stored decision format."""
    if not isinstance(raw, dict) or not isinstance(raw.get('decisions'), list):
        raise ValueError('Expected a decisions array')
    source_ids = {segment['id'] for segment in meeting['segments']}
    decisions = []
    for row in raw['decisions']:
        if not isinstance(row, dict) or row.get('final_status') not in (
                'effective', 'open', 'withdrawn', 'superseded'):
            raise ValueError('Decision requires a final status')
        if row['final_status'] != 'effective':
            continue
        if row.get('basis') not in ('newly_adopted', 'communicated_rule'):
            raise ValueError('Decision requires a valid adoption basis')
        if not isinstance(row.get('statement'), str) or not row['statement'].strip():
            raise ValueError('Decision requires a final statement')
        if 'supersedes' not in row:
            raise ValueError('Missing decision supersedes')
        evidence = []
        for field in ('choice_ids', 'adoption_ids', 'later_ids'):
            refs = row.get(field)
            if not isinstance(refs, list) or (field != 'later_ids' and not refs):
                raise ValueError('Invalid decision evidence: ' + field)
            if any(not isinstance(ref, str) or ref not in source_ids for ref in refs):
                raise ValueError('Unknown decision evidence: ' + field)
            evidence.extend(refs)
        decisions.append(dict(attribute=row.get('attribute'), statement=row['statement'],
                              supersedes=row['supersedes'], evidence_ids=list(dict.fromkeys(evidence))))
    return decisions


def validate(result, meeting, context):
    ids = {s['id'] for s in meeting['segments']}
    people = set(meeting['roster'])
    for field in ('items','facts','unresolved','decisions','updates'):
        if not isinstance(result.get(field), list):
            raise ValueError('Missing list: '+field)
        for item in result[field]:
            ev = item.get('evidence_ids')
            if (not isinstance(ev,list) or not ev or not all(isinstance(e,str) for e in ev)
                    or len(ev) != len(set(ev)) or not set(ev) <= ids):
                raise ValueError('Invalid evidence: '+field)
            if field in ('facts','unresolved','decisions') and not isinstance(item.get('statement'),str):
                raise ValueError('Invalid statement')
    for item in result['items']:
        for f in ('description','operation','owner_kind','owner_label','owner_ref','due_text','due_date','action_anchor'):
            if f not in item or item[f] is not None and not isinstance(item[f],str):
                raise ValueError('Invalid action field: '+f)
        if not item['description'] or item['operation'] not in ('create','candidate'):
            raise ValueError('Invalid action')
        if item['action_anchor'] not in item['evidence_ids']:
            raise ValueError('Anchor not in evidence')
        if item['owner_ref'] is not None and item['owner_ref'] not in people:
            raise ValueError('Unknown person reference')
        if item['operation'] == 'create' and not item['owner_ref']:
            raise ValueError('Create requires a known person')
        if item['due_date']:
            date.fromisoformat(item['due_date'])
    for d in result['decisions']:
        if not isinstance(d.get('attribute'),str) or not d['attribute']:
            raise ValueError('Decision requires attribute')
        if d.get('supersedes') is not None and not isinstance(d['supersedes'],str):
            raise ValueError('Invalid decision replacement type')
        if d.get('supersedes') and d['supersedes'] not in {x['id'] for x in context['decisions']}:
            raise ValueError('Unknown replacement target')
        same = d.get('reaffirms')
        if same is not None and (d.get('supersedes') is not None or not isinstance(same,str)
                or not any(x['id']==same and x['attribute']==d['attribute'] for x in context['decisions'])):
            raise ValueError('Invalid decision reaffirmation')
    for u in result['updates']:
        for field in ('target_guid','description','owner_ref','effective_at'):
            if u.get(field) is not None and not isinstance(u[field],str):
                raise ValueError('Invalid update field: '+field)
        if u.get('effective_at'):
            instant(u['effective_at'])
        if u.get('owner_ref') is not None and u['owner_ref'] not in people:
            raise ValueError('Unknown update owner')
        if 'changes' in u:
            from .context_updates import validate_changes
            validate_changes(u,ids)
        elif u.get('status') not in ('open','done'):
            raise ValueError('Invalid proposed status')
        if u.get('target_guid') and u['target_guid'] not in {t['guid'] for t in context['tasks']}:
            raise ValueError('Update target not in authorized context')
    return result


def model_input(meeting):
    """Keep semantic identity; omit execution policy, account mapping and source hashes."""
    keys = ('case_id','meeting_id','series','language','source','meeting_date','started_at','timezone','roster')
    value = {k:meeting[k] for k in keys if k in meeting and meeting[k] is not None}
    value['case_id'] = meeting.get('case_id',meeting['source_key'])
    value['segments'] = [{k:s[k] for k in ('id','start_ms','end_ms','speaker','speaker_name','person_ref','text') if k in s}
                         for s in meeting['segments']]
    if 'participants' in meeting:
        value['participants'] = [{k:p[k] for k in ('speaker','speaker_name','person_ref') if k in p}
                                 for p in meeting['participants']]
    return value


def validate_partial(result,meeting,context,errors=None):
    clean = {f:[] for f in FIELDS}
    errors = list(errors or [])
    for field in FIELDS:
        rows = result.get(field)
        if not isinstance(rows,list):
            errors.append(dict(field=field,error='Missing or invalid list'))
            continue
        for index,item in enumerate(rows):
            singleton = {f:[] for f in FIELDS}
            singleton[field] = [item]
            try:
                validate(singleton,meeting,context)
                clean[field].append({k:item[k] for k in ALLOWED_FIELDS[field] if k in item})
            except (ValueError,KeyError,TypeError,AttributeError) as exc:
                errors.append(dict(field=field,index=index,error=str(exc),rejected=item))
    clean['_errors'] = errors
    return clean


def assemble(stages,meeting,context):
    owners = {k:STAGE_FIELDS[k] for k in ('actions','facts','decisions','updates')}
    result = {f:[] for f in FIELDS}
    errors = []
    for stage,fields in owners.items():
        if stage not in stages:
            continue
        value = stages[stage]
        errors.extend(value.get('_errors',[]))
        for field in fields:
            if field in value:
                result[field] = value[field]
            elif not value.get('_errors'):
                errors.append(dict(stage=stage,field=field,error='Missing stage field'))
    return validate_partial(result,meeting,context,errors)


class Extractor:
    def __init__(self,env_file,out,strategy=DEFAULT_STRATEGY,*,inference_config=None,review_decisions=False):
        if strategy not in STRATEGIES:
            raise ValueError('Unknown extraction strategy')
        self.client = ModelClient(env_file,out)
        self.out = Path(out)
        self.strategy = strategy
        self.decision_reviewer = None
        if review_decisions:
            if strategy!='context-v5':
                raise ValueError('Decision review requires context-v5')
            from .decision_review import DecisionReview
            self.decision_reviewer = DecisionReview(self.client,self.out/'independent',
                dict(thinking='disabled',max_tokens=10000))
        self.inference_config = inference_config or {}
        allowed_stages = set(STAGE_FIELDS) | {'locate_work','track_context','interpret_work','check_work','repair_work','check_repair',
            'check_minutes','repair_minutes','check_minutes_repair'}
        if not isinstance(self.inference_config,dict) or set(self.inference_config)-allowed_stages:
            raise ValueError('Unknown inference stage')
        for settings in self.inference_config.values():
            inference_parameters(self.client.model,6000,settings)
        names = {'actions':'extract-actions-v1.txt','combined':'extract-meeting-v2.txt',
                 'legacy':'extract-meeting-v1.txt','facts':'extract-facts-v1.txt',
                 'decisions':'extract-decisions-v1.txt','updates':'extract-updates-v1.txt'}
        used = ('facts','decisions') if strategy in ('evidence-v1','context-v1','context-v2','context-v3','context-v4','context-v5') else ('actions','facts','decisions','updates') if strategy.startswith('split') else ('actions',) if strategy=='actions-v2' else (strategy,)
        if strategy.endswith('-v2'):
            names.update(actions='extract-actions-v2.txt',facts='extract-facts-v2.txt')
        if strategy in ('split-v3','evidence-v1','context-v1','context-v2','context-v3','context-v4','context-v5'):
            names.update(facts='extract-facts-v2.txt',decisions='extract-decisions-v2.txt')
        if strategy in ('context-v1','context-v2','context-v3','context-v4','context-v5'):
            names['facts']='extract-facts-context-v1.txt'
        if strategy=='context-v5':
            names['decisions']='extract-decisions-v3.txt'
        self.prompts = {k:(ROOT/'prompts'/names[k]).read_text(encoding='utf-8') for k in used}
        if strategy=='context-v5':
            self.prompts['facts']+='\n明确暂缓的议题以事实保留议题及暂缓安排，不放入立即待答的 unresolved；不能依赖工作分支替你保留。未决仅指本场提出或采用、最终仍开放的问题，不因引用/举例没给答案就列为未决。调查者与调查内容分开，承接调查不等于调查的问题已解决。'
            from .minutes_review import MinutesReviewer
            self.minutes_reviewer=MinutesReviewer(self.client,self.out,self.inference_config)
        self.config = dict(strategy=strategy,model=self.client.model,endpoint=self.client.endpoint,
                           prompts={k:digest(v) for k,v in self.prompts.items()},input_version=3,validation_version=11 if strategy=='context-v5' else 10 if strategy=='context-v4' else 9 if strategy=='context-v3' else 8 if strategy=='context-v2' else 7 if strategy=='context-v1' else 6)
        if self.inference_config:
            self.config['inference'] = self.inference_config
        if self.decision_reviewer:
            self.config['decision_review'] = dict(version=2,
                prompts={k:digest(v) for k,v in self.decision_reviewer.prompts.items()},
                implementation=digest((ROOT/'meeting_eval/decision_review.py').read_text(encoding='utf8')))
        if strategy=='context-v5':self.config['minutes_review']=self.minutes_reviewer.config
        if strategy in ('evidence-v1','context-v1','context-v2','context-v3','context-v4','context-v5'):
            from .task_pipeline import TaskPipeline
            from .context_pipeline import ContextPipeline
            from .context_v2 import ContextV2Pipeline
            from .context_v3 import ContextV3Pipeline
            from .context_v4 import ContextV4Pipeline
            from .context_v5 import ContextV5Pipeline
            pipeline_class = ContextV5Pipeline if strategy=='context-v5' else ContextV4Pipeline if strategy=='context-v4' else ContextV3Pipeline if strategy=='context-v3' else ContextV2Pipeline if strategy=='context-v2' else ContextPipeline if strategy=='context-v1' else TaskPipeline
            self.task_pipeline = pipeline_class(self.client,self.out,self.inference_config)
            self.config['task_pipeline'] = self.task_pipeline.config

    def evidence_extract(self,meeting,context,retry_fields,resume=False):
        from .task_events import reduce_task_events
        projected = model_input(meeting)
        jobs = {}
        if retry_fields & {'facts','unresolved'}:
            jobs['facts'] = lambda: self.stage('facts',{'meeting':projected},resume)
        if 'decisions' in retry_fields:
            jobs['decisions'] = lambda: self.stage('decisions',{'meeting':projected,'decisions':context['decisions']},resume)
        if retry_fields & {'items','updates'}:
            inverse = {account:person for person,account in meeting['account_map'].items()}
            tasks = [{**{k:t[k] for k in ('guid','summary','status','due_date','due_text') if k in t},
                      'owner_ref':inverse.get(t.get('assignee')) if isinstance(t.get('assignee'),str) else None}
                     for t in context['tasks']]
            history = {'tasks':tasks}
            jobs['task_pipeline'] = lambda: self.task_pipeline.run(meeting,history,resume=resume)
        with ThreadPoolExecutor(max_workers=max(1,len(jobs))) as pool:
            futures = {name:pool.submit(copy_context().run,fn) for name,fn in jobs.items()}
            stages = {name:future.result() for name,future in futures.items()}
        result = assemble({k:v for k,v in stages.items() if k!='task_pipeline'},meeting,context)
        if 'task_pipeline' in stages:
            pipeline = stages['task_pipeline']
            trace = pipeline['trace']
            if pipeline['errors']:
                result['_errors'].extend({**error,'field':field} for error in pipeline['errors'] for field in ('items','updates'))
                trace['pending'] = []
            else:
                if self.strategy in ('context-v1','context-v2','context-v3','context-v4','context-v5'):
                    from .context_state import reduce_context
                    if self.strategy in ('context-v2','context-v3','context-v4','context-v5'):
                        from .context_v2 import reduce_v2
                        if self.strategy in ('context-v3','context-v4','context-v5'):
                            from .context_v3 import reduce_v3
                            proposed = reduce_v3(pipeline,meeting,history)
                        else:proposed = reduce_v2(pipeline,meeting,history)
                    else:
                        proposed = reduce_context(pipeline['checked_events'],pipeline['uncovered_spans'],pipeline['checked_records'],meeting,history)
                    trace['review_records'] = proposed['review_records']
                    trace['item_records'] = proposed['item_records']
                    trace['reports'] = proposed['reports']
                    trace['context_records'] = proposed['context_records']
                    trace['deferred_topics'] = proposed.get('deferred_topics', [])
                else:
                    proposed = reduce_task_events(pipeline['checked_events'],pipeline['uncovered_spans'],meeting,history)
                result.update(items=proposed['items'],updates=proposed['updates'])
                trace['pending'] = proposed['pending']
                result = validate_partial(result,meeting,context,result['_errors'])
                if failed_fields(result) & {'items','updates'}:
                    result['_errors'].extend(dict(field=f,error='Task dependency group incomplete') for f in ('items','updates'))
            result['_task_trace'] = trace
            if pipeline.get('repair_errors'):
                result['_errors'].extend({**error,'field':field} for error in pipeline['repair_errors'] for field in ('items','updates'))
        return result

    def stage(self,name,payload,fresh=False):
        try:
            if self.strategy=='context-v5' and name in ('facts','decisions'):
                from .stage_runner import run_stage
                def checked(raw):
                    value={field:[] for field in FIELDS}
                    if name=='decisions':
                        value[name]=decision_output(raw,payload['meeting'])
                    else:
                        value.update({field:raw[field] for field in STAGE_FIELDS[name]})
                    validate(value,payload['meeting'],dict(tasks=[],decisions=payload.get('decisions',[])))
                    return {field:value[field] for field in STAGE_FIELDS[name]}
                settings=dict(thinking='disabled',max_tokens=6000);settings.update(self.inference_config.get(name,{}))
                result=run_stage(self.client,self.prompts[name],payload,name,checked,self.out/'independent',settings,require_case_id=False)
                if name=='decisions' and self.decision_reviewer:
                    reviewed = self.decision_reviewer.review(payload['meeting'],result[name],payload['decisions'])
                    validate({**{field:[] for field in FIELDS},name:reviewed},payload['meeting'],
                             dict(tasks=[],decisions=payload['decisions']))
                    result = {name:reviewed}
            else:
                result = self.client.call(self.prompts[name],payload,name,2500 if name=='actions' else 6000,fresh=fresh,
                                          inference=getattr(self,'inference_config',{}).get(name))
            if name=='actions' and result.get('case_id') != payload['case_id']:
                raise ValueError('Wrong case_id')
            result.pop('_errors',None)  # This key is reserved for local validation/transport errors.
            return result
        except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
            # Preserve other independent stages and make the failed stage visible.
            return {'_errors':[dict(stage=name,error=type(exc).__name__,detail=str(exc)[:500],recovery=getattr(exc,'recovery',None))]}

    def retry(self,meeting,context,previous):
        return self.extract(meeting,context,previous)

    def extract(self,meeting,context,previous=None):
        projected = model_input(meeting)
        retry_fields = failed_fields(previous) if previous else set(FIELDS)
        if self.strategy in ('evidence-v1','context-v1','context-v2','context-v3','context-v4','context-v5'):
            result = self.evidence_extract(meeting,context,retry_fields,bool(previous))
        elif self.strategy in ('combined','legacy'):
            payload = {'meeting':projected,'history':context}
            raw = self.stage(self.strategy,payload,fresh=bool(previous))
            result = validate_partial(raw,meeting,context,raw.get('_errors'))
        else:
            jobs = {'actions':projected}
            if self.strategy.startswith('split'):
                jobs.update(facts={'meeting':projected},
                            decisions={'meeting':projected,'decisions':context['decisions']})
                if context['tasks']:
                    inverse = {account:person for person,account in meeting['account_map'].items()}
                    tasks = [{**t,'owner_ref':inverse.get(t.get('assignee')) if isinstance(t.get('assignee'),str) else None}
                             for t in context['tasks']]
                    jobs['updates'] = {'meeting':projected,'tasks':tasks}
            jobs = {name:payload for name,payload in jobs.items() if set(STAGE_FIELDS[name]) & retry_fields}
            with ThreadPoolExecutor(max_workers=max(1,len(jobs))) as pool:
                futures = {name:pool.submit(copy_context().run,self.stage,name,payload,bool(previous)) for name,payload in jobs.items()}
                stages = {name:future.result() for name,future in futures.items()}
            result = assemble(stages,meeting,context)
        if previous:
            result = merge_retry(previous,result)
        if self.strategy=='context-v5' and retry_fields & {'facts','unresolved'} and not failed_fields(result) & {'facts','unresolved'}:
            trace=result.get('_task_trace',{})
            review_context=dict(work_records=trace.get('checked_records',[]),deferred_topics=trace.get('deferred_topics',[]),
                work_errors=[e for e in result['_errors'] if e.get('field') in ('items','updates')],decisions=result['decisions'])
            reviewed=self.minutes_reviewer.review(projected,dict(facts=result['facts'],unresolved=result['unresolved']),review_context)
            result.update(facts=reviewed['facts'],unresolved=reviewed['unresolved'],_minutes_review=reviewed['trace'])
            result['_errors'].extend({**error,'field':field} for error in reviewed['errors'] for field in ('facts','unresolved'))
        resolve_calendar_dates(result,meeting)
        from .stage_runner import semantic_config
        cache_config=semantic_config(self.config) if self.strategy=='context-v5' else self.config
        key = digest([meeting['source_key'],meeting['version'],cache_config,context])
        write_json(self.out/(key+'.result.json'),result)
        return result

