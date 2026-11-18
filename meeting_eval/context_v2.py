"""Context-v2: checked gaps and one bounded, evidence-backed coverage repair."""
import copy
from .context_pipeline import ContextPipeline
from .context_state import canonical_ledger, ledger_candidates, canonical_records, check_records, reduce_context, record_content_supported
from .context_updates import validate_time_changes
from .context_new_work import local_record_issues
from .context_coverage import plan_repair, apply_repair, validate_check_alignment
from .context_protocol import INTERPRET, REPAIR, CHECK, RECHECK, validate_schema, prompt_schema, expand_refs, validate_clarification
from .task_events import canonical_events, canonical_checks, align_spans
from .inputs import digest
from .task_pipeline import ROOT
from scripts.run_action_baseline import write_json


class ContextV2Pipeline(ContextPipeline):
    def __init__(self,client,out,inference_config):
        super().__init__(client,out,inference_config)
        interpret=(ROOT/'prompts/interpret-work-context-v2.txt').read_text(encoding='utf8')
        check=(ROOT/'prompts/check-work-context-v2.txt').read_text(encoding='utf8')
        recheck='\n'.join(line for line in check.splitlines() if not line.startswith('仅输出新版本 coverage_findings'))
        self.prompts.update(interpret_work=interpret+prompt_schema(INTERPRET),check_work=check+prompt_schema(CHECK),
            repair_work=interpret+'\n'+(ROOT/'prompts/repair-work-context-v2.txt').read_text(encoding='utf8')+prompt_schema(REPAIR),
            check_repair=recheck+'\n本次只核验 records/events 和 dispositions；context_records 是其他已核验记录。逐项独立核验每个处置与记录对应关系，不能因处置写了 rejected/added 就通过。不得新增遗漏，不输出 coverage_findings。\n'+prompt_schema(RECHECK))
        self.config.update(version=8,protocol='context-v2',prompts={s:digest(p) for s,p in self.prompts.items()})
        self.config['code'].update({n:digest((ROOT/'meeting_eval'/n).read_text(encoding='utf8')) for n in ('context_v2.py','context_protocol.py','context_coverage.py')})

    def interpret(self,raw,ledger,candidates,meeting,history,repair=False):
        validate_schema(raw,REPAIR if repair else INTERPRET)
        events,expanded=canonical_events(raw['events'],candidates,meeting,history)
        validate_time_changes(events)
        for e,original in zip(events,raw['events']):
            e.update(record_id=original['record_id'],other_changes=original['other_changes'])
            if e['commitment']['kind']=='conditional' and not e['commitment']['evidence']:raise ValueError('Conditional work requires evidence')
        records=canonical_records(raw['records'],ledger,events,meeting)
        return dict(records=records,events=events,candidates=expanded)

    def check(self,raw,interpreted,meeting,catalog,recheck=False):
        validate_schema(raw,RECHECK if recheck else CHECK)
        if 'uncovered_spans' in raw or recheck and 'coverage_findings' in raw:raise ValueError('Mixed check protocol versions')
        validate_check_alignment(interpreted['records'],raw['record_checks'])
        expanded=copy.deepcopy(raw)
        for c in expanded['checks']:
            for field in c['fields'].values():field['evidence']=expand_refs(field['evidence'],catalog)
        for c in expanded['record_checks']:
            validate_clarification(c,catalog)
            c['evidence']=expand_refs(c['evidence'],catalog,True)
        expanded['uncovered_spans']=[] # Only the old deterministic event validator sees this field.
        checked=canonical_checks(expanded,interpreted['events'],meeting)
        checked['checked_records']=check_records(expanded['record_checks'],interpreted['records'],meeting)
        by_id={c['record_id']:c for c in raw['record_checks']}
        for r in checked['checked_records']:
            r.update({k:copy.deepcopy(by_id[r['record_id']][k]) for k in ('gap_checks','clarification','proposed_kind')})
            event=next((e for e in checked['checked_events'] if e['record_id']==r['record_id']),None)
            r['event_supported']=event is None or all(c['verdict']=='supported' for c in event['checks'].values())
        return checked

    def _track_ledger(self,meeting,folder,trace,resume):
        from .extract import model_input
        ledger=None;start=0
        ends=list(range(self.checkpoint_size,len(meeting['segments']),self.checkpoint_size))+[len(meeting['segments'])]
        for end in ends:
            prefix={**meeting,'segments':meeting['segments'][:end]}
            ledger=self._stage('track_context',dict(meeting=model_input(prefix),previous=ledger,new_segment_ids=[s['id'] for s in meeting['segments'][start:end]]),lambda raw:canonical_ledger(raw,prefix,ledger),folder,resume)
            trace['checkpoints'].append(dict(through_segment=prefix['segments'][-1]['id'] if end else None,ledger=copy.deepcopy(ledger)));start=end
        return ledger

    def run(self,meeting,history,*,resume=False):
        from .extract import model_input
        projected=model_input(meeting);folder=self.out/'context_v2'/digest([projected,history,getattr(self,'cache_config',lambda:self.config)()])
        result=dict(events=[],checked_events=[],checked_records=[],coverage_findings=[],uncovered_spans=[],errors=[],trace={'checkpoints':[]})
        stage='track_context'
        try:
            ledger=self._track_ledger(meeting,folder,result['trace'],resume)
            candidates=ledger_candidates(ledger);result['trace'].update(ledger=ledger,candidates=candidates)
            stage='interpret_work'
            interpreted=self._stage(stage,dict(meeting=projected,ledger=ledger,candidates=candidates,history=history),lambda raw:self.interpret(raw,ledger,candidates,meeting,history),folder,resume)
            result['events']=interpreted['events'];result['trace'].update(interpreted)
            catalog={f'Q{i}':dict(segment_id=s['id'],quote=s['text']) for i,s in enumerate(meeting['segments'],1) if s['text']}
            stage='check_work'
            def initial_check(raw):
                checked=self.check(raw,interpreted,meeting,catalog)
                plan=plan_repair(checked['checked_records'],raw['coverage_findings'],catalog,digest([projected,raw]))
                return {**checked,'plan':plan}
            checked=self._stage(stage,dict(meeting=projected,ledger=ledger,**interpreted,history=history,evidence_catalog=catalog),initial_check,folder,resume)
            plan=checked.pop('plan');findings=plan['findings']
            result.update(checked);result['coverage_findings']=findings
            result['trace'].update(checked,coverage_scope=plan['scope'],coverage_findings=findings,coverage_plan=plan)
            if self.repair_enabled and plan['needs_repair']:
                targets=set(plan['target_record_ids']);originals=[r for r in interpreted['records'] if r['record_id'] in targets]
                original_events=[e for e in interpreted['events'] if e['record_id'] in targets]
                context_records=[r for r in checked['checked_records'] if r['record_id'] not in targets]
                tids={t for r in originals for t in r['thread_ids']};subset={**ledger,'threads':[t for t in ledger['threads'] if t['thread_id'] in tids]}
                repair=dict(target_record_ids=sorted(targets),status='started',before=copy.deepcopy({**interpreted,**checked}),findings=copy.deepcopy(findings))
                issues=getattr(self,'review_issues',lambda records,events:[])(
                    [r for r in checked['checked_records'] if r['record_id'] in targets],
                    [e for e in checked['checked_events'] if e['record_id'] in targets])
                issue_payload={'review_issues':issues} if hasattr(self,'review_issues') else {}
                if issues:repair['issues']=copy.deepcopy(issues)
                result['trace']['repair']=repair;repair_stage='repair_work'
                try:
                    oldids={e['record_id']:e['event_id'] for e in interpreted['events']}
                    def fixed_validate(raw):
                        fixed=self.interpret(raw,subset,interpreted['candidates'],meeting,history,True)
                        original_by={r['record_id']:r for r in originals}
                        present={r['record_id'] for r in fixed['records']}
                        if not targets<=present:raise ValueError('Repair removed target records')
                        for r in fixed['records']:
                            if r['record_id'] in original_by and r['thread_ids']!=original_by[r['record_id']]['thread_ids']:raise ValueError('Changed original threads')
                            if r['record_id'] not in targets and r['record_id'] in {r['record_id'] for r in interpreted['records']}:raise ValueError('Repair changed unselected record')
                        next_id=max([int(e['event_id'][1:]) for e in interpreted['events']]+[0])+1
                        for e in fixed['events']:
                            rid=e['record_id']
                            if rid in oldids:e['event_id']=oldids[rid]
                            else:e['event_id']=f'E{next_id}';next_id+=1
                        fixed['dispositions']=raw['dispositions'];return fixed
                    fixed=self._stage(repair_stage,dict(meeting=projected,ledger=subset,candidates=interpreted['candidates'],history=history,
                        target_record_ids=sorted(targets),original_records=originals,original_events=original_events,
                        record_checks=[r for r in checked['checked_records'] if r['record_id'] in targets],
                        event_checks=[e for e in checked['checked_events'] if e['record_id'] in targets],context_records=context_records,
                        coverage_findings=findings,evidence_catalog=catalog,**issue_payload),fixed_validate,folder,resume)
                    repair['proposal']=copy.deepcopy(fixed);repair_stage='check_repair'
                    def recheck(raw):
                        verified=self.check(raw,fixed,meeting,catalog,True)
                        merged=apply_repair(plan,verified['checked_records'],fixed['dispositions'],raw['disposition_checks'])
                        if merged['status']=='invalid':raise ValueError(merged['detail'])
                        return {**verified,'merged':merged,'disposition_checks':raw['disposition_checks']}
                    rechecked=self._stage(repair_stage,dict(meeting=projected,ledger=subset,**fixed,history=history,
                        context_records=context_records,coverage_findings=findings,evidence_catalog=catalog,**issue_payload),recheck,folder,resume)
                    merged=rechecked.pop('merged');final_records=merged['records'];new_by={r['record_id']:r for r in rechecked['checked_records']}
                    # Retained originals keep their original events. Accepted proposals use rechecked events.
                    applied={r['record_id'] for r in final_records if r['record_id'] in new_by and r==new_by[r['record_id']]}
                    final_events=[e for e in checked['checked_events'] if e['record_id'] not in applied]+[e for e in rechecked['checked_events'] if e['record_id'] in applied]
                    allowed_ids={r['record_id'] for r in final_records};final_events=[e for e in final_events if e['record_id'] in allowed_ids]
                    result.update(checked_events=final_events,checked_records=final_records,coverage_findings=merged['unresolved_findings'],events=[{k:v for k,v in e.items() if k!='checks'} for e in final_events])
                    result['trace'].update(records=final_records,events=result['events'],candidates=fixed['candidates'],checked_records=final_records,checked_events=final_events,coverage_findings=result['coverage_findings'])
                    repair.update(status='checked',after=copy.deepcopy(rechecked),dispositions=fixed['dispositions'])
                except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError) as exc:
                    repair.update(status='failed',stage=repair_stage,error=type(exc).__name__,detail=str(exc)[:1000],recovery=getattr(exc,'recovery',None))
                    if hasattr(self,'review_issues'):
                        result['repair_errors']=[dict(stage=repair_stage,error=type(exc).__name__,detail=str(exc)[:1000],recovery=getattr(exc,'recovery',None))]
        except (OSError,ValueError,TypeError,KeyError,AttributeError,IndexError) as exc:
            result['errors']=[dict(stage=stage,error=type(exc).__name__,detail=str(exc)[:1000],recovery=getattr(exc,'recovery',None))]
        result['trace'].update(errors=result['errors'],config=self.config,uncovered_spans=[])
        write_json(folder/'result.json',result)
        return result


def reduce_v2(pipeline,meeting,history):
    records=[];disputed=[]
    event_by={e['record_id']:e for e in pipeline['checked_events']}
    for original in pipeline['checked_records']:
        r=copy.deepcopy(original)
        event=event_by.get(r['record_id'])
        content_gap=(r['check']['verdict']=='supported' and r['clarification']['status']=='needed' and
                     any(g['verdict']=='supported' and g['blocking_for']=='content' for g in r['gap_checks']))
        work_check=event['checks']['work'] if event else None
        work_disputed=work_check and (work_check['verdict']=='contradicted' or work_check['verdict']=='insufficient' and not content_gap)
        if (not (record_content_supported(r) or local_record_issues(event,r)) or
                r['clarification']['status']=='unresolved' or work_disputed):
            if work_disputed:r['check']['reason']=work_check['reason']
            disputed.append(r);continue
        r['missing_fields']=[g['field'] for g in r['gap_checks'] if g['verdict']=='supported' and g['blocking_for']!='none']
        r['question']=r['clarification']['question']
        records.append(r)
    allowed={r['record_id'] for r in records}
    result=reduce_context([e for e in pipeline['checked_events'] if e['record_id'] in allowed],[],records,meeting,history)
    def unresolved(rid,spans,reason):
        refs=list(dict.fromkeys(s['segment_id'] for s in spans))
        result['review_records'].append(dict(record_id=rid,category='interpretation_unresolved',description='原话：'+'；'.join(s['quote'] for s in spans),
            content_basis='unknown',description_status='unverified_hypothesis',missing_fields=[],question='原话含义尚未可靠确定，当前没有可执行的工作解释。',issuer_ref=None,
            evidence_ids=refs,check_reason=reason,can_add_task=False))
        result['pending'].append(dict(record_id=rid,reason='interpretation_unresolved',evidence_ids=refs))
    for r in disputed:unresolved(r['record_id'],r['evidence'],r['check']['reason'])
    catalog={f'Q{i}':dict(segment_id=s['id'],quote=s['text']) for i,s in enumerate(meeting['segments'],1)}
    scope=pipeline['trace'].get('coverage_scope','')
    for f in pipeline['coverage_findings']:
        unresolved('O-'+digest([scope,f['finding_id']])[:16],align_spans(expand_refs(f['evidence'],catalog),meeting),'遗漏工作尚未通过补回或关闭核验')
    return result
