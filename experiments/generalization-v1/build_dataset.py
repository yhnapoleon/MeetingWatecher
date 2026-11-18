"""Deterministic source-first sampling; never reads model predictions."""
import hashlib
import json
from pathlib import Path
import re
import shutil
from urllib.request import Request, urlopen
from concurrent.futures import ThreadPoolExecutor
import tiktoken

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'data/generalization-v1'
RAW = OUT/'raw'
QREV = '83d7768c1f2b4dfeb091385d3dc7e239b8e5bb7e'
VREV = '8e51d72e4e6f3af4074fd5b260b6f6d2e75e86c7'
SEED = 'generalization-v1-20261117'
ENC = tiktoken.get_encoding('cl100k_base')


def read(p): return json.loads(p.read_text(encoding='utf8'))
def sha(b): return hashlib.sha256(b).hexdigest()
def write(p, x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def rank(s): return sha((SEED+':'+s).encode())


def fetch(path):
    dest=RAW/'qmsum'/Path(path).name;dest.parent.mkdir(parents=True,exist_ok=True)
    url=f'https://raw.githubusercontent.com/Yale-LILY/QMSum/{QREV}/{path}'
    if not dest.exists():
        with urlopen(Request(url,headers={'User-Agent':'meeting-eval-research'}),timeout=60) as r:
            dest.write_bytes(r.read())
    return dict(path=dest.relative_to(ROOT).as_posix(),url=url,sha256=sha(dest.read_bytes()),revision=QREV)


def used_vcsum():
    used=set()
    # All earlier source inputs, not only the latest 115. Raw candidate caches are
    # excluded: loading a public corpus is not equivalent to evaluating it.
    paths=list((ROOT/'data').glob('*/input*.jsonl'))+list((ROOT/'runs').rglob('manifest.json'))
    for p in paths:
        if 'generalization-v1' in str(p):continue
        text=p.read_text(encoding='utf8')
        used.update(re.findall(r'vc\.(\d+)\.',text))
    used.add('65')  # original pilot V65
    return used


def select_suffix(turns, boundaries, target):
    candidates=[]
    for start in sorted(set([0]+boundaries)):
        if start>=len(turns):continue
        count=len(ENC.encode('\n'.join(t['text'] for t in turns[start:])))
        if count>=target:candidates.append((count,start))
    if candidates:
        count,start=min(candidates)
    else:
        start=0;count=len(ENC.encode('\n'.join(t['text'] for t in turns)))
    return start,count


def main():
    OUT.mkdir(exist_ok=True);RAW.mkdir(exist_ok=True)
    if (OUT/'natural-inputs.json').exists():raise FileExistsError('Do not resample existing inputs')
    tree=read(RAW/'qmsum-tree.json')['tree']
    selected=[]
    for domain,prefix,n,split in [('Academic','Bro',3,'pilot'),('Committee','covid_',3,'pilot'),
                                  ('Academic','Bed',8,'test'),('Committee','education_',8,'test')]:
        paths=[x['path'] for x in tree if x['path'].startswith(f'data/{domain}/all/{prefix}') and x['path'].endswith('.json')]
        assert len(paths)>=n,(domain,prefix,len(paths))
        selected.extend(dict(source='QMSum',domain=domain,series=prefix,split=split,path=p) for p in sorted(paths,key=rank)[:n])
    downloads=[x['path'] for x in selected]+['LICENSE','README.md']
    with ThreadPoolExecutor(max_workers=4) as pool:
        provenance=list(pool.map(fetch,downloads))
    vcpath=ROOT/'data/mvp-v1/raw/vcsum_overall_context.txt'
    vcopy=RAW/'vcsum_overall_context.txt';shutil.copy2(vcpath,vcopy)
    shutil.copy2(ROOT/'data/mvp-v1/raw/vcsum_LICENSE',RAW/'vcsum_LICENSE')
    provenance.append(dict(path=vcopy.relative_to(ROOT).as_posix(),url=f'https://raw.githubusercontent.com/hahahawu/VCSum/{VREV}/vcsum_data/overall_context.txt',revision=VREV,sha256=sha(vcopy.read_bytes())))
    vc=[json.loads(s) for s in vcopy.read_text(encoding='utf8').splitlines() if s.strip()]
    excluded=used_vcsum();eligible=sorted([x for x in vc if str(x['id']) not in excluded],key=lambda x:rank('VCSum:'+str(x['id'])))
    assert len(eligible)>=30
    vc_selected=[dict(source='VCSum',domain='unclassified',series='VCSum:'+str(x['av_num']),split='pilot' if i<6 else 'test',raw=x) for i,x in enumerate(eligible[:30])]
    all_sources=vc_selected+selected
    counters={};cases=[]
    lengths={'zh':[1200]*6+[4000]*12+[8500]*6,'en':[1200]*4+[4000]*6+[8500]*6}
    perlang={'zh':0,'en':0}
    for src in all_sources:
        if src['source']=='VCSum':
            raw=src['raw'];mid=str(raw['id']);language='zh'
            turns=[dict(id=f'vc.{mid}.{i}',speaker=str(raw['speaker'][i]),text='\n'.join(lines)) for i,lines in enumerate(raw['context'])]
            boundaries=[int(i)+1 for i in raw['eos_index']]
            original=vcopy.relative_to(ROOT).as_posix();original_hash=sha(json.dumps(raw,ensure_ascii=False,sort_keys=True).encode())
            url=provenance[-1]['url'];source_id=str(raw['av_num'])
        else:
            raw=read(RAW/'qmsum'/Path(src['path']).name);mid=Path(src['path']).stem;language='en'
            turns=[dict(id=f'qm.{mid}.{i}',speaker=t['speaker'],text=t['content']) for i,t in enumerate(raw['meeting_transcripts'])]
            boundaries=[int(span[0]) for t in raw['topic_list'] for span in t['relevant_text_span']]
            original=(RAW/'qmsum'/Path(src['path']).name).relative_to(ROOT).as_posix();original_hash=sha((ROOT/original).read_bytes())
            url=f'https://raw.githubusercontent.com/Yale-LILY/QMSum/{QREV}/{src["path"]}';source_id=mid
        key=src['split'];counters[key]=counters.get(key,0)+1
        cid=('GP' if key=='pilot' else 'GN')+str(counters[key]).zfill(2)
        if key=='pilot':target=600
        else:target=lengths[language][perlang[language]];perlang[language]+=1
        start,count=select_suffix(turns,boundaries,target)
        kept=turns[start:]
        # Speaker IDs are corpus references only, never real platform accounts.
        speakers=list(dict.fromkeys(t['speaker'] for t in turns))
        refs={s:src['source'].lower()+':'+mid+':'+str(i) for i,s in enumerate(speakers)}
        participants=[dict(speaker=s,speaker_name=s,person_ref=refs[s]) for s in speakers if any(t['speaker']==s for t in kept)]
        meeting=dict(meeting_id=cid,series=src['series'],source=src['source'],source_meeting_id=mid,
                     participants=participants,audience=['host'],segments=[dict(**t,start_ms=None,end_ms=None) for t in kept])
        cases.append(dict(case_id=cid,split=key,kind='natural',language=language,domain=src['domain'],
                          source=src['source'],source_meeting=mid,source_recording=source_id,series=src['series'],
                          original_file=original,original_hash=original_hash,source_url=url,
                          range=dict(first_turn=start,last_turn=len(turns)-1,original_turns=len(turns)),
                          selection='Seed-ranked unseen meeting; continuous topic-boundary suffix through original end; no task-keyword or prediction selection.',
                          target_tokens=target,measured_tokens=count,tokenizer='cl100k_base reference tokenizer (not provider-native)',
                          text_hash=sha('\n'.join(t['text'] for t in kept).encode()),meeting=meeting))
    write(OUT/'natural-inputs.json',cases)
    write(OUT/'provenance.json',dict(seed=SEED,files=provenance,excluded_vcsum_meetings=sorted(excluded),
                                  sampling='30 distinct VCSum recordings and 22 QMSum meetings; 12 pilot, 40 test.',
                                  license_notes={'VCSum':'Author repository MIT license retained; original transcript provenance preserved.',
                                                 'QMSum':'Repository MIT retained; Academic transcripts originate from ICSI (CC BY 4.0 per AMI/ICSI site); Committee original-source terms must be recorded separately; no redistribution package created.'}))
    for c in cases:
        path=OUT/'annotation-inputs'/f'{c["case_id"]}.txt';path.parent.mkdir(exist_ok=True)
        path.write_text(f'{c["case_id"]} {c["source"]} {c["source_meeting"]} {c["measured_tokens"]} reference tokens\n'+
                        '\n\n'.join(f'[{t["id"]}] {t["speaker"]}\n{t["text"]}' for t in c['meeting']['segments']),encoding='utf8')
    print(json.dumps([dict(id=c['case_id'],source=c['source'],meeting=c['source_meeting'],tokens=c['measured_tokens'],turns=len(c['meeting']['segments'])) for c in cases],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
