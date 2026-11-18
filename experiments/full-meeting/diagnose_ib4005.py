"""Replay saved IB4005 failures without network calls; preserve original scores."""
import copy
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.context_coverage import plan_repair
from meeting_eval.decision_review import DecisionReview
from meeting_eval.minutes_review import MinutesReviewer

RUN = ROOT / 'runs/2026-11-18-unseen-IB4005-v19'
OUT = RUN / 'root-cause-review'


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def node(stage, prefix=''):
    matches = [p.parent for p in (RUN / 'model').rglob('state.json')
               if p.parent.parent.name == stage and p.parent.name.startswith(prefix)]
    assert len(matches) == 1, (stage, prefix, matches)
    return matches[0]


def outcome(fn):
    try:
        fn()
        return 'accepted'
    except ValueError as exc:
        return str(exc)


def main():
    frozen = {name: sha(RUN / name) for name in (
        'input.json', 'reference.json', 'result.json', 'annotations.json', 'evaluation.json')}
    assert frozen['result.json'] == 'b76ba4e74099ffe038fdf1915d5a6663c6e7374ff9b6f154a2525a2f1a8f73d3'
    assert frozen['reference.json'] == '676fc70702f005d4d07c375b0e218421461308d3321c30fe09c780e9117e1f07'
    with zipfile.ZipFile(RUN / 'source.zip') as archive:
        files = [n for n in archive.namelist() if not n.endswith('/')]
        for name in files:
            assert (ROOT / name).read_bytes() == archive.read(name), name

    # Replay the actual minutes check callback, intercepting run_stage before I/O.
    mn = node('check_minutes', '1c861')
    req = read(mn / 'attempt-1/stage-request.json')
    raw = read(mn / 'attempt-1/raw.json')
    fixed = copy.deepcopy(raw)
    catalog = req['evidence_catalog']
    mapping = {}
    for alias in raw['coverage_findings'][0]['evidence']:
        source_id = 'IB4005.sync.' + alias[1:]
        matches = [q for q, ev in catalog.items() if ev['segment_id'] == source_id]
        assert len(matches) == 1
        mapping[alias] = matches[0]
    fixed['coverage_findings'][0]['evidence'] = [mapping[x] for x in raw['coverage_findings'][0]['evidence']]
    reviewer = MinutesReviewer(None, OUT, {})

    def replay_minutes(response):
        def replay(client, prompt, payload, stage, validate, folder, settings):
            assert payload['scope'] == req['scope']
            return validate(copy.deepcopy(response))
        with patch('meeting_eval.minutes_review.run_stage', replay):
            return reviewer.check(req['meeting'], req['candidates'], req['read_only_context'], OUT,
                                  read_only=req['read_only_candidates'])

    minutes_error = outcome(lambda: replay_minutes(raw))
    assert 'invalid enum' in minutes_error
    minutes_probe = outcome(lambda: replay_minutes(fixed))
    assert minutes_probe == 'accepted'

    # Isolate the same relation invariant using saved findings and known IDs.
    # Supported dummy checks avoid unrelated checks; this is not full check_work replay.
    wn = node('check_work', '66090')
    wr = read(wn / 'attempt-2/stage-request.json')
    findings = read(wn / 'attempt-2/raw.json')['coverage_findings']
    records = [dict(record_id=r['record_id'], check=dict(verdict='supported')) for r in wr['records']]
    refs = {e for f in findings for e in f['evidence']}
    relation_error = outcome(lambda: plan_repair(records, findings, refs, wr['scope']))
    assert relation_error == 'Contradictory finding relation'
    uncertain = [{**f, 'relation': 'uncertain'} for f in findings]
    relation_probe = outcome(lambda: plan_repair(records, uncertain, refs, wr['scope']))
    assert relation_probe == 'accepted'

    # Replay the real decision validator and closing selection with saved responses.
    dn = node('decision_reconcile')
    dr = read(dn / 'attempt-2/stage-request.json')
    decisions_raw = read(dn / 'attempt-2/raw.json')
    decision = DecisionReview(None, OUT, {})

    def reconcile_call(stage, payload, check):
        assert stage == 'decision_reconcile'
        return check(copy.deepcopy(decisions_raw))

    decision.call = reconcile_call
    topics = [dr['topics'][str(i)] for i in range(1, len(dr['topics']) + 1)]
    confirmed = decision.reconcile(dr['turns'], topics, dr['draft'], dr['independent'], dr['history'])
    visitor = next(c for c in decisions_raw['decisions'] if c['topic'] == 6)
    assert visitor['quote'] == 'So Agnes with Marianne and David .'
    assert '访客一' in visitor['statement']
    cn = node('decision_close')
    close_req = read(cn / 'attempt-1/stage-request.json')
    close_raw = read(cn / 'attempt-1/raw.json')

    def close_call(stage, payload, check):
        assert stage == 'decision_close' and payload == close_req
        return check(copy.deepcopy(close_raw))

    decision.call = close_call
    retained = decision.closing_status(dr['turns'], confirmed, dr['independent'])
    assert list(close_req['cases']) == ['1']
    assert len(confirmed) == 7 and len(retained) == 6
    assert any(c['topic'] == 2 for c in confirmed) and not any(c['topic'] == 2 for c in retained)
    assert any(c['topic'] == 6 for c in retained)

    probes = dict(
        network_calls=0, production_snapshot_files_equal=len(files), frozen_sha256=frozen,
        minutes=dict(original_error=minutes_error, diagnostic_alias_mapping=mapping,
                     changed_aliases_only=minutes_probe,
                     limitation='Protocol-only counterfactual; the visitor assertion remains semantically unsupported.'),
        work_relation=dict(original_error=relation_error, actual_findings=findings,
                           uncertain_relation_only=relation_probe,
                           limitation='Isolated plan_repair invariant; uncertain is a diagnostic value, not a semantic adjudication.'),
        decisions=dict(visitor=visitor, real_validator_accepted=True,
                       closing_case_keys=list(close_req['cases']), closing_states=close_raw['states'],
                       gisella_removed=True, visitor_not_rechecked=True),
    )
    review = dict(
        meeting_id='IB4005', result_sha256=frozen['result.json'], reference_sha256=frozen['reference.json'],
        policy='Post-run source-grounded semantic review requested by user; accepts bundled work and agreed personal commitments. Routing is separate from false content.',
        tasks=[
            dict(record_id='R3', verdict='TP', reference_hits=['T1', 'T2'],
                 reason='B requests figures, A accepts and promises to circulate those figures with the final plan; combined task covers both references.'),
            dict(record_id='R6', verdict='TP', reference_hits=[],
                 reason='A volunteers to switch with Bruno and C agrees. This supports the accepted personal arrangement, without inventing physical moving work.')],
        decision_changes=[dict(index=6, old='FP', new='supported_operational_decision', routing_issue=True,
                               reason='Saving and circulating the plan is explicitly agreed; no false content, though it duplicates the task column.')],
        retained_unsupported_decisions=[dict(index=5, reason='Final quoted roster names Agnes, not visitor one; keeping visitor space in general does not support this specific final roster.')],
        missing_decisions=[
            dict(reference='D3', cause='Extracted and reconciled, then deleted by open verdict with no required withdrawal evidence; later text is ambiguous.'),
            dict(reference='D7', cause='Proposal uses deictic that room and alternatives professor/student/visitor; final adoption is unclear from transcript alone.'),
            dict(reference='D10', cause='Explicit final Agnes/Marianne/David roster is visible but omitted; older visitor version survives.')],
        metrics=dict(
            tasks=dict(tp=2, fp=0, predictions=2, precision=1.0, reference_hits=2, reference=2, reference_recall=1.0),
            decision_content=dict(supported=8, unsupported=1, predictions=9, precision=8/9,
                                  routing_issues=1, reference_hits=7, reference=10, reference_recall=0.7)),
        limitations=['Post-hoc rubric revision, not a model improvement or a comparable rerun.',
                     'Original frozen references and strict scores are preserved.',
                     'No missing reference was counted as recalled solely because omission was reasonable.',
                     'Task references are non-exhaustive; R6 is source-supported outside the two reference tasks.'])
    OUT.mkdir(exist_ok=True)
    for name, value in [('offline-probes.json', probes), ('semantic-review.json', review)]:
        (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    assert frozen == {name: sha(RUN / name) for name in frozen}
    print(json.dumps(dict(status='passed', network_calls=0, unchanged_source_files=len(files),
                         unchanged_frozen_files=len(frozen), minutes_alias_mapping=mapping,
                         metrics=review['metrics']), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
