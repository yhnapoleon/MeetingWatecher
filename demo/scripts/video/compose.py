import argparse,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def run(args):subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y',*args],check=True)
def compose(name):
 out=ROOT/'videos'/name;m=json.loads((out/'manifest.json').read_text(encoding='utf-8'));f=m['frames'];assert f and not m['dry'];start=f[0][0];duration=m['end']-start
 lines=[]
 for i,(t,n) in enumerate(f):
  end=f[i+1][0] if i+1<len(f) else m['end'];lines.extend([f"file '{n}'",f'duration {max(.001,end-t):.6f}'])
 lines.append(f"file '{f[-1][1]}'");(out/'frames.txt').write_text('\n'.join(lines),encoding='utf-8')
 run(['-f','concat','-safe','0','-i',str(out/'frames.txt'),'-vf','fps=30,scale=1920:1080','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p','-an',str(out/'silent.mp4')])
 import numpy as np, wave
 raw=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-i',str(ROOT/'public/audio/ami-es2002-bc.mp3'),'-f','f32le','-ac','1','-ar','16000','pipe:1'])
 source=np.frombuffer(raw,dtype=np.float32);mix=np.zeros(round(duration*16000),dtype=np.float32)
 for v in m['intervals']:
  pos=round(max(0,v['start']-start)*16000);offset=round(v['media']*16000);count=min(round((v['end']-v['start'])*16000),len(mix)-pos,len(source)-offset)
  assert count>0
  mix[pos:pos+count]+=source[offset:offset+count]
 gain=min(6.0,.95/max(float(np.max(np.abs(mix))),1e-9));mix*=gain
 (out/'audio-gain.json').write_text(json.dumps({'linear_gain':gain,'peak_limit':.95}),encoding='utf-8')
 with wave.open(str(out/'audio.wav'),'wb') as wav:
  wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes((np.clip(mix,-1,1)*32767).astype('<i2').tobytes())
 run(['-i',str(out/'silent.mp4'),'-i',str(out/'audio.wav'),'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','128k','-t',str(duration),'-movflags','+faststart',str(out/'演示成片.mp4')])
 print('COMPOSED',duration,out/'演示成片.mp4',flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('name');compose(p.parse_args().name)
