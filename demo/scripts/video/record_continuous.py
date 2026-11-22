"""Record two uninterrupted meetings. Only the rehearsal may seek; production never does."""
import argparse,asyncio,base64,json
from pathlib import Path
from playwright.async_api import async_playwright
from record import Story,INIT,ROOT

class ContinuousStory(Story):
 def __init__(self,*args):super().__init__(*args);self.samples=[]
 async def note(self,t):
  print(t,flush=True);self.steps.append(t)
 async def action(self,kind,value):
  if kind=='tab':await self.click(value)
  elif kind=='scroll':await self.scroll('.ai-scroll',value)
  elif kind=='shot':await self.p.screenshot(path=str(self.out/value))
 async def meeting(self,start,end,actions):
  await self.click('进入会议现场 →')
  await self.p.wait_for_function('document.querySelector(".meeting-app")?.dataset.ready==="true"')
  if self.dry:await self.click('开始播放')
  else:
   assert await self.p.locator('.playback-bar').count()==0
   await self.p.wait_for_function('document.querySelector(".meeting-app").dataset.playing==="true"')
   first=await self.observe()
  queue=list(actions)
  while queue:
   at,kind,value=queue.pop(0)
   if self.dry:await self.seek(at*1000)
   else:
    while True:
     state=await self.observe();state['playing']=await self.p.locator('.meeting-app').get_attribute('data-playing');self.samples.append(state)
     assert state['playing']=='true',f'Unexpected pause at {state}'
     if state['media']>=at*1000:break
     await asyncio.sleep(.8)
   await self.action(kind,value)
   print(f'MEDIA {at}s: {kind} {value}',flush=True)
  if self.dry:await self.seek(end*1000-100)
  else:
   while True:
    state=await self.observe();state['playing']=await self.p.locator('.meeting-app').get_attribute('data-playing');self.samples.append(state)
    if state['media']>=end*1000-101:break
    assert state['playing']=='true',f'Unexpected pause at {state}'
    await asyncio.sleep(.8)
   begin=first['wall']/1000-(first['media']/1000-start)
   self.intervals.append({'start':begin,'end':begin+(end-start),'media':start})
   # A continuously advancing media clock catches accidental seeks, rate changes, and pauses.
   samples=[s for s in self.samples if start*1000<=s['media']<end*1000-150]
   drift=[abs((s['media']-first['media'])-(s['wall']-first['wall'])) for s in samples]
   assert max(drift,default=0)<300,('Clock discontinuity',max(drift))
  await self.hold(2)
  await self.click('结束并归档本场')

 async def run(self):
  await self.note('项目入口');await self.hold(4)
  await self.click(self.p.locator('.project-card').first);await self.hold(4)
  await self.click('进入会议 →');await self.hold(4)
  await self.note('第一场连续播放 00:00–06:30 · 无暂停、无跳段')
  await self.meeting(0,390,[
   (55,'shot','首场决定.jpg'),(100,'scroll',160),(125,'scroll',0),
   (166,'tab','讨论全览'),(188,'tab','实时纪要'),(212,'scroll',180),
   (247,'shot','分工完成.jpg'),(255,'scroll',0),(280,'scroll',180),
   (305,'tab','文字记录'),(327,'tab','实时纪要'),(350,'scroll',160),
   (375,'scroll',0)])
  await self.note('会后翻阅纪要与项目承接');await self.hold(5)
  await self.scroll('.archive-scroll',340);await self.hold(5);await self.scroll('.archive-scroll',-1);await self.hold(5)
  await self.click('项目承接');await self.scroll('.archive-scroll',0);await self.hold(5)
  await self.click(self.p.get_by_role('button',name='前场原话',exact=True).first);await self.hold(5);await self.click('关闭原话')
  await self.scroll('.archive-scroll',-1);await self.hold(4)
  await self.click('返回项目，查看累计结果 →');await self.hold(5)
  assert await self.p.locator('.meeting-card').count()==1
  await self.note('同一项目现场创建第二场，快捷邀请上场成员')
  await self.click('＋ 新建会议');await self.p.get_by_label('会议名称').press_sequentially('方案汇报与迭代',delay=150 if not self.dry else 1);await self.hold(3)
  await self.click('创建会议');await self.hold(4)
  await self.p.keyboard.press('Alt+i');await self.hold(4);await self.p.screenshot(path=str(self.out/'快捷邀请.jpg'))
  await self.click('邀请 3 位成员加入');await self.hold(4);await self.scroll('.memory-panel',-1);await self.hold(4)
  await self.note('第二场连续播放 00:00–06:32 · 无暂停、无跳段')
  await self.meeting(390,782,[
   (391,'shot','第二场起点.jpg'),(430,'tab','跨会追踪'),(450,'tab','实时纪要'),
   (490,'scroll',180),(515,'scroll',0),(555,'scroll',180),
   (580,'tab','讨论全览'),(605,'tab','实时纪要'),(635,'scroll',180),
   (665,'tab','文字记录'),(687,'tab','实时纪要'),(710,'scroll',0),
   (745,'tab','跨会追踪'),(765,'tab','实时纪要'),(779,'shot','供电修订.jpg')])
  await self.note('最终纪要与同一任务的前后原话');await self.hold(4)
  await self.click('项目承接');await self.scroll('.archive-scroll',0);await self.hold(5)
  task=self.p.locator('.cross-task').filter(has=self.p.get_by_role('button',name='查看本场汇报',exact=True)).first
  await task.scroll_into_view_if_needed();await self.hold(4)
  await self.click(task.get_by_role('button',name='查看原分工',exact=True));await self.hold(5);await self.click('关闭原话')
  await self.click(task.get_by_role('button',name='查看本场汇报',exact=True));await self.hold(5);await self.click('关闭原话')
  await self.click('返回项目，查看累计结果 →');await self.hold(7)
  await self.p.screenshot(path=str(self.out/'最终项目.jpg'))
  saved=await self.p.evaluate('JSON.parse(localStorage.getItem("meeting-projects-v1"))');assert len(saved[0]['archives'])==2
  await self.p.reload();await self.p.locator('.project-card').first.wait_for();await self.click(self.p.locator('.project-card').first)
  assert await self.p.get_by_role('button',name='查看归档 →').count()==2
  await self.hold(3)

async def main(a):
 out=ROOT/'videos'/a.name;out.mkdir(parents=True,exist_ok=False)
 frames=[];tasks=set();errors=[]
 async with async_playwright() as p:
  b=await p.chromium.launch(channel='msedge',headless=True,args=['--autoplay-policy=no-user-gesture-required'])
  page=await b.new_page(viewport={'width':1920,'height':1080},device_scale_factor=1)
  page.on('pageerror',lambda e:errors.append(str(e)))
  await page.add_init_script(INIT.replace('font-size:24px;color:#2466ff','font-size:18px;color:#34435c'));await page.goto('http://127.0.0.1:4174/'+('?review=1' if a.dry else ''));await page.locator('.project-card').first.wait_for()
  await page.add_style_tag(content='#demo-cursor{font-size:18px!important;color:#34435c!important}#chapter-note{display:none!important}')
  cdp=await page.context.new_cdp_session(page)
  async def frame(ev):
   name=f'f{len(frames):06d}.jpg';frames.append([ev['metadata']['timestamp'],name]);(out/name).write_bytes(base64.b64decode(ev['data']));await cdp.send('Page.screencastFrameAck',{'sessionId':ev['sessionId']})
  def receive(ev):
   t=asyncio.create_task(frame(ev));tasks.add(t);t.add_done_callback(tasks.discard)
  if not a.dry:
   cdp.on('Page.screencastFrame',receive);await cdp.send('Page.startScreencast',{'format':'jpeg','quality':90,'maxWidth':1920,'maxHeight':1080,'everyNthFrame':2})
  s=ContinuousStory(page,a.dry,out)
  try:await s.run()
  finally:
   await page.screenshot(path=str(out/'last-screen.jpg'));end=await page.evaluate('(performance.timeOrigin+performance.now())/1000')
   if not a.dry:
    await cdp.send('Page.stopScreencast')
    cdp.remove_listener('Page.screencastFrame',receive)
    await asyncio.gather(*tasks)
   (out/'manifest.json').write_text(json.dumps({'frames':frames,'intervals':s.intervals,'steps':s.steps,'samples':s.samples,'end':end,'errors':errors,'dry':a.dry,'recording':'continuous-meetings'},ensure_ascii=False,indent=2),encoding='utf8')
   await b.close()
  assert not errors,errors
  print('COMPLETE',out,flush=True)
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--dry',action='store_true');parser.add_argument('--name',required=True);asyncio.run(main(parser.parse_args()))
