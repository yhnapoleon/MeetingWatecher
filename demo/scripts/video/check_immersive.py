import asyncio,json
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
 out=Path(__file__).resolve().parents[2]/'videos/ui-v3';out.mkdir(parents=True,exist_ok=True)
 async with async_playwright() as p:
  b=await p.chromium.launch(channel='msedge',headless=True,args=['--autoplay-policy=no-user-gesture-required'])
  page=await b.new_page(viewport={'width':1920,'height':1080});errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  async def enter():
   await page.locator('.project-card').first.click();await page.get_by_role('button',name='进入会议 →').first.click();await page.get_by_role('button',name='进入会议现场 →').click()
   await page.wait_for_function('document.querySelector(".meeting-app")?.dataset.ready==="true"')
  await page.goto('http://127.0.0.1:4174/');await enter()
  await page.wait_for_function('Number(document.querySelector(".meeting-app").dataset.mediaTime)>3000')
  assert await page.locator('.playback-bar').count()==0
  assert await page.get_by_role('button',name='暂停播放',exact=True).count()==0
  assert await page.get_by_role('slider').count()==0
  assert await page.locator('.meeting-app').get_attribute('data-playing')=='true'
  await page.goto('http://127.0.0.1:4174/?review=1');await enter()
  await page.add_style_tag(content='.playback-bar{position:fixed;bottom:0;opacity:0}')
  for time,name in [(90000,'first-decisions'),(275000,'first-tasks')]:
   await page.get_by_role('slider',name='会议播放进度').fill(str(time),force=True)
   await page.wait_for_timeout(350);await page.screenshot(path=str(out/f'{name}.jpg'))
  await page.get_by_role('button',name='开始播放',exact=True).click(force=True)
  await page.get_by_role('button',name='查看供电方案原话',exact=True).click()
  t=float(await page.locator('.meeting-app').get_attribute('data-media-time'));await page.wait_for_timeout(800)
  assert float(await page.locator('.meeting-app').get_attribute('data-media-time'))>t+600
  assert await page.locator('.meeting-app').get_attribute('data-playing')=='true'
  await page.get_by_role('button',name='关闭证据').click()
  await page.get_by_role('slider',name='会议播放进度').fill('389900',force=True);await page.get_by_role('button',name='结束并归档本场').click()
  await page.get_by_role('button',name='返回项目，查看累计结果 →').click();await page.get_by_role('button',name='＋ 新建会议').click();await page.get_by_label('会议名称').fill('方案汇报与迭代');await page.get_by_role('button',name='创建会议',exact=True).click();await page.keyboard.press('Alt+i');await page.get_by_role('button',name='邀请 3 位成员加入').click();await page.get_by_role('button',name='进入会议现场 →').click();await page.wait_for_function('document.querySelector(".meeting-app")?.dataset.ready==="true"')
  for time,name in [(390000,'second-empty'),(779000,'second-revised')]:
   await page.get_by_role('slider',name='会议播放进度').fill(str(time),force=True);await page.wait_for_timeout(350);await page.screenshot(path=str(out/f'{name}.jpg'))
  assert '动能辅助' in await page.locator('[data-decision="power"] .outcome-value').inner_text()
  assert await page.locator('[data-decision="power"] del').inner_text()=='常规电池'
  assert not errors,errors
  await b.close();print('PASS: automatic start, no transport controls, evidence without pause, prominent version diff, screenshots')
asyncio.run(main())


