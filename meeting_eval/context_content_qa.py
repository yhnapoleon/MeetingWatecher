"""Experimental source-first coverage check. Not enabled by the default strategy."""
import copy
import json
from . import context_protocol as base
from . import context_protocol_v3 as v3
from .context_protocol_v4 import CHECK,closed_validate,coverage_to_v3
from .context_v3 import ContextV3Pipeline
from .context_v4 import ContextV4Pipeline
from .inputs import digest
from .task_pipeline import ROOT
from scripts.run_action_baseline import write_json

SOURCE=base.obj(case_id=base.string(),requirements=base.array(base.obj(work=base.string(),question=base.string(),
    expected_answer=base.string(),basis=base.enum('explicit','contextual'),evidence=v3.Q),True))
ANSWERS=base.obj(case_id=base.string(),answers=base.array(base.obj(question_id=base.string('K1'),
    record_id=base.string(None,nullable=True),answer=base.string(None,nullable=True),quote=base.string(None,nullable=True)),True))
ASSESSMENT=base.array(base.obj(question_id=base.string('K1'),target_ref=base.string('record:R1',nullable=True),
    status=base.enum('covered','missing','not_required','uncertain'),reason=base.string(),evidence=v3.Q),True)


def validate_answers(raw,questions,records):
    closed_validate(raw,ANSWERS)
    rows=base.rows_by_id(raw['answers'],'question_id');known={q['question_id'] for q in questions}
    if set(rows)!=known:raise ValueError('Incomplete question answers')
    records={r['record_id']:r for r in records}
    for a in rows.values():
        rid=a['record_id']
        if rid is not None and rid not in records:raise ValueError('Unknown answer record')
        if a['answer'] is None:
            if a['quote'] is not None:raise ValueError('Unanswered question cannot claim support')
        elif not a['answer'].strip() or rid is None or not a['quote'] or a['quote'] not in records[rid]['description']:
            raise ValueError('Answer lacks literal description support')
    return raw


class ContextQAPipeline(ContextV4Pipeline):
    def __init__(self,client,out,inference_config):
        super().__init__(client,out,inference_config)
        self.prompts['source_requirements']=(ROOT/'prompts/source-requirements-context-v4.txt').read_text(encoding='utf8')+v3.prompt_schema(SOURCE)
        self.prompts['answer_requirements']=(ROOT/'prompts/answer-requirements-context-v4.txt').read_text(encoding='utf8')+v3.prompt_schema(ANSWERS)
        extra=(ROOT/'prompts/check-requirements-context-v4.txt').read_text(encoding='utf8')
        for s in ('check_work','check_repair'):
            self.prompts[s]+='\n'+extra+'\n额外必填 requirement_checks 的元素结构：'+json.dumps(base.example(ASSESSMENT['items']),ensure_ascii=False)
        self.config.update(protocol='context-v4-qa-experiment',prompts={s:digest(p) for s,p in self.prompts.items()})
        self.config['code']['context_content_qa.py']=digest((ROOT/'meeting_eval/context_content_qa.py').read_text(encoding='utf8'))

    def _qa_call(self,stage,payload,validate,folder,resume):
        path=folder/stage/digest([payload,self.config]);path.mkdir(parents=True,exist_ok=True)
        saved=path/'validated.json'
        if saved.exists():return json.loads(saved.read_text(encoding='utf8'))
        status=path/'state.json';fresh=resume and status.exists()
        write_json(status,dict(status='started'))
        raw=self.client.call(self.prompts['answer_requirements' if stage.startswith('answer_requirements') else stage],payload,stage,
                             inference=self.inference['check_work'],fresh=fresh)
        write_json(path/'raw.json',raw)
        if raw.get('case_id')!=payload.get('case_id',payload.get('meeting',{}).get('case_id')):raise ValueError('Wrong case_id')
        checked=validate(raw);write_json(saved,checked);write_json(status,dict(status='complete'))
        return checked

    def _stage(self,stage,payload,validate,folder,resume):
        if stage not in ('check_work','check_repair'):return super()._stage(stage,payload,validate,folder,resume)
        catalog=v3.evidence_catalog(payload['meeting'])
        def source_check(raw):
            closed_validate(raw,SOURCE)
            for q in raw['requirements']:
                base.expand_refs(q['evidence'],catalog,True)
                if any(not q[k].strip() for k in ('work','question','expected_answer')):raise ValueError('Empty source requirement')
            return [dict(**q,question_id=f'K{i}') for i,q in enumerate(raw['requirements'],1)]
        questions=self._qa_call('source_requirements',dict(meeting=payload['meeting'],evidence_catalog=catalog),source_check,folder,resume)
        if stage=='check_repair':
            writable={r['record_id'] for r in payload['records']}
            bindings=self.qa_bindings
            questions=[q for q in questions if bindings[q['question_id']] is not None and
                       (bindings[q['question_id']].startswith('finding:') or bindings[q['question_id']] in {'record:'+rid for rid in writable})]
        records=payload['records']+payload.get('context_records',[])
        answer_records=[r for r in records if r['kind']=='work']
        answer_payload=dict(case_id=payload['meeting']['case_id'],questions=[{k:q[k] for k in ('question_id','question')} for q in questions],
                            records=[{k:r[k] for k in ('record_id','description')} for r in answer_records])
        answers=self._qa_call('answer_requirements_'+stage,answer_payload,lambda raw:validate_answers(raw,questions,answer_records),folder,resume) if questions else dict(case_id=payload['meeting']['case_id'],answers=[])
        request={**payload,'source_requirements':questions,'description_answers':answers['answers']}
        schema=copy.deepcopy(CHECK if stage=='check_work' else v3.RECHECK)
        schema['properties']['requirement_checks']=ASSESSMENT;schema['required'].append('requirement_checks')
        def checked(raw):
            closed_validate(raw,schema)
            out=copy.deepcopy(raw);qs=base.rows_by_id(out.pop('requirement_checks'),'question_id')
            if set(qs)!={q['question_id'] for q in questions}:raise ValueError('Incomplete requirement checks')
            if stage=='check_work':out=coverage_to_v3(out)
            checks=base.rows_by_id(out['record_checks'],'record_id');all_ids={r['record_id'] for r in records}
            answered=base.rows_by_id(answers['answers'],'question_id')
            for q in questions:
                row=qs[q['question_id']];target=row['target_ref'];base.expand_refs(row['evidence'],catalog,True)
                if not row['reason'].strip():raise ValueError('Invalid requirement check')
                rid=target[len('record:'):] if target and target.startswith('record:') else None
                if target is not None and rid is None:
                    finding_refs={f'finding:{i}':f for i,f in enumerate(out.get('coverage_findings',[]),1)}
                    if stage!='check_work' or target not in finding_refs or row['status'] not in ('missing','uncertain'):
                        raise ValueError('Invalid requirement finding target')
                    finding=finding_refs[target]
                    if not set(q['evidence']) & set(finding['evidence']):raise ValueError('Finding lacks requirement source')
                    finding['description']+='；必要信息：'+q['expected_answer']
                    continue
                if rid is not None and rid not in all_ids:raise ValueError('Unknown requirement record')
                if row['status']=='covered' and (answered[q['question_id']]['answer'] is None or rid!=answered[q['question_id']]['record_id']):
                    raise ValueError('Covered requirement lacks matching description answer')
                if row['status'] in ('missing','uncertain'):
                    if rid not in checks:raise ValueError('Missing content needs a writable record check')
                    content=checks[rid]['content']
                    if row['status']=='missing':content['missing_details'].append(dict(description=q['work']+'：'+q['expected_answer'],evidence=q['evidence']))
                    else:content['verdict']='insufficient'
                    content['reason']+='；必要信息核验：'+row['reason']
            result=validate(out)
            if stage=='check_work':result['qa_bindings']={qid:row['target_ref'] for qid,row in qs.items()}
            return result
        result=ContextV3Pipeline._stage(self,stage,request,checked,folder,resume)
        if stage=='check_work':self.qa_bindings=result['qa_bindings']
        return result
