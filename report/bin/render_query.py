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
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

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

    # ----- 高度 -----
    header_h = 110
    body_h   = 280
    compare_h = 80
    H = header_h + body_h + compare_h + FOOTER_H

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
        msg = ("CN/Asia/EU/NA 均无该船 pvp 数据\n"
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

    # ----- Footer -----
    _draw_footer(draw, 0, H - FOOTER_H, W, FOOTER_H)

    img.save(out_path)
    return out_path


def _draw_kv(draw, x, y, label, value, f_label, f_value,
             big=False, color_value=GAME_TEXT):
    """单个 label/value 块。"""
    draw.text((x, y), label, GAME_DIM, f_label)
    draw.text((x, y + (24 if big else 22)), value, color_value, f_value)


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
