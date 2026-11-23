import csv
import hashlib
import html
import io
import json
import zipfile
import copy
import re
from pathlib import Path
from .storage import dumps

TEMPLATES = {'design': {'name': '设计评审', 'sections': ['已确认方案', '方案权衡', '待验证问题', '材料与证据']},
             'sync': {'name': '项目同步', 'sections': ['已报告进展', '任务与阻塞', '待确认分工', '下次建议议题']}}


def ordered_sections(answer, template=None):
    if not template:return answer['sections']
    groups=([r'方案|决定|基线',r'比较|权衡|成本|体积|体验',r'风险|验证|未决|未解决',r'分工|任务|建议|议程']
            if template=='design' else [r'进展|汇报',r'任务|分工|阻塞',r'决定|方案|基线',r'建议|议程|验证'])
    def order(section):
        return next((i for i,pattern in enumerate(groups) if re.search(pattern,section['title'])),len(groups))
    return sorted(answer['sections'],key=order)


def render(answer, evidence, template=None):
    out = ['# '+answer['title'], '', answer['summary'], '']
    for s in ordered_sections(answer,template):
        label = {'fact': '原话依据', 'suggestion': '建议', 'unknown': '待确认'}[s['kind']]
        out.extend(['## '+s['title']+' · '+label, '', s['text'], '', ' '.join('['+i+']' for i in s['evidence_ids']), ''])
    if answer['columns']:
        escape = lambda s: s.replace('|', '\\|').replace('\n', '<br>')
        out.extend(['| '+' | '.join(map(escape, answer['columns']))+' |', '| '+' | '.join('---' for _ in answer['columns'])+' |'])
        out.extend('| '+' | '.join(map(escape, r['cells']))+' |' for r in answer['rows'])
    out.extend(['', '## 待确认', *['- '+q for q in answer['questions']], '', '## 证据索引'])
    for e in evidence:
        position=e.get('url') or f"原会议 {e['source_start_ms']/1000:.1f}s"
        out.extend(['', f"### {e['id']}", f"{e['meeting_id']} · {e['speaker']} · {position} · {e['provenance']}", '', e['quote']])
    return '\n'.join(out)


def html_page(answer,evidence,children,template=None):
    esc=lambda value:html.escape(str(value))
    title=TEMPLATES[template]['name']+'会议交付文档' if template else answer['title']
    pieces=['<!doctype html><html lang="zh"><meta charset="utf-8"><title>'+esc(answer['title'])+'</title>',
        '<style>body{max-width:960px;margin:40px auto;font:16px/1.8 system-ui;padding:24px;color:#26334b}h1{color:#2453a2}h2{font-size:21px;margin-top:28px}p{white-space:pre-wrap}table{width:100%;border-collapse:collapse}td,th{padding:10px;border:1px solid #dce3ee;text-align:left;vertical-align:top}th{background:#eef3fb}small{color:#66758b}blockquote{background:#f5f7fb;margin:12px 0;padding:12px;border-left:3px solid #a7bfeb}a{color:#2862ba}</style><body>',
        '<h1>'+esc(title)+'</h1>']
    if template:pieces.append('<p>输出格式：'+esc(TEMPLATES[template]['name'])+'</p>')
    pieces.append('<p>'+esc(answer['summary'])+'</p>')
    refs=lambda ids:' '.join('<a href="#'+esc(i)+'">[依据]</a>' for i in ids)
    for s in ordered_sections(answer,template):
        pieces.extend(['<h2>'+esc(s['title'])+'</h2>','<small>'+esc({'fact':'证据事实','suggestion':'建议','unknown':'待确认'}[s['kind']])+'</small>',
                       '<p>'+esc(s['text'])+'</p>',refs(s['evidence_ids'])])
    if answer['columns']:
        pieces.append('<table><thead><tr>'+''.join('<th>'+esc(c)+'</th>' for c in answer['columns'])+'<th>依据</th></tr></thead><tbody>')
        for row in answer['rows']:pieces.append('<tr>'+''.join('<td>'+esc(c)+'</td>' for c in row['cells'])+'<td>'+refs(row['evidence_ids'])+'</td></tr>')
        pieces.append('</tbody></table>')
    pieces.append('<h2>待确认</h2><ul>'+''.join('<li>'+esc(q)+'</li>' for q in answer['questions'])+'</ul>')
    if children:
        pieces.append('<h2>关联材料</h2><ul>')
        for a in children:pieces.append(f'<li><a href="材料/{esc(a["id"])}/主文档.html">{esc(a["title"])} · v{a["version"]}</a></li>')
        pieces.append('</ul>')
    pieces.append('<h2>证据索引</h2>')
    for e in evidence:
        pieces.extend(['<h3 id="'+esc(e['id'])+'">'+esc(e['id'])+'</h3>',
                       '<small>'+esc(e['meeting_id']+' · '+e['speaker']+' · '+e['provenance'])+'</small>',
                       '<blockquote>'+esc(e['quote'])+'</blockquote>'])
        if e.get('url','').startswith(('https://','http://')):
            pieces.append('<a href="'+esc(e['url'])+'">来源网页</a>')
    return '\n'.join(pieces)+ '</body></html>'


def save_artifact(storage, job, result, parent=None):
    aid = job['id']
    folder = storage.root / 'artifacts' / aid
    folder.mkdir(parents=True, exist_ok=True)
    evidence=copy.deepcopy(result['evidence'])
    for e in evidence:
        if e['provenance'].startswith('external'):
            e['quote']=' '.join(e['quote'].split()[:24])[:160]+' …'
    content = render(result['answer'], evidence,job.get('template') if job['kind']=='handover' else None)
    if job['kind']=='handover':
        template=TEMPLATES[job['template']]
        content='# '+template['name']+'交付包\n\n'+ '阅读顺序：'+' → '.join(template['sections'])+'\n\n'+content
        for child in result.get('included_artifacts', []):
            content+=f"\n- [{child['title']} · v{child['version']}](材料/{child['id']}/主文档.md)"
    (folder / '主文档.md').write_text(content, encoding='utf-8')
    page=html_page(result['answer'],evidence,result.get('included_artifacts',[]),job.get('template') if job['kind']=='handover' else None)
    (folder / '主文档.html').write_text(page, encoding='utf-8')
    files = ['主文档.md', '主文档.html']
    if result['answer']['columns']:
        with (folder / '比较表.csv').open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            def safe(value):
                return "'"+value if value.lstrip().startswith(('=', '+', '-', '@')) else value
            writer.writerow([safe(v) for v in result['answer']['columns']])
            writer.writerows([safe(v) for v in r['cells']] for r in result['answer']['rows'])
        files.append('比较表.csv')
    manifest = {'artifact_id': aid, 'version': (parent['version']+1) if parent else 1,
                'parent_id': parent['id'] if parent else None, 'scope': job['scope'],
                'kind': job['kind'], 'template': job.get('template'), 'evidence': evidence,
                'business_snapshot': result.get('business', {}), 'included_artifacts': result.get('included_artifacts', [])}
    (folder / '引用与材料清单.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    files.append('引用与材料清单.json')
    # An explicit allowlist prevents packaging model logs, keys or the business database.
    with zipfile.ZipFile(folder / '交付包.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for name in files:
            z.write(folder / name, name)
        for child in result.get('included_artifacts', []):
            child_folder = storage.root / 'artifacts' / child['id']
            for name in child['files']:
                if name != '交付包.zip':
                    z.write(child_folder / name, '材料/'+child['id']+'/'+name)
    files.append('交付包.zip')
    artifact = {'id': aid, 'project_id': job['scope']['project_id'], 'title': TEMPLATES[job['template']]['name']+'会议交付文档' if job['kind']=='handover' else result['answer']['title'],
                'scope': job['scope'], 'version': manifest['version'], 'parent_id': manifest['parent_id'],
                'kind': job['kind'], 'base_kind':parent.get('base_kind',parent['kind']) if parent else job['kind'],
                'files': files, 'sha256': hashlib.sha256(content.encode()).hexdigest(),
                'result': result}
    with storage.connect() as db:
        db.execute('INSERT OR REPLACE INTO artifacts VALUES (?,?,?)', (aid, artifact['project_id'], dumps(artifact)))
    return artifact
