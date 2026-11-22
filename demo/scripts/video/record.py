import argparse,asyncio,base64,json,time
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[2]
INIT='''(()=>{addEventListener('DOMContentLoaded',()=>{let c=document.createElement('div');c.id='demo-cursor';c.style.cssText='position:fixed;z-index:999999;pointer-events:none;font-size:24px;color:#2466ff;text-shadow:0 1px white;left:20px;top:20px';c.textContent='➤';document.body.appendChild(c);addEventListener('mousemove',e=>{c.style.left=e.clientX+'px';c.style.top=e.clientY+'px'});let n=document.createElement('div');n.id='chapter-note';n.style.cssText='position:fixed;z-index:99999;left:50%;top:8px;transform:translateX(-50%);background:#16335c;color:white;padding:9px 22px;border-radius:25px;font:13px Microsoft YaHei;box-shadow:0 4px 18px #152e5520;display:none';document.body.appendChild(n)})})();'''
class Story:
 def __init__(self,page,dry,out):self.p=page;self.dry=dry;self.out=out;self.intervals=[];self.steps=[]
 async def hold(self,n):await asyncio.sleep(.15 if self.dry else n)
 async def click(self,loc):
  name=loc if isinstance(loc,str) else None
  if isinstance(loc,str):loc=self.p.get_by_role('button',name=loc,exact=True)
  await loc.wait_for();box=await loc.bounding_box()
  await self.p.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2,steps=12)
  await loc.click();await self.hold(.7)
  if name in ['实时纪要','讨论全览','跨会追踪']:
   await self.p.locator('.ai-scroll').evaluate('(e)=>e.scrollTo({top:0})')
 async def note(self,t):
  print(t,flush=True);self.steps.append(t)
  await self.p.evaluate('(t)=>{let e=document.getElementById("chapter-note");e.textContent=t;e.style.display="block"}',t)
  # Force a compositor frame even when only the chapter note changes on a static page.
  await self.p.screenshot()
 async def seek(self,t):await self.p.get_by_role('slider',name='会议播放进度').fill(str(round(t)))
 async def observe(self):return await self.p.evaluate('()=>{let e=document.querySelector(".meeting-app");return {wall:performance.timeOrigin+performance.now(),media:Number(e.dataset.mediaTime)}}')
 async def scroll(self,selector,top):
  loc=self.p.locator(selector);box=await loc.bounding_box()
  await self.p.mouse.move(box['x']+box['width']*.8,box['y']+box['height']*.55,steps=8)
  await loc.evaluate('(e,top)=>e.scrollTo({top:top<0?e.scrollHeight:top,behavior:"smooth"})',top)
  await self.hold(1)
 async def clip(self,start,end,label,tab=None,actions=()):
  await self.note(label)
  if await self.p.get_by_role('button',name='暂停播放',exact=True).count():await self.click('暂停播放')
  await self.seek(start*1000)
  if tab:await self.click(tab)
  await self.click('开始播放')
  if not self.dry:first=await self.observe()
  for at,kind,value in actions:
   if self.dry:await self.seek(at*1000)
   else:await self.p.wait_for_function('(at)=>Number(document.querySelector(".meeting-app").dataset.mediaTime)>=at',arg=at*1000,timeout=(end-start+15)*1000)
   if kind=='tab':await self.click(value)
   else:await self.scroll('.ai-scroll',value)
  if self.dry:
   await self.seek(end*1000);await self.hold(.2)
  else:
   await self.p.wait_for_function('(end)=>Number(document.querySelector(".meeting-app").dataset.mediaTime)>=end',arg=end*1000,timeout=(end-start+15)*1000)
   last=await self.observe()
  if await self.p.get_by_role('button',name='暂停播放',exact=True).count():await self.click('暂停播放')
  if not self.dry:
   stopped=await self.observe();begin=first['wall']/1000-(first['media']/1000-start);self.intervals.append({'start':begin,'end':begin+(stopped['media']/1000-start),'media':start})
  await self.hold(2)
 async def run(self,trial):
  await self.note('项目工作台 · 把每一场讨论接到下一次行动');await self.hold(7)
  await self.click(self.p.locator('.project-card').first);await self.hold(7)
  await self.click(self.p.get_by_role('button',name='进入会议 →').first);await self.hold(7)
  await self.click('进入会议现场 →');await self.p.wait_for_function('!document.querySelector(".play-button").disabled');await self.hold(3)
  if trial:
   await self.clip(28,38,'同步试录 · 真人发言与逐词字幕')
   await self.clip(205,215,'同步试录 · 定位后声音跟随')
   return
  await self.clip(20,52,'01 第一场 · 转写与议题随发言出现',actions=[(30,'tab','文字记录'),(40,'tab','实时纪要'),(48.5,'scroll',320)])
  await self.scroll('.ai-scroll',0)
  await self.clip(71,87,'目标人群 · 新决定出现后再收进纪要',actions=[(80,'scroll',320)])
  await self.scroll('.ai-scroll',0)
  await self.clip(133,154,'功能分类 · 新观点进入讨论图')
  await self.p.screenshot(path=str(self.out/'first-live.jpg'))
  await self.click('讨论全览');await self.hold(6)
  await self.clip(199,246,'明确分工 · 任务逐条出现，确认卡自动选择','实时纪要',actions=[(207,'scroll',420),(220,'scroll',-1),(230,'scroll',-1)])
  await self.scroll('.ai-scroll',0)
  await self.clip(258,275,'形成共识 · 分类提议更新为已采纳')
  await self.click('实时纪要')
  await self.seek(389900);await self.hold(3);await self.click('结束并归档本场')
  await self.note('会后翻阅 · 会议纪要、决定与行动事项');await self.hold(6)
  await self.scroll('.archive-scroll',380);await self.hold(6)
  await self.p.screenshot(path=str(self.out/'first-minutes.jpg'))
  await self.scroll('.archive-scroll',-1);await self.hold(6)
  await self.click('项目承接');await self.scroll('.archive-scroll',0)
  await self.note('项目承接 · 把本场决定与未完成任务留给下一场');await self.hold(7)
  await self.click(self.p.get_by_role('button',name='前场原话',exact=True).first);await self.hold(5);await self.click('关闭原话')
  await self.scroll('.archive-scroll',-1);await self.hold(5)
  await self.click('返回项目，查看累计结果 →');await self.note('第一场归档 · 决定与任务进入项目记忆');await self.hold(9)
  await self.p.screenshot(path=str(self.out/'project-archived.jpg'))
  assert await self.p.locator('.meeting-card').count()==1
  await self.click('＋ 新建会议');await self.note('在同一项目内，现场创建第二场会议');await self.hold(3)
  await self.p.get_by_label('会议名称').press_sequentially('方案汇报与迭代',delay=150 if not self.dry else 1);await self.hold(3)
  await self.click('创建会议');await self.hold(5)
  await self.note('Alt + I · 快捷邀请上一场的同一批成员');await self.p.keyboard.press('Alt+i');await self.hold(6)
  await self.p.screenshot(path=str(self.out/'invite-dialog.jpg'))
  await self.click('邀请 3 位成员加入');await self.hold(5)
  await self.note('02 第二场 · 已邀请原班成员，项目记忆自动带入');await self.hold(5);await self.scroll('.memory-panel',-1);await self.hold(6)
  await self.p.screenshot(path=str(self.out/'carryover.jpg'))
  await self.click('进入会议现场 →');await self.p.wait_for_function('!document.querySelector(".play-button").disabled');await self.hold(3)
  await self.p.screenshot(path=str(self.out/'second-empty.jpg'))
  await self.clip(390,427,'本场纪要从空白开始 · 回顾后再逐步形成观点','实时纪要',actions=[(410,'tab','文字记录'),(420,'tab','实时纪要'),(424,'scroll',160)])
  await self.click('跨会追踪');await self.scroll('.ai-scroll',0);await self.note('相同决定被重申 · 沿用原事项并增加本场来源');await self.hold(6)
  await self.clip(480,515,'Andrew 汇报 · 文字与本场讨论同步生成','实时纪要',actions=[(493,'tab','文字记录'),(505,'tab','实时纪要')])
  await self.clip(547,580,'阶段汇报后 · 原任务更新，图中新增进展',actions=[(557,'scroll',-1),(571,'scroll',0)])
  await self.clip(627,666,'David 汇报 · 组件方案与约束',actions=[(638,'scroll',-1),(654,'scroll',0)])
  await self.seek(705000);await self.click('跨会追踪');await self.note('任务延续 · 查看前场分工与本场汇报')
  task=self.p.locator('.cross-task').filter(has=self.p.get_by_role('button',name='查看本场汇报',exact=True)).first
  await task.scroll_into_view_if_needed();await self.hold(6)
  await self.click(task.get_by_role('button',name='查看原分工',exact=True));await self.hold(7);await self.click('关闭证据')
  await self.click(task.get_by_role('button',name='查看本场汇报',exact=True));await self.hold(7);await self.click('关闭证据')
  await self.p.locator('.cross-heading').scroll_into_view_if_needed()
  await self.clip(711,779,'继续讨论供电方案 · 对比原决定与本场修订','跨会追踪',actions=[(727,'tab','实时纪要'),(747,'tab','文字记录'),(768,'tab','跨会追踪'),(773,'scroll',0)])
  await self.p.screenshot(path=str(self.out/'revision.jpg'));await self.hold(6)
  await self.click(self.p.get_by_role('button',name='本场原话',exact=True).first);await self.hold(7);await self.click('关闭证据')
  await self.seek(782000);await self.click('结束并归档本场');await self.hold(7)
  await self.click('返回项目，查看累计结果 →');await self.note('两场会议，一份持续更新的项目记忆');await self.hold(9)
  saved=await self.p.evaluate('JSON.parse(localStorage.getItem("meeting-projects-v1"))');assert len(saved[0]['archives'])==2
  await self.p.screenshot(path=str(self.out/'final-project.jpg'))
  await self.p.reload();await self.p.locator('.project-card').first.wait_for();await self.click(self.p.locator('.project-card').first)
  assert await self.p.get_by_role('button',name='查看归档 →').count()==2
  await self.hold(3)
async def main(a):
 out=ROOT/'videos'/a.name;out.mkdir(parents=True,exist_ok=False)
 frames=[];tasks=set();errors=[]
 async with async_playwright() as p:
  b=await p.chromium.launch(channel='msedge',headless=True,args=['--autoplay-policy=no-user-gesture-required'])
  page=await b.new_page(viewport={'width':1600,'height':900},device_scale_factor=1.2)
  page.on('pageerror',lambda e:errors.append(str(e)))
  await page.add_init_script(INIT);await page.goto('http://127.0.0.1:4174/?review=1');await page.locator('.project-card').first.wait_for()
  cdp=await page.context.new_cdp_session(page)
  async def frame(ev):
   name=f'f{len(frames):06d}.jpg';frames.append([ev['metadata']['timestamp'],name]);(out/name).write_bytes(base64.b64decode(ev['data']));await cdp.send('Page.screencastFrameAck',{'sessionId':ev['sessionId']})
  def receive(ev):
   t=asyncio.create_task(frame(ev));tasks.add(t);t.add_done_callback(tasks.discard)
  if not a.dry:
   cdp.on('Page.screencastFrame',receive);await cdp.send('Page.startScreencast',{'format':'jpeg','quality':88,'maxWidth':1920,'maxHeight':1080,'everyNthFrame':2})
  s=Story(page,a.dry,out)
  try:await s.run(a.trial)
  finally:
   await page.screenshot(path=str(out/'last-screen.jpg'))
   end=await page.evaluate('(performance.timeOrigin+performance.now())/1000')
   if not a.dry:await cdp.send('Page.stopScreencast');await asyncio.gather(*tasks)
   (out/'manifest.json').write_text(json.dumps({'frames':frames,'intervals':s.intervals,'steps':s.steps,'end':end,'errors':errors,'dry':a.dry},ensure_ascii=False,indent=2),encoding='utf-8')
   await b.close()
  assert not errors,errors
  print('COMPLETE',out,flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--dry',action='store_true');p.add_argument('--trial',action='store_true');p.add_argument('--name',required=True);asyncio.run(main(p.parse_args()))
