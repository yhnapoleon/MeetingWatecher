"""Copy recorded upstream calls for a normal-entry checker-only experiment."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from meeting_eval.inputs import digest
from scripts.run_action_baseline import write_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():raise ValueError('Use a new output directory')
    (a.out/'model').mkdir(parents=True)
    imported=[]
    for folder in (a.source/'model').iterdir():
        meta=folder/'meta.json'
        if not meta.exists():continue
        data=json.loads(meta.read_text(encoding='utf-8'))
        if data['stage']=='check_work':continue
        shutil.copytree(folder,a.out/'model'/folder.name)
        for m in folder.rglob('meta.json'):
            request=m.with_name('request.json')
            response=m.with_name('response.json')
            imported.append(dict(path=str(m.relative_to(a.source)),
                request_hash=digest(json.loads(request.read_text(encoding='utf-8'))),
                response_hash=digest(json.loads(response.read_text(encoding='utf-8'))) if response.exists() else None,
                meta=json.loads(m.read_text(encoding='utf-8'))))
    write_json(a.out/'cache-provenance.json',dict(source=str(a.source.resolve()),
        mode='checker_only_frozen_upstream_not_independent_round',imported=imported))
    print(f'Seeded {len(imported)} recorded upstream calls; no model request made')


if __name__=='__main__':main()
