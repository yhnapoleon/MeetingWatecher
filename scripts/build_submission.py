"""Package project materials in the Agent1 / Agent2 delivery format."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent / 'MeetingWatcher_项目材料'

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = json.loads((ROOT / 'scripts/submission_files.json').read_text(encoding='utf8'))
    manifest = []
    with zipfile.ZipFile(OUT / '04_源码_MeetingWatcher.zip', 'w', zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
        for name in paths:
            p = ROOT / name
            assert p.is_file(), name
            manifest.append({'path': name, 'bytes': p.stat().st_size,
                             'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
            archive.write(p, name)
        archive.writestr('源码文件清单.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    files = {
        '交付/项目文档/会议助手_项目复盘.pdf': '01_项目复盘报告.pdf',
        '交付/项目文档/会议助手_任务与决策提取调优.pdf': '02_任务与决策提取调优记录.pdf',
        '交付/项目文档/会议助手_配置与运行说明.pdf': '03_配置说明.pdf',
        'docs/images/architecture.png': '架构图.png',
        'data/测试用例_115场景.json': '测试用例_115场景.json',
        '交付/双场演示_第二场修订版/会议助手_双场演示_第二场修订版.mp4': '演示视频.mp4',
        'docs/提交说明与复现入口.md': '00_阅读说明.md',
    }
    for src, dst in files.items():
        shutil.copy2(ROOT / src, OUT / dst)
    print(json.dumps({'folder': str(OUT), 'source_files': len(manifest),
                      'delivery_files': len(files)+1}, ensure_ascii=False))

if __name__ == '__main__':
    main()
