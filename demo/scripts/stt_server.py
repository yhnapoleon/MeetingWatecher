"""Local PCM -> real rolling Whisper hypotheses. No transcript prompt or canned text."""
import asyncio,json,time
import numpy as np
from fastapi import FastAPI,WebSocket,WebSocketDisconnect
from faster_whisper import WhisperModel
import uvicorn

app=FastAPI()
model=WhisperModel('base.en',device='cpu',compute_type='int8',cpu_threads=6)
lock=asyncio.Lock()

@app.get('/health')
def health():return {'ready':True,'engine':'faster-whisper','model':'base.en'}

@app.websocket('/transcribe')
async def transcribe(ws:WebSocket):
    origin=ws.headers.get('origin','')
    if origin and origin not in ['http://127.0.0.1:4173','http://127.0.0.1:4174','http://localhost:4173','http://localhost:4174']:
        await ws.close(code=1008);return
    await ws.accept()
    window=np.zeros(0,dtype=np.float32);last_end=None
    try:
        while True:
            meta=await ws.receive_json()
            data=await ws.receive_bytes()
            start,end=meta.get('start'),meta.get('end')
            if not isinstance(start,(int,float)) or not isinstance(end,(int,float)) or not 0<end-start<=5000 or len(data)%4 or len(data)>320000:
                await ws.send_json({'error':'无效音频块'});continue
            block=np.frombuffer(data,dtype='<f4').copy()
            if not np.isfinite(block).all():await ws.send_json({'error':'音频数据无效'});continue
            if last_end is None or abs(start-last_end)>250:window=np.zeros(0,dtype=np.float32)
            window=np.concatenate((window,block))[-128000:];last_end=end
            began=time.monotonic()
            def recognize():
                parts,_=model.transcribe(window,language='en',beam_size=1,vad_filter=True,condition_on_previous_text=False)
                return ' '.join(p.text.strip() for p in parts)
            async with lock:text=await asyncio.to_thread(recognize)
            silence=float(np.sqrt(np.mean(block[-min(6400,len(block)):]**2)))<.008
            await ws.send_json({'text':text,'speaker':meta.get('speaker',''),'final':silence,'audioEnd':end,'inferenceMs':round((time.monotonic()-began)*1000)})
    except WebSocketDisconnect:pass

if __name__=='__main__':uvicorn.run(app,host='127.0.0.1',port=8766,log_level='warning',ws_max_size=400000)
