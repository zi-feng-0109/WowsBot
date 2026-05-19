# -*- coding: utf-8 -*-
"""
从本地已经解包的 wows-toolkit extracted/<version>_<build>/vfs/ 目录,
拼出战报渲染器要的 specs_out/ (免去访问 GitHub 拉 wowsinfo/data)。

用法:
  python build_specs_from_local.py [--extracted PATH] [--out PATH]

不传参时:
  --extracted 从环境变量 WOWS_EXTRACTED_ROOT 读;再没有就报错并提示
  --out       默认写到 <repo>/specs_out/

输出结构:
  specs_out/
    metadata.toml
    scripts/        ← from <extracted>/vfs/scripts/
    content/
      GameParams.data
"""
import argparse
import os
import re
import shutil
import sys
from pathlib import Path


def find_latest(extracted_root: Path):
    """挑 extracted_root 下版本号最大的 <version>_<build>/ 子目录。"""
    pat = re.compile(r"^(\d+(?:\.\d+)+)_(\d+)$")
    cands = []
    for sub in extracted_root.iterdir():
        if not sub.is_dir():
            continue
        m = pat.match(sub.name)
        if not m:
            continue
        ver_tuple = tuple(int(x) for x in m.group(1).split('.'))
        build = int(m.group(2))
        cands.append(((ver_tuple, build), m.group(1), build, sub))
    if not cands:
        sys.exit(f"error: 没找到 <version>_<build> 子目录 (如 15.3.0_12267945) 在 {extracted_root}")
    cands.sort(key=lambda x: x[0])
    _, ver_str, build, path = cands[-1]
    return ver_str, build, path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--extracted", type=Path,
                    default=os.environ.get("WOWS_EXTRACTED_ROOT"),
                    help="wows-toolkit 解包根目录 (覆盖 $WOWS_EXTRACTED_ROOT)")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parent.parent / "specs_out",
                    help="specs 输出目录 (默认仓库根/specs_out)")
    args = ap.parse_args()

    if args.extracted is None:
        sys.exit(
            "error: 没指定 --extracted,也没设 WOWS_EXTRACTED_ROOT 环境变量。\n"
            "  例: python build_specs_from_local.py --extracted "
            "%APPDATA%/wows-toolkit/game_data/builds"
        )
    extracted = Path(args.extracted).expanduser().resolve()
    if not extracted.is_dir():
        sys.exit(f"error: --extracted 不是目录: {extracted}")

    ver, build, src = find_latest(extracted)
    print(f"using {src.name} (version {ver} build {build})")

    src_scripts = src / "vfs" / "scripts"
    src_gameparams = src / "vfs" / "content" / "GameParams.data"
    for p in (src_scripts, src_gameparams):
        if not p.exists():
            sys.exit(f"error: 缺文件: {p}")

    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "content").mkdir()

    print(f"copy scripts/ ...")
    shutil.copytree(src_scripts, out / "scripts")
    print(f"copy GameParams.data ({src_gameparams.stat().st_size / 1e6:.1f} MB) ...")
    shutil.copyfile(src_gameparams, out / "content" / "GameParams.data")

    (out / "metadata.toml").write_text(
        f'version = "{ver}"\nbuild = {build}\n', encoding='utf-8'
    )

    size_mb = sum(p.stat().st_size for p in out.rglob('*') if p.is_file()) / 1e6
    print(f"\ndone -> {out} ({size_mb:.1f} MB)")
    print(f"\n下一步 scp 到服务器 (改成你自己的 user/host/path):")
    print(f"  scp -r {out} <user>@<bot-host>:/tmp/specs_new/")


if __name__ == '__main__':
    main()
