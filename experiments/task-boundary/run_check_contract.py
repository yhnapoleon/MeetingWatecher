"""Equal-input current/new checker comparison with frozen interpretations."""
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).parent))
from run_repair_study import ROOT, OUT, HERE, CONFIG, KINDS, read, write_json, digest, ModelClient, validate_records
from meeting_eval.context_state import check_records
from meeting_eval.task_events import canonical_checks
from repair_contract import plan_repair


def build_cases():
    source=read(ROOT/'runs/2026-11-15-m2-system-diagnosis/evidence.json');frozen=read(OUT/'inputs.json')
    cases={}
    for name,key in [('M2','cross_bad'),('positive','positive'),('C20','C20'),('P07b','P07b')]:
        f=frozen[name];t=source[key]['extraction']['_task_trace'];first=t.get('repair',{}).get('before',t)
        cases[name]=dict(meeting=source[key]['meeting'],payload=dict(meeting=f['meeting'],history=f['history'],
            ledger=f['upstream']['ledger'],records=f['upstream']['records'],events=f['upstream']['events'],
            candidates=first['candidates'],evidence_catalog=f['evidence_catalog']))
    # Guards start from coherent frozen records, with changed text and evidence.
    def changed(base,name,texts):
        c=copy.deepcopy(cases[base]);p=c['payload'];m=c['meeting']
        for s,text in zip(m['segments'],texts):s['text']=text
        for s,text in zip(p['meeting']['segments'],texts):s['text']=text
        p['meeting']['case_id']=name;m['case_id']=name
        catalog={s['id']:s['text'] for s in m['segments']}
        def rewrite(value):
            if isinstance(value,dict):
                if 'segment_id' in value and 'quote' in value:
                    text=catalog[value['segment_id']];value.update(quote=text,start=0,end=len(text));value.pop('occurrence',None)
                else:
                    for v in value.values():rewrite(v)
            elif isinstance(value,list):
                for v in value:rewrite(v)
        for key in ('ledger','records','events','candidates'):rewrite(p[key])
        p['evidence_catalog']={f'Q{i}':dict(segment_id=s['id'],quote=s['text']) for i,s in enumerate(m['segments'],1)}
        cases[name]=c
        return p
    p=changed('P07b','G-reference',[
        '登录和支付两个场景都还没细化。小林，会后细化其中一个，先选哪个还没定。',
        '可以，我来，场景等选定。'])
    description='小林接受会后细化登录或支付其中一个场景，具体选哪个场景尚未决定。'
    p['records'][0].update(description=description,missing_fields=['reference'],question='先细化登录还是支付场景？')
    p['events'][0]['work']['description']=description
    for t in p['ledger']['threads']:
        for u in t['updates']:u['description']=description
    p=changed('C20','G-manuscript',[
        '好，那今天就到这里，谢谢各位。',
        '我们会把这个视频剪辑后发给大家确认，文稿也发给大家确认。',
        '好嘞。'])
    description='把本次会议文稿发给大家确认。'
    p['records'][1].update(kind='work',description=description,missing_fields=[],question=None)
    e=copy.deepcopy(p['events'][0]);e.update(event_id='E2',record_id=p['records'][1]['record_id'],candidate_ids=['C2'])
    e['work']['description']=description;p['events'].append(e)
    p['ledger']['threads'][1]['updates'][-1].update(kind='work',description=description)
    p=changed('M2','G-same-segment',[
        '上周说的三个登录失败案例，今天早上我已经发到研发群了。',
        '登录改版第一批的范围今天改一下，内部员工和试点客户都开放。另外，陈可今天下班前把测试结果发给客服。'])
    # Intentionally omitted second work, while original scope record stays non-work.
    p['records'][1]['description']='登录改版第一批范围改为内部员工和试点客户都开放。'
    return cases


def validate(raw,case,arm):
    p=case['payload'];expanded=copy.deepcopy(raw);catalog=p['evidence_catalog']
    def expand(values):
        if not isinstance(values,list) or any(v not in catalog for v in values):raise ValueError('Unknown evidence')
        return [catalog[v] for v in values]
    for check in expanded['checks']:
        for field in check['fields'].values():field['evidence']=expand(field['evidence'])
    for check in expanded['record_checks']:check['evidence']=expand(check['evidence'])
    expanded['uncovered_spans']=expand(expanded['uncovered_spans'])
    v=canonical_checks(expanded,p['events'],case['meeting'])
    records=check_records(expanded['record_checks'],p['records'],case['meeting'])
    if arm=='contract':
        if raw['uncovered_spans']:raise ValueError('Legacy omissions forbidden in new contract')
        originals={r['record_id']:r for r in p['records']}
        for rc in raw['record_checks']:
            r=originals[rc['record_id']]
            if rc['proposed_kind'] is not None and rc['proposed_kind'] not in KINDS:raise ValueError('Unknown proposed kind')
            if not set(r['missing_fields'])<={g['field'] for g in rc['gap_checks']}:raise ValueError('Unchecked original gap')
            validate_records({'records':[{**r,'evidence':[q for q in rc['evidence']],
                'gap_checks':rc['gap_checks'],'clarification':rc['clarification']}]},catalog)
        plan_repair(records,raw['coverage_findings'],catalog,'frozen-check')
    return dict(checked_records=records,**v)


def one(name,case,arm,round_,prompt):
    folder=OUT/'check-contract'/f'{name}-{arm}-r{round_}';folder.mkdir(exist_ok=False)
    result=dict(case=name,arm=arm,round=round_,status='failed')
    try:
        client=ModelClient(ROOT.parent.parent/'meeting-agent/.env',folder/'model')
        raw=client.call(prompt,case['payload'],'check_contract',inference=CONFIG)
        write_json(folder/'raw.json',raw)
        if raw.get('case_id')!=case['payload']['meeting']['case_id']:raise ValueError('Wrong case_id')
        write_json(folder/'validated.json',validate(raw,case,arm));result['status']='valid'
    except Exception as exc:result.update(error=type(exc).__name__,detail=str(exc)[:300])
    write_json(folder/'result.json',result);return result


def main():
    base=OUT/'check-contract';base.mkdir(exist_ok=False);cases=build_cases()
    prompts={'current':(ROOT/'prompts/check-work-context-v1.txt').read_text(encoding='utf8')}
    prompts['contract']=prompts['current']+(HERE/'check-contract-v1.txt').read_text(encoding='utf8')
    write_json(base/'inputs.json',cases);write_json(base/'prompts.json',prompts)
    write_json(base/'plan.json',dict(cases=list(cases),rounds=2,arms=list(prompts),config=CONFIG,calls=28,
        scope='checker only; one call per job, no correction, no persistence',
        rubric={'M2':'Q2 context accepted, no invented owner gap and no omission; Q1 complete existing unchanged',
        'positive':'scope non-work and Chen accepted gray-config work supported, no gap/omission',
        'C20':'video work supported; manuscript ambiguous hypothesis rejected, proposed nonwork/no user question',
        'P07b':'reject original reference gap and question; preserve accepted work',
        'G-reference':'retain actual pending choice and content-blocking question',
        'G-manuscript':'retain both video and manuscript work',
        'G-same-segment':'scope stays nonwork; identify distinct testing-results delivery omission'},
        gate='contract all seven cases both rounds, structure/unresolved fail; only then candidate for pipeline integration',
        ruling='C3 stage integration failed M2 repeatability; test chosen local checker contract before production integration'))
    results=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs=[pool.submit(one,n,c,a,r,p) for r in (1,2) for n,c in cases.items() for a,p in prompts.items()]
        for f in as_completed(jobs):
            result=f.result();results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
    metas=[read(p) for p in base.rglob('meta.json')]
    write_json(OUT/'check-contract-summary.json',dict(results=results,calls=len(metas),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in metas),call_seconds=sum(m['duration_seconds'] for m in metas)))


if __name__=='__main__':main()
