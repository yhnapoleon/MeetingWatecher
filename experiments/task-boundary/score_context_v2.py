"""Source-reviewed corpus judgments and original/updated observable contracts."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(Path(__file__).parent)]
import assess
from meeting_eval.inputs import digest
from scripts.review_action_semantics import export_review,read_jsonl,JUDGMENTS
from scripts.score_action_semantics import score_semantics
from scripts.run_action_baseline import write_json
BASE=ROOT/'runs/2026-11-15-context-v2';OLD=ROOT/'runs/2026-11-15-full-validation'


def read(p):return json.loads(p.read_text(encoding='utf8'))


MATCHES={'C02':['C02.1'],'C03':['C03.1','C03.2'],'C06':['C06.1'],'C07':['C07.1','C07.2','C07.3'],
    'C08':['C08.1'],'C09':['C09.1'],'C14':['C14.1'],'C15':['C15.1'],'C16':['C16.1','C16.2'],
    'C20':['C20.1'],'C21':['C21.1'],'C22':['C22.1'],'C23':['C23.1']}
NOTES={'C02':'本人接受工作设计，未把工作时段当截止。','C03':'UI分工保留候选，市场本人接受，两个工作完整。',
 'C06':'项目经理承诺上传会议纪要。','C07':'三个角色分工完整，无本人承接，工作时段非截止。',
 'C08':'上传纪要并保留尽快原话，无具体日期。','C09':'营销询问研究范围，说明书回答与背景构成工作目的；本人接受，保留下次会前。',
 'C14':'保留电视/录像功能范围核查和 If I can 条件，候选不自动创建。','C15':'Alima本人接受工作设计。',
 'C16':'纪要整理与发幻灯片两项分别承诺，纪要邮件发送仍保留probably限定。',
 'C20':'仅视频剪辑与交确认，文稿对象未变成任务或问题。','C21':'团队承诺整理意见，缺个人映射保留候选。',
 'C22':'保留联系夏校长及学习文化类型对学校建设帮助的目标，会后为时段。',
 'C23':'保留联系袁校长和继续沟通，但item遗漏核对刚才未听清内容的具体目的；只在trace保留信号背景，content_complete=false。'}


def select(group,cid,recovered=False):
    path=BASE/'full'/group/cid
    if recovered and (BASE/'full-recovery'/group/cid/'result.json').exists():path=BASE/'full-recovery'/group/cid
    return path


def corpus(recovered):
    inputs=read_jsonl(OLD/'corpus/input.jsonl');predictions=[];sources={}
    for c in inputs:
        path=select('corpus',c['case_id'],recovered);predictions.append(read(path/'summary.json'));sources[c['case_id']]=path
    scores={}
    for version,label in [('original','labels.snapshot.jsonl'),('audited','labels.audited.jsonl')]:
        labels=read_jsonl(OLD/'corpus'/label);review=export_review(inputs,labels,predictions)
        review.update(status='agent_reviewed',reviewer='codex-context-v2-source-review')
        exact=[]
        for case,pred in zip(review['cases'],predictions):
            cid=case['case_id'];ids=MATCHES.get(cid,[])
            assert len(ids)==len(case['judgments']),(cid,'changed output requires new source review')
            case['reviewed']=True
            for row,gold in zip(case['judgments'],ids):
                row.update({k:True for k in JUDGMENTS});row.update(gold_event_id=gold,reason=NOTES[cid],evidence_ids=case['predictions'][row['prediction_index']]['evidence_ids'])
                if cid=='C23':row['content_complete']=False
                if version=='original':
                    if cid=='C09':row['content_complete']=False
                    if cid in ('C22','C23'):row['time_correct']=False
            expected={r['event_id'] for r in case['references'] if r['operation'] in ('create','candidate')}
            correct={r['gold_event_id'] for r in case['judgments'] if all(r[k] for k in JUDGMENTS)}
            exact.append(dict(case_id=cid,passed=pred['status']=='processed' and expected==correct and len(correct)==len(case['predictions'])))
        score=score_semantics(predictions,labels,review);score['exact_cases']=dict(passed=sum(r['passed'] for r in exact),total=len(exact),cases=exact)
        tag='after-recovery' if recovered else 'first'
        write_json(BASE/f'corpus-review-{version}-{tag}.json',review);scores[version]=score
    write_json(BASE/('corpus-scores-after-recovery.json' if recovered else 'corpus-scores-first.json'),dict(scores=scores,
        sources={cid:dict(path=p.relative_to(ROOT).as_posix(),result_hash=digest(read(p/'result.json'))) for cid,p in sources.items()}))
    return scores


def update_contracts(recovered):
    view=BASE/('updates-after-recovery' if recovered else 'updates-first');view.mkdir(exist_ok=True)
    def view_read(p):
        try:rel=p.relative_to(view)
        except ValueError:return read(p)
        return read(select(rel.parts[0],rel.parts[1],recovered)/Path(*rel.parts[2:]))
    with patch.object(assess,'read',view_read):report=assess.updates(view)
    corrected=[]
    for row in report['cases']:
        checks=dict(row['checks'])
        if row['case_id']=='M2':
            checks.pop('pending',None);checks.update(row['extra_semantic_checks'])
        corrected.append({**row,'checks':checks,'passed':all(checks.values())})
    updated=dict(original_passed=report['passed'],total=report['total'],current_passed=sum(r['passed'] for r in corrected),cases=corrected,
        label_change='M2 original pending=true conflicts with current requirement; remove only that expectation, require no extra items/reviews; old results preserved')
    write_json(view/'current-contracts.json',updated);return updated


def main():
    for recovered in (False,True):
        scores=corpus(recovered);updates=update_contracts(recovered)
        print('after recovery' if recovered else 'first',scores['audited']['fully_correct'],'updates',updates['current_passed'],'/',updates['total'])
    pairs=assess.pairs(BASE/'pairs');print('pairs',pairs['passed'],'/',pairs['total'])


if __name__=='__main__':main()
