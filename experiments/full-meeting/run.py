"""One complete AMI meeting through the normal Service; no cached model output."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import zipfile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from meeting_eval.extract import Extractor
from meeting_eval.service import Service
from meeting_eval.store import Store

NITE = '{http://nite.sourceforge.net/}'
MID = 'ES2002a'
ACTOR = 'evaluator'
AT = '2026-11-17T12:00:00+08:00'


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def prepare(out):
    out.mkdir(parents=True, exist_ok=True)
    assert not any(out.iterdir()), 'Preparation requires an empty output directory'
    archive = ROOT / 'data/mvp-v1/raw/ami_public_manual_1.6.2.zip'
    cases = [json.loads(s) for s in (ROOT / 'data/mvp-v1/input.jsonl').read_text(encoding='utf8').splitlines()]
    source = next(c for c in cases if c['meeting_id'] == MID)
    meeting = {k:source[k] for k in ('meeting_id','series','language','source','participants')}
    meeting.update(case_id='FULL-'+MID, account_map={}, segments=[])
    counts = {}
    with zipfile.ZipFile(archive) as z:
        metadata = next(m for m in ET.fromstring(z.read('corpusResources/meetings.xml')) if m.get('observation') == MID)
        # Preserve the corpus's ambiguous two-digit date as provenance, not a guessed calendar anchor.
        for person in meeting['participants']:
            channel = MID + '.' + person['speaker']
            words = list(ET.fromstring(z.read('words/'+channel+'.words.xml')))
            positions = {w.get(NITE+'id'):i for i,w in enumerate(words)}
            all_spoken = {w.get(NITE+'id') for w in words if w.tag == 'w' and w.text}
            covered = set()
            for act in ET.fromstring(z.read('dialogueActs/'+channel+'.dialog-act.xml')):
                selected = []
                for ref in act.findall(NITE+'child'):
                    ids = re.findall(r'id\(([^)]+)\)', ref.get('href'))
                    selected.extend(words[positions[ids[0]]:positions[ids[-1]]+1])
                spoken = [w for w in selected if w.tag == 'w' and w.text]
                if not spoken:
                    continue
                covered.update(w.get(NITE+'id') for w in spoken)
                meeting['segments'].append(dict(id=act.get(NITE+'id'), **person,
                    text=' '.join(w.text for w in spoken),
                    start_ms=round(float(spoken[0].get('starttime'))*1000),
                    end_ms=round(float(spoken[-1].get('endtime'))*1000)))
            # AMI dialogue-act annotations can omit a spoken word (ES2002b: "um").
            # Retain the original word ID and timing instead of dropping source speech.
            recovered = [w for w in words if w.tag == 'w' and w.text
                         and w.get(NITE+'id') not in covered and w.get('punc') != 'true']
            for word in recovered:
                meeting['segments'].append(dict(id=word.get(NITE+'id'), **person,
                    text=word.text, start_ms=round(float(word.get('starttime'))*1000),
                    end_ms=round(float(word.get('endtime'))*1000)))
                covered.add(word.get(NITE+'id'))
            orphan_punctuation = {w.get(NITE+'id') for w in words if w.get('punc') == 'true'} - covered
            assert covered | orphan_punctuation == all_spoken, (channel, 'Missing source words')
            counts[channel] = dict(source_word_xml_tokens=len(all_spoken), covered_tokens=len(covered),
                unassigned_punctuation_tokens=len(orphan_punctuation), lexical_word_coverage='100%',
                recovered_word_ids=[w.get(NITE+'id') for w in recovered])
        (out/'corpus-reference.xml').write_bytes(z.read('abstractive/'+MID+'.abssumm.xml'))
    meeting['segments'].sort(key=lambda s:(s['start_ms'], s['speaker'], s['id']))
    assert len({s['id'] for s in meeting['segments']}) == len(meeting['segments'])
    write(out/'input.json', meeting)
    (out/'完整会议原文.txt').write_text('\n\n'.join(
        f"[{s['start_ms']/1000:.2f}s] {s['speaker_name']} ({s['id']})\n{s['text']}" for s in meeting['segments']), encoding='utf8')
    settings = json.loads((ROOT/'experiments/action-context/compact-check.json').read_text())
    settings['interpret_work'].update(reasoning_effort='low', max_tokens=32768)
    write(out/'inference.json', settings)
    manifest = dict(meeting_id=MID, scope='Complete source transcript; full Service; fresh inference; one meeting',
        source_archive=str(archive.relative_to(ROOT)), source_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        original_date=metadata.get('dateOnly'), segments=len(meeting['segments']),
        transcript_start_seconds=min(s['start_ms'] for s in meeting['segments'])/1000,
        transcript_end_seconds=max(s['end_ms'] for s in meeting['segments'])/1000,
        word_coverage=counts, task_reference='corpus-reference.xml; scoring only, never model input',
        prior_exposure='Selected excerpts C01-C03 have been used previously; this is a full-workflow case study, not a blind benchmark',
        account_scope='Local SQLite; no live Feishu accounts mapped', inference=settings,
        retry_policy='Existing bounded per-stage recovery only; no whole-meeting rerun')
    write(out/'manifest.json', manifest)
    with zipfile.ZipFile(out/'source.zip','w',zipfile.ZIP_DEFLATED) as z:
        for directory in ('meeting_eval','prompts','scripts'):
            for p in (ROOT/directory).rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts:
                    z.write(p, p.relative_to(ROOT))
        z.write(Path(__file__), Path(__file__).relative_to(ROOT))
    return manifest


def run(out, review_decisions=False):
    assert not (out/'state.sqlite').exists(), 'Fresh run only'
    meeting = json.loads((out/'input.json').read_text(encoding='utf8'))
    settings = json.loads((out/'inference.json').read_text())
    ex = Extractor(ROOT.parent.parent/'meeting-agent/.env',out/'model','context-v5',inference_config=settings,
                   review_decisions=review_decisions)
    write(out/'config.json',ex.config)
    started=time.perf_counter()
    store=Store(out/'state.sqlite')
    try:
        svc=Service(store,ex)
        result=svc.process(meeting,ACTOR,AT)
        write(out/'result.json',result)
        sid=result['source_id']
        minutes=svc.minutes(sid,ACTOR)
        requirements=svc.requirements(sid,ACTOR)
        (out/'minutes.md').write_text(minutes,encoding='utf8')
        write(out/'requirements.json',requirements)
        write(out/'tasks.json',store.tasks())
        write(out/'collected-issues.json',svc.collected_issues(sid,ACTOR))
        stored_result=svc.result(sid)
        call_count=len(list((out/'model').rglob('meta.json')))
        repeat_checked = result['status']=='processed'
        if repeat_checked:
            repeat=svc.process(meeting,ACTOR,AT)
            assert repeat['source_id']==sid and svc.result(sid)==stored_result
            assert len(list((out/'model').rglob('meta.json')))==call_count
    finally:
        store.close()
    reopened=Store(out/'state.sqlite')
    try:
        reader=Service(reopened)
        assert reader.result(sid)==stored_result
        assert reader.minutes(sid,ACTOR)==minutes
        assert reader.requirements(sid,ACTOR)==requirements
    finally:
        reopened.close()
    meta=[json.loads(p.read_text()) for p in (out/'model').rglob('meta.json')]
    extraction=result['extraction']
    summary=dict(status=result['status'],seconds=round(time.perf_counter()-started,2),
        calls=len(meta),tokens=sum((m.get('usage') or {}).get('total_tokens',0) for m in meta),
        counts={k:len(extraction.get(k,[])) for k in ('items','facts','unresolved','decisions','updates')},
        errors=extraction.get('_errors',[]),repeat_no_model_calls=repeat_checked,reopen_consistent=True)
    write(out/'summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--review-decisions',action='store_true')
    args=parser.parse_args()
    if args.live:
        run(args.out,review_decisions=args.review_decisions)
    else:
        print(json.dumps(prepare(args.out),ensure_ascii=False))
