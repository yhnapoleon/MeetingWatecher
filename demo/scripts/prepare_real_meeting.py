"""Reproducible AMI excerpt. Source words are annotations, never labelled as ASR."""
import json, re, subprocess, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT.parent / 'data/mvp-v1/raw'
START, END = 1775, 2165
OUT = ROOT / 'public'
BUILD = ROOT / '.audio-build'
BUILD.mkdir(exist_ok=True)

def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def run(*args):
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', *map(str, args)], check=True)

run('-i', RAW/'ES2002b.Mix-Headset.rm', '-ss', START, '-t', END-START,
    '-ac', 1, '-ar', 16000, BUILD/'ami.wav')
run('-i', BUILD/'ami.wav', '-c:a', 'libmp3lame', '-b:a', '64k', OUT/'audio/ami-es2002b.mp3')
(OUT/'video').mkdir(exist_ok=True)
run('-i', RAW/'ES2002b.Corner.rm', '-ss', START, '-t', END-START,
    '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', 24, '-pix_fmt', 'yuv420p',
    '-movflags', '+faststart', OUT/'video/ami-es2002b.mp4')

z = zipfile.ZipFile(RAW/'ami_public_manual_1.6.2.zip')
segments=[]
for who in 'ABCD':
    words=[]
    for w in ET.fromstring(z.read(f'words/ES2002b.{who}.words.xml')):
        if w.tag != 'w' or not w.get('starttime') or not w.text: continue
        a,b=float(w.get('starttime')),float(w.get('endtime'))
        if a<START or b>END: continue
        words.append({'start':round((a-START)*1000),'end':round((b-START)*1000),
                      'text':w.text.replace('_','')})
    group=[]
    def flush():
        if not group:return
        text=' '.join(w['text'] for w in group)
        text=re.sub(r'\s+([.,?!:;])',r'\1',text)
        segments.append({'id':f'{who}-{len(segments)}','speaker':who,'start':group[0]['start'],
                         'end':max(group[-1]['end'],group[0]['start']+1),'text':text,
                         'words':list(group)})
        group.clear()
    for w in words:
        if group and (w['start']-group[-1]['end']>900 or w['end']-group[0]['start']>6500):flush()
        group.append(w)
        if w['text'] in ['.','?','!']:flush()
    flush()
segments.sort(key=lambda s:s['start'])

def evidence(a,b,who=None):
    matches=[s['id'] for s in segments if s['start']>=(a-START)*1000 and s['end']<=(b-START)*1000 and (not who or s['speaker']==who)]
    assert matches,(a,b,who)
    return matches

nodes=[]
def node(at, nid, title, body, status, kind='point', parent=None, refs=None):
    nodes.append({'at':round((at-START)*1000),'node':{'id':nid,'kind':kind,'title':title,'body':body,
        'status':status,'parent':parent,'evidence':refs or []}})

node(1775,'root','遥控器功能设计','从功能范围到可执行分工','discussing','root')
node(1823,'power','使用常规电池','充电底座会增加组件、成本与使用复杂度','confirmed','point','root',evidence(1776,1823))
node(1858,'audience','15–35 岁用户','目标人群得到再次确认','confirmed','point','root',evidence(1835,1858))
node(1886,'scope','基础功能优先','开关、换台、音量、数字键，补充静音','confirmed','point','root',evidence(1860,1886))
node(1918,'advanced','高级功能如何保留？','考虑放在盖板下；具体功能尚待细化','open','point','root',evidence(1887,1918))
node(1968,'grouping','按用户感知分为三类','David 提议：声音、画面、设备；方便理解与组件划分','proposed','root',None,evidence(1918,1968))
for nid,title,body in [('audio','音频控制','与听觉体验有关'),('visual','画面控制','与视觉体验有关'),('device','设备控制','设备操作与其他功能')]:
    node(1968,nid,title,body,'proposed','category','grouping',evidence(1918,1968,'A'))
node(2045,'grouping','三类功能框架获采纳','后续讨论共同使用音频、画面、设备三类框架','confirmed','root',None,evidence(2018,2045))
for nid,title,body,at,span in [
    ('audio','音频控制','音量 · 低音',2095,(2084,2095)),
    ('visual','画面控制','亮度 · 对比度 · 色彩',2104,(2093,2104)),
    ('device','设备控制','电源开关 · 频道选择',2113,(2104,2113))]:
    node(at,nid,title,body,'confirmed','category','grouping',evidence(*span))

events=[]
def decision(at,nid,title,value,detail,span):
    events.append({'id':f'd-{len(events)}','at':(at-START)*1000,'kind':'decision','label':title,
      'decision':{'id':nid,'title':title,'value':value,'unit':'','detail':detail,'evidence':evidence(*span)}})
decision(1823,'power','供电方案','常规电池','减少附加组件与成本，符合现有使用习惯',(1776,1823))
decision(1858,'audience','目标用户','15–35 岁','本场再次确认年轻用户市场',(1835,1858))
decision(1886,'scope','核心功能','基础功能＋静音','开关、频道、音量与数字选台',(1860,1886))
decision(1918,'scope','功能范围补充','基础功能＋可选高级功能','高级功能可藏于盖板下，具体清单仍待细化',(1887,1918))
decision(2045,'grouping','共同讨论框架','音频 / 画面 / 设备','分类提议获明确采纳，作为后续讨论框架',(2018,2045))

tasks=[]
for who,title,detail,at,span in [
 ('B','归档本次会议纪要','放入项目文档文件夹',1986,(1976,1986)),
 ('A','准备组件概念方案','工业设计：梳理所需组件及实现方式',2002,(1987,2002)),
 ('C','推进用户界面设计','界面设计：围绕已讨论的功能组织操作',2008,(1991,2008)),
 ('D','开展趋势研究','市场：继续研究用户与产品趋势',2012,(1991,2012))]:
    t={'id':f'task-{who}','title':title,'owner':who,'due':'会后' if who=='B' else '午餐后 30 分钟工作时段','status':'待开始','detail':detail,'evidence':evidence(*span)}
    tasks.append(t)
    if who!='D':events.append({'id':f't-{who}','at':(at-START)*1000,'kind':'task','task':t,'label':f'明确分工：{title}'})

s={'version':1,'title':'遥控器产品设计 · 功能方案评审','subtitle':'从真实讨论到结构化共识',
 'duration':(END-START)*1000,'provenance':'AMI ES2002b · 真人角色扮演会议 · CC BY 4.0 · 原会议 29:35–36:05 连续节选',
 'audioMode':'mixed','tracks':[{'speaker':'*','src':'audio/ami-es2002b.mp3'}],
 'video':'video/ami-es2002b.mp4','captionSource':'AMI 人工逐词标注',
 'people':[{'id':i,'name':n,'role':r,'initial':x,'color':c} for i,n,r,x,c in [
 ('B','项目经理','主持人','PM','#E3ECFA'),('A','David','工业设计','D','#EEE6D9'),
 ('C','Craig','用户界面设计','C','#E1EDE8'),('D','Andrew','市场研究','A','#EAE4F4')]],
 'segments':segments,'events':events,
 'interactions':[{'id':'confirm-market','showAt':237000,'selectAt':242000,'completeAt':242600,
 'title':'将明确分工加入行动清单','quote':'Marketing, you’re gonna be thinking about trend watching.', 'task':tasks[-1]}],
 'chapters':[{'at':(at-START)*1000,'title':title} for at,title in [(1775,'供电与产品取舍'),(1825,'收敛用户与功能范围'),(1918,'提议功能分类'),(1974,'明确下一阶段分工'),(2018,'采纳分类与补充细节'),(2135,'会议收尾')]],
 'context':{'title':'承接产品启动会','source':'AMI ES2002a · 上一场会议','summary':'为国际市场设计一款易用、有吸引力的遥控器。',
   'facts':['售价 €25','生产成本 ≤ €12.50','面向国际市场'],'open':'上一场遗留：是否只控制电视？本场前段已收敛为仅控制电视。'},
 'minuteEvents':nodes,
 'sourceUrl':'https://groups.inf.ed.ac.uk/ami/download/'}
dump(OUT/'scenario-real.json',s)
dump(BUILD/'real-reference.json',s)
print(f'Prepared {len(segments)} turns, {len(nodes)} graph updates, {len(events)} actions/decisions')
