#!/usr/bin/env python3
"""build_builds_json.py — generate report/data/builds.json.

Pipeline:
  1. run `replayshark builds-dump --extracted <specs>` to get raw IDs + name
     keys (Modernization / Exterior / Crew / CrewSkill)
  2. translate each name via report/data/zh_sg.mo (polib)
  3. write report/data/builds.json,Python 渲染端 (render_query.py) load 一次缓存

为什么需要这个:
  replay 里 ship.build 给的是 GameParamId (u32/u64),不是中文。这份 json
  把 "PCM001_MainGun_Mod_I" → "主炮组修改型 1" 的映射打表,/查询 PNG 渲染
  时直接查表,不用每次跑 wowsunpack。

每次游戏大版本更新后重跑 (UPDATE.md 里有挂)。
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


BOT_HOME = Path(__file__).resolve().parent.parent
DEFAULT_SPECS = BOT_HOME / "specs"
DEFAULT_MO = BOT_HOME / "report" / "data" / "zh_sg.mo"
DEFAULT_OUT = BOT_HOME / "report" / "data" / "builds.json"
DEFAULT_REPLAYSHARK = BOT_HOME / "replayshark"


def run_replayshark(replayshark: Path, specs: Path) -> dict:
    """运行 replayshark builds-dump 拿原始 ID + name 映射。"""
    tmp = Path("/tmp/builds_raw.json")
    if tmp.exists():
        tmp.unlink()
    cmd = [str(replayshark), "--extracted", str(specs), "builds-dump", "-o", str(tmp)]
    print(f"+ {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True, stderr=sys.stderr)
    return json.loads(tmp.read_text("utf-8"))


def load_translations(mo_path: Path) -> dict[str, str]:
    import polib  # 仅本脚本依赖,bot 运行时不需要
    mo = polib.mofile(str(mo_path))
    return {e.msgid: e.msgstr for e in mo if e.msgstr}


def translate_modernization(name: str, tr: dict[str, str]) -> Optional[str]:
    """改装件:键固定为 IDS_TITLE_<NAME_UPPER>。"""
    key = f"IDS_TITLE_{name.upper()}"
    return tr.get(key)


def translate_exterior(name: str, tr: dict[str, str]) -> Optional[str]:
    """旗帜/伪装:键固定为 IDS_<NAME_UPPER>。"""
    key = f"IDS_{name.upper()}"
    return tr.get(key)


def translate_crew(name: str, tr: dict[str, str]) -> Optional[str]:
    """舰长:WG 用 IDS_<LAST_PART_UPPER> (suffix after first '_')。
    覆盖率约 76%,剩下的多是非人名 token (DefaultCrew / 玩家名),回退原文。"""
    parts = name.split("_", 1)
    if len(parts) == 2:
        key = f"IDS_{parts[1].upper()}"
        return tr.get(key)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--specs", type=Path, default=DEFAULT_SPECS,
                    help=f"WoWs extracted specs dir (default: {DEFAULT_SPECS})")
    ap.add_argument("--mo", type=Path, default=DEFAULT_MO,
                    help=f"zh_sg.mo path (default: {DEFAULT_MO})")
    ap.add_argument("--replayshark", type=Path, default=DEFAULT_REPLAYSHARK,
                    help=f"replayshark binary (default: {DEFAULT_REPLAYSHARK})")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"output (default: {DEFAULT_OUT})")
    args = ap.parse_args()

    # WOWS_REPLAYSHARK env override (与 wows_report 同款)
    rs = Path(os.environ.get("WOWS_REPLAYSHARK", str(args.replayshark)))
    if not rs.is_file():
        sys.exit(f"error: replayshark not found at {rs} (set WOWS_REPLAYSHARK or --replayshark)")

    raw = run_replayshark(rs, args.specs)
    tr = load_translations(args.mo)
    print(f"  loaded {len(tr)} translation entries from {args.mo}", file=sys.stderr)

    out: dict = {
        "version": raw.get("version", "?"),
        "build":   raw.get("build", 0),
        "modernization": {},
        "exterior":      {},
        "crew":          {},
        "skill":         {},
    }

    miss_mod = miss_ext = miss_crew = miss_skill = 0
    for m in raw["modernizations"]:
        zh = translate_modernization(m["name"], tr)
        if zh is None:
            miss_mod += 1
            zh = m["name"]  # fallback
        out["modernization"][str(m["id"])] = zh

    for e in raw["exteriors"]:
        zh = translate_exterior(e["name"], tr)
        if zh is None:
            miss_ext += 1
            zh = e["name"]
        out["exterior"][str(e["id"])] = zh

    for c in raw["crews"]:
        zh = translate_crew(c["name"], tr)
        if zh is None:
            miss_crew += 1
            zh = c["name"]
        out["crew"][str(c["id"])] = zh

    for s in raw["skills"]:
        zh = tr.get(s["name_key"])
        if zh is None:
            miss_skill += 1
            zh = s["internal_name"]
        out["skill"][str(s["skill_type"])] = {"name": zh, "tier": s["tier"]}

    n = {k: len(v) for k, v in out.items() if isinstance(v, dict)}
    print(
        f"  modernization {n['modernization']} (miss {miss_mod}) | "
        f"exterior {n['exterior']} (miss {miss_ext}) | "
        f"crew {n['crew']} (miss {miss_crew}) | "
        f"skill {n['skill']} (miss {miss_skill})",
        file=sys.stderr,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
    print(f"  wrote {args.out} ({args.out.stat().st_size / 1024:.1f} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
