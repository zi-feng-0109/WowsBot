"""Render damage breakdown chart (two pies + ribbons row) for the replay owner.

Usage:
    python render_damage_chart.py <battle_report.json> <out.png>

The JSON is the output of replayshark battle-report (same format as the
main battle report renderer consumes).
"""
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# Reuse helpers + constants from the main renderer (path resolution, fonts,
# translation, results-index lookup, ID parsing).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_battle_report import (  # noqa: E402
    CJK_FONT, MONO_FONT,
    GAME_BG, GAME_PANEL, GAME_GREEN, GAME_RED, GAME_GOLD, GAME_PURPLE,
    GAME_TEXT, GAME_DIM, GAME_BORDER,
    t, result_field, load_result_indices,
    fmt_time, strip_known,
)

RIBBON_ICON_DIR = os.environ.get(
    "WOWS_RIBBON_ICONS",
    str(Path(__file__).resolve().parent.parent / "data" / "ribbon_icons"),
)


# ---------- damage category aggregators ------------------------------------
# Each entry: (display_label, color, [results_info_keys to sum])
# We use the BASE key for bomb/tbomb/rocket/skip categories (sums all subcats
# already). For tpd/atba we list the leaf keys.

_PALETTE = {
    "ap":             (220, 70, 70),
    "he":             (240, 145, 50),
    "cs":             (240, 200, 80),
    "atba":           (210, 110, 90),
    "tpd":            (60, 165, 230),
    "tbomb":          (80, 190, 200),
    "bomb":           (180, 100, 200),
    "rocket":         (220, 95, 175),
    "skip":           (200, 60, 130),
    "dbomb":          (140, 100, 70),
    "fire":           (235, 120, 70),
    "flood":          (90, 130, 220),
    "ram":            (150, 150, 160),
    "sea_mine":       (90, 160, 110),
    "adbomb":         (150, 95, 180),
    "missile":        (190, 190, 200),
    "special":        (170, 170, 110),
    "event":          (130, 200, 130),
    # Airstrike-consumable variants (called in from surface ships).
    "airstrike_he":   (210, 165, 110),  # bomb_airsupport (Lion/Prins van Oranje-type HE)
    "airstrike_misc": (165, 140, 120),  # rare tbomb/skip/rocket airsupport
}

# WG 在 results_info 里把每种"飞机类武器"拆成 4 个变体：
#   damage_XXX            → 总和（avia + alt + airsupport），不要直接用
#   damage_XXX_avia       → CV 永久中队 - 主中队
#   damage_XXX_alt        → CV 永久中队 - 备选中队（部分 CV 才有）
#   damage_XXX_airsupport → 空袭消耗品（陆航召唤过来的临时中队，金狮 / 奥兰治亲王等用）
# 把 CV 攻击和空袭分两类标签，避免来源混淆。
#
# 另：ADBOMB (weapon id 28) 是反潜空袭专用深弹；damage_dbomb_airsupport (196) 与
# damage_adbomb (197) 始终是同一数字的镜像，只能取其一，否则双倍。这里保留
# damage_adbomb 作"空袭深弹"，舰射深弹只取 direct + splash。
DEALT_CATEGORIES = [
    ("主炮 AP",  _PALETTE["ap"],       ["damage_main_ap"]),
    ("主炮 HE",  _PALETTE["he"],       ["damage_main_he"]),
    ("主炮 CS",  _PALETTE["cs"],       ["damage_main_cs"]),
    ("副炮",     _PALETTE["atba"],     ["damage_atba_ap","damage_atba_he","damage_atba_cs",
                                        "damage_atba_ap_manual","damage_atba_he_manual","damage_atba_cs_manual"]),
    ("鱼雷",     _PALETTE["tpd"],      ["damage_tpd_normal","damage_tpd_alter","damage_tpd_deep"]),
    # --- CV 舰载机攻击 ---
    ("炸弹",     _PALETTE["bomb"],     ["damage_bomb_avia","damage_bomb_alt"]),
    ("跳炸",     _PALETTE["skip"],     ["damage_skip_avia","damage_skip_alt"]),
    ("鱼雷机",   _PALETTE["tbomb"],    ["damage_tbomb_avia","damage_tbomb_alt"]),
    ("火箭机",   _PALETTE["rocket"],   ["damage_rocket_avia","damage_rocket_alt"]),
    # --- 空袭消耗品（陆航空袭） ---
    ("空袭 HE",  _PALETTE["airstrike_he"],   ["damage_bomb_airsupport"]),
    ("空袭深弹", _PALETTE["adbomb"],          ["damage_adbomb"]),
    ("其他空袭", _PALETTE["airstrike_misc"],  ["damage_tbomb_airsupport",
                                              "damage_skip_airsupport",
                                              "damage_rocket_airsupport"]),
    # --- 舰射深弹（DD/CL 尾投或前甩） ---
    ("深弹",     _PALETTE["dbomb"],    ["damage_dbomb_direct","damage_dbomb_splash"]),
    # --- 其他 ---
    ("火灾",     _PALETTE["fire"],     ["damage_fire"]),
    ("进水",     _PALETTE["flood"],    ["damage_flood"]),
    ("撞击",     _PALETTE["ram"],      ["damage_ram"]),
    ("水雷",     _PALETTE["sea_mine"], ["damage_sea_mine"]),
    ("导弹",     _PALETTE["missile"],  ["damage_missile"]),
    ("事件伤害", _PALETTE["event"],    ["damage_event_1","damage_event_2"]),
]

# 受伤侧字段拆分规律与 DEALT 一致。received_damage_dbomb (227) 经验上是舰射深弹收到的，
# received_damage_adbomb (237) 是空袭深弹收到的，received_damage_dbomb_airsupport (236)
# 多半是 adbomb 的镜像（未在样本中证实，先不算入避免双倍）。
RECEIVED_CATEGORIES = [
    ("主炮 AP",  _PALETTE["ap"],       ["received_damage_main_ap"]),
    ("主炮 HE",  _PALETTE["he"],       ["received_damage_main_he"]),
    ("主炮 CS",  _PALETTE["cs"],       ["received_damage_main_cs"]),
    ("副炮",     _PALETTE["atba"],     ["received_damage_atba_ap","received_damage_atba_he","received_damage_atba_cs",
                                        "received_damage_atba_ap_manual","received_damage_atba_he_manual","received_damage_atba_cs_manual"]),
    ("鱼雷",     _PALETTE["tpd"],      ["received_damage_tpd_normal","received_damage_tpd_alter","received_damage_tpd_deep"]),
    # --- CV 舰载机攻击 ---
    ("炸弹",     _PALETTE["bomb"],     ["received_damage_bomb_avia","received_damage_bomb_alt"]),
    ("跳炸",     _PALETTE["skip"],     ["received_damage_skip_avia","received_damage_skip_alt"]),
    ("鱼雷机",   _PALETTE["tbomb"],    ["received_damage_tbomb_avia","received_damage_tbomb_alt"]),
    ("火箭机",   _PALETTE["rocket"],   ["received_damage_rocket_avia","received_damage_rocket_alt"]),
    # --- 空袭消耗品 ---
    ("空袭 HE",  _PALETTE["airstrike_he"],   ["received_damage_bomb_airsupport"]),
    ("空袭深弹", _PALETTE["adbomb"],          ["received_damage_adbomb"]),
    ("其他空袭", _PALETTE["airstrike_misc"],  ["received_damage_tbomb_airsupport",
                                              "received_damage_skip_airsupport",
                                              "received_damage_rocket_airsupport"]),
    # --- 舰射深弹 ---
    ("深弹",     _PALETTE["dbomb"],    ["received_damage_dbomb"]),
    # --- 其他 ---
    ("火灾",     _PALETTE["fire"],     ["received_damage_fire"]),
    ("进水",     _PALETTE["flood"],    ["received_damage_flood"]),
    ("撞击",     _PALETTE["ram"],      ["received_damage_ram"]),
    ("水雷",     _PALETTE["sea_mine"], ["received_damage_sea_mine"]),
    ("导弹",     _PALETTE["missile"],  ["received_damage_missile"]),
    ("特殊伤害", _PALETTE["special"],  ["received_damage_special","received_damage_mirror"]),
    ("事件伤害", _PALETTE["event"],    ["received_damage_event_1","received_damage_event_2"]),
]


def aggregate(ri, categories):
    """[(label, color, total)...] dropping zero-value categories."""
    out = []
    for label, color, keys in categories:
        v = sum(result_field(ri, k, 0) or 0 for k in keys)
        if v > 0:
            out.append((label, color, int(v)))
    out.sort(key=lambda x: -x[2])
    return out


# ---------- ribbons ---------------------------------------------------------

# Map ribbon key (from constants) -> (display label, icon basename without ext)
RIBBON_DISPLAY = {
    "MAIN_CALIBER":              ("主炮命中",  "ribbon_main_caliber"),
    "MAIN_CALIBER_PENETRATION":  ("穿透",     "ribbon_main_caliber"),
    "MAIN_CALIBER_NO_PENETRATION":("未穿",    "ribbon_main_caliber"),
    "MAIN_CALIBER_OVER_PENETRATION":("过穿","ribbon_main_caliber"),
    "MAIN_CALIBER_RICOCHET":     ("跳弹",     "ribbon_main_caliber"),
    "CITADEL":                   ("命中装甲区", "ribbon_citadel"),
    "TORPEDO":                   ("鱼雷命中", "ribbon_torpedo"),
    "TORPEDO_PROTECTION_HIT":    ("鱼雷防护命中", "ribbon_torpedo"),
    "SECONDARY_CALIBER":         ("副炮",     "ribbon_secondary_caliber"),
    "PLANE":                     ("击落",     "ribbon_plane"),
    "FRAG":                      ("击沉",     "ribbon_frag"),
    "BURN":                      ("纵火",     "ribbon_burn"),
    "FLOOD":                     ("进水",     "ribbon_flood"),
    "CRIT":                      ("瘫痪",     "ribbon_crit"),
    "DETECTED":                  ("点亮",     "ribbon_detected"),
    "BUILDING_KILL":             ("摧毁建筑", "ribbon_building_kill"),
    "BASE_DEFENSE":              ("防御",     "ribbon_base_defense"),
    "BASE_CAPTURE":              ("占点",     "ribbon_base_capture"),
    "BASE_CAPTURE_ASSIST":       ("协占",     "ribbon_base_capture_assist"),
    "ASSIST":                    ("协助击杀", "ribbon_assist"),
    "BOMB":                      ("炸弹",     "ribbon_bomb"),
    "BOMB_PENETRATION":          ("炸穿",     "ribbon_bomb"),
    "BOMB_NO_PENETRATION":       ("炸未穿",   "ribbon_bomb"),
    "BOMB_OVER_PENETRATION":     ("炸过穿",   "ribbon_bomb"),
    "BOMB_RICOCHET":             ("炸跳弹",   "ribbon_bomb"),
    "ROCKET":                    ("火箭命中", "ribbon_rocket"),
    "ROCKET_PENETRATION":        ("火箭穿",   "ribbon_rocket"),
    "ROCKET_NO_PENETRATION":     ("火箭未穿", "ribbon_rocket"),
    "ROCKET_OVER_PENETRATION":   ("火箭过穿", "ribbon_rocket"),
    "ROCKET_RICOCHET":           ("火箭跳",   "ribbon_rocket"),
    "DBOMB":                     ("深弹命中", "ribbon_dbomb"),
    "DBOMB_FULL_DAMAGE":         ("深弹满伤", "ribbon_dbomb"),
    "DBOMB_PARTIAL_DAMAGE":      ("深弹半伤", "ribbon_dbomb"),
    "DROP":                      ("拾取增益", "ribbon_drop"),
    "ACOUSTIC_HIT_VEHICLE_NEW":   ("声纳命中",     "ribbon_acoustic_hit"),
    "ACOUSTIC_HIT_VEHICLE_CURR":  ("声纳二次命中", "ribbon_acoustic_hit"),
    "ACOUSTIC_HIT_VEHICLE_BLOCK": ("声纳被吸收",   "ribbon_acoustic_hit"),
    "ACOUSTIC_HIT":               ("声纳命中",     "ribbon_acoustic_hit"),
    "SUPPRESSED":                ("压制",     "ribbon_suppressed"),
    "BULGE":                     ("主炮中鱼雷防护",  "ribbon_main_caliber"),
    "BOMB_BULGE":                ("炸弹中鱼雷防护",  "ribbon_bomb"),
    "ROCKET_BULGE":              ("火箭中鱼雷防护",  "ribbon_rocket"),
    "MISSILE":                   ("导弹",     "ribbon_missile"),
    "MINE":                      ("水雷",     "ribbon_mine"),
    "DEMINING_MINE":             ("排除水雷", "ribbon_demining_mine"),
    "DEMINING_MINEFIELD":        ("清空雷场", "ribbon_demining_minefield"),
}


_RIBBON_ICON_CACHE = {}


def load_ribbon_icon(basename: str, target_w: int = 36) -> Optional[Image.Image]:
    """加载勋带 PNG 并缩放(按宽度,保持原比例)。
    原图通常是 133x51 的横向 banner,target_w 可以大于原宽实现上采样。"""
    key = f"{basename}@w{target_w}"
    if key in _RIBBON_ICON_CACHE:
        return _RIBBON_ICON_CACHE[key]
    path = Path(RIBBON_ICON_DIR) / f"{basename}.png"
    try:
        src = Image.open(path).convert("RGBA")
        sw, sh = src.size
        target_h = max(1, round(target_w * sh / sw))
        img = src.resize((target_w, target_h), Image.LANCZOS)
        _RIBBON_ICON_CACHE[key] = img
        return img
    except Exception:
        _RIBBON_ICON_CACHE[key] = None
        return None


def extract_ribbons(ri):
    """[(label, icon_basename, count)] non-zero, in display order."""
    load_result_indices()
    out = []
    for raw_key, (label, icon) in RIBBON_DISPLAY.items():
        n = result_field(ri, f"RIBBON_{raw_key}", 0) or 0
        if n > 0:
            out.append((label, icon, int(n)))
    return out


# ---------- pie chart helpers ----------------------------------------------

def draw_pie(img: Image.Image, draw: ImageDraw.ImageDraw,
             center: tuple[int, int], radius: int,
             slices: list[tuple[str, tuple[int, int, int], int]]):
    cx, cy = center
    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
    total = sum(v for _, _, v in slices)
    if total == 0:
        draw.ellipse(bbox, fill=GAME_PANEL, outline=GAME_BORDER, width=2)
        return
    angle = -90  # start at 12 o'clock
    for label, color, value in slices:
        frac = value / total
        end = angle + frac * 360
        draw.pieslice(bbox, angle, end, fill=color, outline=GAME_BG, width=2)
        angle = end
    # inner hole (donut)
    inner = int(radius * 0.45)
    draw.ellipse([cx - inner, cy - inner, cx + inner, cy + inner],
                 fill=GAME_BG, outline=GAME_BORDER, width=1)


def draw_legend(draw, x, y, w, slices, total, f_label, f_num):
    """Vertical legend with color square, label, value, percentage."""
    line_h = 26
    for i, (label, color, value) in enumerate(slices):
        ly = y + i * line_h
        # color square
        draw.rectangle([x, ly + 4, x + 14, ly + 18], fill=color, outline=GAME_BORDER)
        # label
        draw.text((x + 22, ly), label, GAME_TEXT, f_label)
        # value (right-aligned to (x+w-90))
        val_str = f"{value:,}".replace(",", " ")
        vb = f_num.getbbox(val_str)
        vw = vb[2] - vb[0]
        draw.text((x + w - 90 - vw, ly + 2), val_str, GAME_TEXT, f_num)
        # percent
        pct = value / total * 100 if total else 0
        draw.text((x + w - 60, ly + 2), f"{pct:5.1f}%", GAME_GOLD, f_num)


# ---------- top-level renderer ---------------------------------------------

def render(json_path: str, out_path: str):
    raw = json.load(open(json_path))
    m = raw["match"]
    self_p = next((p for p in raw["players"]
                   if p["name"] == m["self_player_name"]), None)
    if self_p is None:
        raise RuntimeError("self player not found in JSON")
    ri = self_p["results_info"] or []

    dealt = aggregate(ri, DEALT_CATEGORIES)
    recvd = aggregate(ri, RECEIVED_CATEGORIES)
    ribbons = extract_ribbons(ri)

    dealt_total = sum(v for _, _, v in dealt)
    recvd_total = sum(v for _, _, v in recvd)
    actual_taken = int(self_p["stats"]["max_health"] - self_p["stats"]["final_health"])
    healed = max(0, recvd_total - actual_taken)

    # Layout
    W = 1700
    skip_header = os.environ.get("WOWS_SKIP_HEADER") == "1"
    skip_footer = os.environ.get("WOWS_SKIP_FOOTER") == "1"
    header_h = 0 if skip_header else 110
    footer_h = 0 if skip_footer else 32
    pie_h = 580
    pad = 20

    # 勋带块: 模仿 WG 后战屏 —— 横向 banner ribbon + 上叠白色 xN + 下方 label。
    # 原始 PNG 是 ~133x51 (2.6:1),拉到 RIBBON_BANNER_W 宽,高按比例。
    RIBBON_BANNER_W = 180       # ribbon 主图宽度(像素),高度自动按比例
    RIBBON_ITEMS_PER_ROW = 8    # 每行 8 个,紧排,1700 宽足够
    RIBBON_ROW_HEIGHT = 110     # ribbon banner ~69 + label 20 + padding
    RIBBON_TITLE_BAND = 50
    ribbon_rows = max(1, -(-len(ribbons) // RIBBON_ITEMS_PER_ROW))  # ceil div
    ribbon_h = RIBBON_TITLE_BAND + ribbon_rows * RIBBON_ROW_HEIGHT + 16

    H = header_h + pad + pie_h + pad + ribbon_h + pad + footer_h

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)

    def f(p, s): return ImageFont.truetype(p, s)
    f_title = f(CJK_FONT, 30)
    f_h2 = f(CJK_FONT, 22)
    f_h3 = f(CJK_FONT, 18)
    f_label = f(CJK_FONT, 15)
    f_num = f(MONO_FONT, 15)
    f_big_num = f(MONO_FONT, 30)
    f_small = f(CJK_FONT, 13)
    f_tiny = f(CJK_FONT, 12)

    # ---- HEADER ----
    if not skip_header:
        draw.rectangle([0, 0, W, header_h], fill=(14, 19, 30))
        draw.line([0, header_h, W, header_h], fill=GAME_GOLD, width=2)
        map_zh = t(f"IDS_SPACES/{m['map_name'].split('/')[-1].upper()}",
                   m["map_name"].split("/")[-1])
        ship_index = self_p["ship"].get("index", "")
        ship_zh = t(f"IDS_{ship_index}", self_p["ship"]["name"]) if ship_index else self_p["ship"]["name"]
        title = f"战斗复盘 — {self_p['name']} · {ship_zh}"
        draw.text((24, 14), title, GAME_TEXT, f_title)
        br = m.get("battle_result") or {}
        result_label = {"Win": "胜利", "Loss": "失败", "Draw": "平局"}.get(br.get("type", "?"), "?")
        result_color = {"胜利": GAME_GREEN, "失败": GAME_RED, "平局": GAME_GOLD}.get(result_label, GAME_DIM)
        # Render the sub-header as a sequence of (text, color) segments, advancing
        # x by the actual width of each piece so nothing overlaps.
        segments = [
            (map_zh, GAME_DIM),
            ("   ", GAME_DIM),
            (result_label, result_color),
            ("   ", GAME_DIM),
            (m.get("date_time", "?"), GAME_DIM),
            ("   时长 " + fmt_time(int(m.get("duration_seconds_played") or 0)), GAME_DIM),
        ]
        sx = 24
        for text, color in segments:
            draw.text((sx, 60), text, color, f_h2)
            sx += f_h2.getbbox(text)[2]

    # ---- TWO PIES ----
    y = header_h + pad
    block_w = (W - 3 * pad) // 2

    def render_pie_block(x, slices, total, title, subtitle):
        # panel bg
        draw.rounded_rectangle([x, y, x + block_w, y + pie_h],
                               radius=10, fill=GAME_PANEL,
                               outline=GAME_BORDER, width=1)
        draw.text((x + 20, y + 14), title, GAME_TEXT, f_h2)
        draw.text((x + 20, y + 46), subtitle, GAME_DIM, f_small)
        # pie
        pie_cx = x + 180
        pie_cy = y + 80 + 200
        pie_r = 150
        if total > 0:
            draw_pie(img, draw, (pie_cx, pie_cy), pie_r, slices)
            # center total
            big = f"{total:,}".replace(",", " ")
            bb = f_big_num.getbbox(big)
            bw, bh = bb[2] - bb[0], bb[3] - bb[1]
            draw.text((pie_cx - bw // 2, pie_cy - bh // 2 - 4),
                      big, GAME_GOLD, f_big_num)
        else:
            # empty placeholder
            draw.ellipse([pie_cx - pie_r, pie_cy - pie_r,
                          pie_cx + pie_r, pie_cy + pie_r],
                         outline=GAME_BORDER, width=2)
            draw.text((pie_cx - 40, pie_cy - 8), "无数据", GAME_DIM, f_h3)
        # legend on right
        legend_x = x + 360
        legend_y = y + 90
        legend_w = block_w - 380
        draw_legend(draw, legend_x, legend_y, legend_w,
                    slices, total, f_label, f_num)

    render_pie_block(pad, dealt, dealt_total,
                     "输出伤害分布",
                     f"总击伤 {dealt_total:,}".replace(",", " "))
    render_pie_block(pad * 2 + block_w, recvd, recvd_total,
                     "受伤来源分布",
                     f"累计被打 {recvd_total:,}   实际承伤 {actual_taken:,}   被治疗 {healed:,}".replace(",", " "))

    # ---- RIBBONS ----
    y += pie_h + pad
    draw.rounded_rectangle([pad, y, W - pad, y + ribbon_h],
                           radius=10, fill=GAME_PANEL,
                           outline=GAME_BORDER, width=1)
    draw.text((pad + 20, y + 14), "勋带", GAME_TEXT, f_h2)
    if not ribbons:
        draw.text((pad + 20, y + 56), "本场无勋带数据", GAME_DIM, f_h3)
    else:
        # WG 后战屏样式: banner + xN 覆盖在右半 + label 在 banner 下方
        inner_w = W - 2 * pad - 32
        item_w = inner_w // RIBBON_ITEMS_PER_ROW
        row_y0 = y + RIBBON_TITLE_BAND
        f_ribbon_count = f(MONO_FONT, 22)   # xN 字号(略小于上一版)
        f_ribbon_label = f(CJK_FONT, 16)    # label 字号
        for i, (label, icon_base, count) in enumerate(ribbons):
            row = i // RIBBON_ITEMS_PER_ROW
            col = i % RIBBON_ITEMS_PER_ROW
            ax = pad + 16 + col * item_w
            ay = row_y0 + row * RIBBON_ROW_HEIGHT + 6
            icon = load_ribbon_icon(icon_base, RIBBON_BANNER_W)
            if icon:
                img.paste(icon, (ax, ay), icon)
                bw, bh = icon.size
            else:
                bw, bh = RIBBON_BANNER_W, int(RIBBON_BANNER_W * 51 / 133)

            # xN 叠在 banner 右半部分(白色 + 1px 黑边,任何底色都可读)
            cnt_str = f"x{count}"
            cb = f_ribbon_count.getbbox(cnt_str)
            cw = cb[2] - cb[0]
            ch = cb[3] - cb[1]
            cx = ax + bw - cw - 12  # 距 banner 右边 12px
            cy = ay + (bh - ch) // 2 - 2
            # 简易黑色描边
            for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                draw.text((cx + ox, cy + oy), cnt_str, (0, 0, 0), f_ribbon_count)
            draw.text((cx, cy), cnt_str, (255, 255, 255), f_ribbon_count)

            # label 在 banner 下方(banner 左对齐)
            draw.text((ax + 4, ay + bh + 4), label, GAME_TEXT, f_ribbon_label)

    if not skip_footer:
        _draw_footer(draw, pad, H - footer_h + 10)

    img.save(out_path)
    print(f"saved: {out_path}", file=sys.stderr)


def _draw_footer(draw, x, y):
    """底部一行作者+版本+时间。"""
    import datetime
    bot_ver = os.environ.get("WOWS_BOT_VERSION", "")
    parts = ["本图由 EssexBot 渲染"]
    if bot_ver:
        parts.append(bot_ver)
    parts.append("作者 [NUIST]___Ciallo___")
    parts.append(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    text = "  ·  ".join(parts)
    f_foot = ImageFont.truetype(CJK_FONT, 13)
    draw.text((x, y), text, fill=GAME_DIM, font=f_foot)


def main():
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    render(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
