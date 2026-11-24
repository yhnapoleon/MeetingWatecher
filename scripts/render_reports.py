"""Render the three Markdown reports to local PDFs with installed Microsoft Edge."""
from pathlib import Path
import argparse
import html
import posixpath
import re
import markdown
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CSS = '''
@page { size:A4; margin:17mm 16mm 18mm; }
body { font-family:"Microsoft YaHei",sans-serif; font-size:10pt; line-height:1.72; color:#25334b; }
h1 { font-size:25pt; line-height:1.35; color:#142644; margin:0 0 22px; padding-bottom:14px; border-bottom:4px solid #2b66cc; }
h2 { font-size:15pt; color:#1c4c89; margin:27px 0 10px; break-after:avoid; }
h3 { break-after:avoid; } p { margin:9px 0; orphans:3; widows:3; break-inside:avoid; }
table { border-collapse:collapse; width:100%; table-layout:fixed; font-size:8.6pt; margin:14px 0; break-inside:avoid; }
thead { display:table-header-group; } th { background:#eaf0f9; color:#15355e; font-weight:600; }
td,th { border:1px solid #cdd8e7; padding:7px 8px; vertical-align:top; overflow-wrap:anywhere; }
tr { break-inside:avoid; } img { display:block; width:100%; height:auto; margin:14px 0; break-inside:avoid; }
pre { background:#f1f4f8; border-left:3px solid #b8c9e3; padding:10px; font-size:8pt; line-height:1.5; white-space:pre-wrap; overflow-wrap:anywhere; break-inside:avoid; }
code { font-family:Consolas,"Microsoft YaHei",monospace; } a { color:#235eaa; text-decoration:none; overflow-wrap:anywhere; }
li { margin:5px 0; } strong { color:#172f51; }
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reports', nargs='+', choices=['RETRO', 'TUNING', 'CONFIG'], default=['RETRO', 'TUNING', 'CONFIG'])
    args = parser.parse_args()
    output = ROOT / '交付/项目文档'
    temp = ROOT / 'tmp/docs'
    output.mkdir(parents=True, exist_ok=True)
    temp.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 860}, device_scale_factor=1.5)
        page.goto((ROOT / 'docs/images/architecture.svg').as_uri())
        page.locator('svg').screenshot(path=str(ROOT / 'docs/images/architecture.png'))
        for name, title in [('RETRO','会议助手_项目复盘'), ('TUNING','会议助手_任务与决策提取调优'), ('CONFIG','会议助手_配置与运行说明')]:
            if name not in args.reports:
                continue
            body = markdown.markdown((ROOT / f'docs/{name}.md').read_text(encoding='utf-8-sig'), extensions=['tables','fenced_code'])
            # PDF links should remain usable outside this workstation; images stay local.
            def public_link(match):
                target = match.group(1)
                if '://' in target or target.startswith('#'):
                    return match.group(0)
                return 'href="https://github.com/yhnapoleon/MeetingWatecher/blob/main/' + posixpath.normpath('docs/' + target) + '"'
            body = re.sub(r'href="([^"]+)"', public_link, body)
            source = temp / f'{name}.html'
            source.write_text(f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><base href="{(ROOT / "docs").as_uri()}/"><title>{html.escape(title)}</title><style>{CSS}</style></head><body>{body}</body></html>', encoding='utf8')
            page.goto(source.as_uri(), wait_until='networkidle')
            page.evaluate('document.fonts.ready')
            missing = page.locator('img').evaluate_all('(xs)=>xs.filter(x=>!x.complete || !x.naturalWidth).map(x=>x.src)')
            if missing:
                raise ValueError(missing)
            page.pdf(path=str(output / f'{title}.pdf'), format='A4', print_background=True,
                     display_header_footer=True, header_template='<span></span>',
                     footer_template='<div style="width:100%;text-align:center;font-size:8px;color:#708097">MeetingWatcher · <span class="pageNumber"></span> / <span class="totalPages"></span></div>')
            print(title + '.pdf')
        browser.close()


if __name__ == '__main__':
    main()
