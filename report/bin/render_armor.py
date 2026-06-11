# report/bin/render_armor.py
"""render_armor.py — /船 <名> 装甲 完整分面装甲图 PNG。

库用法 (bot 直接 import):
    from render_armor import render_armor_png
    render_armor_png(out_path, ship=<ships.json 一条>, armor=<armor.json 一条>)

CLI (调试):
    python render_armor.py <out.png> --ship-id PJSB018

数据来自 report/data/armor.json (replayshark armor-dump 预构建)。
视觉复用 render_ship / render_query 的面板与调色板。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_query import (  # noqa: E402
    GAME_BG, GAME_PANEL, GAME_TEXT, GAME_DIM, GAME_GOLD,
    CJK_FONT, MONO_FONT, W, PAD, FOOTER_H, _font, _draw_footer,
)
from render_ship import (  # noqa: E402
    _draw_panel, _panel_height, _load_ship_img, _HEADER_H, _PANEL_GAP,
)
from PIL import Image, ImageDraw  # noqa: E402

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_ARMOR_PATH = _DATA_DIR / "armor.json"
_SHIPS_PATH = _DATA_DIR / "ships.json"

# 装甲区英文 → 中文
ZONE_ZH = {
    "Citadel": "装甲核心", "Casemate": "炮郭", "Superstructure": "上层建筑",
    "Bow": "舰艏", "Stern": "舰艉", "Turret": "主炮塔", "SteeringGear": "操舵室",
    "TorpedoProtection": "防雷", "Hull": "船体", "Other": "其他", "unknown": "未知",
}
# 装甲区显示顺序(未列到的排最后,按字母序)
_ZONE_ORDER = ["Citadel", "Hull", "Bow", "Stern", "Casemate", "Superstructure",
               "TorpedoProtection", "SteeringGear", "Turret", "Other", "unknown"]

import re  # noqa: E402

# 分面 material 名是组合式内部名 (WG 无官方中文,wows-toolkit 也显示原文)。
# 按词根组合翻译:<区>_<部件> / Dual_<区A>_<区B>_<部件> / Tur<N>Gk<部位>。
# 区 (zone) 词根
_FACE_ZONE = {
    "Bow": "舰艏", "St": "舰艉", "SS": "上层建筑", "Cit": "核心区", "Cas": "炮郭",
    "SSC": "上建核心", "OCit": "外核心", "Art": "弹药库",
}
# 部件 / 整词 (单 token,含复合的舵机·舰桥·炮塔分面)
_FACE_PART = {
    "Deck": "甲板", "Trans": "横隔壁", "Bottom": "船底", "ConstrSide": "外壳侧",
    "Belt": "装甲带", "Side": "侧面", "Top": "顶部", "FwdTrans": "前横隔壁",
    "AftTrans": "后横隔壁", "Bulge": "防雷鼓包", "Inclin": "倾斜装甲",
    "Fdck": "艏楼甲板", "Hang": "机库",
    "ArtSide": "弹药库侧", "ArtBottom": "弹药库底", "ArtTop": "弹药库顶", "ArtDeck": "弹药库甲板",
    "RudderTop": "舵机顶", "RudderAft": "舵机后", "RudderFwd": "舵机前", "RudderSide": "舵机侧",
    "BridgeSide": "舰桥侧", "BridgeTop": "舰桥顶", "BridgeBottom": "舰桥底",
    # 炮塔分面 (armor.turrets[].faces 用)
    "TurretFront": "炮塔正面", "TurretFwd": "炮塔正面", "TurretSide": "炮塔侧面",
    "TurretTop": "炮塔顶部", "TurretAft": "炮塔背面", "TurretDown": "炮塔底部",
    "TurretBarbette": "座圈", "AuTurretSide": "副炮塔侧面", "AuTurretDown": "副炮塔底部",
}
_GK_PART = {"Bar": "座圈", "Top": "顶部", "Down": "底部"}


def _tok_zh(t: str) -> str:
    return _FACE_ZONE.get(t) or _FACE_PART.get(t) or t


def face_zh(name: str) -> str:
    """分面中文名:词根组合翻译;完全未识别的 token 原样保留,保证零丢失。"""
    if name in _FACE_PART:
        return _FACE_PART[name]
    m = re.fullmatch(r"Tur(\d+)Gk(Bar|Top|Down)", name)   # 主炮座圈/顶/底
    if m:
        return f"{m.group(1)}号炮塔{_GK_PART[m.group(2)]}"
    parts = name.split("_")
    if parts and parts[0] == "Dual" and len(parts) >= 3:  # 两区交界板
        a, b, rest = parts[1], parts[2], parts[3:]
        tail = "".join(_tok_zh(p) for p in rest)
        return f"{_tok_zh(a)}–{_tok_zh(b)}间{tail}"
    return "".join(_tok_zh(p) for p in parts)


def _fmt_mm(mm: list) -> str:
    """[370, 350] -> '370 / 350 mm';[410] -> '410 mm'。"""
    if not mm:
        return "-"
    return " / ".join(str(int(v)) for v in mm) + " mm"


def _armor_sections(armor: dict) -> list:
    """armor.json 一条 → [(title, kvs, cols)],喂 render_ship._draw_panel。"""
    secs = []
    hull = armor.get("hull") or {}

    def _zkey(z):
        return (_ZONE_ORDER.index(z) if z in _ZONE_ORDER else 99, z)

    for z in sorted(hull.keys(), key=_zkey):
        kvs = [(face_zh(f["face"]), _fmt_mm(f.get("mm") or [])) for f in hull[z]]
        if kvs:
            secs.append((ZONE_ZH.get(z, z), kvs, 2))
    for t in armor.get("turrets") or []:
        kvs = [(face_zh(f["face"]), _fmt_mm(f.get("mm") or [])) for f in t.get("faces") or []]
        if kvs:
            secs.append((f"{t.get('name', '主炮')}装甲", kvs, 2))
    return secs


def render_armor_png(out_path: str, *, ship: dict, armor: dict) -> str:
    """渲一张装甲分面图。ship = ships.json 一条;armor = armor.json 一条。"""
    fonts = {
        "tier":  _font(MONO_FONT, 34),
        "name":  _font(CJK_FONT, 32),
        "sub":   _font(CJK_FONT, 20),
        "title": _font(CJK_FONT, 18),
        "label": _font(CJK_FONT, 15),
        "value": _font(CJK_FONT, 21),
    }
    sections = _armor_sections(armor)
    if not sections:
        sections = [("装甲", [("无数据", "-")], 2)]

    body_h = 12
    for _, kvs, cols in sections:
        body_h += _panel_height(len(kvs), cols) + _PANEL_GAP
    H = _HEADER_H + body_h + FOOTER_H

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)

    # ----- Header(同 render_ship 风格) -----
    draw.rectangle([0, 0, W, _HEADER_H], fill=GAME_PANEL)
    draw.line([0, _HEADER_H, W, _HEADER_H], fill=GAME_GOLD, width=2)
    tier_txt = f"T{ship.get('tier', '?')}"
    bw = int(fonts["tier"].getlength(tier_txt)) + 28
    draw.rounded_rectangle([PAD, 20, PAD + bw, 20 + 64], radius=10, fill=GAME_GOLD)
    draw.text((PAD + 14, 28), tier_txt, (10, 16, 28), fonts["tier"])
    tx = PAD + bw + 24
    draw.text((tx, 22), ship.get("name_zh", "?"), GAME_TEXT, fonts["name"])
    sub_line = "  ·  ".join(x for x in [
        ship.get("name_en", ""),
        ship.get("species_zh") or ship.get("species", ""),
        ship.get("nation_zh") or ship.get("nation", ""),
        "装甲",
    ] if x)
    draw.text((tx, 66), sub_line, GAME_DIM, fonts["sub"])
    pic = _load_ship_img(ship.get("icon") or ship.get("index", ""), _HEADER_H - 28)
    if pic is not None:
        img.paste(pic, (W - PAD - pic.width, max(8, (_HEADER_H - pic.height) // 2)), pic)

    # ----- 装甲区面板(单列) -----
    y = _HEADER_H + 12
    for title, kvs, cols in sections:
        used = _draw_panel(img, draw, PAD, y, W - 2 * PAD, title, kvs, cols, fonts)
        y += used + _PANEL_GAP

    _draw_footer(draw, 0, H - FOOTER_H, W, FOOTER_H)
    img.save(out_path)
    return out_path


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--ship-id", required=True, help="短 index,如 PJSB018")
    args = ap.parse_args()
    ships_raw = json.loads(_SHIPS_PATH.read_text("utf-8"))
    ships = ships_raw.get("ships") or ships_raw
    # ships.json 以数字 ID 为 key;按 index 字段反查
    ship = ships.get(args.ship_id) or next(
        (v for v in ships.values() if isinstance(v, dict) and v.get("index") == args.ship_id),
        None,
    )
    if not ship:
        sys.exit(f"ship-id {args.ship_id} 不在 ships.json")
    armor = json.loads(_ARMOR_PATH.read_text("utf-8")).get(args.ship_id)
    if not armor:
        sys.exit(f"ship-id {args.ship_id} 不在 armor.json")
    render_armor_png(args.out, ship=ship, armor=armor)
    print(args.out)


if __name__ == "__main__":
    _cli()
