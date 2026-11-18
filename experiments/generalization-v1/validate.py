"""Dataset/source/label preflight. No model calls."""
import hashlib
import json
from pathlib import Path
from collections import Counter
from annotate import validate as validate_label

ROOT=Path(__file__).resolve().parents[2];DATA=ROOT/'data/generalization-v1'
def read(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def input_job(case):
    # The only model-facing object comes from raw input; gold and corpus summaries
    # are never copied. Keep this whitelist independent of the annotation schema.
    allowed={'meeting_id','series','source','source_meeting_id','participants','audience','segments','speaker_map'}
    meeting={k:v for k,v in case['meeting'].items() if k in allowed}
    return dict(id=case['case_id'],group=case['kind'],meeting=meeting,actor='host',tasks=[])

def validate(require_labels=True):
    cases=read(DATA/'natural-inputs.json')+read(DATA/'control-inputs.json')
    ids=[c['case_id'] for c in cases];assert len(ids)==72 and len(set(ids))==72
    natural=[c for c in cases if c['kind']=='natural'];formal=[c for c in cases if c['split']=='test']
    assert len(formal)==60 and len(natural)==52
    assert Counter(c['language'] for c in formal if c['kind']=='natural')=={'zh':24,'en':16}
    pilot=[c for c in natural if c['split']=='pilot'];test=[c for c in natural if c['split']=='test']
    assert {c['series'] for c in pilot}.isdisjoint(c['series'] for c in test)
    assert len({(c['source'],c['source_meeting']) for c in natural})==52
    original_vc={str(r['id']):r for r in [json.loads(s) for s in (DATA/'raw/vcsum_overall_context.txt').read_text(encoding='utf8').splitlines()]}
    provenance=read(DATA/'provenance.json')
    for source in provenance['files']:assert sha(ROOT/source['path'])==source['sha256'],('Raw source changed',source['path'])
    for c in natural:
        if c['source']=='VCSum':
            raw=original_vc[c['source_meeting']]
            original=[(str(raw['speaker'][i]),'\n'.join(lines)) for i,lines in enumerate(raw['context'])]
            assert hashlib.sha256(json.dumps(raw,ensure_ascii=False,sort_keys=True).encode()).hexdigest()==c['original_hash']
        else:
            path=ROOT/c['original_file'];assert sha(path)==c['original_hash']
            original=[(x['speaker'],x['content']) for x in read(path)['meeting_transcripts']]
        start,end=c['range']['first_turn'],c['range']['last_turn']
        assert end==len(original)-1
        assert [(s['speaker'],s['text']) for s in c['meeting']['segments']]==original[start:end+1]
    from build_dataset import used_vcsum
    assert used_vcsum().isdisjoint(c['source_meeting'] for c in natural if c['source']=='VCSum')
    from meeting_eval.inputs import normalize
    for c in cases:normalize(input_job(c)['meeting'],'host')
    if require_labels:
        labels=read(DATA/'labels.json');assert set(ids)=={l['case_id'] for l in labels} and len(labels)==72
        byid={c['case_id']:c for c in cases}
        for label in labels:validate_label(byid[label['case_id']],label)
    return dict(cases=72,formal=60,natural_formal=40,control_formal=20,pilot=12,source_roundtrip=True,unique_source_meetings=52,labels_checked=require_labels)

if __name__=='__main__':print(json.dumps(validate(),ensure_ascii=False,indent=2))
