"""Identical downstream merge/check/one-repair for the frozen C3 arms."""
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).parent))
from run_repair_study import ROOT, OUT, read, write_json, digest, ModelClient
from meeting_eval.context_pipeline import ContextPipeline
from meeting_eval.context_state import reduce_context

MERGE = '''\n本调用是合并解释：original_interpretation 是冻结的首次解释，semantic_classification 是另一次分类的建议，两者都可能有误。以原文为准综合判断，输出以上既有 records/events 完整协议，不输出分类器的 S 编号或 gap_checks。无依据的缺口应移除，有依据的缺口必须保留；建议 not_needed 不能自动删除真实工作。分类建议 unresolved 不能变成已经确认的事实。仍覆盖 ledger 全部 threads，可依原文增减 records。每个 event 必须有 other_changes，time 必须有 change。'''


class FrozenMerge(ContextPipeline):
    def __init__(self,client,out,inference,case,classification):
        super().__init__(client,out,inference)
        self.frozen=case;self.classification=classification
        self.prompts['interpret_work'] += MERGE
        self.config.update(experiment='c3-frozen-merge-v1',frozen_hash=digest(case),classification_hash=digest(classification),
                           merge_prompt_hash=digest(self.prompts['interpret_work']))

    def _stage(self,stage,payload,validate,folder,resume):
        if stage=='track_context':
            # Validated saved ledger, not a fresh tracker call. All four inputs <8 segments.
            return copy.deepcopy(self.frozen['upstream']['ledger'])
        if stage=='interpret_work':
            payload={**payload,'original_interpretation':{k:self.frozen['upstream'][k] for k in ('records','events')},
                     'semantic_classification':self.classification}
        return super()._stage(stage,payload,validate,folder,resume)


def one(name,key,arm,round_,cases,frozen):
    classification=read(OUT/'c3'/f'{name}-{arm}-r{round_}'/'raw.json')
    folder=OUT/'merge'/f'{name}-{arm}-r{round_}';folder.mkdir(parents=True,exist_ok=False)
    c=cases[key];client=ModelClient(ROOT.parent.parent/'meeting-agent/.env',folder/'model')
    pipe=FrozenMerge(client,folder,read(ROOT/'experiments/action-context/compact-check.json'),frozen[name],classification)
    result=pipe.run(c['meeting'],c['history'])
    write_json(folder/'pipeline.json',result)
    reduced=None
    if not result['errors']:
        reduced=reduce_context(result['checked_events'],result['uncovered_spans'],result['checked_records'],c['meeting'],c['history'])
        write_json(folder/'reduced.json',reduced)
    summary=dict(case=name,arm=arm,round=round_,errors=result['errors'],repair=result['trace'].get('repair',{}).get('status'),
        items=reduced['items'] if reduced else None,updates=reduced['updates'] if reduced else None,
        reviews=reduced['review_records'] if reduced else None,uncovered=result['uncovered_spans'])
    write_json(folder/'summary.json',summary)
    return dict(case=name,arm=arm,round=round_,errors=result['errors'],items=len(reduced['items']) if reduced else None,
                reviews=len(reduced['review_records']) if reduced else None,repair=summary['repair'])


def main():
    cases=read(ROOT/'runs/2026-11-15-m2-system-diagnosis/evidence.json');frozen=read(OUT/'inputs.json')
    (OUT/'merge').mkdir(exist_ok=False)
    (OUT/'merge'/'merge-instruction.txt').write_text(MERGE,encoding='utf8')
    write_json(OUT/'merge'/'plan.json',dict(expected_jobs=16,tracker='frozen validated ledger',initial_interpretation='frozen original',
        new_calls='one common merge + normal check + at most one repair/recheck',
        gate_basis='C3 blind M2/positive pass both; C20 video and P07b acceptance retained in both arms; blind case counts 2>1 each round',
        scope='stage integration only; not Service, no new facts/decisions calls or persistence claims',
        acceptance='original C3 whole-case rubric plus reducer items/reviews/updates/uncovered; structural or unresolved failure'))
    results=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(one,n,k,a,r,cases,frozen) for r in (1,2) for n,k in [('M2','cross_bad'),('positive','positive'),('C20','C20'),('P07b','P07b')] for a in ('visible','blind')]
        for f in as_completed(jobs):
            v=f.result();results.append(v);print(json.dumps(v,ensure_ascii=False),flush=True)
    metas=[read(p) for p in (OUT/'merge').rglob('meta.json')]
    write_json(OUT/'merge-summary.json',dict(results=results,calls=len(metas),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),call_seconds=sum(m['duration_seconds'] for m in metas)))


if __name__=='__main__':main()
