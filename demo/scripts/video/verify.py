import json,subprocess
from pathlib import Path
import numpy as np
from scipy.signal import correlate,correlation_lags
import sys
ROOT=Path(__file__).resolve().parents[2]
def pcm(path,start,length):
 raw=subprocess.check_output(['ffmpeg','-nostdin','-loglevel','error','-ss',str(start),'-i',str(path),'-t',str(length),'-f','f32le','-ac','1','-ar','8000','pipe:1']);return np.frombuffer(raw,dtype=np.float32)
def main(name):
 p=ROOT/'videos'/name;m=json.loads((p/'manifest.json').read_text(encoding='utf-8'));base=m['frames'][0][0];checks=[]
 for i,v in enumerate(m['intervals']):
  duration=v['end']-v['start'];offsets=sorted(set([1,*range(61,int(duration)-3,60),max(1,duration-4)])) if duration>90 else [1]
  for offset in offsets:
   length=min(3,duration-offset);actual=pcm(p/'演示成片.mp4',v['start']-base+offset,length);source=pcm(ROOT/'public/audio/ami-es2002-bc.mp3',v['media']+offset,length)
   n=min(len(actual),len(source));a=actual[:n];s=source[:n];rms=float(np.sqrt(np.mean(a*a)))
   if np.max(np.abs(s))<1e-5:
    assert rms<1e-4;checks.append({'clip':i+1,'offset':offset,'silence':True});continue
   c=correlate(a,s,method='fft');lags=correlation_lags(n,n);mask=np.abs(lags)<1200;lag=int(lags[mask][np.argmax(c[mask])]);score=float(np.dot(a,s)/(np.linalg.norm(a)*np.linalg.norm(s)+1e-15));checks.append({'clip':i+1,'offset':offset,'lag_ms':lag/8,'correlation':round(score,4),'rms':round(rms,5)})
 assert all(x.get('silence') or (abs(x['lag_ms'])<150 and x['correlation']>.9) for x in checks),checks
 subprocess.run(['ffmpeg','-nostdin','-v','error','-i',str(p/'演示成片.mp4'),'-f','null','-'],check=True)
 summary={'audio_source_checks':checks,'decode':'passed','browser_errors':m['errors'],'duration_seconds':m['end']-base,'frames':len(m['frames'])}
 if m.get('samples'):
  drift=[]
  for v in m['intervals']:
   samples=[s for s in m['samples'] if v['media']*1000<=s['media']<(v['media']+v['end']-v['start'])*1000-150]
   assert all(s['playing']=='true' for s in samples)
   drift.extend(abs((s['media']/1000-v['media'])-(s['wall']/1000-v['start']))*1000 for s in samples)
  assert max(drift)<300
  summary['continuous_playback']={'intervals':len(m['intervals']),'samples':len(m['samples']),'max_clock_drift_ms':round(max(drift),2),'unexpected_pauses':0}
 (p/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main(sys.argv[1])
