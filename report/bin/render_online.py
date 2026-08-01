# report/bin/render_online.py
"""render_online.py — /在线 (WG 三服在线人数) 柱形图 PNG。

库用法 (bot import):
    from render_online import render_online_png
    render_online_png(out_path,
                      rows=[{"code":"asia","name":"亚服 ASIA","online":3996}, ...],
                      note="CN 360 服 / RU Lesta 独立运营,不含在内")
    rows 传进来的顺序不影响出图 —— 柱子恒按 亚→欧→美 从左到右排;
    online 为 None = 该服查询失败。

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
_CHART_TOP_PAD = 46      # header 到最高柱顶的留白 (放柱顶数值标签)
_CHART_H = 330           # 满格柱高
_XLABEL_H = 56           # 基线下方的服名区
_NOTE_H = 32

_FIXED_ORDER = ["asia", "eu", "na"]   # 亚 → 欧 → 美,左到右,恒定不排序

# realm code → 强调色 (柱身 + 数值)
_REALM_COLOR = {
    "asia": (240, 200, 80),    # 金
    "eu":   (95, 155, 235),    # 蓝
    "na":   (110, 200, 120),   # 绿
}


def render_online_png(out_path: str, *, rows: list, note: str = "") -> str:
    by_code = {r.get("code"): r for r in rows}
    # 恒定 亚欧美 顺序;传进来有哪些就画哪些 (缺的跳过)
    order = [c for c in _FIXED_ORDER if c in by_code]
    order += [c for c in by_code if c not in _FIXED_ORDER]  # 兜底:未知服排最后

    ok_vals = [by_code[c]["online"] for c in order if by_code[c].get("online") is not None]
    total = sum(ok_vals)
    max_val = max(ok_vals) if ok_vals else 1

    fonts = {
        "title": _font(CJK_FONT, 30),
        "sub":   _font(CJK_FONT, 17),
        "value": _font(MONO_FONT, 30),
        "name":  _font(CJK_FONT, 24),
        "fail":  _font(CJK_FONT, 18),
        "note":  _font(CJK_FONT, 15),
    }

    H = (_HEADER_H + _CHART_TOP_PAD + _CHART_H + _XLABEL_H
         + (_NOTE_H if note else 0) + FOOTER_H)

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)

    # ----- Header -----
    draw.rectangle([0, 0, W, _HEADER_H], fill=GAME_PANEL)
    draw.line([0, _HEADER_H, W, _HEADER_H], fill=GAME_GOLD, width=2)
    draw.text((PAD, 20), "WoWs 在线人数", GAME_TEXT, fonts["title"])
    sub = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    if len(ok_vals) >= 2:
        sub += f"   ·   合计 {_fmt_int(total)}"
    draw.text((PAD, 62), sub, GAME_DIM, fonts["sub"])

    # ----- 柱形图 -----
    baseline_y = _HEADER_H + _CHART_TOP_PAD + _CHART_H
    plot_left = PAD + 20
    plot_right = W - PAD - 20
    draw.line([plot_left, baseline_y, plot_right, baseline_y],
              fill=GAME_BORDER, width=2)

    n = max(1, len(order))
    slot_w = (plot_right - plot_left) / n
    bar_w = int(min(150, slot_w * 0.46))

    for i, code in enumerate(order):
        r = by_code[code]
        name = r.get("name", code)
        online = r.get("online")
        col = _REALM_COLOR.get(code, GAME_GREEN)
        cx = int(plot_left + slot_w * (i + 0.5))
        x0, x1 = cx - bar_w // 2, cx + bar_w // 2

        if online is None:
            # 失败:画个矮灰墩 + 红字
            stub_top = baseline_y - 24
            draw.rounded_rectangle([x0, stub_top, x1, baseline_y],
                                   radius=6, fill=GAME_PANEL_ALT)
            draw.rectangle([x0, baseline_y - 6, x1, baseline_y], fill=GAME_PANEL_ALT)
            _centered(draw, cx, stub_top - 28, "查询失败", GAME_RED, fonts["fail"])
        else:
            bar_h = max(8, int(_CHART_H * (online / max_val))) if max_val else 8
            bar_top = baseline_y - bar_h
            draw.rounded_rectangle([x0, bar_top, x1, baseline_y], radius=6, fill=col)
            draw.rectangle([x0, baseline_y - 6, x1, baseline_y], fill=col)  # 方底座
            _centered(draw, cx, bar_top - 36, _fmt_int(online), col, fonts["value"])

        # 服名 (基线下方)
        _centered(draw, cx, baseline_y + 16, name, GAME_TEXT, fonts["name"])

    # ----- 备注 -----
    if note:
        draw.text((plot_left, baseline_y + _XLABEL_H - 4), note,
                  GAME_DIM, fonts["note"])

    _draw_footer(draw, 0, H - FOOTER_H, W, FOOTER_H)
    img.save(out_path)
    return out_path


def _centered(draw, cx, y, text, fill, font):
    w = int(font.getlength(text))
    draw.text((cx - w // 2, y), text, fill, font)


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
