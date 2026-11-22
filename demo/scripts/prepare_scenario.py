"""Build aligned speaker tracks and annotated synthetic demonstration data."""
import json
from pathlib import Path
import subprocess
import wave

ROOT = Path(__file__).resolve().parents[1]
source = json.loads((ROOT / 'scenario-source.json').read_text(encoding='utf-8'))
build = ROOT / '.audio-build'
media = ROOT / 'public' / 'audio'
media.mkdir(parents=True, exist_ok=True)
segments = []
cursor = 1500
clips = []
for row in source['segments']:
    with wave.open(str(build / f"{row['id']}.wav"), 'rb') as audio:
        params = audio.getparams()
        samples = audio.readframes(params.nframes)
    if clips and params[:3] != clips[0][2][:3]:
        raise ValueError('Voice sample formats differ')
    length = round(params.nframes / params.framerate * 1000)
    segments.append({**row, 'start': cursor, 'end': cursor + length})
    clips.append((row, samples, params, cursor))
    cursor += length + (10000 if row['id'] == 's08' else 1800)
duration = cursor + 6000
channels, width, rate = clips[0][2][:3]
frame_size = channels * width
for person in source['people']:
    track = bytearray(round(duration * rate / 1000) * frame_size)
    for row, samples, _, start in clips:
        if row['speaker'] == person['id']:
            offset = round(start * rate / 1000) * frame_size
            track[offset:offset + len(samples)] = samples
    wav = build / f"{person['id']}.wav"
    with wave.open(str(wav), 'wb') as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        audio.writeframes(track)
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(wav), '-codec:a', 'libmp3lame',
                    '-b:a', '64k', str(media / f"{person['id']}.mp3")], check=True)

ends = {row['id']: row['end'] for row in segments}
def at(segment):
    return ends[segment] + 300

task = {'id': 'roster', 'title': '整理首批报名名单', 'owner': 'lin', 'due': '本周五',
        'status': '待开始', 'detail': '去重并补齐联系方式', 'evidence': ['s02', 's03']}
clarified = {'id': 'guide', 'title': '补充报名须知', 'owner': 'zhou', 'due': '周四下午',
             'status': '待开始', 'detail': '参与条件与退款说明，交陈一卓审核', 'evidence': ['s06', 's07', 's08']}
events = [
    {'id':'e1','at':at('s03'),'kind':'task','task':task,'label':'明确名单分工'},
    {'id':'e2','at':at('s05'),'kind':'decision','decision':{'id':'price','title':'会员年费','value':'99',
     'unit':'元 / 年','detail':'每月一次会员活动 · 活动资料下载','evidence':['s04','s05']},'label':'确定初版定价'},
    {'id':'e3','at':at('s11'),'kind':'task','task':{**task,'due':'本周四','evidence':['s09','s10','s11']},'label':'名单交付提前'},
    {'id':'e4','at':at('s14'),'kind':'decision','decision':{'id':'price','title':'会员年费','value':'89',
     'unit':'元 / 年','detail':'渠道补贴支持 · 原会员权益保留','evidence':['s12','s13','s14']},'label':'会员定价调整'},
    {'id':'e5','at':at('s16'),'kind':'decision','decision':{'id':'price','title':'会员年费','value':'89',
     'unit':'元 / 年','detail':'渠道补贴支持 · 原会员权益保留','evidence':['s16']},'label':'重申最终方案'}
]
people = [{k: v for k, v in person.items() if k not in ('voice','rate')} for person in source['people']]
scenario = {
    'version':1, 'title':source['title'], 'subtitle':source['subtitle'], 'duration':duration,
    'provenance':'人工编排演示 · Windows 中文语音合成 · 句级时间标注',
    'people':people, 'tracks':[{'speaker':p['id'],'src':f"audio/{p['id']}.mp3"} for p in people],
    'segments':segments, 'events':events,
    'interactions':[{'id':'clarify','showAt':at('s08'),'selectAt':at('s08')+5000,
                     'completeAt':at('s08')+5600, 'title':'确认一项待澄清意向',
                     'quote':'我之后再补一下', 'task':clarified}],
    'chapters':[{'at':0,'title':'开场与分工'},{'at':ends['s03']+1800,'title':'确认会员定价'},
                {'at':ends['s05']+1800,'title':'澄清与确认'},
                {'at':ends['s08']+10000,'title':'更新交付时间'},
                {'at':ends['s11']+1800,'title':'调整会员定价'},
                {'at':ends['s15']+1800,'title':'收敛与回顾'}]
}
(ROOT / 'public' / 'scenario.json').write_text(json.dumps(scenario, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Created {len(segments)} segments, {len(people)} aligned tracks, {duration / 1000:.1f} seconds')
