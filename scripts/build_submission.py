"""Create a curated submission folder; never traverse the working tree wholesale."""
import hashlib
import ast
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '交付/会议助手_提交材料_2026-11-23'
CORE_TESTS = ['test_unclear_intent', 'test_context_system', 'test_requirement_review',
              'test_report_routing', 'test_context_state', 'test_context_v5_regressions']
REPORTS = ['RETRO.md', 'TUNING.md', 'CONFIG.md', 'design.md', 'EVALUATION.md',
           'GitHub同步与复现范围.md', 'annotation.md', 'context-v5-task-metrics.md',
           '两场会议重测_v19_任务与决策指标.md', '新会议双场泛化测试_语义复核_v19.md',
           '跨会议真人演示与实测.md', '任务边界与条件保留_实施结果.md', '扩展评测_未解决问题清单.md',
           '完整会议证据协议_修复结果.md', '完整会议重跑与第二场测试.md',
           '模糊意向分类_实施与验证.md', '决策提取三个系统缺口_实施与验证.md',
           '会中纪要增量更新_实现与验证.md', '第二场AI视图修订_实现与验证.md',
           'AI参会助手_双场会议演示剧本.md', '会议任务跟进_实施与录制.md']

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    files = {}

    def add(source, target, runtime=True):
        source = Path(source).as_posix()
        assert (ROOT / source).is_file(), source
        assert target not in files, target
        files[target] = {'source': source, 'runtime_path': source if runtime else None}

    def tree(source, dest, extensions):
        for p in sorted((ROOT / source).rglob('*')):
            if p.is_file() and p.suffix in extensions and '__pycache__' not in p.parts:
                add(p.relative_to(ROOT), dest + '/' + p.relative_to(ROOT / source).as_posix())

    # Data: final inputs/labels/provenance, with small review clips; no raw corpus archives.
    for directory in ['mvp-v1', 'context-prerequisites-v1', 'context-probes-v1', 'action-semantics-v2', 'licenses']:
        for p in sorted((ROOT / 'data' / directory).rglob('*')):
            if p.is_file() and not any(x in p.parts for x in ['raw', '__pycache__']):
                if p.suffix in {'.md', '.json', '.jsonl', '.txt', '.csv', '.mp4', '.py'}:
                    add(p.relative_to(ROOT), '01_数据集/' + p.relative_to(ROOT / 'data').as_posix())
    for name in ['README.md', 'annotation-guide.md', 'annotation-review.json', 'control-inputs.json',
                 'control-labels.json', 'dataset-stats.json', 'freeze.json', 'labels.json',
                 'natural-inputs.json', 'provenance.json', 'sources-and-rights.md', 'pinned-vcsum-verification.json']:
        add('data/generalization-v1/' + name, '01_数据集/generalization-v1/' + name)
    for name in ['AMI_LICENCE.txt', 'vcsum_LICENSE']:
        add('data/mvp-v1/raw/' + name, '01_数据集/mvp-v1/raw/' + name)

    for source in ['meeting_eval', 'meeting_copilot', 'prompts', 'config', 'examples']:
        tree(source, '02_代码与配置/' + source, {'.py', '.json', '.txt', '.md', '.jsonl'})
    for name in ['README.md', '.env.example', '.gitattributes']:
        add(name, '02_代码与配置/' + name)
    scripts = ['run_action_baseline.py', 'run_current.py', 'verify_release_evidence.py',
               'score_mvp_actions.py', 'verify_mvp_dataset.py', 'score_recap.py']
    for name in scripts:
        add('scripts/' + name, '02_代码与配置/scripts/' + name)
    test_names = set(CORE_TESTS + ['test_copilot', 'test_copilot_incremental', 'test_copilot_work'])
    pending = list(test_names)
    while pending:
        for node in ast.walk(ast.parse((ROOT / 'tests' / (pending.pop() + '.py')).read_text(encoding='utf-8-sig'))):
            imports = [node.module] if isinstance(node, ast.ImportFrom) else [n.name for n in node.names] if isinstance(node, ast.Import) else []
            for name in imports:
                if name and name.startswith('test_') and name not in test_names:
                    test_names.add(name)
                    pending.append(name)
    for name in sorted(test_names):
        add('tests/' + name + '.py', '02_代码与配置/tests/' + name + '.py')
    tree('tests/fixtures', '02_代码与配置/tests/fixtures', {'.json'})
    for source in ['src', 'public', 'worker', 'tests', '.openai']:
        tree('demo/' + source, '02_代码与配置/demo/' + source,
             {'.ts', '.tsx', '.js', '.jsx', '.mjs', '.css', '.svg', '.json', '.txt', '.md', '.mp4', '.mp3'})
    for name in ['README.md', 'package.json', 'package-lock.json', 'tsconfig.json', 'vite.config.mjs', 'index.html', '.npmrc',
                 'scripts/prepare-sites-build.mjs']:
        add('demo/' + name, '02_代码与配置/demo/' + name)

    # Published frozen evidence. These filenames are the release contract.
    base = 'runs/2026-11-18-two-unseen-v19'
    for name in ['evaluation.json', 'selection-audit.json', 'scoring-clarification.json']:
        add(base + '/' + name, '03_评测日志与结果/2026-11-18-two-unseen-v19/' + name)
    selected = ['input.json', '完整会议原文.txt', 'reference.json', 'reference-original.json', 'corpus-reference.xml',
                'rubric-before-run.json', 'manifest.json', 'inference.json', 'config.json', 'summary.json',
                'evaluation.json', 'annotations.json', 'acceptance.json', 'minutes.md', 'requirements.json',
                '标注与可接受答案.md', '人工逐条复核.md']
    for mid in ['IS1000a', 'TS3003b']:
        for name in selected:
            add(base + '/' + mid + '/' + name, '03_评测日志与结果/2026-11-18-two-unseen-v19/' + mid + '/' + name)
    for name in ['review-and-score.json', 'review.md', 'verification.json']:
        add('runs/2026-11-17-full-baseline/task-metrics/' + name,
            '03_评测日志与结果/历史115场景评分/' + name)
    for name in ['评测用例索引.csv', 'second-view-v5-2026-11-23.json', 'incremental-summary-2026-11-23.json',
                 'live-actions-demo-2026-11-23.json']:
        add('docs/evidence/' + name, '03_评测日志与结果/产品与评测索引/' + name)

    for name in REPORTS:
        add('docs/' + name, '04_技术报告/' + name)
    # Only images actually referenced by the selected documents or README.
    images = {'docs/images/architecture.svg', 'docs/images/architecture.mmd'}
    for name in REPORTS:
        source = ROOT / 'docs' / name
        for ref in re.findall(r'!\[[^\]]*\]\(([^)]+)\)', source.read_text(encoding='utf-8-sig')):
            candidate = (source.parent / ref).resolve()
            if candidate.is_file():
                images.add(candidate.relative_to(ROOT).as_posix())
    for ref in re.findall(r'!\[[^\]]*\]\(([^)]+)\)', (ROOT / 'README.md').read_text(encoding='utf8')):
        images.add(ref)
    for name in sorted(images):
        add(name, '04_技术报告/images/' + Path(name).name)
    for name in ['会议助手_项目复盘.pdf', '会议助手_任务与决策提取调优.pdf', '会议助手_配置与运行说明.pdf']:
        add('交付/项目文档/' + name, '04_技术报告/' + name, False)
    source = '交付/双场演示_第二场修订版/'
    add(source + '会议助手_双场演示_第二场修订版.mp4', '05_演示视频/会议助手_双场完整演示.mp4', False)
    add(source + '观看说明与时间表.md', '05_演示视频/观看说明与时间表.md', False)
    for name in ['供电方案比较_修订版.html', '本次跟进与评测证据.html']:
        add(source + name, '03_评测日志与结果/当前应用生成材料/' + name, False)
    add('scripts/submission_entry.py', '复现.py', False)
    add('docs/提交说明与复现入口.md', '00_提交说明与复现入口.md', False)

    mapping = {v['source']: k for k, v in files.items()}
    omitted_links = set()
    import os
    for target, row in files.items():
        src, dst = ROOT / row['source'], OUT / target
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == '.md':
            content = src.read_text(encoding='utf-8-sig')
            def link(match):
                label, ref = match.group(1), match.group(2)
                if ref.startswith(('http:', 'https:', '#', 'mailto:')):
                    return match.group(0)
                file, sep, anchor = ref.partition('#')
                candidate = (src.parent / file).resolve()
                try:
                    original = candidate.relative_to(ROOT).as_posix()
                except ValueError:
                    original = ref
                if original in mapping:
                    relative = os.path.relpath(OUT / mapping[original], dst.parent).replace('\\', '/')
                    return '[' + label + '](' + relative + (sep + anchor if sep else '') + ')'
                omitted_links.add(original)
                return label + '（原工作区专项记录）'
            content = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, content)
            dst.write_text(content, encoding='utf8')
        else:
            shutil.copy2(src, dst)
        row['path'] = target
        row['bytes'] = dst.stat().st_size
        row['sha256'] = hashlib.sha256(dst.read_bytes()).hexdigest()

    (OUT / '提交文件清单.json').write_text(json.dumps({'files': list(files.values()),
        'historical_references_not_required_for_entry': sorted(omitted_links)}, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'folder': str(OUT), 'files': len(files),
                      'size_mb': round(sum(x['bytes'] for x in files.values()) / 1e6, 1)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
