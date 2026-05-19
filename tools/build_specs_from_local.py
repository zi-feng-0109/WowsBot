# -*- coding: utf-8 -*-
"""
从本地已经解包的 wows-toolkit extracted/<version>/vfs/ 目录拼出 specs_out/
(避免走 GitHub 拉 wowsinfo/data)。

输出:
  specs_out/
    metadata.toml
    scripts/        ← from extracted/<ver>/vfs/scripts/
    content/
      GameParams.data
"""
import re
import shutil
import sys
from pathlib import Path

EXTRACTED_ROOT = Path(r"C:\Users\29801\Desktop\minimap\extracted")
OUT_DIR = Path(__file__).resolve().parent.parent / "specs_out"


def find_latest():
    """挑 extracted/ 下版本号最大的目录,返回 (version, build, path)。"""
    pat = re.compile(r"^(\d+(?:\.\d+)+)_(\d+)$")
    cands = []
    for sub in EXTRACTED_ROOT.iterdir():
        if not sub.is_dir():
            continue
        m = pat.match(sub.name)
        if not m:
            continue
        ver_tuple = tuple(int(x) for x in m.group(1).split('.'))
        build = int(m.group(2))
        cands.append(((ver_tuple, build), m.group(1), build, sub))
    if not cands:
        sys.exit(f"no version dir under {EXTRACTED_ROOT}")
    cands.sort(key=lambda x: x[0])
    _, ver_str, build, path = cands[-1]
    return ver_str, build, path


def main():
    ver, build, src = find_latest()
    print(f"using {src.name} (version {ver} build {build})")

    src_scripts = src / "vfs" / "scripts"
    src_gameparams = src / "vfs" / "content" / "GameParams.data"
    for p in (src_scripts, src_gameparams):
        if not p.exists():
            sys.exit(f"missing: {p}")

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)
    (OUT_DIR / "content").mkdir()

    print(f"copy scripts/ ...")
    shutil.copytree(src_scripts, OUT_DIR / "scripts")
    print(f"copy GameParams.data ({src_gameparams.stat().st_size/1e6:.1f} MB) ...")
    # 用 copyfile 直接读 symlink target
    shutil.copyfile(src_gameparams, OUT_DIR / "content" / "GameParams.data")

    (OUT_DIR / "metadata.toml").write_text(
        f'version = "{ver}"\nbuild = {build}\n', encoding='utf-8'
    )

    size_mb = sum(p.stat().st_size for p in OUT_DIR.rglob('*') if p.is_file()) / 1e6
    print(f"\ndone -> {OUT_DIR} ({size_mb:.1f} MB)")
    print(f"\nscp to server:")
    print(f"  scp -r {OUT_DIR} zifeng@192.168.31.252:/tmp/specs_new/")


if __name__ == '__main__':
    main()
