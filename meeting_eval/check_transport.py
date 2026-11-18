"""Recover only unambiguous v5 check containers; never invent semantic values."""
import copy
import json
import re

from .context_protocol_v4 import closed_validate
from .inputs import digest

ROOT_FIELDS={'checks','coverage_findings','disposition_checks','issue_checks'}
TOKEN=re.compile(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null|[{}\[\],:]')


def unique_json(text):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:raise ValueError('Duplicate JSON key: '+key)
            out[key]=value
        return out
    return json.loads(text,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Invalid JSON constant')))


def normalize_check_output(raw_text,contract):
    if not isinstance(raw_text,str):return None
    root=contract.get('properties',{})
    if 'record_checks' not in root:return None
    candidates=[]
    try:
        original=unique_json(raw_text)
    except json.JSONDecodeError:
        # Only one missing object closer immediately before a known protocol field.
        tokens=[];pos=0
        while pos<len(raw_text):
            if raw_text[pos].isspace():pos+=1;continue
            match=TOKEN.match(raw_text,pos)
            if not match:return None
            tokens.append((match.group(),pos));pos=match.end()
        for i,(token,start) in enumerate(tokens):
            if not token.startswith('"') or i==0 or i+1>=len(tokens):continue
            if json.loads(token) not in ROOT_FIELDS & set(root):continue
            if tokens[i-1][0]!=',' or tokens[i+1][0]!=':':continue
            offset=tokens[i-1][1]
            try:value=unique_json(raw_text[:offset]+'}'+raw_text[offset:])
            except ValueError:continue
            candidates.append((value,dict(rule='close_record_checks',insert_at=offset,text='}')))
    except ValueError:return None  # Duplicate keys are never repaired.
    else:
        if not isinstance(original,dict):return None
        try:closed_validate(original,contract)
        except ValueError:pass
        else:return None
        records=original.get('record_checks')
        if not isinstance(records,dict):return None
        moved=ROOT_FIELDS & set(root) & set(records)
        record_ids=set(root['record_checks'].get('properties',{}))
        if not moved or moved & (set(original)|record_ids):return None
        value=copy.deepcopy(original)
        for key in records:
            if key in moved:value[key]=value['record_checks'].pop(key)
        candidates.append((value,dict(rule='restore_protocol_roots',fields=sorted(moved))))
    valid={}
    for value,edit in candidates:
        try:closed_validate(value,contract)
        except (ValueError,TypeError,KeyError):continue
        valid[digest(value)]=(value,edit)
    if len(valid)!=1:return None
    after,(value,edit)=next(iter(valid.items()))
    return dict(value=value,normalization=dict(before_hash=digest(raw_text),after_hash=after,edit=edit,version=1))
