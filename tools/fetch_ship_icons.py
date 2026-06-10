#!/usr/bin/env python3
"""fetch_ship_icons.py — 拉战舰预览图 (港口渲染图) 到 report/data/ship_icons/。

产物:
  report/data/ship_icons/<index>.png   (~960 张 medium 渲染图, ~17 MB)

`/船 <中文名>` 卡片 header 右侧贴这张图。文件名用 ship index (PJSB018 这种),
跟 ships.json 里每船的 "icon" 字段对应,render_ship.py 直接 ship_icons/<icon>.png。

数据来源:WG public API encyclopedia 的 images.medium URL (wgcdn 上的渲染图)。
ship_id → index 映射从 report/data/ships.json 读 (build_ships_json.py 先跑)。

大版本更新后跟 build_ships_json.py 一并重跑 (UPDATE.md 里有挂)。图标缺失时
render_ship.py 兜底不贴图,功能不挂。
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


BOT_HOME = Path(__file__).resolve().parent.parent
DEFAULT_SHIPS_JSON = BOT_HOME / "report" / "data" / "ships.json"
DEFAULT_ICON_DIR = BOT_HOME / "report" / "data" / "ship_icons"
DEFAULT_HOST = "api.worldofwarships.asia"
DEFAULT_APP_ID = "8ea66b76f5483555ae2594a68882cbf9"


def wg_images(host: str, app_id: str, kind: str) -> dict:
    """分页拉全船 images → {ship_id_str: url(kind)}。"""
    out = {}
    page = 1
    while True:
        u = (f"https://{host}/wows/encyclopedia/ships/?" + urllib.parse.urlencode(
            {"application_id": app_id, "fields": "ship_id,images",
             "language": "en", "page_no": page, "limit": 100}))
        req = urllib.request.Request(u, headers={"User-Agent": "wows-bot/1"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        if d.get("status") != "ok":
            raise RuntimeError(f"WG ships error: {d.get('error')}")
        for sid, v in (d.get("data") or {}).items():
            if v and v.get("images", {}).get(kind):
                out[sid] = v["images"][kind]
        meta = d.get("meta") or {}
        if page >= int(meta.get("page_total") or 1):
            break
        page += 1
    return out


def fetch(url: str, dest: Path, force: bool) -> tuple[bool, str]:
    if dest.exists() and not force:
        return True, "skip"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "wows-bot/1"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
        if not data or data[:8] != b"\x89PNG\r\n\x1a\n":
            return False, f"not PNG ({len(data)} bytes)"
        dest.write_bytes(data)
        return True, f"{len(data) // 1024} KB"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return False, str(e).split("\n", 1)[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ships-json", type=Path, default=DEFAULT_SHIPS_JSON)
    ap.add_argument("--icon-dir", type=Path, default=DEFAULT_ICON_DIR)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--app-id", default=os.environ.get("WOWS_WG_APP_ID", DEFAULT_APP_ID))
    ap.add_argument("--kind", default="medium", choices=["small", "medium", "large"],
                    help="预览图尺寸 (default: medium)")
    ap.add_argument("--force", action="store_true", help="重下已存在的图")
    ap.add_argument("--parallel", type=int, default=8)
    args = ap.parse_args()

    if not args.ships_json.is_file():
        sys.exit(f"error: {args.ships_json} not found (先跑 build_ships_json.py)")

    data = json.loads(args.ships_json.read_text("utf-8"))
    ships = data.get("ships") or {}
    # ship_id → index
    id_to_index = {sid: s.get("icon") or s.get("index")
                   for sid, s in ships.items() if s.get("index")}

    print(f"  fetching image URLs from {args.host} ...", file=sys.stderr)
    urls = wg_images(args.host, args.app_id, args.kind)

    args.icon_dir.mkdir(parents=True, exist_ok=True)
    items = [(idx, args.icon_dir / f"{idx}.png", urls[sid])
             for sid, idx in id_to_index.items() if sid in urls]
    missing_url = len(id_to_index) - len(items)

    print(f"  downloading {len(items)} ship icons (kind={args.kind}, parallel={args.parallel})",
          file=sys.stderr)
    new_ok = skip = fail = 0
    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futs = {ex.submit(fetch, url, dest, args.force): idx
                for idx, dest, url in items}
        for fut in as_completed(futs):
            ok, msg = fut.result()
            if ok and msg == "skip":
                skip += 1
            elif ok:
                new_ok += 1
            else:
                fail += 1
                print(f"  ✗ {futs[fut]}: {msg}", file=sys.stderr)

    print(f"  ship icons: new={new_ok} skip={skip} fail={fail} "
          f"(no URL: {missing_url})", file=sys.stderr)


if __name__ == "__main__":
    main()
