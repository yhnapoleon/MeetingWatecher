"""Offline evidence inventory after source review; never calls the model."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest

BASE=ROOT/'runs/2026-11-16-user-solutions'


def read(p):return json.loads(p.read_text(encoding='utf8'))
def write(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def main():
    batches=[]
    for version in ('live-v1','live-v2','live-v3'):
        p=BASE/version;result=read(p/'results.json')
        rows=read(p/'assessment-overlay.json')['rows'] if version=='live-v1' else result['rows']
        key='current_observable_passed' if version=='live-v1' else 'observable_passed'
        batches.append(dict(version=version,passed=sum(r[key] for r in rows),total=len(rows),usage=result['usage']))
    notes={
        'C23':'保留会后联系袁校长与沟通其他问题。两轮对信号背景的表述不同；补问目的不作必写门槛，未增加独立执行义务。',
        'C23-explicit':'明确补问未听清内容被保留；仍为群体候选，没有虚构个人归属或截止日。',
        'C23-unrelated':'联系议题为报名问题；信号问题未变成补问义务。',
        'G-omitted':'同段两项独立工作：范围调整仅缺个人，发送测试结果仅缺陈可承接；旧任务完成更新保留，O1新增记录有程序绑定。',
        'CP06':'与减少重复咨询目标关联的真实潜在需求保留，确认落实方向，不被误判为暂缓议题。',
        'HT04':'仍需在两个授权旧任务之间选择，不新建任务或擅自更新其中之一。',
        'no-date':'明确自愿整理并发送的工作保留，无期限不导致暂缓；无个人映射所以仍待分配具体账号。',
        'activate':'同会议后文明确继续做并自愿完成，最终只有一项工作，不再保留一条并列暂缓事项。',
        'M2-service':'M1任务归属陈可、截止11月13日；监控面板仅收集。M2完成旧任务，范围调整保留今天和两个开放对象，仅问负责人，无新增自动写入。',
        'positive-service':'M1正确；M2范围与配置测试合为一项陈可已承接工作，截止今天下班前，旧任务完成、决定替换及重复导入均通过。',
    }
    reviewed=[];audits=[];p=BASE/'live-v3'
    with zipfile.ZipFile(p/'source.zip') as z:
        for f in sorted(p.glob('r*/*/assessment.json')):
            assessment=read(f);name=assessment['case']
            outputs=[f.parent/'m1-result.json',f.parent/'m2-result.json'] if name.endswith('-service') else [f.parent/'reduced.json']
            sources=[dict(path=str(s.relative_to(ROOT)).replace('\\','/'),sha256=hashlib.sha256(s.read_bytes()).hexdigest()) for s in outputs]
            reviewed.append(dict(round=f.parent.parent.name,case=name,observable_passed=assessment['observable_passed'],
                source_review_passed=assessment['observable_passed'],reviewer='assistant_source_review',notes=notes[name],sources=sources))
            pipelines=[read(s)['extraction']['_task_trace'] for s in outputs] if name.endswith('-service') else [read(f.parent/'pipeline.json')['trace']]
            for trace in pipelines:
                mismatches=[]
                for filename,expected in trace['config']['code'].items():
                    text=z.read('meeting_eval/'+filename).decode('utf8').replace('\r\n','\n')
                    if digest(text)!=expected:mismatches.append(filename)
                audits.append(dict(round=f.parent.parent.name,case=name,mismatches=mismatches))
    assert len(reviewed)==20, 'Expected two complete ten-case rounds'
    assert not any(r['mismatches'] for r in audits),audits
    write(BASE/'source-review.json',dict(policy='user-review-2026-11-16',annotation='assistant reviewed; not independent human ground truth',rows=reviewed))
    write(BASE/'source-audit.json',audits)
    write(BASE/'verification-summary.json',dict(batches=batches,
        total_calls=sum(b['usage']['calls'] for b in batches),total_tokens=sum(b['usage']['tokens'] for b in batches),
        retries=0,final_source_review_passed=sum(r['source_review_passed'] for r in reviewed),final_cases=len(reviewed)))
    print(json.dumps(read(BASE/'verification-summary.json'),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
