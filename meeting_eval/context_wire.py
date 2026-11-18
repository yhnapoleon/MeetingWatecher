"""Compact model transport; original source IDs outside, legacy aliases inside."""
import copy
import json
import re
from collections import Counter

from .context_protocol_v3 import evidence_catalog


def reference_field(key):return key=='evidence' or key.endswith('_evidence')


class ReferenceValidationError(ValueError):
    def __init__(self,issues):
        self.issues=copy.deepcopy(issues)
        super().__init__('Invalid evidence references: '+', '.join(
            '.'.join(map(str,i['path']))+' '+i['code']+
            (' '+repr(i['invalid'][:3])[:160] if i['code']=='reference_unknown' else '') for i in issues[:8]))

    def feedback(self,meeting):
        first=next((s['id'] for s in meeting['segments'] if s['text']),None)
        return dict(total_issues=len(self.issues),counts=dict(Counter(i['code'] for i in self.issues)),
            issues=[{k:v for k,v in i.items() if k in ('path','code','expected','actual_type')} for i in self.issues[:8]],
            example={'evidence':[first] if first else []},
            instruction='证据输出必须是原始segment_id字符串数组，不是对象数组，不是调整start/end。根据原文选择支持该字段的ID；保持其他含义和身份，完整满足输出契约。')


def wire_prompt(prompt,meeting):
    first=next((s['id'] for s in meeting['segments'] if s['text']),'segment_id')
    prompt=re.sub(r'(?<![A-Za-z0-9_])Q\d+(?![A-Za-z0-9_])',lambda _:first,prompt)
    prompt=prompt.replace('Q 编号','原始 segment_id').replace('Q编号','原始 segment_id').replace('Q ID','原始 segment_id')
    prompt=prompt.replace('evidence_catalog','meeting.segments')
    return (prompt+'\n输入 ledger/candidates 等上下文中的证据对象使用 start/end 表示原文字符区间，仅用于读取输入。'
        '输出的 evidence 及 *_evidence 必须是原始 segment_id 字符串数组，不得输出证据对象或 start/end。'
        '非空输出格式示例：'+json.dumps({'evidence':[first]},ensure_ascii=False)+
        '。ID只取 meeting.segments 的非空发言，不另编别名或按尾号拼编号。原文只在 meeting 中提供一次。')


def wire_request(payload):
    meeting=payload['meeting'];catalog=evidence_catalog(meeting)
    aliases={q:s['segment_id'] for q,s in catalog.items()}
    texts={s['id']:s['text'] for s in meeting['segments']}
    def schema(node):
        if isinstance(node,list):return [schema(v) for v in node]
        if not isinstance(node,dict):return copy.deepcopy(node)
        out={k:schema(v) for k,v in node.items()}
        if isinstance(out.get('example'),str) and out['example'] in aliases:out['example']=aliases[out['example']]
        values=out.get('enum')
        # Membership is checked locally. Repeating hundreds of IDs in every
        # check field expands the request without adding source information.
        if values and all(isinstance(v,str) and v in aliases for v in values):out.pop('enum')
        def examples(v):
            if isinstance(v,str):return aliases.get(v,v)
            if isinstance(v,list):return [examples(x) for x in v]
            if isinstance(v,dict):return {k:examples(x) for k,x in v.items()}
            return v
        if 'example' in out:out['example']=examples(out['example'])
        return out
    def visit(value,key=''):
        if isinstance(value,list):
            if reference_field(key):return [aliases.get(v,v) if isinstance(v,str) else visit(v) for v in value]
            return [visit(v) for v in value]
        if not isinstance(value,dict):return copy.deepcopy(value)
        if 'segment_id' in value and 'quote' in value and value['segment_id'] in texts:
            text=texts[value['segment_id']];quote=value['quote']
            start=value.get('start');end=value.get('end')
            if start is None and end is None:
                if quote==text:start,end=0,len(text)
                elif quote and text.count(quote)==1:start=text.index(quote);end=start+len(quote)
                else:raise ValueError('Evidence requires unambiguous source offsets')
            if (not isinstance(start,int) or not isinstance(end,int) or not 0<=start<=end<=len(text)
                    or text[start:end]!=quote):raise ValueError('Evidence source offsets do not match quote')
            return {**{k:visit(v,k) for k,v in value.items() if k!='quote'},'start':start,'end':end}
        return {k:visit(v,k) for k,v in value.items()}
    result={k:(schema(v) if k=='output_schema' else copy.deepcopy(v) if k=='meeting' else visit(v,k))
            for k,v in payload.items() if k not in ('evidence_catalog','output_contract')}
    return result


def reference_issues(raw,meeting):
    ids={s['id'] for s in meeting['segments'] if s['text']};issues=[]
    def typename(v):
        if isinstance(v,list):return 'array['+','.join(sorted({typename(x) for x in v}))+']'
        if isinstance(v,dict):return 'object'
        if isinstance(v,str):return 'string'
        if v is None:return 'null'
        return type(v).__name__
    def add(path,value,code,reason):
        issues.append(dict(path=path,invalid=value,code=code,reason=reason,
            expected='array[string: original segment_id]',actual_type=typename(value)))
    def visit(value,path):
        if isinstance(value,dict):
            for key,v in value.items():
                if reference_field(key):
                    if not isinstance(v,list) or any(not isinstance(x,str) for x in v):
                        add(path+[key],v,'reference_type','Use a string ID array, not evidence objects')
                    elif any(x not in ids for x in v):
                        add(path+[key],v,'reference_unknown','Use original nonempty segment IDs')
                    elif not v and ((len(path)==2 and path[0]=='records') or
                                    (len(path)==3 and path[0]=='events' and path[-1]=='work')):
                        add(path+[key],v,'reference_empty','Grounded record/work requires evidence')
                else:visit(v,path+[key])
        elif isinstance(value,list):
            for i,v in enumerate(value):visit(v,path+[i])
    visit(raw,[]);return issues


def decode_output(raw,meeting):
    issues=reference_issues(raw,meeting)
    if issues:raise ReferenceValidationError(issues)
    aliases={s['segment_id']:q for q,s in evidence_catalog(meeting).items()}
    def visit(value):
        if isinstance(value,list):return [visit(v) for v in value]
        if isinstance(value,dict):
            return {k:[aliases[q] for q in v] if reference_field(k) else visit(v) for k,v in value.items()}
        return copy.deepcopy(value)
    return visit(raw)
