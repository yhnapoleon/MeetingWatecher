"""Compare fields on a fixed gold denominator, including missed actions as incorrect."""
import argparse
import csv
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_action_baseline import read_jsonl,write_json

FIELDS = ('operation','owner_kind','owner_ref','due_text','due_date')


def analyze(parents,out):
    with (ROOT/'data/mvp-v1/splits.csv').open(encoding='utf-8-sig',newline='') as f:
        dev = {r['case_id'] for r in csv.DictReader(f) if r['split']=='dev'}
    gold = {(r['case_id'],r['action_anchor']):r for r in read_jsonl(ROOT/'data/mvp-v1/labels.jsonl')
            if r['case_id'] in dev and r['operation'] in ('create','candidate')}
    runs = []
    for parent in parents:
        for p in sorted(parent.glob('*/scores.json')):
            report = json.loads(p.read_text(encoding='utf-8'))
            if report['excerpts']!=len(dev):
                continue
            prediction = {}
            for row in read_jsonl(p.parent/'predictions.jsonl'):
                for item in row['items']:
                    prediction.setdefault((row['case_id'],item['action_anchor']),item)
            assert len(gold)==report['action_anchors']['expected']
            assert len(gold.keys() & prediction.keys())==report['action_anchors']['hits']
            runs.append((p.parent,report,prediction))
    common = set(gold)
    for _,_,pred in runs:
        common &= pred.keys()
    rows = []
    for path,report,pred in runs:
        fixed = {f:sum(pred.get(k,{}).get(f,object())==g[f] for k,g in gold.items()) for f in FIELDS}
        matched = {f:sum(pred[k][f]==gold[k][f] for k in common) for f in FIELDS}
        evidence_hits = sum(len(set(g['evidence_ids']) & set(pred.get(k,{}).get('evidence_ids',[]))) for k,g in gold.items())
        evidence_expected = sum(len(g['evidence_ids']) for g in gold.values())
        rows.append(dict(run=path.name,strategy=path.name.rsplit('-r',1)[0],
            action_anchors=report['action_anchors'],fixed_correct=fixed,fixed_total=len(gold),
            common_correct=matched,common_total=len(common),
            evidence_hits=evidence_hits,evidence_expected=evidence_expected,errors=report['errors']))
    grouped = {}
    for strategy in dict.fromkeys(r['strategy'] for r in rows):
        group = [r for r in rows if r['strategy']==strategy]
        grouped[strategy] = dict(repeats=len(group),fixed_total=len(gold),
            mean_fixed_correct={f:statistics.mean(r['fixed_correct'][f] for r in group) for f in FIELDS},
            common_total=len(common),mean_common_correct={f:statistics.mean(r['common_correct'][f] for r in group) for f in FIELDS},
            mean_evidence_hits=statistics.mean(r['evidence_hits'] for r in group),evidence_expected=evidence_expected)
    result = dict(annotation_status='agent_labeled',common_keys=sorted(common),strategies=grouped,runs=rows)
    write_json(out,result)
    return grouped


if __name__=='__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('parents',type=Path,nargs='+')
    p.add_argument('--out',type=Path,required=True)
    a = p.parse_args()
    print(json.dumps(analyze(a.parents,a.out),ensure_ascii=False,indent=2))
