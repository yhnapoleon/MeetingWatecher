"""Experimental source inventory on A, plus controlled A Service replays.

No production strategy registration, automatic retries, or historical writes.
"""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).parent)]
from run_context_v4 import PromptOnly, full_flow_checks, INFERENCE, ENV
from run_context_v3 import snapshot
from validate_m2 import positive_meeting, assess as assess_cross
from assess_context_v3 import assess
from meeting_eval.context_v3 import reduce_v3
from meeting_eval.context_protocol import obj, array, string, Q, validate_schema, prompt_schema, expand_refs
from meeting_eval.context_protocol_v3 import evidence_catalog
from meeting_eval.extract import model_input
from meeting_eval.inputs import digest
from meeting_eval.model_client import ModelClient
from scripts import replay_mvp
from scripts.run_action_baseline import write_json

BASE = ROOT / 'runs/2026-11-16-baseline-reassessment'
FIXTURES = ROOT / 'runs/2026-11-15-context-v4/fixtures/inputs.json'
SOURCE_SCHEMA = obj(case_id=string('输入case_id'),
    works=array(obj(description=string('原文建立的工作及状态'), evidence=Q)),
    implicit_need=array(obj(description=string('原文建立的待处理需求'), evidence=Q)),
    context=array(obj(description=string('不应变成独立工作的背景'), reason=string('原文话语功能'), evidence=Q)))
SOURCE_PROMPT = (Path(__file__).with_name('source-work-inventory.txt').read_text(encoding='utf8') +
    '\n' + (ROOT / 'prompts/need-policy-context-v3.txt').read_text(encoding='utf8') + prompt_schema(SOURCE_SCHEMA))
ALIGNMENT = '''
source_work_inventory 是另一遍只看原文得到的待核验工作清单，不是真值。
先逐项与原文及现有 records 的实际描述对齐，再核验现有记录。
逐个核对清单中的工作是否已有记录表达了同一动作与对象；同段引用重合不能证明工作已覆盖。
原文支持且真正没有任何现有记录表达的独立工作，输出 new_work 的 coverage_findings，related_record_ids=[]。
已有记录只是分类错，修正对应 record_check；同工作描述不完整，写 content.missing_details，不能当成独立新工作。
清单本身有误时依原文否定它；决定/背景记录也不能替代尚未表达的真实工作。
最终分类仍由本次核验提出、原修正与再核验裁定，不直接照搬清单，不改变输出协议。
'''


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def source_payload(case):
    meeting = model_input(case['meeting'])
    return dict(meeting=meeting, history=copy.deepcopy(case['history']), evidence_catalog=evidence_catalog(meeting))


def validate_inventory(raw, payload):
    validate_schema(raw, SOURCE_SCHEMA)
    if raw['case_id'] != payload['meeting']['case_id']:
        raise ValueError('Wrong source inventory case_id')
    for section in ('works', 'implicit_need', 'context'):
        for item in raw[section]:
            if not item['description'].strip() or not item['evidence']:
                raise ValueError('Source proposition needs description and evidence')
            expand_refs(item['evidence'], payload['evidence_catalog'])
    return raw


def inventory(case, folder):
    folder.mkdir(parents=True, exist_ok=False)
    payload = source_payload(case)
    write_json(folder / 'input.json', payload)
    client = ModelClient(ENV, folder / 'model')
    settings = PromptOnly(client, folder, INFERENCE).inference['check_work']
    write_json(folder / 'config.json', dict(prompt_sha256=digest(SOURCE_PROMPT), inference=settings))
    try:
        raw = client.call(SOURCE_PROMPT, payload, 'source_inventory', inference=settings)
        validate_inventory(raw, payload)
        write_json(folder / 'inventory.json', raw)
        return dict(value=raw, error=None, payload_sha256=digest(payload))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        error = dict(type=type(exc).__name__, detail=str(exc)[:1000])
        write_json(folder / 'error.json', error)
        return dict(value=None, error=error, payload_sha256=digest(payload))


def focused(arm, round_no, name, case, source, out):
    folder = out / f'{arm}-r{round_no}' / name
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / 'input.json', case)
    if arm == 'D':
        write_json(folder / 'source-inventory.json', source)
    class Pipeline(PromptOnly):
        def __init__(self, *args):
            super().__init__(*args)
            if arm == 'D':
                self.prompts['check_work'] += ALIGNMENT
                self.config.update(protocol='experiment-source-inventory-on-A',
                    source_inventory_sha256=digest(source), prompts={k:digest(v) for k,v in self.prompts.items()})

        def _stage(self, stage, payload, validate, stage_folder, resume):
            if stage in ('track_context', 'interpret_work'):
                return copy.deepcopy(case['frozen']['ledger' if stage == 'track_context' else 'interpreted'])
            if stage == 'check_work' and arm == 'D':
                if source['error']:
                    raise ValueError('Independent source stage failed: ' + str(source['error']))
                if source['payload_sha256'] != digest(source_payload(case)):
                    raise ValueError('Source inventory input mismatch')
                payload = {**payload, 'source_work_inventory': copy.deepcopy(source['value'])}
            return super()._stage(stage, payload, validate, stage_folder, resume)

    pipe = Pipeline(ModelClient(ENV, folder / 'model'), folder, INFERENCE)
    result = pipe.run(case['meeting'], case['history'])
    write_json(folder / 'pipeline.json', result)
    reduced = reduce_v3(result, case['meeting'], case['history']) if not result['errors'] else None
    write_json(folder / 'reduced.json', reduced)
    summary = dict(case='G-same-segment' if name == 'G-omitted' else name,
        errors=result['errors'], repair=result['trace'].get('repair', {}).get('status'),
        repair_error=result['trace'].get('repair', {}).get('detail'),
        items=reduced['items'] if reduced else None, reviews=reduced['review_records'] if reduced else None,
        updates=reduced['updates'] if reduced else None, findings=result['coverage_findings'])
    write_json(folder / 'summary.json', summary)
    score = assess(folder)
    write_json(folder / 'contract-review.json', score)
    return dict(arm=arm, round=round_no, case=name, observable_passed=score['observable_passed'],
        failed_checks=[k for k,v in score['checks'].items() if not v],
        errors=result['errors'], repair_error=summary['repair_error'])


def service_replay(out, positive):
    import meeting_eval.context_v3 as v3
    original_read = replay_mvp.read
    def input_read(path):
        return positive_meeting() if positive and path == ROOT / 'examples/m2.json' else original_read(path)
    if positive:
        write_json(out / 'm2-input.json', positive_meeting())
    write_json(out / 'adapter.json', dict(requested_arm='A', service_strategy='context-v3',
        implementation='run_context_v4.PromptOnly', expected_protocol='context-v3-coverage-prompt-control'))
    with patch.object(v3, 'ContextV3Pipeline', PromptOnly), patch.object(replay_mvp, 'read', input_read):
        replay_mvp.replay(out, ENV, 'context-v3', inference_config=INFERENCE)
    for meeting in ('m1', 'm2'):
        trace = read(out / f'{meeting}-result.json')['extraction']['_task_trace']
        if trace['config']['protocol'] != 'context-v3-coverage-prompt-control':
            raise AssertionError('A adapter not active')
    return full_flow_checks(assess_cross(out, positive=positive), out)


def usage(out):
    metas = [read(p) for p in out.rglob('meta.json')]
    return dict(calls=len(metas), received=sum(m['status']=='received' for m in metas),
        tokens=sum((m.get('usage') or {}).get('total_tokens', 0) for m in metas))


def scored_service_replay(out, positive):
    """Keep early Service/acceptance failures in the denominator, without retries."""
    try:
        return service_replay(out, positive)
    except Exception as exc:
        error = dict(type=type(exc).__name__, detail=str(exc)[:2000])
        write_json(out / 'replay-error.json', error)
        return dict(passed=False, original_contract_passed=False,
            checks={'replay_completed': False}, failure=error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--mode', choices=('small','cross','positive'), required=True)
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    if Path(args.name).name != args.name or args.name in ('.','..'):
        raise ValueError('New single-component output name required')
    out = BASE / args.name
    out.mkdir(parents=True, exist_ok=False)
    snapshot(out)
    write_json(out / 'plan.json', dict(**vars(args), inference=INFERENCE, retries=0,
        fixtures_sha256=digest(read(FIXTURES)), source_prompt_sha256=digest(SOURCE_PROMPT),
        gate='All four cases, both rounds, correct final content and zero extra scope work/questions; failures stop expansion.'))
    if args.mode == 'small':
        cases = {k:v for k,v in read(FIXTURES).items() if k in ('M2','positive','G-same-segment','G-omitted')}
        assert source_payload(cases['G-omitted']) == source_payload(cases['G-same-segment'])
        sources = {}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs = {pool.submit(inventory, cases[n], out / f'source-r{r}' / n):(r,n)
                for r in range(1,args.rounds+1) for n in ('M2','positive','G-same-segment')}
            for future in as_completed(jobs):
                key = jobs[future]
                sources[key] = future.result()
                print('source', *key, 'error', sources[key]['error'], flush=True)
        rows = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            jobs = [pool.submit(focused, a, r, n, c,
                sources[(r,'G-same-segment' if n == 'G-omitted' else n)], out)
                for r in range(1,args.rounds+1) for a in ('A','D') for n,c in cases.items()]
            for future in as_completed(jobs):
                row = future.result()
                rows.append(row)
                write_json(out / 'progress.json', rows)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    else:
        rows = scored_service_replay(out, positive=args.mode == 'positive')
    write_json(out / 'summary.json', dict(results=rows, **usage(out)))
    print(json.dumps(usage(out)), flush=True)


if __name__ == '__main__':
    main()
