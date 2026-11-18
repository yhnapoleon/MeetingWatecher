"""Optional user-policy candidate: bound checks and repairs, no extra stage."""
import copy
from .context_v3 import ContextV3Pipeline
from .context_protocol_v3 import INTERPRET, prompt_schema, evidence_catalog
from .context_protocol_v4 import repair_contract, expand_patch, closed_validate
from .context_protocol_v5 import check_contract, expand_checks, closed_schema, review_issues
from .context_tracking_reliable import tracking_schema, expand_tracking, source_catalog
from .context_checkpoints import track_checkpoints, MAX_BYTES, MAX_SEGMENTS, MAX_SPLIT_DEPTH
from .context_state import canonical_records
from .context_protocol import validate_schema
from .context_protocol_v3 import REPAIR
from .inputs import digest
from .task_pipeline import ROOT
from .stage_runner import run_stage,semantic_config
from .context_wire import wire_request,wire_prompt,decode_output
from .reference_repair import ReferenceRepair


def represented_segments(records,events):
    represented={s['segment_id'] for r in records for s in r['evidence']}
    represented.update(s['segment_id'] for e in events
        for field in ('work','owner','commitment','time','state','relation') for s in e[field]['evidence'])
    return represented


class ContextV5Pipeline(ContextV3Pipeline):
    review_issues=staticmethod(review_issues)
    def cache_config(self):return semantic_config(self.config)
    def __init__(self,*args):
        super().__init__(*args)
        policy=(ROOT/'prompts/policy-context-v5.txt').read_text(encoding='utf8')
        intent_policy=(ROOT/'prompts/dialogue-intent-context-v1.txt').read_text(encoding='utf8')
        # Candidate prompt files are independent of historical prompt versions.
        interpret=(ROOT/'prompts/interpret-work-context-v5.txt').read_text(encoding='utf8')
        check=(ROOT/'prompts/check-work-context-v5.txt').read_text(encoding='utf8')
        self.prompts.update(
            track_context=policy+'\n'+(ROOT/'prompts/track-context-reliable-v1.txt').read_text(encoding='utf8'),
            interpret_work=policy+'\n'+interpret+'\n'+intent_policy+prompt_schema(INTERPRET),
            repair_work=policy+'\n'+(ROOT/'prompts/repair-work-context-v4.txt').read_text(encoding='utf8')+'\n'+intent_policy,
            check_work=policy+'\n'+check+'\n'+intent_policy,
            check_repair=policy+'\n'+check+'\n'+intent_policy+'\n本次只检查修正后的 records/events 和 dispositions，输出 disposition_checks，不输出 coverage_findings。')
        self.prompts['check_repair']+='\nreview_issues 是必须逐项处理的首检异议。issue_checks 恰好覆盖给定 issue_id；resolved 说明修正如何消除异议，overturned 用原话说明首检为何错，unresolved 保留未解决。不得只因新结论 supported 忽略原异议；原文优先，不机械服从首检。'
        self.config.update(version=19,protocol='context-v5-system-review',wire_protocol='original-source-id-v2',
            tracking=dict(protocol='source-grounded-v1',max_bytes=MAX_BYTES,max_segments=MAX_SEGMENTS,max_split_depth=MAX_SPLIT_DEPTH),
            prompts={s:digest(p) for s,p in self.prompts.items()})
        self.config.pop('checkpoint_size',None)
        self.config['code'].update({n:digest((ROOT/'meeting_eval'/n).read_text(encoding='utf8')) for n in
            ('context_v5.py','context_protocol_v5.py','context_protocol_v4.py','context_tracking_reliable.py','context_checkpoints.py','context_wire.py','reference_repair.py','stage_runner.py','model_client.py','check_transport.py')})

    def _track_ledger(self,meeting,folder,trace,resume):
        return track_checkpoints(self,meeting,folder,trace,resume)

    def interpret(self,raw,ledger,candidates,meeting,history,repair=False):
        validate_schema(raw,REPAIR if repair else INTERPRET)
        raw=copy.deepcopy(raw)
        for event in raw['events']:
            time=event['time']
            # A new work window has no existing deadline to set. Keep its
            # semantic kind and evidence for the independent time check.
            if (event['relation']['kind']=='new' and event['state']['kind']=='future_work'
                    and time['kind']=='work_window' and time['change']=='set'
                    and time['text'] and time['evidence']):
                time['change']='keep'
        result=super().interpret(raw,ledger,candidates,meeting,history,repair)
        if repair:return result
        represented=represented_segments(result['records'],result['events'])
        linked={eid for t in ledger['threads'] for eid in t['entity_ids']}
        identities={r['record_id'] for r in result['records']}
        for entity in ledger['entities']:
            if entity['entity_id'] in linked or any(s['segment_id'] in represented for s in entity['mentions']):continue
            rid='R_ENTITY_'+entity['entity_id']
            while rid in identities:rid+='_'
            identities.add(rid)
            result['records'].append(dict(record_id=rid,thread_ids=[],kind='entity_only',
                content_basis='explicit',description=entity['label'],evidence=copy.deepcopy(entity['mentions']),
                missing_fields=[],question=None,issuer_ref=None,need_basis=dict(goal=None,evidence=[])))
        result['records']=canonical_records(result['records'],ledger,result['events'],meeting)
        return result

    def check(self,raw,*args,**kwargs):
        checked=super().check(raw,*args,**kwargs)
        if 'issue_checks' in raw:checked['issue_checks']=copy.deepcopy(raw['issue_checks'])
        rows={r['record_id']:r for r in raw['record_checks']}
        for record in checked['checked_records']:
            if 'qualification' in rows[record['record_id']]:
                record['qualification']=copy.deepcopy(rows[record['record_id']]['qualification'])
        return checked

    def _stage(self,stage,payload,validate,folder,resume):
        if stage=='interpret_work':
            request={**payload,'output_schema':closed_schema(INTERPRET)}
            def interpreted(raw):
                closed_validate(raw,INTERPRET)
                return validate(raw)
            return self._recorded_stage(stage,request,interpreted,folder)
        if stage=='track_context':
            schema=tracking_schema(payload)
            request=copy.deepcopy(payload)
            request.update(evidence_catalog=source_catalog(payload['meeting']),
                output_schema=schema,output_contract=prompt_schema(schema))
            return run_stage(self.client,self.prompts[stage],request,stage,
                lambda raw:validate(expand_tracking(raw,payload)),folder,self.inference[stage])
        if stage in ('check_work','check_repair','repair_work'):
            repair=stage=='repair_work';recheck=stage=='check_repair'
            schema,binding=repair_contract(payload) if repair else check_contract(payload,recheck)
            request=copy.deepcopy(payload)
            request.update(scope=binding['scope'],output_schema=closed_schema(schema),output_contract=prompt_schema(schema))
            if repair:request.update(repair_scope=binding['scope'],target_slots=binding['slots'])
            else:
                request['check_targets']=dict(record_ids=[r['record_id'] for r in payload['records']],
                    event_field_keys=list(schema['properties']['checks']['properties']))
                context=request.pop('context_records',[])
                request['read_only_context']=[{k:copy.deepcopy(r[k]) for k in
                    ('kind','description','evidence') if k in r} for r in context]
                # A covered disposition needs its original identity for lookup,
                # but never adds that identity to the output check targets.
                covered={rid for d in payload.get('dispositions',[]) for rid in d['record_ids']}
                request['disposition_reference_records']={r['record_id']:{k:copy.deepcopy(r[k]) for k in
                    ('kind','description','evidence') if k in r} for r in context if r['record_id'] in covered}
                if stage=='check_work':
                    represented=represented_segments(payload['records'],payload['events'])
                    linked={eid for t in payload['ledger']['threads'] for eid in t['entity_ids']}
                    request['coverage_review']=dict(
                        unrepresented_evidence=[q for q,s in evidence_catalog(payload['meeting']).items()
                            if s['segment_id'] not in represented],
                        nonwork_record_evidence=[dict(record_id=r['record_id'],kind=r['kind'],
                            evidence=list(dict.fromkeys(s['segment_id'] for s in r['evidence'])))
                            for r in payload['records'] if r.get('kind') in
                            ('context_only','entity_only','deferred_topic','withdrawn','resolved')],
                        unthreaded_entities=[copy.deepcopy(e) for e in payload['ledger']['entities']
                            if e['entity_id'] not in linked])
            def convert(raw):
                return validate(expand_patch(raw,payload) if repair else expand_checks(raw,payload,recheck))
            return self._recorded_stage(stage,request,convert,folder)
        return self._recorded_stage(stage,payload,validate,folder)

    def _recorded_stage(self,stage,payload,validate,folder):
        request=wire_request(payload)
        return run_stage(self.client,wire_prompt(self.prompts[stage],payload['meeting']),request,stage,
            lambda raw:validate(decode_output(raw,payload['meeting'])),folder,self.inference[stage],
            reference_repair=ReferenceRepair() if stage=='interpret_work' else None)
