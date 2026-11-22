"""Build chronological, explicitly labelled excerpts from two consecutive AMI meetings."""
import copy
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT.parent/'data/mvp-v1/raw'
OUT=ROOT/'public'
BUILD=ROOT/'.audio-build/cross-meeting'
BUILD.mkdir(parents=True,exist_ok=True)
clips=[('ES2002b',1775,2165,'第一场 · 功能方案与分工'),
       ('ES2002c',15,85,'第二场 · 回顾上场决定'),
       ('ES2002c',186,277,'Andrew · 汇报趋势研究'),
       ('ES2002c',664,743,'Craig · 汇报界面研究'),
       ('ES2002c',957,1032,'David · 汇报组件方案'),
       ('ES2002c',1916,1993,'重新讨论供电方案')]
s=json.loads((OUT/'scenario-real.json').read_text(encoding='utf-8'))
s.pop('captionWords',None)
s.update(title='连续两场会议 · 从分工到方案迭代',subtitle='同一团队，同一项目，决定与任务跨会延续',
         provenance='AMI ES2002b → ES2002c · 同日同团队连续会议 · 按原顺序节选，含跳段 · CC BY 4.0',
         tracks=[{'speaker':'*','src':'audio/ami-es2002-bc.mp3'}],video='video/ami-es2002-bc.mp4',
         captionSource='AMI 人工逐词标注 · 等待实测 STT',clips=[],meetings=[])

def ff(*args):
    subprocess.run(['ffmpeg','-y','-loglevel','error',*map(str,args)],check=True)

cursor=0
for i,(mid,start,end,label) in enumerate(clips):
    duration=(end-start)*1000
    s['clips'].append({'meetingId':mid,'at':cursor,'end':cursor+duration,'sourceStart':start*1000,'label':label})
    ff('-i',RAW/f'{mid}.Mix-Headset.rm','-ss',start,'-t',end-start,'-ac',1,'-ar',16000,BUILD/f'{i}.wav')
    ff('-i',RAW/f'{mid}.Corner.rm','-ss',start,'-t',end-start,'-an','-vf','scale=360:284,setsar=1',
       '-r',25,'-c:v','libx264','-preset','fast','-crf',24,'-pix_fmt','yuv420p',BUILD/f'{i}.mp4')
    cursor+=duration
for ext in ['wav','mp4']:
    (BUILD/f'{ext}-concat.txt').write_text(''.join(f"file '{i}.{ext}'\n" for i in range(len(clips))),encoding='utf-8')
ff('-f','concat','-safe',0,'-i',BUILD/'wav-concat.txt','-c:a','pcm_s16le',BUILD/'pair.wav')
ff('-i',BUILD/'pair.wav','-c:a','libmp3lame','-b:a','64k',OUT/'audio/ami-es2002-bc.mp3')
ff('-f','concat','-safe',0,'-i',BUILD/'mp4-concat.txt','-c','copy','-movflags','+faststart',OUT/'video/ami-es2002-bc.mp4')
s['duration']=cursor
s['meetings']=[{'id':'ES2002b','title':'01 功能方案与分工','at':0,'end':390000},
               {'id':'ES2002c','title':'02 方案汇报与迭代','at':390000,'end':cursor}]

with zipfile.ZipFile(RAW/'ami_public_manual_1.6.2.zip') as z:
    for clip in s['clips'][1:]:
        start=clip['sourceStart']; end=start+clip['end']-clip['at']
        for person in 'ABCD':
            group=[]
            def flush():
                if not group:return
                text=re.sub(r'\s+([.,?!:;])',r'\1',' '.join(w['text'] for w in group))
                s['segments'].append({'id':f'ES2002c-{len(s["segments"])}','speaker':person,
                     'start':group[0]['start'],'end':max(group[-1]['end'],group[0]['start']+1),
                     'text':text,'words':list(group)})
                group.clear()
            for w in ET.fromstring(z.read(f'words/ES2002c.{person}.words.xml')):
                if w.tag!='w' or not w.get('starttime') or not w.text:continue
                a=round(float(w.get('starttime'))*1000); b=round(float(w.get('endtime'))*1000)
                if a<start or b>end:continue
                item={'start':a-start+clip['at'],'end':b-start+clip['at'],'text':w.text.replace('_','')}
                if group and (item['start']-group[-1]['end']>900 or item['end']-group[0]['start']>6500):flush()
                group.append(item)
                if item['text'] in ['.','?','!']:flush()
            flush()
s['segments'].sort(key=lambda x:x['start'])

def at(source):
    ms=source*1000
    clip=next(c for c in s['clips'][1:] if c['sourceStart']<=ms<=c['sourceStart']+c['end']-c['at'])
    return round(clip['at']+ms-clip['sourceStart'])
def refs(a,b,person=None):
    ids=[x['id'] for x in s['segments'] if x['start']>=at(a) and x['end']<=at(b) and (not person or x['speaker']==person)]
    assert ids,(a,b)
    return ids
def decision(source,key,label,value,detail,evidence):
    s['events'].append({'id':f'c-{key}-{source}','at':at(source),'kind':'decision','label':label,
        'decision':{'id':key,'title':{'power':'供电方案','audience':'目标用户','grouping':'共同讨论框架'}[key],
        'value':value,'unit':'','detail':detail,'evidence':evidence}})
recap=refs(25,48,'B')
decision(48,'power','跨会重申：常规电池','常规电池','项目经理在第二场回顾非充电电池方案。',recap)
decision(48,'audience','跨会重申：15–35 岁用户','15–35 岁','第二场沿用上一场目标人群。',recap)
decision(48,'grouping','跨会承接：三类功能','音频 / 画面 / 设备','第二场开头再次沿用音频、视觉和其他功能分类。',recap)
tasks={e['task']['id']:e['task'] for e in s['events'] if e['kind']=='task'}
tasks['task-D']=s['interactions'][0]['task']
for who,source,span,detail in [
 ('D',277,(186,277),'已汇报市场研究方法、外观体验与创新方向；未明确宣告任务完成。'),
 ('C',743,(664,743),'已汇报现有遥控器的形态、按钮与配色问题；未明确宣告任务完成。'),
 ('A',1032,(957,1032),'已汇报组件对成本、复杂度与尺寸的影响；未明确宣告任务完成。')]:
    task=copy.deepcopy(tasks[f'task-{who}'])
    task.update(status='进行中',detail=detail,evidence=refs(*span,who))
    s['events'].append({'id':f'c-report-{who}','at':at(source),'kind':'task','label':f'跨会进展：{task["title"]}', 'task':task})
decision(1988,'power','跨会修订：供电方案','动能辅助＋电池后备','动能提供辅助，电池维持基础供电；保留第一场常规电池版本。',refs(1916,1988))
for clip in s['clips'][1:]:
    s['chapters'].append({'at':398000 if clip['at']==390000 else clip['at'],'title':clip['label']})
node=lambda t,n: s['minuteEvents'].append({'at':t,'node':n})
node(398000,{'id':'continuity','kind':'root','title':'本场讨论','body':'回顾已归档决定，听取本轮讨论','status':'discussing','parent':None,'evidence':[]})
for source,who,span,name,title in [(277,'D',(186,277),'Andrew','市场研究已汇报'),(743,'C',(664,743),'Craig','界面方案已汇报')]:
    node(at(source),{'id':'report-'+name,'kind':'point','parent':'continuity','title':title,'body':'原任务继续推进，等待后续验收','status':'confirmed','evidence':refs(*span,who)})
for key,title,body in [('carry-power','重申供电方案','常规电池'),('carry-audience','重申目标用户','15–35 岁')]:
    node(at(48),{'id':key,'kind':'point','title':title,'body':body,'status':'confirmed','parent':'continuity','evidence':recap})
node(at(1032),{'id':'carry-work','kind':'point','title':'三项阶段汇报','body':'市场、界面与组件方案均有进展','status':'confirmed','parent':'continuity','evidence':refs(186,277,'D')+refs(664,743,'C')+refs(957,1032,'A')})
node(at(1988),{'id':'carry-power','kind':'point','title':'供电方案已修订','body':'常规电池 → 动能辅助＋电池后备','status':'confirmed','parent':'continuity','evidence':refs(1916,1988)})
s['events'].sort(key=lambda e:e['at'])
s['minuteEvents'].sort(key=lambda e:e['at'])
(OUT/'scenario-cross.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'Prepared pair: {cursor/1000}s, {len(s["segments"])} turns; 2 meetings, {len(clips)} labelled excerpts')
