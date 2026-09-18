#!/usr/bin/env python3
"""fetch_build_icons.py — 从 wowsinfo/data 镜像拉 升级 + 技能 PNG 图标。

产物:
  report/data/upgrade_icons/<name>.png            (~118 张, ~290 KB)
  report/data/skill_icons/<internal_name>.png     (~86 张, ~140 KB)

命名对应 GameParams 里的原始 name / internal_name —— 通过现成的
replayshark builds-dump 拿(builds.json 翻译过了,不能直接用),render_query
再通过 builds.json 的 ID→中文名查到要用哪个文件名。

大版本更新后跟 build_builds_json.py 一并重跑,刷新图标(WoWs 偶尔加新图)。
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "report" / "lib"))
from wowsbot import paths                # noqa: E402

DEFAULT_SPECS = Path(paths.SPECS_DIR)              # 原 BOT_HOME/"specs" —— 少了 report/
DEFAULT_REPLAYSHARK = Path(paths.REPLAYSHARK)      # 原 BOT_HOME/"replayshark" —— 少了 report/
DEFAULT_UPGRADE_DIR = Path(paths.UPGRADE_ICON_DIR)
DEFAULT_SKILL_DIR = Path(paths.SKILL_ICON_DIR)

UPGRADE_URL = "https://raw.githubusercontent.com/wowsinfo/data/master/live/app/assets/upgrades/{name}.png"
SKILL_URL   = "https://raw.githubusercontent.com/wowsinfo/data/master/live/app/assets/skills/{name}.png"


def dump_raw(replayshark: Path, specs: Path) -> dict:
    """跑 replayshark builds-dump 拿带原始 name 的 raw JSON。"""
    tmp = Path("/tmp/builds_raw.json")
    if tmp.exists():
        tmp.unlink()
    cmd = [str(replayshark), "--extracted", str(specs), "builds-dump", "-o", str(tmp)]
    print(f"+ {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True, stderr=sys.stderr)
    return json.loads(tmp.read_text("utf-8"))


def fetch(url: str, dest: Path, force: bool) -> tuple[bool, str]:
    """下载单个图标。返回 (ok, msg)。msg='skip' 表示已存在跳过。"""
    if dest.exists() and not force:
        return True, "skip"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "wows-bot/1"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        if not data or data[:8] != b"\x89PNG\r\n\x1a\n":
            return False, f"not PNG ({len(data)} bytes)"
        dest.write_bytes(data)
        return True, f"{len(data) // 1024} KB"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e).split("\n", 1)[0]


def fetch_set(label: str, items: list[tuple[str, Path, str]],
              force: bool, parallel: int) -> tuple[int, int, int]:
    """items: [(name, dest, url)] 并行下载,返回 (new_ok, skip, fail)。"""
    new_ok = skip = fail = 0
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futs = {ex.submit(fetch, url, dest, force): name
                for name, dest, url in items}
        for fut in as_completed(futs):
            name = futs[fut]
            success, msg = fut.result()
            if success and msg == "skip":
                skip += 1
            elif success:
                new_ok += 1
            else:
                fail += 1
                print(f"  ✗ {label}/{name}: {msg}", file=sys.stderr)
    return new_ok, skip, fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", type=Path, default=DEFAULT_SPECS,
                    help=f"WoWs extracted specs dir (default: {DEFAULT_SPECS})")
    ap.add_argument("--replayshark", type=Path, default=DEFAULT_REPLAYSHARK,
                    help=f"replayshark binary (default: {DEFAULT_REPLAYSHARK})")
    ap.add_argument("--upgrade-dir", type=Path, default=DEFAULT_UPGRADE_DIR)
    ap.add_argument("--skill-dir",   type=Path, default=DEFAULT_SKILL_DIR)
    ap.add_argument("--force", action="store_true",
                    help="重下已存在的图标")
    ap.add_argument("--parallel", type=int, default=8)
    args = ap.parse_args()

    rs = Path(os.environ.get("WOWS_REPLAYSHARK", str(args.replayshark)))
    if not rs.is_file():
        sys.exit(f"error: replayshark not found at {rs} (set WOWS_REPLAYSHARK or --replayshark)")

    raw = dump_raw(rs, args.specs)

    args.upgrade_dir.mkdir(parents=True, exist_ok=True)
    args.skill_dir.mkdir(parents=True, exist_ok=True)

    # 升级:用 GameParams 原始 name (PCM001_MainGun_Mod_I 这种)
    upgrade_names = sorted({m["name"] for m in raw["modernizations"]})
    upgrade_items = [(n, args.upgrade_dir / f"{n}.png", UPGRADE_URL.format(name=n))
                     for n in upgrade_names]
    # 技能:用 internal_name CamelCase
    skill_names = sorted({s["internal_name"] for s in raw["skills"]})
    skill_items = [(n, args.skill_dir / f"{n}.png", SKILL_URL.format(name=n))
                   for n in skill_names]

    print(f"  fetching {len(upgrade_items)} upgrade icons (parallel={args.parallel})",
          file=sys.stderr)
    u_new, u_skip, u_fail = fetch_set("upgrade", upgrade_items, args.force, args.parallel)
    print(f"  fetching {len(skill_items)} skill icons", file=sys.stderr)
    s_new, s_skip, s_fail = fetch_set("skill", skill_items, args.force, args.parallel)

    print(
        f"  upgrade: new={u_new} skip={u_skip} fail={u_fail} | "
        f"skill: new={s_new} skip={s_skip} fail={s_fail}",
        file=sys.stderr,
    )
    if u_fail or s_fail:
        print("  (失败的多半是 wowsinfo/data 镜像没收录的旧/小众 mod;render 端兜底显示文字)",
              file=sys.stderr)


if __name__ == "__main__":
    main()
