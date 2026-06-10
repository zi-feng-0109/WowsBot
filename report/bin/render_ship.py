# report/bin/render_ship.py
"""render_ship.py — /船 <中文名> 战舰数值卡 PNG。

库用法 (bot 直接 import):
    from render_ship import render_ship_png
    render_ship_png("/tmp/x.png", ship=<ships.json 里一条>)

CLI (调试):
    python render_ship.py <out.png> --ship-json '{"name_zh":...}'
    python render_ship.py <out.png> --ship-id 4276041424   # 从 ships.json 查

视觉风格复用 /查询 卡 (render_query / render_battle_report 的调色板 + helper)。
数值来自 report/data/ships.json (tools/build_ships_json.py 预构建)。
"""
import argparse
import json
import math
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_query import (  # noqa: E402  复用 /查询 那套
    GAME_BG, GAME_PANEL, GAME_PANEL_ALT, GAME_TEXT, GAME_DIM, GAME_BORDER,
    GAME_GREEN, GAME_RED, GAME_GOLD, CJK_FONT, MONO_FONT,
    W, PAD, FOOTER_H, _font, _draw_footer, _fmt_int,
)
from PIL import Image, ImageDraw  # noqa: E402

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_SHIPS_PATH = _DATA_DIR / "ships.json"
_SHIP_ICON_DIR = _DATA_DIR / "ship_icons"

# panel 布局常量
_PANEL_TITLE_H = 40
_PANEL_ROW_H = 50
_PANEL_PAD_BOTTOM = 14
_PANEL_GAP = 12
_HEADER_H = 132


def _ships() -> dict:
    try:
        return json.loads(_SHIPS_PATH.read_text("utf-8"))
    except Exception:
        return {}


def _load_ship_img(index: str, max_h: int) -> Optional["Image.Image"]:
    """加载战舰预览图,等比缩放到高 max_h。缺失返回 None。"""
    path = _SHIP_ICON_DIR / f"{index}.png"
    if not path.is_file():
        return None
    try:
        im = Image.open(path).convert("RGBA")
        if im.height != max_h:
            w = int(im.width * max_h / im.height)
            im = im.resize((w, max_h), Image.LANCZOS)
        return im
    except Exception:
        return None


def _fmt_km(v) -> str:
    return f"{v:.1f} km" if isinstance(v, (int, float)) else "-"


def _fmt_s(v) -> str:
    return f"{v:g} s" if isinstance(v, (int, float)) else "-"


def _panel_height(n_rows: int, cols: int) -> int:
    rows = max(1, math.ceil(n_rows / cols))
    return _PANEL_TITLE_H + rows * _PANEL_ROW_H + _PANEL_PAD_BOTTOM


def _draw_panel(img, draw, x, y, w, title, kvs, cols, fonts) -> int:
    """画一个圆角 stat panel。kvs: [(label, value)] 或 [(label, value, color)]。
    返回该 panel 占的高度。"""
    f_title, f_label, f_value = fonts["title"], fonts["label"], fonts["value"]
    rows = max(1, math.ceil(len(kvs) / cols))
    h = _PANEL_TITLE_H + rows * _PANEL_ROW_H + _PANEL_PAD_BOTTOM
    draw.rounded_rectangle([x, y, x + w, y + h], radius=10,
                           fill=GAME_PANEL_ALT, outline=GAME_BORDER)
    draw.text((x + 18, y + 11), title, GAME_GOLD, f_title)

    col_w = (w - 36) // cols
    for i, kv in enumerate(kvs):
        label, value = kv[0], kv[1]
        color = kv[2] if len(kv) > 2 else GAME_TEXT
        r, c = divmod(i, cols)
        cx = x + 18 + c * col_w
        cy = y + _PANEL_TITLE_H + r * _PANEL_ROW_H
        draw.text((cx, cy), label, GAME_DIM, f_label)
        draw.text((cx, cy + 20), str(value), color, f_value)
    return h


def _build_sections(ship: dict) -> list:
    """按船的数据组装 section 列表 [(title, kvs, cols)]。缺的字段对应 section 跳过。"""
    secs = []

    # 火力 (主炮)
    a = ship.get("artillery")
    if a:
        shells = a.get("shells") or {}
        ap = shells.get("AP") or {}
        he = shells.get("HE") or {}
        sap = shells.get("CS") or shells.get("SAP") or {}
        kvs = [
            ("射程", _fmt_km(a.get("range_km"))),
            ("装填", _fmt_s(a.get("reload_s"))),
        ]
        if ap.get("dmg"):
            kvs.append(("AP 单发", _fmt_int(ap["dmg"])))
        if he.get("dmg"):
            fire = he.get("fire")
            ftxt = f"  火{fire:g}%" if isinstance(fire, (int, float)) else ""
            kvs.append(("HE 单发", f"{_fmt_int(he['dmg'])}{ftxt}"))
        if sap.get("dmg"):
            kvs.append(("SAP 单发", _fmt_int(sap["dmg"])))
        if a.get("traverse_s"):
            kvs.append(("炮塔转向", _fmt_s(a.get("traverse_s"))))
        sec = ship.get("secondary") or {}
        if sec.get("range_km"):
            kvs.append(("副炮射程", _fmt_km(sec["range_km"])))
        secs.append(("火力", kvs, 3))

    # 鱼雷
    t = ship.get("torpedoes")
    if t:
        kvs = [
            ("单发伤害", _fmt_int(t["dmg"]) if t.get("dmg") else "-"),
            ("射程", _fmt_km(t.get("range_km"))),
            ("航速", f"{t.get('speed_kt','-')} 节"),
            ("装填", _fmt_s(t.get("reload_s"))),
            ("被发现", _fmt_km(t.get("detect_km"))),
        ]
        if t.get("tubes"):
            kvs.append(("发射管", t["tubes"]))
        secs.append(("鱼雷", kvs, 3))

    # 生存 + 机动 + 隐蔽 合一个 panel (信息密度)
    surv = []
    if ship.get("hp"):
        surv.append(("生命值", _fmt_int(ship["hp"])))
    m = ship.get("mobility") or {}
    if m.get("speed_kt"):
        surv.append(("航速", f"{m['speed_kt']:g} 节"))
    if m.get("turn_m"):
        surv.append(("转弯半径", f"{m['turn_m']} m"))
    if m.get("rudder_s"):
        surv.append(("转舵时间", _fmt_s(m.get("rudder_s"))))
    c = ship.get("concealment") or {}
    if c.get("sea_km"):
        surv.append(("对海隐蔽", _fmt_km(c["sea_km"])))
    if c.get("air_km"):
        surv.append(("对空隐蔽", _fmt_km(c["air_km"])))
    if surv:
        secs.append(("生存 · 机动 · 隐蔽", surv, 3))

    # 消耗品 (每 slot 一行,内层多个=二选一,用 / 连)
    cons = ship.get("consumables") or []
    if cons:
        kvs = []
        for i, slot in enumerate(cons):
            parts = []
            for a in slot:
                if isinstance(a, dict):           # 新格式 {name, charges}
                    nm = a.get("name", "?")
                    ch = a.get("charges")
                    if isinstance(ch, (int, float)) and ch > 0:  # -1=无限,不写
                        nm = f"{nm} ×{int(ch)}"
                    parts.append(nm)
                else:                              # 旧格式:纯字符串
                    parts.append(str(a))
            kvs.append((f"槽位 {i + 1}", " / ".join(parts)))
        secs.append(("消耗品", kvs, 2))

    return secs


def render_ship_png(out_path: str, *, ship: dict) -> str:
    """渲一张战舰数值卡。ship = ships.json 里一条 (含 name_zh/tier/hp/artillery...)。"""
    fonts = {
        "tier":   _font(MONO_FONT, 34),
        "name":   _font(CJK_FONT, 32),
        "en":     _font(CJK_FONT, 20),
        "sub":    _font(CJK_FONT, 20),
        "title":  _font(CJK_FONT, 18),
        "label":  _font(CJK_FONT, 15),
        "value":  _font(CJK_FONT, 21),
    }

    sections = _build_sections(ship)

    # ----- 高度 -----
    body_h = 12
    for _, kvs, cols in sections:
        body_h += _panel_height(len(kvs), cols) + _PANEL_GAP
    H = _HEADER_H + body_h + FOOTER_H

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)

    # ----- Header -----
    draw.rectangle([0, 0, W, _HEADER_H], fill=GAME_PANEL)
    draw.line([0, _HEADER_H, W, _HEADER_H], fill=GAME_GOLD, width=2)

    tier = ship.get("tier", "?")
    tier_txt = f"T{tier}"
    bw = int(fonts["tier"].getlength(tier_txt)) + 28
    draw.rounded_rectangle([PAD, 20, PAD + bw, 20 + 64], radius=10, fill=GAME_GOLD)
    draw.text((PAD + 14, 28), tier_txt, (10, 16, 28), fonts["tier"])

    tx = PAD + bw + 24
    draw.text((tx, 22), ship.get("name_zh", "?"), GAME_TEXT, fonts["name"])
    sub = ship.get("name_en", "")
    sp = ship.get("species_zh") or ship.get("species", "")
    nat = ship.get("nation_zh") or ship.get("nation", "")
    sub_line = "  ·  ".join(x for x in [sub, sp, nat] if x)
    draw.text((tx, 66), sub_line, GAME_DIM, fonts["sub"])

    # 右侧预览图
    pic = _load_ship_img(ship.get("icon") or ship.get("index", ""), _HEADER_H - 28)
    if pic is not None:
        px = W - PAD - pic.width
        py = (_HEADER_H - pic.height) // 2
        img.paste(pic, (px, max(8, py)), pic)

    # ----- Sections -----
    y = _HEADER_H + 12
    for title, kvs, cols in sections:
        used = _draw_panel(img, draw, PAD, y, W - 2 * PAD, title, kvs, cols, fonts)
        y += used + _PANEL_GAP

    # ----- Footer -----
    _draw_footer(draw, 0, H - FOOTER_H, W, FOOTER_H)

    img.save(out_path)
    return out_path


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--ship-json", default="")
    ap.add_argument("--ship-id", default="")
    args = ap.parse_args()
    if args.ship_json:
        ship = json.loads(args.ship_json)
    elif args.ship_id:
        ship = (_ships().get("ships") or {}).get(str(args.ship_id))
        if not ship:
            sys.exit(f"ship_id {args.ship_id} not in ships.json")
    else:
        sys.exit("need --ship-json or --ship-id")
    render_ship_png(args.out, ship=ship)
    print(args.out)


if __name__ == "__main__":
    _cli()
