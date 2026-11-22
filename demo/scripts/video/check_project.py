import asyncio,json
from pathlib import Path
from playwright.async_api import async_playwright
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(channel='msedge',headless=True);page=await b.new_page(viewport={'width':1440,'height':900})
  await page.goto('http://127.0.0.1:4174/?review=1');await page.locator('.project-card').first.click()
  assert await page.locator('.meeting-card').count()==1
  assert await page.get_by_role('button',name='＋ 新建会议').is_disabled()
  await page.get_by_role('button',name='进入会议 →').first.click();await page.get_by_role('button',name='进入会议现场 →').click();await page.wait_for_function('!document.querySelector(".play-button").disabled')
  assert await page.locator('.live-topic h2').count()==1
  await page.get_by_role('slider',name='会议播放进度').fill('50000')
  assert '收敛' in await page.locator('.live-topic h2').inner_text()
  await page.get_by_role('button',name='结束并归档本场').click()
  assert await page.locator('.memory-item').count()==1
  await page.get_by_role('button',name='项目承接',exact=True).click()
  assert await page.locator('.cross-decision').count()==1
  await page.get_by_role('button',name='返回项目，查看累计结果 →').click()
  await page.get_by_role('button',name='＋ 新建会议').click()
  await page.get_by_label('会议名称').fill('方案汇报与迭代')
  await page.get_by_role('button',name='创建会议',exact=True).click()
  assert await page.locator('.memory-item').count()==1
  assert await page.locator('.people-grid>div').count()==1
  assert await page.get_by_role('button',name='进入会议现场 →').is_disabled()
  await page.keyboard.press('Alt+i');await page.get_by_role('dialog',name='邀请上场成员').wait_for()
  await page.get_by_role('button',name='邀请 3 位成员加入').click()
  assert await page.locator('.people-grid>div').count()==4
  await page.get_by_role('button',name='进入会议现场 →').click();await page.wait_for_function('!document.querySelector(".play-button").disabled');await page.wait_for_timeout(300)
  assert float(await page.locator('.meeting-app').get_attribute('data-media-time'))==390000
  assert '等待讨论' in await page.locator('.live-topic h2').inner_text()
  assert await page.locator('.topic-node').count()==0
  assert await page.locator('.outcome-card').count()==1
  await page.get_by_role('slider',name='会议播放进度').fill('424000')
  assert await page.locator('.live-topic h2').count()==1
  assert await page.locator('.topic-node').count()==3
  await page.get_by_role('slider',name='会议播放进度').fill('390000')
  assert await page.locator('.topic-node').count()==0
  await page.get_by_role('button',name='← 返回项目').click();await page.get_by_role('button',name='▦　我的项目').click()
  page.on('dialog',lambda d:d.accept('独立项目'))
  await page.get_by_role('button',name='＋ 新建项目').click()
  assert await page.locator('.memory-item').count()==0
  await page.reload();await page.locator('.project-card').first.wait_for();assert await page.locator('.project-card').count()==2
  print('PASS: live creation, keyboard invite, progressive chapters/graph, rewind, archive cutoff, inheritance, isolation, persistence')
  await b.close()
asyncio.run(main())
