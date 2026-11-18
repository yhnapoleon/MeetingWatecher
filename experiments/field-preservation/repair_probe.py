"""One bounded reinterpretation followed by independent checking; no task writes."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.inputs import digest, normalize
from meeting_eval.extract import model_input
from meeting_eval.model_client import ModelClient
from meeting_eval.task_events import canonical_events, canonical_checks
from meeting_eval.context_state import canonical_records, check_records, reduce_context
from meeting_eval.context_updates import validate_time_changes
from scripts.run_action_baseline import write_json

BASE = ROOT/'runs/2026-11-15-field-preservation/repair-probe'
CASES = [
    dict(case_id='C03', source='runs/2026-11-14-context-prerequisites/guarded-regression', targets=['R1','R3'],
         feedback='核验认为用户界面分类应恢复连续分工；同时检查通知邮件是否只需保留为上下文。仅修正有依据的问题。'),
    dict(case_id='C26', source='runs/2026-11-14-task-updates/regression', targets=['R1'],
         feedback='复查可以的含义：是否已明确决定执行，还是仅提议；结合完整上下文，不能按单词直接决定。'),
    dict(case_id='C09', source='runs/2026-11-14-task-updates/regression', targets=['R1'],
         feedback='复查研究目的是否真正明确，以及是否必须补日历日期；若有缺口，针对实际范围提出可回答的问题。')]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def one(spec):
    source = ROOT/spec['source']; out = BASE/spec['case_id']; out.mkdir(parents=True, exist_ok=False)
    inputs = [json.loads(line) for line in (source/'input.jsonl').read_text(encoding='utf-8').splitlines()]
    raw_meeting = next(row for row in inputs if row['case_id']==spec['case_id'])
    meeting = normalize(raw_meeting, 'evaluator'); projected = model_input(meeting)
    trace = read(source/(spec['case_id']+'.json'))['extraction']['_task_trace']
    originals = [row for row in trace['records'] if row['record_id'] in spec['targets']]
    tids = {tid for row in originals for tid in row['thread_ids']}
    ledger = {**trace['ledger'], 'threads': [t for t in trace['ledger']['threads'] if t['thread_id'] in tids]}
    candidates = [c for c in trace['candidates'] if c.get('thread_id') in tids]
    client = ModelClient(ROOT.parent.parent/'meeting-agent/.env', out/'model')
    settings = read(ROOT/'experiments/action-context/compact-check.json')
    payload = dict(meeting=projected, ledger=ledger, candidates=candidates, history={'tasks':[]},
                   original_records=originals, original_checks=[r for r in trace['checked_records'] if r['record_id'] in spec['targets']],
                   target_record_ids=spec['targets'], diagnostic_feedback=spec['feedback'])
    write_json(out/'input.json', payload)
    prompt = (ROOT/'prompts/interpret-work-context-v1.txt').read_text(encoding='utf-8')
    prompt += '\n这是一次限定修正实验。只输出 target_record_ids 中每个 record，保持它们的 record_id 和 thread_ids；不得添加范围之外的记录或事件。反馈只是待复查线索，以原话为准。没有发现错误可保持原判断。允许为目标补事件或撤去不成立的事件，但不扩大工作范围。只做一次。'
    result = dict(case_id=spec['case_id'], source=spec['source'], targets=spec['targets'], writes=0)
    try:
        repaired = client.call(prompt, payload, 'repair_work', inference=settings['interpret_work'])
        assert repaired['case_id']==spec['case_id']
        assert sorted(r['record_id'] for r in repaired['records'])==sorted(spec['targets'])
        original_threads={r['record_id']:r['thread_ids'] for r in originals}
        assert all(r['thread_ids']==original_threads[r['record_id']] for r in repaired['records'])
        events, candidates = canonical_events(repaired['events'], candidates, meeting, {'tasks':[]})
        validate_time_changes(events)
        for event, raw in zip(events, repaired['events']):
            event.update(record_id=raw['record_id'], other_changes=raw['other_changes'])
            assert event['record_id'] in spec['targets']
            assert isinstance(event['other_changes'],list) and set(event['other_changes']) <= {'content','owner','other'}
        records = canonical_records(repaired['records'], ledger, events, meeting)
        catalog = {f'Q{i}':dict(segment_id=s['id'],quote=s['text']) for i,s in enumerate(meeting['segments'],1) if s['text']}
        check_payload = dict(meeting=projected,ledger=ledger,candidates=candidates,history={'tasks':[]},records=records,events=events,evidence_catalog=catalog)
        checked = client.call((ROOT/'prompts/check-work-context-v1.txt').read_text(encoding='utf-8'),check_payload,'check_repair',inference=settings['check_work'])
        assert checked['case_id']==spec['case_id']
        def expand(refs):
            assert isinstance(refs,list) and all(isinstance(ref,str) and ref in catalog for ref in refs)
            return [catalog[ref] for ref in refs]
        expanded=copy.deepcopy(checked)
        for row in expanded['checks']:
            for value in row['fields'].values():value['evidence']=expand(value['evidence'])
        for row in expanded['record_checks']:row['evidence']=expand(row['evidence'])
        expanded['uncovered_spans']=expand(expanded['uncovered_spans'])
        verified=canonical_checks(expanded,events,meeting)
        checked_records=check_records(expanded['record_checks'],records,meeting)
        reduced=reduce_context(verified['checked_events'],verified['uncovered_spans'],checked_records,meeting,{'tasks':[]})
        result.update(status='processed',records=records,events=events,checked_records=checked_records,**verified,reduced=reduced)
    except (ValueError,KeyError,TypeError,AssertionError,OSError) as exc:
        result.update(status='failed',error=repr(exc))
    write_json(out/'result.json',result)
    return dict(case_id=spec['case_id'],status=result['status'],items=len(result.get('reduced',{}).get('items',[])),error=result.get('error'))


def main():
    BASE.mkdir(exist_ok=False)
    write_json(BASE/'manifest.json',dict(cases=CASES,cases_hash=digest(CASES),is_blind=False,kind='diagnostic_single_repair'))
    with ThreadPoolExecutor(max_workers=3) as pool:
        for future in as_completed([pool.submit(one,spec) for spec in CASES]):
            print(json.dumps(future.result(),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
