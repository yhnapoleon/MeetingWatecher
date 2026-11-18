"""Optional context-v4: typed coverage and program-bound repair targets."""
import copy
from .context_v3 import ContextV3Pipeline,reduce_v3
from .context_protocol_v3 import prompt_schema
from .context_protocol_v4 import CHECK,coverage_to_v3,repair_contract,expand_patch
from .inputs import digest
from .task_pipeline import ROOT


COVERAGE_RULES='''
已有记录分类错误只在对应 record_check 指出，不能把同一个命题重复报成遗漏。
同一工作遗漏的目的/范围/条件只填对应 content.missing_details。
new_work_findings 只列真正独立且没有记录表达的另一工作，不含关联 ID。
uncertain_findings 只用于无法可靠确定是否同一工作，列出相关记录；不是分类异议的替代入口。
范围值的决定/变更不自动意味着另有人实施；只有原文或完整对话建立了实施动作才有独立工作。
同段另有发送/修改等真实工作必须保留。未明确个人负责人并不否定工作本身。
'''


class ContextV4Pipeline(ContextV3Pipeline):
    def __init__(self,client,out,inference_config):
        super().__init__(client,out,inference_config)
        check=(ROOT/'prompts/check-work-context-v3.txt').read_text(encoding='utf8')
        check=check.replace('coverage_findings','new_work_findings')
        policy=(ROOT/'prompts/need-policy-context-v3.txt').read_text(encoding='utf8')
        self.prompts['check_work']=check+'\n'+policy+COVERAGE_RULES+prompt_schema(CHECK)
        self.prompts['repair_work']=(ROOT/'prompts/repair-work-context-v4.txt').read_text(encoding='utf8')+'\n'+policy
        self.config.update(version=10,protocol='context-v4',prompts={s:digest(p) for s,p in self.prompts.items()})
        self.config['code'].update({n:digest((ROOT/'meeting_eval'/n).read_text(encoding='utf8')) for n in ('context_v4.py','context_protocol_v4.py')})

    def _stage(self,stage,payload,validate,folder,resume):
        if stage=='check_work':
            return super()._stage(stage,payload,lambda raw:validate(coverage_to_v3(raw)),folder,resume)
        if stage=='repair_work':
            schema,binding=repair_contract(payload)
            request=copy.deepcopy(payload)
            request.update(repair_scope=binding['scope'],target_slots=binding['slots'],output_contract=prompt_schema(schema),output_schema=schema)
            return super()._stage(stage,request,lambda raw:validate(expand_patch(raw,payload)),folder,resume)
        return super()._stage(stage,payload,validate,folder,resume)
