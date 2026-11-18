"""Freeze synthetic boundary contrasts; expectations are evaluator-only."""
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent


def main():
    groups=[
      ('P01',[('host','现在在白板画喜欢的动物。'),('lin','我先来。')],0,
             [('host','会后请把白板上的动物图整理后发给大家。'),('lin','好。')],1),
      ('P02',[('host','遥控器只控制电视，不支持DVD。')],0,
             [('host','遥控器只控制电视，不支持DVD。小林，请据此修改规格并发评审。'),('lin','好。')],1),
      ('P03',[('host','今天决定取消图文电视功能。')],0,
             [('host','取消图文电视功能，小林把这一项从规格表移除。'),('lin','好。')],1),
      ('P04',[('host','接下来有30分钟做下一阶段工作。我会上传纪要。')],1,
             [('host','接下来30分钟，小林看组件概念，小周看界面功能。我会上传纪要。')],3),
      ('P05',[('host','培训时老师常问：“人事要我们核对孩子信息，能发群里吗？”')],0,
             [('host','培训时老师常问：“人事要我们核对孩子信息，能发群里吗？”'),('host','说回本园这次核对，小林请核对名单。'),('lin','好。')],1),
      ('P06',[('host','我在举一个老师们过去常问的问题：怎么恢复出厂设置？')],0,
             [('host','客服反馈用户常问怎么恢复出厂设置，这影响我们减少重复咨询的目标，尚未决定怎么做。')],0),
      ('P07',[('host','我们可以会后细化这个场景，先作为一个建议。')],0,
             [('host','小林，这个场景会后细化一下可以吗？'),('lin','可以，我来。')],1),
      ('P08',[('host','这类遥控器可以支持录像功能。')],0,
             [('lin','能否支持录像我去了解一下，如果我能查到的话。')],1),
      ('P09',[('host','感谢参加，稍后导览员带大家参观，请在入口集合。')],0,
             [('host','导览路线还没排。小林请在活动开始前排好路线并发给导览员。'),('lin','好。')],1),
      ('P10',[('host','上一位老师的环节结束，下面交给安老师。')],0,
             [('host','这个客户投诉交给安老师跟进。'),('an','好。')],1),
      ('P11',[('lin','纪要我已经发了，现在正放入共享文件夹。')],0,
             [('lin','我会把纪要发给大家，再放进共享文件夹。')],[1,2]),
      ('P12',[('host','之前定的第一批只限员工。现在第一批范围改为员工和试点客户。')],0,
             [('host','之前定的第一批只限员工。现在第一批范围改为员工和试点客户。小林今天下班前改好灰度配置并发测试。'),('lin','好。')],1),
      ('P13',[('host','有需要可以会后找老师交流。')],0,
             [('lin','还有两个问题，我会后单独联系袁老师。')],1),
      ('P14',[('host','核对的是哪个页面？'),('lin','移动端登录页。'),('host','好，清楚了。')],0,
             [('lin','核对的是哪个页面？'),('host','移动端登录页。'),('lin','好，我来检查这个页面的按钮文案。')],1),
    ]
    cases=[];expectations=[]
    def add(cid,turns,count,**extra):
        meeting=dict(case_id=cid,meeting_id=cid,series='任务边界对照',language='zh',source='synthetic_boundary_contrast',
            started_at='2026-11-16T10:00:00+08:00',audience=['host','lin','zhou','an'],writers=['host'],
            speaker_map={x:x for x in ('host','lin','zhou','an')},
            roster=dict(host='主持人',lin='小林',zhou='小周',an='安老师'),
            segments=[dict(id=f'{cid}.{i}',speaker=s,text=t) for i,(s,t) in enumerate(turns,1)])
        cases.append(dict(id=cid,group='pairs',actor='host',meeting=meeting))
        expectations.append(dict(case_id=cid,item_counts=count if isinstance(count,list) else [count],**extra))
    for g,a,na,b,nb in groups:
        add(g+'a',a,na,no_review=g not in ('P07',),needs_report=g=='P11')
        add(g+'b',b,nb,no_review=g not in ('P04','P06','P08'),
            needs_implicit=g=='P06',conditional=g=='P08',no_deadline=g in ('P04','P13'))
    for cid,reply,speaker,op in [('R01','好。','lin','create'),('R02','好。','zhou','candidate'),
                                 ('R03','会议时间我可以，任务我还要评估。','lin','candidate')]:
        add(cid,[('host','半小时后再开会。小林，请整理移动端登录页的功能清单。'),(speaker,reply)],1,operations=[op])
    add('R04',[('host','小周，请整理电脑端注册页的功能清单。'),('zhou','Okay.')],1,operations=['create'])
    add('R05',[('host','先介绍一个培训时老师常问的例子：怎么核对名单？'),
              ('host','例子中的老师担心姓名重复。'),('host','我们目前有两个班。'),
              ('host','一个是大班。'),('host','一个是小班。'),('host','两个班的表分开放。'),
              ('host','先不要把例子当本次工作安排。'),('lin','我在听介绍。'),
              ('host','现在安排本次工作：小林核对大班名单中的重复姓名。'),('lin','好，我来。')],1,
        operations=['create'],promoted_context=True)
    for name,value in [('fixtures.json',dict(cases=cases)),('expectations.json',dict(cases=expectations))]:
        with (HERE/name).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
    print(f'Frozen {len(cases)} cases; expectations are in a separate file.')


if __name__=='__main__':main()
