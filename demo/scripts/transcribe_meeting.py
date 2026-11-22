"""Run real local STT once; preserve unmodified output and acoustic word timings."""
import argparse, json, time
from pathlib import Path
from faster_whisper import WhisperModel

p=argparse.ArgumentParser()
p.add_argument('--model',default='base.en')
p.add_argument('--audio',default='.audio-build/ami.wav')
p.add_argument('--scenario',default='public/scenario-real.json')
p.add_argument('--output',default='public/asr-result.json')
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
started=time.monotonic()
print('Loading STT model',a.model,flush=True)
model=WhisperModel(a.model,device='cpu',compute_type='int8',cpu_threads=6)
print('Model ready; transcribing actual audio',flush=True)
segments,info=model.transcribe(str(root/a.audio),language='en',beam_size=3,
    word_timestamps=True,vad_filter=True,condition_on_previous_text=False)
rows=[]
for s in segments:
    rows.append({'start':round(s.start*1000),'end':round(s.end*1000),'text':s.text,
      'words':[{'start':round(w.start*1000),'end':round(w.end*1000),'text':w.word,'probability':w.probability} for w in s.words or []]})
    print(round(s.end,1),s.text,flush=True)
out={'model':a.model,'engine':'faster-whisper','mode':'offline-word-alignment','elapsedSeconds':round(time.monotonic()-started,2),'segments':rows}
(root/a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
scenario=json.loads((root/a.scenario).read_text(encoding='utf-8'))
ref=scenario['segments']
asr=[]
for row in rows:
    for word in row['words']:
        # Speaker comes from supplied annotation, not a claim of ASR diarization.
        midpoint=(word['start']+word['end'])/2
        match=min(ref,key=lambda s:max(s['start']-midpoint,midpoint-s['end'],0))
        asr.append({**word,'speaker':match['speaker']})
scenario['captionWords']=asr
scenario['captionSource']=f'faster-whisper {a.model} · 实测词级时间轴'
(root/a.scenario).write_text(json.dumps(scenario,ensure_ascii=False,indent=2),encoding='utf-8')
print('Saved',len(asr),'ASR words. seconds',out['elapsedSeconds'],flush=True)
