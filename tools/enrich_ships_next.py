#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 next_ships / is_premium / is_special 增量补进现有 report/data/ships.json。

为什么单独一个脚本:build_ships_json.py 跑全量重建要 GameParams.data(换设备后
不一定有);而科技树(/线)只需要 next_ships,这些纯从 WG public API 就能拿,不碰
GameParams。所以提供这个轻量增量脚本,直接打 API 把字段补进现有 ships.json。

(build_ships_json.py 也已同步加了这几个字段,以后全量重建会原生带上;两条路一致。)

用法:
    python tools/enrich_ships_next.py
    python tools/enrich_ships_next.py --ships report/data/ships.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_ships_json import DEFAULT_HOST, DEFAULT_APP_ID, wg_get  # noqa: E402

DEFAULT_SHIPS = Path(__file__).resolve().parent.parent / "report" / "data" / "ships.json"


def fetch_next_ships(host: str, app_id: str) -> dict:
    """{ship_id(str): {"next_ships": {sid: xp}, "is_premium": bool, "is_special": bool}}"""
    out = {}
    page = 1
    while True:
        d = wg_get(host, app_id, "/wows/encyclopedia/ships/",
                   fields="ship_id,next_ships,is_premium,is_special",
                   language="en", page_no=page, limit=100)
        if d.get("status") != "ok":
            raise RuntimeError(f"WG API error: {d.get('error')}")
        for sid, info in (d.get("data") or {}).items():
            out[str(sid)] = {
                "next_ships": info.get("next_ships") or {},
                "is_premium": bool(info.get("is_premium")),
                "is_special": bool(info.get("is_special")),
            }
        meta = d.get("meta", {})
        if page >= meta.get("page_total", page):
            break
        page += 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ships", type=Path, default=DEFAULT_SHIPS)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--app-id", default=DEFAULT_APP_ID)
    args = ap.parse_args()

    data = json.loads(args.ships.read_text(encoding="utf-8"))
    ships = data["ships"]
    print(f"  ships.json: {len(ships)} ships", file=sys.stderr)

    print(f"  fetching next_ships from {args.host} ...", file=sys.stderr)
    api = fetch_next_ships(args.host, args.app_id)
    print(f"  API: {len(api)} ships", file=sys.stderr)

    n_next = n_prem = n_spec = matched = 0
    for sid, ship in ships.items():
        info = api.get(str(sid))
        if not info:
            # API 没有这条(GameParams 独有的 PVE/辅助舰等);给空字段保持结构一致
            ship["next_ships"] = {}
            ship["is_premium"] = bool(ship.get("is_premium", False))
            ship["is_special"] = bool(ship.get("is_special", False))
            continue
        matched += 1
        # next_ships 值统一成 int 研发经验;key 用字符串 ship_id
        ns = {str(k): int(v) for k, v in (info["next_ships"] or {}).items()}
        ship["next_ships"] = ns
        ship["is_premium"] = info["is_premium"]
        ship["is_special"] = info["is_special"]
        if ns:
            n_next += 1
        if info["is_premium"]:
            n_prem += 1
        if info["is_special"]:
            n_spec += 1

    print(f"  matched={matched}  with next_ships={n_next}  "
          f"premium={n_prem}  special={n_spec}", file=sys.stderr)

    args.ships.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote {args.ships}", file=sys.stderr)


if __name__ == "__main__":
    main()
