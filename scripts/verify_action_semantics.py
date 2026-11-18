"""Verify frozen semantic evaluation views and source/series boundaries."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from meeting_eval.inputs import digest
from scripts.review_action_semantics import read_jsonl, index_cases


def verify_dataset(data_dir):
    result, used_series, blind_series = {}, set(), set()
    for view in ('regression','context','blind'):
        folder = Path(data_dir)/view
        if not (folder/'manifest.json').exists():
            continue
        manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        if manifest['status'] != 'frozen':
            result[view] = {'status':manifest['status']}
            continue
        inputs, labels = read_jsonl(folder/'input.jsonl'), read_jsonl(folder/'labels.jsonl')
        if manifest.get('input_hash') != digest(inputs) or manifest.get('labels_hash') != digest(labels):
            raise ValueError('Dataset hash mismatch: '+view)
        cases = index_cases(inputs)
        event_ids = set()
        for label in labels:
            cid, eid = label['case_id'], label['event_id']
            if cid not in cases or eid in event_ids:
                raise ValueError('Invalid or duplicate reference event')
            event_ids.add(eid)
            case = cases[cid]
            source = {s['id']:s['text'] for s in case['segments']}
            if len(source) != len(case['segments']) or not set(label['evidence_ids']) <= source.keys():
                raise ValueError('Unknown or duplicate evidence')
            people = {p.get('person_ref') for p in case.get('participants',[])} | set(case.get('roster',{}))
            people |= {s.get('person_ref') for s in case['segments']}
            if label.get('owner_ref') is not None and label['owner_ref'] not in people:
                raise ValueError('Unknown reference owner')
            for spans in label.get('field_evidence',{}).values():
                for span in spans:
                    text = source.get(span['segment_id'])
                    start,end = span['start'],span['end']
                    if text is None or type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text) or text[start:end] != span['quote']:
                        raise ValueError('Invalid reference span')
        series = {c['series'] for c in inputs}
        (blind_series if view=='blind' else used_series).update(series)
        result[view] = dict(status='frozen',cases=len(cases),actions=sum(l['operation'] in ('create','candidate') for l in labels),series=sorted(series))
    if blind_series & used_series:
        raise ValueError('Blind series overlap: '+str(sorted(blind_series & used_series)))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir',type=Path,required=True)
    print(json.dumps(verify_dataset(p.parse_args().data_dir),ensure_ascii=False,indent=2))
