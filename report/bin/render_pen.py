# report/bin/render_pen.py
"""render_pen.py — /装甲分析 <船名> 防御视角穿深矩阵 PNG。

每块关键装甲板出一张子矩阵:格子写"≥X mm"= 该距离+该角度下,主流战列弹达到
该口径就可穿/过穿/核心区(按板属性)。垂直板的角度=目标偏航角(0=对舷暴露,
60=对头收尾);水平甲板的角度由距离决定(落角),只有一列。

库:
    render_armor_analysis_png(out, target=<ship>, armor=<armor>, all_ap_shells=[...])

公式 + 临界口径反查在 calc_penetration.py。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_query import (  # noqa: E402
    GAME_BG, GAME_PANEL, GAME_PANEL_ALT, GAME_TEXT, GAME_DIM, GAME_BORDER,
    GAME_GREEN, GAME_RED, GAME_GOLD, CJK_FONT, MONO_FONT,
    W, PAD, FOOTER_H, _font, _draw_footer,
)
from render_ship import _load_ship_img, _HEADER_H  # noqa: E402
from calc_penetration import (  # noqa: E402
    build_typical_shells, critical_caliber, DEFAULT_CALIBERS_MM,
)
from PIL import Image, ImageDraw  # noqa: E402

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# 关键代表板:(标签, [(zone|None, face 关键字优先列表, 取最小?)...], 板倾角°, 核心区?, 轴)
# 同一标签可以多 zone 备选 (从前往后挑第一个有数据的);take_min=True 优先取该 zone
# 里最薄的板 (玩家最常打到那块,如上层取 19mm 而非装甲舰桥 457mm)。
# 轴: "yaw" 偏航角扫 0/15/30/45/60° / "deck" 水平甲板单列
_KEY_PLATES = [
    ("舰艏外壳",   [("Bow",            ("Bow_ConstrSide",),       False)],   0,  False, "yaw"),
    ("水平甲板",   [("Casemate",       ("Cas_Deck",),             False),
                    ("Hull",           ("Deck",),                 False)],   90, False, "deck"),
    ("核心区主装", [("Citadel",        ("Cit_Belt",),             False)],   0,  True,  "yaw"),
    ("上层(薄)",  [("Superstructure", ("SS_Side", "SS_Top"),     True)],    0,  False, "yaw"),
    ("主炮塔正面", [(None,             ("TurretFwd","TurretFront"), False)], 0,  False, "yaw"),
]

RANGES_KM = [5, 10, 15, 20, 25]
YAW_DEGS = [0, 15, 30, 45, 60]

# 判定 → 色
_RESULT_COLOR = {
    "CITADEL":  (230, 195, 70),   # 金:核心区
    "PEN":      (90, 200, 100),   # 绿:击穿
    "OVER":     (220, 180, 80),   # 黄:过穿
    None:       (220, 80, 80),    # 红:无任何口径可穿
    "RICOCHET": (140, 145, 160),  # 灰:必跳
}


def _pick_plate(armor, options):
    """options: [(zone|None, face_patterns, take_min)...] 从前到后试,挑到的第一个返回。
    take_min=True 时同 zone 内取符合关键字的所有板中**最薄**那块。"""
    for zone, patterns, take_min in options:
        candidates = []
        if zone:
            for f in (armor.get("hull", {}).get(zone) or []):
                if any(p in f["face"] for p in patterns):
                    mm = max(f.get("mm") or [0])
                    if mm > 0:
                        candidates.append((f["face"], mm))
        else:
            for t in armor.get("turrets") or []:
                for f in t.get("faces") or []:
                    if any(p in f["face"] for p in patterns):
                        mm = max(f.get("mm") or [0])
                        if mm > 0:
                            candidates.append((f["face"], mm))
        if candidates:
            if take_min:
                return min(candidates, key=lambda x: x[1])
            return candidates[0]
    return None, None


def _solve_plate(mm, tilt, is_cit, axis):
    """对一块板,生成 grid: [[cell, ...row by ranges], ...col by axis]。
    每个 cell = critical_caliber 返回的 dict。"""
    rows = []
    if axis == "deck":
        # 单列(角度由落角决定,目标偏航 0)
        for rng in RANGES_KM:
            rows.append([critical_caliber(rng * 1000, mm, tilt, 0,
                                          is_citadel=is_cit)])
    else:
        for rng in RANGES_KM:
            row = [critical_caliber(rng * 1000, mm, tilt, yaw,
                                    is_citadel=is_cit) for yaw in YAW_DEGS]
            rows.append(row)
    return rows


def _cell_text(cell):
    """单元格内容:"≥X mm" / "≥X 碾" / "必跳" / "无"。"""
    if cell["all_ricochet"]:
        return "必跳", "RICOCHET"
    if cell["min_cal"] is None:
        return "无", None
    tag = f"≥{cell['min_cal']}"
    if cell["is_overmatch_only"]:
        tag += "·碾压"
    return tag, cell["verdict"]


def _draw_header(img, draw, target, fonts, h=120):
    draw.rectangle([0, 0, W, h], fill=GAME_PANEL)
    draw.line([0, h, W, h], fill=GAME_GOLD, width=2)
    tier = f"T{target.get('tier', '?')}"
    bw = int(fonts["tier"].getlength(tier)) + 24
    draw.rounded_rectangle([PAD, 22, PAD + bw, 22 + 56], radius=8, fill=GAME_GOLD)
    draw.text((PAD + 12, 28), tier, (10, 16, 28), fonts["tier"])
    tx = PAD + bw + 16
    draw.text((tx, 14), "防御分析", GAME_GOLD, fonts["sub"])
    draw.text((tx, 30), target.get("name_zh", "?"), GAME_TEXT, fonts["name"])
    sub = " · ".join(x for x in [target.get("name_en", ""),
                                  target.get("species_zh", ""),
                                  target.get("nation_zh", "")] if x)
    draw.text((tx, 64), sub, GAME_DIM, fonts["sub"])
    note = "格内「≥X mm」= 该距离+角度下,主流战列弹达到该口径就可穿;碾=靠口径>14.3×厚度强行直穿"
    nw = int(fonts["small"].getlength(note))
    draw.text(((W - nw) // 2, 92), note, GAME_DIM, fonts["small"])


def _draw_subplot(img, draw, x, y, w, plate, fonts):
    """一块板的子矩阵 panel。返回占用高度。"""
    title_h = 32
    head_h = 22
    cell_h = 36
    if plate["axis"] == "deck":
        n_cols = 1
        labels = ["落角(由距离决定)"]
    else:
        n_cols = len(YAW_DEGS)
        labels = [f"{a}°" for a in YAW_DEGS]
    label_col_w = 64                          # 距离列
    cell_w = (w - label_col_w - 8) // n_cols
    n_rows = len(RANGES_KM)
    body_h = head_h + cell_h * n_rows
    h = title_h + body_h + 10

    draw.rounded_rectangle([x, y, x + w, y + h], radius=8,
                            fill=GAME_PANEL_ALT, outline=GAME_BORDER)
    title = f"{plate['label']}  ({plate['mm']} mm)"
    draw.text((x + 12, y + 8), title, GAME_GOLD, fonts["sub_title"])

    # 列表头
    hy = y + title_h
    draw.text((x + 8, hy + 4), "距离\\", GAME_DIM, fonts["head"])
    if plate["axis"] == "yaw":
        # 二级表头说明
        draw.text((x + 8 + 32, hy + 4), "偏航", GAME_DIM, fonts["head"])
    else:
        draw.text((x + 8 + 32, hy + 4), "判定", GAME_DIM, fonts["head"])
    for ci, lab in enumerate(labels):
        cx = x + label_col_w + 4 + ci * cell_w
        lw = int(fonts["head"].getlength(lab))
        draw.text((cx + (cell_w - lw) // 2, hy + 4), lab, GAME_DIM, fonts["head"])

    # 行
    for ri, rng in enumerate(RANGES_KM):
        ry = hy + head_h + ri * cell_h
        if ri > 0:
            draw.line([x + 6, ry - 1, x + w - 6, ry - 1],
                      fill=(60, 76, 110), width=1)
        draw.text((x + 8, ry + (cell_h - 18) // 2),
                  f"{rng} km", GAME_TEXT, fonts["row"])
        cells = plate["grid"][ri]
        for ci, cell in enumerate(cells):
            cx = x + label_col_w + 4 + ci * cell_w
            box = [cx + 3, ry + 3, cx + cell_w - 3, ry + cell_h - 5]
            text, verdict = _cell_text(cell)
            color = _RESULT_COLOR[verdict]
            draw.rounded_rectangle(box, radius=4, fill=color)
            if verdict == "CITADEL":
                draw.rounded_rectangle(box, radius=4,
                                       outline=(255, 240, 200), width=2)
            tw = int(fonts["cell"].getlength(text))
            draw.text((cx + (cell_w - tw) // 2,
                       ry + (cell_h - 20) // 2),
                      text, (16, 22, 32), fonts["cell"])
    return h


def _draw_legend(draw, x, y, w, fonts):
    items = [("CITADEL", "≥X→核心区(满)"), ("PEN", "≥X→击穿(1/3)"),
             ("OVER", "≥X→过穿(1/10)"), (None, "任何口径不可穿"),
             ("RICOCHET", "必跳")]
    cx = x
    for k, lbl in items:
        col = _RESULT_COLOR[k]
        draw.rounded_rectangle([cx, y + 4, cx + 22, y + 24], radius=4, fill=col)
        draw.text((cx + 28, y + 6), lbl, GAME_TEXT, fonts["small"])
        cx += int(fonts["small"].getlength(lbl)) + 50


def render_armor_analysis_png(out_path: str, *, target, armor, all_ap_shells):
    fonts = {
        "tier":      _font(MONO_FONT, 30),
        "name":      _font(CJK_FONT, 26),
        "sub":       _font(CJK_FONT, 17),
        "sub_title": _font(CJK_FONT, 17),
        "head":      _font(CJK_FONT, 13),
        "row":       _font(CJK_FONT, 15),
        "cell":      _font(CJK_FONT, 14),
        "small":     _font(CJK_FONT, 13),
    }
    # 构建典型弹表(每口径中位弹)
    build_typical_shells(all_ap_shells, calibers_mm=DEFAULT_CALIBERS_MM)

    # 逐板算 grid
    plates = []
    for label, options, tilt, is_cit, axis in _KEY_PLATES:
        face, mm = _pick_plate(armor, options)
        if not mm:
            continue
        grid = _solve_plate(mm, tilt, is_cit, axis)
        plates.append({"label": label, "face": face, "mm": mm,
                       "is_citadel": is_cit, "axis": axis, "grid": grid})

    head_h = 120
    sub_w = (W - 2 * PAD - 12) // 2          # 两列
    # 子图高度由内容定
    sub_h_yaw = 32 + 22 + 36 * len(RANGES_KM) + 10
    sub_h_deck = sub_h_yaw                    # 同高,只少列数
    legend_h = 36
    note_h = 24

    # 排版:2 列网格
    n = len(plates)
    rows = (n + 1) // 2
    grid_h = rows * (sub_h_yaw + 12) - 12     # 最后一行不加 gap

    H = head_h + 12 + grid_h + 16 + legend_h + note_h + FOOTER_H

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)
    _draw_header(img, draw, target, fonts, h=head_h)

    # 排子图
    y = head_h + 12
    for i, p in enumerate(plates):
        col = i % 2
        row = i // 2
        x = PAD + col * (sub_w + 12)
        sy = y + row * (sub_h_yaw + 12)
        _draw_subplot(img, draw, x, sy, sub_w, p, fonts)

    y += grid_h + 12

    _draw_legend(draw, PAD, y, W - 2 * PAD, fonts)
    y += legend_h

    draw.text((PAD, y), "口径按 ships.json 所有 AP 弹按口径取中位 (主流战列弹近似), "
                        "实际不同船差 ±15%; 倾角/法线化为简化几何。",
              GAME_DIM, fonts["small"])

    _draw_footer(draw, 0, H - FOOTER_H, W, FOOTER_H)
    img.save(out_path)
    return out_path


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--target", required=True, help="目标船 index 或中文名")
    args = ap.parse_args()
    ships_raw = json.loads((_DATA_DIR / "ships.json").read_text("utf-8"))
    ships = ships_raw.get("ships") or ships_raw
    armor_all = json.loads((_DATA_DIR / "armor.json").read_text("utf-8"))
    target = next((v for v in ships.values()
                   if v.get("index") == args.target or v.get("name_zh") == args.target),
                  None)
    if not target:
        sys.exit(f"找不到 {args.target}")
    armor = armor_all.get(target["index"])
    if not armor:
        sys.exit(f"{target['name_zh']} 无装甲数据")
    all_ap = [s.get("ap_ballistic") for s in ships.values()
              if s.get("ap_ballistic")]
    render_armor_analysis_png(args.out, target=target, armor=armor,
                              all_ap_shells=all_ap)
    print(args.out)


if __name__ == "__main__":
    _cli()