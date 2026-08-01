# report/bin/render_online.py
"""render_online.py — /在线 (WG 三服在线人数) 卡片 PNG。

库用法 (bot import):
    from render_online import render_online_png
    render_online_png(out_path,
                      rows=[{"code":"asia","name":"亚服 ASIA","online":3996}, ...],
                      note="CN 360 服 / RU Lesta 独立运营,不含在内")
    rows 已按调用方期望顺序排好;online 为 None = 该服查询失败。

CLI (调试):
    render_online.py <out.png> --json '{"rows":[{"code":"na","name":"美服 NA","online":5052}],"note":"..."}'

风格复用 /查询 卡 (render_query 的配色 / 字体 / footer)。
"""
import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_query import (  # noqa: E402
    GAME_BG, GAME_PANEL, GAME_PANEL_ALT, GAME_TEXT, GAME_DIM, GAME_BORDER,
    GAME_GREEN, GAME_RED, GAME_GOLD, CJK_FONT, MONO_FONT,
    W, PAD, FOOTER_H, _font, _draw_footer, _fmt_int,
)
from PIL import Image, ImageDraw  # noqa: E402

_HEADER_H = 100
_ROW_H = 84
_TOTAL_H = 62
_NOTE_H = 34

# realm code → 强调色 (进度条 / 数字)
_REALM_COLOR = {
    "asia": (240, 200, 80),    # 金
    "eu":   (95, 155, 235),    # 蓝
    "na":   (110, 200, 120),   # 绿
}


def render_online_png(out_path: str, *, rows: list, note: str = "") -> str:
    fonts = {
        "title":   _font(CJK_FONT, 30),
        "sub":     _font(CJK_FONT, 17),
        "name":    _font(CJK_FONT, 24),
        "count":   _font(MONO_FONT, 32),
        "fail":    _font(CJK_FONT, 20),
        "total_l": _font(CJK_FONT, 22),
        "total_v": _font(MONO_FONT, 34),
        "note":    _font(CJK_FONT, 15),
    }
    ok_vals = [r["online"] for r in rows if r.get("online") is not None]
    total = sum(ok_vals)
    show_total = len(ok_vals) >= 2
    max_val = max(ok_vals) if ok_vals else 1

    n = len(rows)
    H = (_HEADER_H + n * _ROW_H + 12
         + (_TOTAL_H if show_total else 0)
         + (_NOTE_H if note else 0)
         + FOOTER_H)

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)

    # ----- Header -----
    draw.rectangle([0, 0, W, _HEADER_H], fill=GAME_PANEL)
    draw.line([0, _HEADER_H, W, _HEADER_H], fill=GAME_GOLD, width=2)
    draw.text((PAD, 20), "WoWs 在线人数", GAME_TEXT, fonts["title"])
    draw.text((PAD, 62),
              _dt.datetime.now().strftime("%Y-%m-%d %H:%M") + "   ·   WG 三服 (亚 / 欧 / 美)",
              GAME_DIM, fonts["sub"])

    # 列布局
    name_x = PAD + 20
    bar_x = PAD + 250
    count_right = W - PAD - 24
    bar_max_w = count_right - 220 - bar_x

    y = _HEADER_H + 6
    for r in rows:
        code = r.get("code", "")
        name = r.get("name", code)
        online = r.get("online")
        col = _REALM_COLOR.get(code, GAME_GREEN)
        row_top = y
        row_bot = y + _ROW_H - 8
        draw.rounded_rectangle([PAD, row_top, W - PAD, row_bot],
                               radius=10, fill=GAME_PANEL_ALT,
                               outline=GAME_BORDER, width=1)
        cy = (row_top + row_bot) // 2
        draw.text((name_x, cy - 16), name, GAME_TEXT, fonts["name"])
        if online is None:
            draw.text((bar_x, cy - 12), "查询失败", GAME_RED, fonts["fail"])
        else:
            # 进度条(底槽 + 前景)
            bar_top, bar_bot = cy - 11, cy + 11
            draw.rounded_rectangle([bar_x, bar_top, bar_x + bar_max_w, bar_bot],
                                   radius=8, fill=GAME_BG)
            bw = max(6, int(bar_max_w * (online / max_val))) if max_val else 6
            draw.rounded_rectangle([bar_x, bar_top, bar_x + bw, bar_bot],
                                   radius=8, fill=col)
            # 人数(右对齐)
            cnt = _fmt_int(online)
            cw = int(fonts["count"].getlength(cnt))
            draw.text((count_right - cw, cy - 18), cnt, col, fonts["count"])
        y += _ROW_H

    # ----- 合计 -----
    if show_total:
        ty = y + 6
        draw.line([name_x, ty, W - PAD - 20, ty], fill=GAME_BORDER, width=1)
        draw.text((name_x, ty + 16), "合计", GAME_GOLD, fonts["total_l"])
        tv = _fmt_int(total)
        tvw = int(fonts["total_v"].getlength(tv))
        draw.text((count_right - tvw, ty + 10), tv, GAME_GOLD, fonts["total_v"])
        y = ty + _TOTAL_H

    # ----- 备注 -----
    if note:
        draw.text((name_x, y + 6), note, GAME_DIM, fonts["note"])

    _draw_footer(draw, 0, H - FOOTER_H, W, FOOTER_H)
    img.save(out_path)
    return out_path


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--json", required=True,
                    help='JSON: {"rows":[{"code":..,"name":..,"online":..|null}],"note":".."}')
    args = ap.parse_args()
    d = json.loads(args.json)
    render_online_png(args.out, rows=d["rows"], note=d.get("note", ""))
    print(args.out)


if __name__ == "__main__":
    _cli()
