"""Apply recorded pre-prediction source review; preserve raw model annotation."""
import copy
import json
import re
from pathlib import Path
from annotate import validate

ROOT=Path(__file__).resolve().parents[2];DATA=ROOT/'data/generalization-v1'
def read(p):return json.loads(p.read_text(encoding='utf8'))
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

def main():
    assert not (DATA/'freeze.json').exists(),'Never revise frozen labels'
    cases=read(DATA/'natural-inputs.json');labels=[];review=[]
    for c in cases:
        cid=c['case_id'];folder=DATA/'preannotation'/cid
        label=copy.deepcopy(read(folder/'label.raw.json'))
        segments={s['id']:s['text'] for s in c['meeting']['segments']}
        changes=[]
        for obj in label['tasks']+label['exclusions']:
            for e in obj['evidence']:
                if e['quote'] in segments.get(e['segment_id'],''):continue
                exact=[sid for sid,text in segments.items() if e['quote'] in text]
                if len(exact)==1:
                    changes.append(dict(kind='citation_segment',before=copy.deepcopy(e),after=exact[0]));e['segment_id']=exact[0]
                else:
                    pattern=re.escape(e['quote']).replace(r'\ ',r'[ \u00a0]')
                    match=re.search(pattern,segments.get(e['segment_id'],''))
                    if match:
                        before=copy.deepcopy(e);e['quote']=match.group();changes.append(dict(kind='citation_unicode_space',before=before,after=copy.deepcopy(e)));continue
                    fixes={
                        ('GP10','qm.covid_8.301'):('September 15','September15'),
                        ('GP09','qm.Bro003.838'):("don 't","don't"),
                        ('GN12','vc.196.74'):('那我现在作为','那那现在我那你现在作为'),
                        ('GN12','vc.196.77'):('结束。好不好？谢谢各位，谢谢。','结束。\n好不好？\n谢谢各位，谢谢。'),
                        ('GN27','qm.Bed010.604'):("aren 't","aren't"),
                        ('GN30','qm.Bed012.313'):('We have to','we have to'),
                        ('GN30','qm.Bed012.274'):("don 't","don't"),
                        ('GN32','qm.Bed009.180'):("won 't","won't"),
                        ('GN37','qm.education_8.122'):('Paper to note 3','paper to note 3'),
                    }
                    fix=fixes.get((cid,e['segment_id']))
                    if fix:
                        before=copy.deepcopy(e);e['quote']=e['quote'].replace(*fix);changes.append(dict(kind='citation_spelling',before=before,after=copy.deepcopy(e)))
        def note(reason):changes.append(dict(kind='source_boundary_review',reason=reason))
        def add_task(tid,sid,description,quote,owner=None,commitment='committed',condition=None):
            label['tasks'].append(dict(id=tid,requirement='required',action=description,object=description,scope=description,
                description=description,owner_ref=owner,owner_text='见原文及参与者映射；未明确的组织负责人不映射个人',
                commitment=commitment,condition=condition,due_text=None,evidence=[dict(segment_id=sid,quote=quote)],
                rationale='执行助手预测前核对原文，保留具体后续动作，未填造截止日。'))
        if cid=='GN06':
            t=label['tasks'][0];t.update(description='会后另找机会继续专门交流共建共享、看见未来话题。',scope='共建共享、看见未来；不强制推断的平台合作交付物')
            note('保留第一人称回头再聊的后续工作；缩减预标注推断的复杂范围。')
        if cid=='GN07':
            t=label['tasks'][0];t.update(requirement='optional',description='与马老师线下进一步交流。',scope='不要求推断的合作或市场资源交付',commitment='unknown')
            note('“我们可以线下好好聊一聊”可读为社交邀约或后续工作；原文没有对方承接，列optional并去除推断目的。')
        if cid=='GN08':
            for t in label['tasks']:t['requirement']='optional';t['due_text']=None
            note('两条均为面向不特定听众的会后服务邀约；有具体主题但没有确定接洽对象，optional；会后是时序而非截止。')
        if cid=='GN09':
            label['tasks'][0]['requirement']='optional'
            for t in label['tasks']:t['owner_ref']=None;t['owner_text']='相应公司/团队（发言人代表陈述，不等于个人承接）'
            note('T1希望/应该会可读为愿景或经营计划，optional；T2数字开店计划明确保留。公司计划不直接映射为个人任务。')
        additions={
            'GN11':('vc.15.39','对即将发行的潮玩进行技术迭代，支持 VR/AR 技术将 NFT 与现实世界呈现相结合。','比如说我们即将发行的一款潮玩，就会去花很多的时间做技术迭代，让大家可以在现实世界中可以运用 VR AR 的技术，可以不只在现虚拟世界拥有这个 NFT 同时你在现实世界中你要看到它上升的效果，它跟你的现实世界产生了强烈的这个共振，就像次元壁的这个破裂一样。'),
            'GN13':('vc.145.73','陆续向交易者推出大宗商品、区块链、期货等交易产品。','所以我们后续还会有一些大宗商品，还有区块链呐、期货等等的这些产品，会陆续地向各位交易者推出，让他们能够有更多的这个交易的途径，还有更多的选择。'),
            'GN18':('vc.198.71','后期发表目前正在制作的慕课。','第三个最直接的就是我们又要做慕课，我们慕课我们现在说的人慕课也在做，这个后期也要发表。'),
        }
        if cid in additions:
            sid,description,quote=additions[cid]
            label['tasks'].append(dict(id='T1',requirement='required',action=description,object=description,scope='只要求原句的工作目标，不推测实施细节',description=description,owner_ref=None,owner_text='发言人所代表的团队',commitment='committed',condition=None,due_text=None,evidence=[dict(segment_id=sid,quote=quote)],rationale='原文明确给出具体产品/课程的后续工作。已经开始的项目仍有明确未来步骤；不能因没有截止日或个人负责人而漏标。'))
            label['exclusions']=[x for x in label['exclusions'] if not any(e['segment_id']==sid for e in x['evidence'])]
            note('补充被预标注误当进度/宽泛计划的明确后续工作；原任务排除理由失效，以本次证据复核为准。')
        if cid=='GN20':
            for t in label['tasks']:t['requirement']='optional';t['commitment']='unknown';t['owner_ref']=None
            add_task('T3','vc.79.28','开展校园改造主题挑战赛，提供赋能讲座并举办方案设计竞赛，收集不少于20个改造方案、至少选择一个孵化。','那另外一个技巧上的活动是校园改造主题挑战赛。\n它包括两个部分，赋能讲座和方案设计竞赛。\n我们希望通过赋能讲座为学生提供一些系统的方法和手段，赋予青年人探索能力。\n同时举办方案设计竞赛，激发青年人的创造力，探索可行的技能。\n改造方案计划收集不少于 20 个改造方案，并且至少选择一个进行孵化。')
            add_task('T4','vc.79.28','汇编国内外校园低碳改造成功案例，并评估引入国内的可能性。','那案例汇编是说我们会，那就会面试，说我们会收集国内外校园的成功极端检盘案例，评估其引入国内的可能性。')
            add_task('T5','vc.79.29','在五个气候地区各选择目标高校开展碳排放评估，并据此探索不同地区和类型高校的低碳转型路径。','在五个每个区域中都会选择目标的高校来对其进行碳平放的评估，并根据此评估结果来探索中国不同地区不同类型的高校低碳转型路径。')
            label['exclusions']=[x for x in label['exclusions'] if not any(e['segment_id'] in ('vc.79.28','vc.79.29') and x['category']=='proposal' for e in x['evidence'])]
            note('具体工作包不能因出现在项目介绍或未指派个人而排除；三年量化愿景与当前三个明确工作包分开。资料可开放/可分享是能力或资源邀请，列optional。')
        if cid=='GN24':
            label['tasks'][0]['owner_ref']=None;label['tasks'][0]['owner_text']='主办方团队，个人执行者未定';label['tasks'][0]['due_text']=None
            note('“我们会安排收集”是主办方承诺，不直接指派主持人本人；随后是时序而非截止日。')
        if cid=='GN25':
            t=label['tasks'][0];t.update(description='Grad B 做一版构式分析，选取词汇与短语构式组成格架，足以解释部分对话，每个构式约半页，不要求完整精确分析。',scope='first cut；lexical + phrasal；能自上而下解释部分对话；每项约半页；无十项硬指标',due_text=None)
            owner=next(p['person_ref'] for p in c['meeting']['participants'] if p['speaker']=='Grad B')
            add_task('T2','qm.Bed011.554','与组内部分成员讨论需要寻找和分析哪些构式。',"Um sometime , I have to talk to some subset of the people in this group , at least about um what sort of constructions I 'm looking for .",owner)
            add_task('T3','qm.Bed011.639','如果大家决定 Grad B 应参加 Santa Barbara 会议，由团队支付其参会费用。',"So , if we all decide it 's a good idea for you to go then you 'll {disfmarker} we 'll pay for it .",commitment='conditional',condition='大家决定 Grad B 参会合适')
            label['exclusions']=[x for x in label['exclusions'] if not any(e['segment_id'] in ('qm.Bed011.554','qm.Bed011.637','qm.Bed011.639') for e in x['evidence'])]
            note('十项/暑期是精做构式的能力上限举例，不是first cut的数量和截止；补充会后沟通及明确if-then付款承诺，后者不要求条件现在已成立。')
        if cid=='GN28':
            next(t for t in label['tasks'] if t['id']=='T6')['requirement']='optional'
            note('Maybe下周演示可能是提案也可能是弱安排，optional，其他明确包选择/准备/运行任务保留。')
        if cid=='GN29':
            t=next(t for t in label['tasks'] if t['id']=='T3');t['scope']='前述系统改造职责的第一版；英文转换模块或整体改造方案两种指代均可接受，不能强加具体实现。';t['description']='Grad C 与 Johno 承担前述系统改造职责，给出第一版草稿。'
            note('T3承诺明确但that指代有歧义，不把最近英文模块指代当作唯一可接受答案。')
        if cid=='GN30':
            t3=next(t for t in label['tasks'] if t['id']=='T3');t4=next(t for t in label['tasks'] if t['id']=='T4')
            t3['evidence']+=t4['evidence'];t3['description']='下周二全体组会上展示并解释 Bayes 网/belief-net 的最终结果和运作方式。'
            label['tasks'].remove(t4)
            next(t for t in label['tasks'] if t['id']=='T5')['requirement']='optional'
            note('同场展示结果与解释运作属于同一交付，合并T3/T4，防止重复召回分母。网络运行后can start接接口是后续路线图与条件安排边界，optional。')
        if cid=='GN31':
            next(t for t in label['tasks'] if t['id']=='T2')['requirement']='optional'
            note('can potentially present与正式条件承诺不同，可能只是提案，列optional。带路给明确对象并获回应的T1保留。')
        if cid=='GN34':
            t=next(t for t in label['tasks'] if t['id']=='T3');t['time_window']=t['due_text'];t['due_text']=None
            for t in label['tasks']:
                if t['id'] in ('T2','T3','T4'):t['owner_ref']=None;t['owner_text']='HEFCW机构，由证人代表陈述'
            note('未来一年左右是执行窗口，机构工作不能仅凭发言者强行分配个人。')
        if cid=='GN33':
            add_task('T5','qm.education_15.135','会后向出席证人发送会议文字记录，供其核对准确性。','You will be sent a transcript to check for accuracy in due course')
            label['tasks'][-1]['action']='发送会议文字记录'
            note('发送与证人已明确承接的核对由不同主体独立完成，T4核对之外补充T5发送，不能以流程合并漏掉独立工作。')
        if cid=='GN35':
            add_task('T3','qm.education_9.195','为 EOTAS 和 PRU 设置最低课程要求，覆盖四个目的、读写、数学、数字能力及健康福祉，并允许按儿童和家庭需要补充适当内容。',"So, we'll be setting a minimum standard, as I said, around the purposes, around the cross-cutting themes and health and well-being")
            label['exclusions']=[x for x in label['exclusions'] if not any(e['segment_id']=='qm.education_9.195' for e in x['evidence'])]
            note('最低课程标准有明确制度对象和内容范围，是具体后续制定工作，不只是泛泛政策愿景。')
        if cid in ('GN36','GN38'):
            sid='qm.education_23.180' if cid=='GN36' else 'qm.education_2.141'
            tid='T7' if cid=='GN36' else 'T8'
            add_task(tid,sid,'会后将会议文字记录发送给出席证人，供其核对准确性。',"As usual, you'll be sent a transcript to check for accuracy following the meeting")
            label['exclusions']=[x for x in label['exclusions'] if not any(e['segment_id']==sid for e in x['evidence'])]
            note('补充其他Committee样例已纳入的同种会后文字记录核对流程，保持行政工作边界一致。')
        if cid.startswith('GN') and int(cid[2:])>=33:
            for t in label['tasks']:
                if '记录' in t['description'] and t.get('due_text'):
                    t['time_window']=t['due_text'];t['due_text']=None
                    note('会后/适当时候/收到后属于时序，不是截止期限；保留time_window与原文。')
        if changes:label['boundary_notes'].append('执行助手预测前复核意见见 annotation-review.json；与预标注冲突时以最终 tasks 为准。')
        label['annotation_method']='full-context model preannotation + assistant evidence/boundary review; not independent human gold'
        validate(c,label);labels.append(label)
        write(folder/'label.json',label)
        review.append(dict(case_id=cid,source_evidence_valid=True,changes=changes,full_independent_human_annotation=False))
    controls=read(DATA/'control-labels.json')
    target=next(l for l in controls if l['case_id']=='GC02a')
    target['tasks'].append(dict(id='T2',requirement='required',action='核实并回复',object='盘点差异记录导出范围',scope='冷库或整个东仓范围',description='主持人核实盘点差异记录应导出冷库还是整个东仓，并在会后回复。',owner_ref='host',owner_text='主持人',commitment='committed',condition=None,due_text=None,evidence=[dict(segment_id='GC02a.3',quote='范围我还要核实，会后再回复；先保留这件事。')],rationale='主持人明确承诺独立的核实和答复，不能因为是另一个任务的范围澄清就漏标。'))
    labels+=controls
    write(DATA/'labels.json',labels);write(DATA/'annotation-review.json',review)
    print('labels',len(labels),'required',sum(t['requirement']=='required' for l in labels for t in l['tasks']),'optional',sum(t['requirement']=='optional' for l in labels for t in l['tasks']))

if __name__=='__main__':main()
