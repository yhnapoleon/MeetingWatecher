"""Source-backed review of minutes claims, with one scoped repair and recheck."""
import copy
from pathlib import Path

from . import context_protocol as schema
from .context_protocol_v3 import evidence_catalog
from .context_protocol_v4 import closed_validate
from .context_protocol_v5 import closed_schema
from .inputs import digest
from .stage_runner import run_stage, atomic_json

ROOT=Path(__file__).resolve().parents[1]


class MinutesReviewer:
    def __init__(self,client,out,inference):
        self.client=client;self.out=Path(out);self.inference=inference
        self.prompts={stage:(ROOT/'prompts'/name).read_text(encoding='utf8') for stage,name in (
            ('check_minutes','check-minutes-v1.txt'),('repair_minutes','repair-minutes-v1.txt'),
            ('check_minutes_repair','check-minutes-v1.txt'))}
        self.config=dict(version=1,prompts={k:digest(v) for k,v in self.prompts.items()},
            code=digest(Path(__file__).read_text(encoding='utf8')))

    def call(self,stage,payload,contract,folder,validate):
        scope=digest([stage,payload,self.config])
        contract=schema.obj(case_id=schema.string(payload['meeting']['case_id']),scope=schema.string(scope),**contract)
        request=copy.deepcopy(payload)
        request.update(scope=scope,output_schema=closed_schema(contract),output_contract=schema.prompt_schema(contract))
        def checked(raw):
            closed_validate(raw,contract)
            if raw['scope']!=scope:raise ValueError('Stale minutes scope')
            return validate(raw)
        settings=dict(thinking='disabled',max_tokens=6000)
        settings.update(self.inference.get(stage,{}))
        return run_stage(self.client,self.prompts[stage],request,stage,checked,folder,settings)

    def check(self,meeting,candidates,context,folder,issues=None,read_only=None):
        catalog=evidence_catalog(meeting);refs=schema.array(schema.string('Q1',values=list(catalog)))
        row=schema.obj(content=schema.enum('supported','insufficient','contradicted'),
            speech_scope=schema.enum('current','quoted','historical','uncertain'),
            adoption_evidence={**copy.deepcopy(refs),'example':[]},
            final_status=schema.enum('open','answered','decided','withdrawn','deferred','not_applicable','uncertain'),
            route=schema.enum('fact','unresolved','omit','unverified'),reason=schema.string(),evidence=refs,
            deferred_record_ids=schema.array(schema.string('R1'),True))
        contract=dict(checks=schema.obj(**{c['claim_id']:copy.deepcopy(row) for c in candidates}))
        payload=dict(meeting=meeting,evidence_catalog=catalog,candidates=candidates,read_only_context=context,
            read_only_candidates=read_only or [])
        stage='check_minutes'
        if issues is None:
            contract['coverage_findings']=schema.array(schema.obj(kind=schema.enum('fact','unresolved'),
                description=schema.string(),evidence=refs),True)
        else:
            stage='check_minutes_repair';payload['review_issues']=issues
            contract['issue_checks']=schema.obj(**{i:schema.obj(status=schema.enum('resolved','overturned','unresolved'),
                reason=schema.string(),evidence=refs) for i in issues})
        def validate(raw):
            known={r['record_id'] for r in context.get('deferred_topics',[])}
            for identity,check in raw['checks'].items():
                if not check['evidence'] or not check['reason'].strip():raise ValueError('Minutes check requires reason and evidence')
                if set(check['deferred_record_ids'])-known:raise ValueError('Unknown deferred record')
                if check['route']=='unresolved' and (check['final_status']!='open' or
                        check['speech_scope']!='current' and not check['adoption_evidence']):
                    check['content']='insufficient'
                    check['reason']+='；未决路线缺少当前议题或最终开放状态。'
                if check['speech_scope']=='uncertain' and check['route']!='omit':check['content']='insufficient'
            for finding in raw.get('coverage_findings',[]):
                if not finding['description'].strip() or not finding['evidence']:raise ValueError('Missing minutes finding basis')
            for identity,check in raw.get('issue_checks',{}).items():
                if not check['reason'].strip() or not check['evidence']:raise ValueError('Missing minutes issue disposition')
                if check['status']=='unresolved':raw['checks'][identity]['content']='insufficient'
            return raw
        return self.call(stage,payload,contract,folder,validate)

    def review(self,meeting,raw_minutes,context):
        catalog=evidence_catalog(meeting);inverse={s['segment_id']:q for q,s in catalog.items()}
        candidates=[]
        for field,prefix,kind in [('facts','F','fact'),('unresolved','U','unresolved')]:
            for i,row in enumerate(raw_minutes[field],1):
                candidates.append(dict(claim_id=prefix+str(i),kind=kind,statement=row['statement'],
                    evidence=[inverse[s] for s in row['evidence_ids']]))
        folder=self.out/'minutes_review'/digest([meeting,candidates,context,self.config])
        trace=dict(original_candidates=copy.deepcopy(candidates),status='started')
        result=dict(facts=[],unresolved=[],errors=[],trace=trace)
        try:
            initial=self.check(meeting,candidates,context,folder);trace['initial_check']=initial
            retained=[];retained_checks={};targets={};issues={}
            for candidate in candidates:
                identity=candidate['claim_id'];check=initial['checks'][identity]
                if check['route']=='omit':continue
                if check['content']=='supported' and check['route']==candidate['kind']:
                    retained.append(candidate);retained_checks[identity]=check
                else:
                    targets[identity]=candidate;issues[identity]=check
            for i,finding in enumerate(initial.get('coverage_findings',[]),1):
                identity='N'+str(i);targets[identity]=dict(claim_id=identity,**finding);issues[identity]=finding
            if targets:
                trace['repair_targets']=copy.deepcopy(targets)
                refs=schema.array(schema.string('Q1',values=list(catalog)))
                replacement=schema.obj(kind=schema.enum('fact','unresolved'),statement=schema.string(),evidence=refs)
                contract=dict(replacements=schema.obj(**{identity:copy.deepcopy(replacement) for identity in targets}))
                def validate(raw):
                    for row in raw['replacements'].values():
                        if not row['statement'].strip() or not row['evidence']:raise ValueError('Empty repaired minutes claim')
                    return raw
                fixed=self.call('repair_minutes',dict(meeting=meeting,evidence_catalog=catalog,targets=targets,
                    review_issues=issues,read_only_candidates=retained,read_only_context=context),contract,folder,validate)
                proposed=[dict(claim_id=identity,**row) for identity,row in fixed['replacements'].items()]
                trace['repair_proposal']=copy.deepcopy(proposed)
                recheck=self.check(meeting,proposed,context,folder,issues,retained);trace['recheck']=recheck
                if any(check['status']=='unresolved' for check in recheck['issue_checks'].values()):
                    raise ValueError('Minutes original objection remains unresolved')
                for candidate in proposed:
                    identity=candidate['claim_id'];check=recheck['checks'][identity]
                    if check['route']=='omit':continue
                    if check['content']!='supported' or check['route']!=candidate['kind']:
                        raise ValueError('Minutes meaning remains unverified: '+identity)
                    retained.append(candidate);retained_checks[identity]=check
            hidden=set()
            for candidate in retained:
                field='facts' if candidate['kind']=='fact' else 'unresolved'
                result[field].append(dict(statement=candidate['statement'],
                    evidence_ids=list(dict.fromkeys(catalog[q]['segment_id'] for q in candidate['evidence']))))
                if candidate['kind']=='fact':hidden.update(retained_checks[candidate['claim_id']]['deferred_record_ids'])
            trace.update(status='accepted',accepted_candidates=retained,covered_deferred_record_ids=sorted(hidden),
                deferred_context_hash=digest(context.get('deferred_topics',[])))
        except (ValueError,TypeError,KeyError,AttributeError,IndexError,OSError) as exc:
            trace.update(status='failed',error=type(exc).__name__,detail=str(exc)[:2000])
            result.update(facts=[],unresolved=[],errors=[dict(stage='minutes_review',error=type(exc).__name__,detail=str(exc)[:1000],recovery=getattr(exc,'recovery',None))])
        atomic_json(folder/'result.json',result)
        return result
