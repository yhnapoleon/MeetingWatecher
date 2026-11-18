"""Prepare a complete non-scenario AMI meeting from original segment/word XML."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
NITE='{http://nite.sourceforge.net/}'


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def prepare(mid,out):
    out.mkdir(parents=True,exist_ok=False)
    archive=ROOT/'data/mvp-v1/raw/ami_public_manual_1.6.2.zip'
    coverage={}
    segments=[]
    participants=[]
    with zipfile.ZipFile(archive) as z:
        metadata=next(m for m in ET.fromstring(z.read('corpusResources/meetings.xml')) if m.get('observation')==mid)
        for speaker in metadata:
            channel=speaker.get('nxt_agent')
            person=dict(speaker=channel,speaker_name='Speaker '+channel,person_ref=speaker.get('global_name'))
            participants.append(person)
            prefix=mid+'.'+channel
            words=list(ET.fromstring(z.read('words/'+prefix+'.words.xml')))
            indices={w.get(NITE+'id'):i for i,w in enumerate(words)}
            covered=set()
            for segment in ET.fromstring(z.read('segments/'+prefix+'.segments.xml')):
                selected=[]
                for ref in segment.findall(NITE+'child'):
                    ids=re.findall(r'id\(([^)]+)\)',ref.get('href'))
                    selected.extend(words[indices[ids[0]]:indices[ids[-1]]+1])
                spoken=[w for w in selected if w.tag=='w' and w.text]
                if not spoken:continue
                covered.update(w.get(NITE+'id') for w in spoken)
                segments.append(dict(id=segment.get(NITE+'id'),**person,
                    text=' '.join(w.text for w in spoken),start_ms=round(float(spoken[0].get('starttime'))*1000),
                    end_ms=round(float(spoken[-1].get('endtime'))*1000)))
            all_words={w.get(NITE+'id') for w in words if w.tag=='w' and w.text}
            recovered=[w for w in words if w.tag=='w' and w.text and w.get(NITE+'id') not in covered and w.get('punc')!='true']
            for w in recovered:
                segments.append(dict(id=w.get(NITE+'id'),**person,text=w.text,
                    start_ms=round(float(w.get('starttime'))*1000),end_ms=round(float(w.get('endtime'))*1000)))
                covered.add(w.get(NITE+'id'))
            punctuation={w.get(NITE+'id') for w in words if w.get('punc')=='true'}-covered
            assert covered|punctuation==all_words
            coverage[channel]=dict(source_tokens=len(all_words),covered_tokens=len(covered),
                orphan_punctuation=len(punctuation),recovered_word_ids=[w.get(NITE+'id') for w in recovered],lexical_coverage=1.0)
        reference=z.read('abstractive/'+mid+'.abssumm.xml')
        (out/'corpus-reference.xml').write_bytes(reference)
    segments.sort(key=lambda s:(s['start_ms'],s['speaker'],s['id']))
    assert len({s['id'] for s in segments})==len(segments)
    meeting=dict(case_id='FULL-'+mid,meeting_id=mid,series='AMI-office-'+mid,language='en',source='AMI_1.6.2',
                 participants=participants,account_map={},segments=segments)
    write(out/'input.json',meeting)
    (out/'完整会议原文.txt').write_text('\n\n'.join(f"{i}. [{s['start_ms']/1000:.2f}s] {s['speaker']} ({s['id']})\n{s['text']}"
        for i,s in enumerate(segments,1)),encoding='utf8')
    settings=json.loads((ROOT/'runs/2026-11-18-full-v19-retest/ES2002b/inference.json').read_text(encoding='utf8'))
    write(out/'inference.json',settings)
    rubric=json.loads((ROOT/'runs/2026-11-18-full-v19-retest/rubric-before-run.json').read_text(encoding='utf8'))
    write(out/'rubric-before-run.json',dict(task_scope=rubric['task_definition']['scope'],
        task_prediction_unit=rubric['task_definition']['prediction_unit'],
        decision_scope=rubric['decision_definition']['scope'],
        reference_scope='Freeze original AMI action and decision sentences before model inference; report additional supported predictions separately.',
        inference=settings,technical_retry_policy='Existing bounded stage recovery; at most one explicit Service retry batch if required. Preserve first attempt and report separately.',
        no_tuning='Keep production code, prompts, model and inference equal to the two-meeting v19 retest. No semantic rerun to improve the score.'))
    refs=ET.fromstring(reference)
    write(out/'reference.json',{kind:[dict(id=('T' if kind=='actions' else 'D')+str(i),
        corpus_id=s.get(NITE+'id'),text=s.text) for i,s in enumerate(refs.find(kind),1)] for kind in ('actions','decisions')})
    write(out/'manifest.json',dict(meeting_id=mid,scope='Complete Service, independent empty history, fresh model outputs',
        original_metadata=metadata.attrib,segments=len(segments),word_coverage=coverage,inference=settings,
        decision_review=True,source_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        input_sha256=hashlib.sha256((out/'input.json').read_bytes()).hexdigest(),
        prior_exposure='No prior local experiment/document/model-output occurrence found outside raw corpus. Related office meeting IB4003 has been diagnosed; not a series-disjoint domain holdout.',
        selection='First alphabetically among unused annotated non-scenario AMI meetings with at least 2 action and 2 decision references, under 45 minutes. Selection precedes model output.'))
    with zipfile.ZipFile(out/'source.zip','w',zipfile.ZIP_DEFLATED) as z:
        for directory in ('meeting_eval','prompts','scripts'):
            for p in (ROOT/directory).rglob('*'):
                if p.is_file() and '__pycache__' not in p.parts:z.write(p,p.relative_to(ROOT))
        for p in (Path(__file__),Path(__file__).with_name('run.py')):z.write(p,p.relative_to(ROOT))
    print(json.dumps(dict(meeting_id=mid,segments=len(segments),participants=participants,coverage=coverage),ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('meeting_id')
    parser.add_argument('out',type=Path)
    args=parser.parse_args()
    prepare(args.meeting_id,args.out)
