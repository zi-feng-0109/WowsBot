# report/bin/render_query.py
"""render_query.py — /查询 <编号> 结果卡片 PNG。

库用法 (bot 直接 import):
    from render_query import render_query_png
    render_query_png("/tmp/x.png", player=..., pvp=...)

CLI (调试):
    python render_query.py <out.png> --player-json '{"idx":1,...}' --pvp-json '{"battles":..}'
"""
import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_battle_report import (  # noqa: E402
    CJK_FONT, MONO_FONT,
    GAME_GREEN, GAME_RED, GAME_GOLD,
)
from PIL import Image, ImageDraw, ImageFont, ImageOps  # noqa: E402

# builds.json (ID→中文名 映射) 模块级缓存,首次调用时加载一次
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_BUILDS_PATH = _DATA_DIR / "builds.json"
_UPGRADE_ICON_DIR = _DATA_DIR / "upgrade_icons"
_SKILL_ICON_DIR   = _DATA_DIR / "skill_icons"
_BUILDS_CACHE: Optional[dict] = None
_ICON_CACHE: dict = {}  # (path, size, gray) → Image (RGBA)

# 每个 species 的舰长技能 grid (按游戏内 4 行 × N 列顺序排,左→右、上→下)。
# 值是 skill_type 列表 (跟 builds.json/replay learned_skills 一致)。
# 用户在 2026-05 用 iwarship 中文译名抓取后反查得到,需要随 WoWs 大版本更新校对。
# WG GameParams 没暴露 per-species mask,只能手工维护。
_SKILL_GRID = {
    # 水面舰种里 4 个 ID 反查中文名时撞了 SS/CV 专用变种 (79/80/82/56),
    # 实际游戏里水面舰种用的是 13/6/23/25。这是按真实 replay 校对过的。
    "Battleship": ([21, 8, 13, 5, 19, 18,
                    3, 33, 61, 7, 28, 35,
                    37, 40, 23, 2, 44, 27,
                    81, 26, 62, 42, 12, 14], 6),
    "Cruiser":    ([3, 24, 13, 21, 19, 20,
                    8, 4, 6, 43, 28, 27,
                    47, 30, 23, 38, 17, 25,
                    63, 66, 34, 33, 12, 35], 6),
    "Destroyer":  ([3, 60, 13, 21, 19, 18,
                    8, 24, 6, 39, 28, 20,
                    1, 4, 23, 33, 17, 25,
                    9, 65, 34, 64, 12, 67], 6),
    "AirCarrier": ([55, 11, 32, 29, 31, 51,
                    57, 58, 16, 83, 36, 49,
                    15, 48, 46, 10, 56, 22,
                    54, 59, 41, 53, 45, 50], 6),
    "Submarine":  ([68, 60, 74, 28, 19,
                    75, 72, 80, 18, 20,
                    69, 70, 79, 76, 17,
                    82, 73, 71, 77, 78], 5),
}


def _builds() -> Optional[dict]:
    global _BUILDS_CACHE
    if _BUILDS_CACHE is None:
        try:
            _BUILDS_CACHE = json.loads(_BUILDS_PATH.read_text("utf-8"))
        except Exception:
            _BUILDS_CACHE = {}
    return _BUILDS_CACHE or None


def _load_icon(path: Path, size: int, gray: bool = False) -> Optional["Image.Image"]:
    """加载图标 RGBA, resize 到 size×size。gray=True 转灰度 + 降透明 (未学技能)。"""
    key = (str(path), size, gray)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    if not path.is_file():
        _ICON_CACHE[key] = None
        return None
    try:
        im = Image.open(path).convert("RGBA")
        if im.size != (size, size):
            im = im.resize((size, size), Image.LANCZOS)
        if gray:
            # 转灰度,保留原 alpha 形状,降透明度让"未学"视觉上更暗
            r, g, b, a = im.split()
            gs = ImageOps.grayscale(im)
            new_a = a.point(lambda v: int(v * 0.4))
            im = Image.merge("RGBA", (gs, gs, gs, new_a))
        _ICON_CACHE[key] = im
        return im
    except Exception:
        _ICON_CACHE[key] = None
        return None

# 跟 render_menu 同步的亮色板 (信息面板风)
GAME_BG        = (38, 52, 78)
GAME_PANEL     = (58, 74, 106)
GAME_PANEL_ALT = (50, 64, 92)
GAME_TEXT      = (245, 248, 255)
GAME_DIM       = (190, 205, 225)
GAME_BORDER    = (105, 125, 155)

AUTHOR = "[NUIST]___Ciallo___"

W = 1100
PAD = 24
FOOTER_H = 48


def _font(path, size):
    return ImageFont.truetype(path, size)


def _draw_footer(draw, x, y, w, h):
    """跟 render_battle_report 同款 footer 条。"""
    draw.rectangle([x, y, x + w, y + h], fill=GAME_PANEL)
    draw.line([x, y, x + w, y], fill=GAME_GOLD, width=2)
    parts = ["本图由 EssexBot 渲染",
             f"作者 {AUTHOR}",
             datetime.datetime.now().strftime("%Y-%m-%d %H:%M")]
    text = "    ·    ".join(parts)
    f_foot = _font(CJK_FONT, 16)
    tw = int(f_foot.getlength(text))
    tx = x + (w - tw) // 2
    ty = y + (h - 20) // 2
    draw.text((tx, ty), text, fill=GAME_TEXT, font=f_foot)


def _fmt_int(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def _fmt_time(secs) -> str:
    if secs is None:
        return "?"
    s = int(secs)
    return f"{s // 60:02d}:{s % 60:02d}"


def render_query_png(out_path: str, *, player: dict, pvp: Optional[dict],
                      realm: Optional[str] = None) -> str:
    """渲一张 /查询 结果卡。
    player: query_index 里的 indexed player 一条 (含 idx/name/ship_zh/this_game…)
    pvp:    wg_api.fetch_ship_stats 返回 (None 即无数据);字段名按 vortex 来
            (battles_count / wins / survived / damage_dealt / frags ...)
    realm:  命中 realm (asia/cn/eu/na) — header 角标显示
    """
    # ----- 字体 -----
    f_idx_big     = _font(CJK_FONT, 56)   # #编号
    f_name        = _font(CJK_FONT, 28)
    f_ship        = _font(CJK_FONT, 22)
    f_section     = _font(CJK_FONT, 18)   # 本局 / 生涯
    f_label       = _font(CJK_FONT, 15)   # 击伤/胜率 等标签
    f_value_big   = _font(MONO_FONT, 32)
    f_value_med   = _font(MONO_FONT, 22)
    f_value_cjk   = _font(CJK_FONT, 22)
    f_compare_big = _font(MONO_FONT, 44)
    f_compare_cjk = _font(CJK_FONT, 16)
    f_dim         = _font(CJK_FONT, 14)

    # ----- 数据备齐 -----
    idx = player.get("idx", "?")
    name = player.get("name", "?")
    ship_zh = player.get("ship_zh") or player.get("ship_name", "?")
    lvl = player.get("ship_level", "?")
    species = player.get("species_zh", "")
    tg = player.get("this_game", {}) or {}
    this_dmg = int(tg.get("dmg", 0) or 0)
    this_frags = int(tg.get("frags", 0) or 0)
    alive = bool(tg.get("alive"))
    tl = tg.get("time_lived_secs")

    # ----- 本局配装数据 (build 缺失则不画 panel) -----
    build = player.get("build") or None
    species_raw = player.get("species_raw", "")
    build_names = _lookup_build_names(build, _builds(), species_raw) if build else None

    # ----- 高度 -----
    header_h = 110
    body_h   = 280
    compare_h = 80
    # panel 内: 50 top + 36 crew + 56 升级 + 4*42 skill grid + outline + bottom pad
    build_h  = 360 if build_names else 0
    H = header_h + body_h + compare_h + build_h + FOOTER_H

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)

    # ----- Header -----
    draw.rectangle([0, 0, W, header_h], fill=GAME_PANEL)
    draw.line([0, header_h, W, header_h], fill=GAME_GOLD, width=2)
    # #编号 圆角矩形 ribbon
    badge_text = f"#{idx}"
    bw = int(f_idx_big.getlength(badge_text)) + 28
    draw.rounded_rectangle([PAD, 18, PAD + bw, 18 + 70],
                           radius=10, fill=GAME_GOLD)
    draw.text((PAD + 14, 22), badge_text, (10, 16, 28), f_idx_big)
    # 名 + 船
    draw.text((PAD + bw + 24, 22), name, GAME_TEXT, f_name)
    ship_line = f"{ship_zh}  L{lvl} {species}"
    draw.text((PAD + bw + 24, 62), ship_line, GAME_DIM, f_ship)

    # ----- Body: 两栏 -----
    y = header_h + 12
    col_w = (W - PAD * 3) // 2
    left_x = PAD
    right_x = PAD + col_w + PAD

    # 左栏: 本局
    draw.rounded_rectangle([left_x, y, left_x + col_w, y + body_h - 12],
                           radius=10, fill=GAME_PANEL_ALT, outline=GAME_BORDER)
    draw.text((left_x + 18, y + 12), "本局", GAME_GOLD, f_section)
    _draw_kv(draw, left_x + 18, y + 50,
             "击伤", _fmt_int(this_dmg), f_label, f_value_big, big=True)
    _draw_kv(draw, left_x + 18, y + 130,
             "击杀", str(this_frags), f_label, f_value_med)
    _draw_kv(draw, left_x + 18, y + 180,
             "结局", ("存活" if alive else f"阵亡 {_fmt_time(tl)}"),
             f_label, f_value_cjk, color_value=(GAME_GREEN if alive else GAME_RED))

    # 右栏: 生涯
    draw.rounded_rectangle([right_x, y, right_x + col_w, y + body_h - 12],
                           radius=10, fill=GAME_PANEL_ALT, outline=GAME_BORDER)

    if not pvp or int(pvp.get("battles_count") or 0) == 0:
        draw.text((right_x + 18, y + 12), "生涯", GAME_GOLD, f_section)
        msg = ("CN/Asia/EU/NA/RU 均无该船 pvp 数据\n"
               "(可能:玩家隐藏隐私 / 未玩过 / vortex 暂不可用)"
               if not pvp else "该船 0 场 pvp 记录")
        draw.text((right_x + 18, y + 60), msg, GAME_DIM, f_label)
        avg_dmg = 0
    else:
        n         = int(pvp.get("battles_count") or 0)
        wins      = int(pvp.get("wins") or 0)
        surv      = int(pvp.get("survived") or 0)
        dmg_total = int(pvp.get("damage_dealt") or 0)
        frags_total = int(pvp.get("frags") or 0)
        win_rate  = wins / n * 100
        surv_rate = surv / n * 100
        avg_dmg   = dmg_total / n
        avg_frags = frags_total / n
        kdr       = frags_total / max(1, n - surv)

        realm_tag = f"  [{realm}服]" if realm else ""
        draw.text((right_x + 18, y + 12),
                  f"生涯 ({n} 场){realm_tag}", GAME_GOLD, f_section)

        # 一排排紧凑显示
        _draw_kv(draw, right_x + 18, y + 50,
                 "均伤", _fmt_int(avg_dmg), f_label, f_value_big, big=True)

        # 第二列开始的小指标
        row_y = y + 130
        _draw_kv(draw, right_x + 18, row_y,
                 "胜率", f"{win_rate:.1f}%", f_label, f_value_med,
                 color_value=_win_color(win_rate))
        _draw_kv(draw, right_x + 18 + col_w // 2, row_y,
                 "生存率", f"{surv_rate:.1f}%", f_label, f_value_med)

        row_y += 60
        _draw_kv(draw, right_x + 18, row_y,
                 "均击杀", f"{avg_frags:.2f}", f_label, f_value_med)
        _draw_kv(draw, right_x + 18 + col_w // 2, row_y,
                 "KDR", f"{kdr:.2f}", f_label, f_value_med)

    # ----- 对比条 -----
    cy = header_h + body_h
    draw.rectangle([0, cy, W, cy + compare_h], fill=GAME_BG)
    if pvp and avg_dmg > 0:
        pct = (this_dmg / avg_dmg - 1) * 100
        sign = "+" if pct >= 0 else ""
        big = f"{sign}{pct:.0f}%"
        color = GAME_GREEN if pct >= 0 else GAME_RED
        bw_big = int(f_compare_big.getlength(big))
        # 居中: "本局击伤是生涯均值的"   <BIG>
        prefix = "本局击伤  vs  生涯均值"
        pw = int(f_compare_cjk.getlength(prefix))
        total_w = pw + 18 + bw_big
        sx = (W - total_w) // 2
        draw.text((sx, cy + 32), prefix, GAME_DIM, f_compare_cjk)
        draw.text((sx + pw + 18, cy + 18), big, color, f_compare_big)
    else:
        msg = "无生涯数据,无法对比"
        mw = int(f_compare_cjk.getlength(msg))
        draw.text(((W - mw) // 2, cy + 32), msg, GAME_DIM, f_compare_cjk)

    # ----- 本局配装 panel -----
    if build_names:
        by = header_h + body_h + compare_h
        _draw_build_panel(img, draw, PAD, by + 12, W - 2 * PAD, build_h - 24,
                          build_names, f_section, f_label, f_value_cjk, f_dim)

    # ----- Footer -----
    _draw_footer(draw, 0, H - FOOTER_H, W, FOOTER_H)

    img.save(out_path)
    return out_path


def _draw_kv(draw, x, y, label, value, f_label, f_value,
             big=False, color_value=GAME_TEXT):
    """单个 label/value 块。"""
    draw.text((x, y), label, GAME_DIM, f_label)
    draw.text((x, y + (24 if big else 22)), value, color_value, f_value)


def _lookup_build_names(build: dict, builds_data: Optional[dict],
                         species_raw: str) -> Optional[dict]:
    """把 build 翻成渲染端用的结构。
    - crew: str
    - mods: [(zh, icon_path | None) | None]  (None = 空槽 → 虚线占位)
    - skills_grid: {"rows": [[item, ...], ...], "cols": int}
      item = {"zh": str, "icon": Path|None, "learned": bool, "st": int}
      没匹配 species (例如 Auxiliary) 时退化成单行只画学过的技能。
    """
    if not builds_data:
        return None

    crew_map = builds_data.get("crew", {})
    mod_map  = builds_data.get("modernization", {})
    mod_raw  = builds_data.get("modernization_raw", {})
    skl_map  = builds_data.get("skill", {})

    crew_id = build.get("crew_id")
    crew_zh = crew_map.get(str(crew_id), f"{crew_id}?") if crew_id else "-"

    mods = []
    for mid in (build.get("modernizations") or []):
        # 空槽 (玩家没装升级) WG 编码为 ID 0 — 用 None sentinel,渲染端画虚线占位
        if not mid:
            mods.append(None)
            continue
        zh = mod_map.get(str(mid), f"{mid}?")
        raw = mod_raw.get(str(mid))
        icon = _UPGRADE_ICON_DIR / f"{raw}.png" if raw else None
        mods.append((zh, icon if icon and icon.is_file() else None))

    learned = set(build.get("crew_skills") or [])

    def _skill_item(st: int, learned_flag: bool) -> dict:
        info = skl_map.get(str(st)) or {}
        internal = info.get("internal")
        icon = _SKILL_ICON_DIR / f"{internal}.png" if internal else None
        return {
            "zh": info.get("name") or f"{st}?",
            "icon": icon if icon and icon.is_file() else None,
            "learned": learned_flag,
            "st": st,
        }

    grid_spec = _SKILL_GRID.get(species_raw)
    if grid_spec:
        ids, cols = grid_spec
        rows = [[_skill_item(st, st in learned) for st in ids[i:i + cols]]
                for i in range(0, len(ids), cols)]
        skills_grid = {"rows": rows, "cols": cols}
    elif learned:
        # 未知 species — 单行平铺学过的,保留旧行为
        flat = [_skill_item(st, True) for st in sorted(learned)]
        skills_grid = {"rows": [flat], "cols": len(flat)}
    else:
        skills_grid = {"rows": [], "cols": 0}

    return {"crew": crew_zh, "mods": mods, "skills_grid": skills_grid}


def _wrap_tokens(tokens: list, sep: str, font, max_w: int) -> list:
    """把 token 列表用 sep 连成多行,每行宽度不超过 max_w。空列表返回 ['-']。"""
    if not tokens:
        return ["-"]
    lines = []
    cur = ""
    for tok in tokens:
        cand = tok if not cur else cur + sep + tok
        if int(font.getlength(cand)) <= max_w:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = tok
            # 单个 token 过长直接截断,避免死循环
            while int(font.getlength(cur)) > max_w and len(cur) > 1:
                cur = cur[:-1]
    if cur:
        lines.append(cur)
    return lines


def _draw_dashed_rect(draw, x0, y0, x1, y1, color, dash=4, gap=3, width=1):
    """画虚线矩形 (PIL 没自带)。用于空升级槽占位。"""
    step = dash + gap
    # 上下边
    px = x0
    while px < x1:
        draw.line([(px, y0), (min(px + dash, x1), y0)], fill=color, width=width)
        draw.line([(px, y1), (min(px + dash, x1), y1)], fill=color, width=width)
        px += step
    # 左右边
    py = y0
    while py < y1:
        draw.line([(x0, py), (x0, min(py + dash, y1))], fill=color, width=width)
        draw.line([(x1, py), (x1, min(py + dash, y1))], fill=color, width=width)
        py += step


def _draw_build_panel(img, draw, x, y, w, h, names: dict,
                       f_title, f_label, f_value, f_dim):
    """本局配装 panel:舰长 + 升级 grid + 技能 grid (4 行 N 列,已学高亮,未学灰度)。"""
    draw.rounded_rectangle([x, y, x + w, y + h],
                           radius=10, fill=GAME_PANEL_ALT, outline=GAME_BORDER)
    draw.text((x + 18, y + 12), "本局配装", GAME_GOLD, f_title)

    label_x = x + 18
    value_x = x + 18 + 72
    value_max_w = w - (value_x - x) - 18

    # 舰长行 (纯文字)
    row_y = y + 50
    draw.text((label_x, row_y + 2), "舰长", GAME_DIM, f_label)
    draw.text((value_x, row_y), names["crew"], GAME_TEXT, f_value)
    row_y += 36

    # 升级行 (单行 icon grid,跟之前一样)
    up_size = 42
    up_gap  = 8
    up_per_row = max(1, (value_max_w + up_gap) // (up_size + up_gap))
    draw.text((label_x, row_y + (up_size - 18) // 2), "升级", GAME_DIM, f_label)
    trimmed = list(names["mods"] or [])
    while trimmed and trimmed[-1] is None:
        trimmed.pop()
    if not trimmed:
        draw.text((value_x, row_y + (up_size - 22) // 2), "-", GAME_DIM, f_value)
    else:
        shown = trimmed[:up_per_row]
        overflow = len(trimmed) - len(shown)
        for i, slot in enumerate(shown):
            ix = value_x + i * (up_size + up_gap)
            if slot is None:
                _draw_dashed_rect(draw, ix, row_y, ix + up_size, row_y + up_size,
                                  GAME_BORDER, dash=4, gap=3)
                continue
            zh, icon_path = slot
            if icon_path:
                ic = _load_icon(icon_path, up_size)
                if ic is not None:
                    img.paste(ic, (ix, row_y), ic)
                    continue
            draw.rounded_rectangle([ix, row_y, ix + up_size, row_y + up_size],
                                   radius=4, fill=GAME_PANEL, outline=GAME_BORDER)
            tag = (zh or "?")[:2]
            tw = int(f_label.getlength(tag))
            draw.text((ix + (up_size - tw) // 2, row_y + up_size // 2 - 9),
                      tag, GAME_TEXT, f_label)
        if overflow > 0:
            ix = value_x + len(shown) * (up_size + up_gap)
            draw.text((ix, row_y + (up_size - 22) // 2),
                      f"+{overflow}", GAME_DIM, f_value)
    row_y += up_size + 14

    # 技能 grid (4 行 × 5 或 6 列,已学全色 + 蓝边框,未学灰度)
    sg = names.get("skills_grid") or {"rows": [], "cols": 0}
    rows = sg["rows"]
    cols = sg["cols"]
    if not rows:
        draw.text((label_x, row_y + 2), "技能", GAME_DIM, f_label)
        draw.text((value_x, row_y), "-", GAME_DIM, f_value)
        return

    sk_size = 36
    sk_gap  = 6
    # tier 数字标签留一列 (左侧) 模拟 game UI;整体左对齐,跟上面"升级"那行齐
    tier_lbl_w = 18
    grid_x = value_x + tier_lbl_w

    draw.text((label_x, row_y + 2), "技能", GAME_DIM, f_label)

    for r, row in enumerate(rows):
        gy = row_y + r * (sk_size + sk_gap)
        # 左侧 tier 数字
        tier_no = str(r + 1)
        draw.text((grid_x - tier_lbl_w + 2, gy + (sk_size - 18) // 2),
                  tier_no, GAME_DIM, f_label)
        for c, item in enumerate(row):
            gx = grid_x + c * (sk_size + sk_gap)
            learned = item["learned"]
            icon_path = item["icon"]
            # 选中的:蓝色高亮背景框
            if learned:
                draw.rounded_rectangle([gx - 2, gy - 2, gx + sk_size + 2, gy + sk_size + 2],
                                       radius=5, fill=(60, 130, 220), outline=GAME_GOLD)
            if icon_path:
                ic = _load_icon(icon_path, sk_size, gray=not learned)
                if ic is not None:
                    img.paste(ic, (gx, gy), ic)
                    continue
            # 兜底
            bg_fill = (245, 248, 255) if learned else (80, 95, 120)
            draw.rounded_rectangle([gx, gy, gx + sk_size, gy + sk_size],
                                   radius=3, fill=bg_fill, outline=GAME_BORDER)
            tag = (item["zh"] or "?")[:2]
            tw = int(f_label.getlength(tag))
            tcol = (10, 16, 28) if learned else GAME_DIM
            draw.text((gx + (sk_size - tw) // 2, gy + sk_size // 2 - 9),
                      tag, tcol, f_label)


def _win_color(pct: float):
    if pct >= 60: return (188, 122, 232)   # GAME_PURPLE
    if pct >= 55: return GAME_GOLD
    if pct >= 50: return GAME_GREEN
    if pct >= 45: return GAME_TEXT
    return GAME_RED


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--player-json", required=True)
    ap.add_argument("--pvp-json", default="")
    args = ap.parse_args()
    player = json.loads(args.player_json)
    pvp = json.loads(args.pvp_json) if args.pvp_json else None
    render_query_png(args.out, player=player, pvp=pvp)
    print(args.out)


if __name__ == "__main__":
    _cli()
