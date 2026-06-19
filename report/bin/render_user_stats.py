# report/bin/render_user_stats.py
"""render_user_stats.py — /用户统计 (仅超管) 卡片 PNG。

库用法 (bot 直接 import):
    from render_user_stats import render_user_stats_png
    render_user_stats_png(out_path, total_users=N, total_calls=M,
                          top=[{"user_id":..,"nickname":..,"total":..,
                                "by_feature":{...}}, ...])

CLI (调试):
    render_user_stats.py <out.png> --json '{"total_users":3,"total_calls":42,"top":[...]}'

风格复用 /船 卡(GAME_BG / GAME_PANEL_ALT / 圆角 / 字体)。
"""
import argparse
import datetime as _dt
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_query import (  # noqa: E402
    GAME_BG, GAME_PANEL, GAME_PANEL_ALT, GAME_TEXT, GAME_DIM, GAME_BORDER,
    GAME_GREEN, GAME_GOLD, CJK_FONT, MONO_FONT,
    W, PAD, FOOTER_H, _font, _draw_footer, _fmt_int,
)
from PIL import Image, ImageDraw  # noqa: E402

_HEADER_H = 110
_ROW_H = 96
_AVATAR_SIZE = 72
_RANK_COLORS = {
    1: (240, 200, 80),     # 金
    2: (200, 210, 220),    # 银
    3: (210, 145, 75),     # 铜
}

# 功能 tag → 中文
_FEATURE_ZH = {
    "ship": "船", "query": "查询", "line": "线",
    "replay": "回放", "guess_start": "猜船", "guess_win": "猜中",
}


def _fetch_avatar(user_id: str, size: int = _AVATAR_SIZE) -> Image.Image:
    """从 QQ 头像 CDN 拉一张,返回 size×size 圆形 RGBA 头像;失败给个灰色 placeholder。"""
    url = f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "EssexBot/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = resp.read()
        im = Image.open(io.BytesIO(data)).convert("RGBA")
    except (urllib.error.URLError, OSError, ValueError):
        im = Image.new("RGBA", (size, size), (90, 110, 140, 255))
    im = im.resize((size, size), Image.LANCZOS)
    # 圆形 mask
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


def _features_str(by_feature: dict) -> str:
    """{'ship': 10, 'query': 5} → '船 10 · 查询 5'(按次数降序,只展示前 4 个)。"""
    if not by_feature:
        return "—"
    items = sorted(by_feature.items(), key=lambda kv: -int(kv[1]))[:4]
    return "  ·  ".join(f"{_FEATURE_ZH.get(k, k)} {v}" for k, v in items)


def render_user_stats_png(out_path: str, *, total_users: int, total_calls: int,
                          top: list) -> str:
    """渲一张用户统计卡。top 是按 total 降序的 list,每条 {user_id, nickname, total, by_feature}。"""
    fonts = {
        "title":   _font(CJK_FONT, 30),
        "sub":     _font(CJK_FONT, 17),
        "rank":    _font(MONO_FONT, 28),
        "name":    _font(CJK_FONT, 20),
        "uid":     _font(MONO_FONT, 13),
        "total":   _font(MONO_FONT, 26),
        "label":   _font(CJK_FONT, 13),
        "feature": _font(CJK_FONT, 14),
    }
    n = min(5, len(top))
    body_h = max(1, n) * _ROW_H + 16
    H = _HEADER_H + body_h + FOOTER_H

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)

    # ----- Header -----
    draw.rectangle([0, 0, W, _HEADER_H], fill=GAME_PANEL)
    draw.line([0, _HEADER_H, W, _HEADER_H], fill=GAME_GOLD, width=2)
    draw.text((PAD, 22), "用户统计", GAME_TEXT, fonts["title"])
    sub = (f"总用户数  {_fmt_int(total_users)}   "
           f"·   总调用  {_fmt_int(total_calls)}   "
           f"·   {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}")
    draw.text((PAD, 66), sub, GAME_DIM, fonts["sub"])

    if n == 0:
        draw.text((PAD, _HEADER_H + 30), "暂无数据", GAME_DIM, fonts["sub"])
        _draw_footer(draw, 0, H - FOOTER_H, W, FOOTER_H)
        img.save(out_path)
        return out_path

    # ----- Top 5 -----
    y = _HEADER_H + 8
    for i in range(n):
        u = top[i]
        rank = i + 1
        rank_col = _RANK_COLORS.get(rank, GAME_DIM)
        row_top = y
        row_bot = y + _ROW_H - 8
        # 行底色 — 1/2/3 名加淡色描边
        draw.rounded_rectangle([PAD, row_top, W - PAD, row_bot],
                               radius=10, fill=GAME_PANEL_ALT,
                               outline=rank_col if rank <= 3 else GAME_BORDER,
                               width=2 if rank <= 3 else 1)
        # rank 数字
        rank_x = PAD + 12
        draw.text((rank_x, row_top + 20), f"#{rank}", rank_col, fonts["rank"])
        # avatar
        avatar = _fetch_avatar(str(u.get("user_id", "0")))
        img.paste(avatar, (rank_x + 60, row_top + 8), avatar)
        # 昵称 + uid
        name_x = rank_x + 60 + _AVATAR_SIZE + 14
        nick = str(u.get("nickname") or u.get("user_id", "?"))
        if len(nick) > 18:
            nick = nick[:18] + "…"
        draw.text((name_x, row_top + 12), nick, GAME_TEXT, fonts["name"])
        draw.text((name_x, row_top + 40), f"QQ {u.get('user_id','?')}",
                  GAME_DIM, fonts["uid"])
        draw.text((name_x, row_top + 58), _features_str(u.get("by_feature") or {}),
                  GAME_DIM, fonts["feature"])
        # 总次数(右对齐大字)
        total_str = _fmt_int(int(u.get("total", 0)))
        total_w = int(fonts["total"].getlength(total_str))
        tx = W - PAD - 18 - total_w
        draw.text((tx, row_top + 18), total_str, GAME_GREEN, fonts["total"])
        draw.text((W - PAD - 18 - int(fonts["label"].getlength("次")),
                   row_top + 54), "次", GAME_DIM, fonts["label"])
        y += _ROW_H

    _draw_footer(draw, 0, H - FOOTER_H, W, FOOTER_H)
    img.save(out_path)
    return out_path


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--json", required=True,
                    help='JSON: {"total_users":N,"total_calls":M,"top":[{"user_id":..,"nickname":..,"total":..,"by_feature":{...}}]}')
    args = ap.parse_args()
    d = json.loads(args.json)
    render_user_stats_png(args.out, total_users=d["total_users"],
                          total_calls=d["total_calls"], top=d["top"])
    print(args.out)


if __name__ == "__main__":
    _cli()
