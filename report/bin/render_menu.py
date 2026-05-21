# report/bin/render_menu.py
"""render_menu.py — bot 功能菜单 PNG。

库用法 (bot 直接 import):
    from render_menu import render_menu_png
    png_bytes = render_menu_png(scope="group", ident="123456",
                                state_snapshot=..., is_super=False)

CLI 用法 (调试):
    render_menu.py <out.png> [--scope group --ident 123456 --super]
    (无 --scope 时按 private + 假 ident '0' 渲染)

复用 render_battle_report 的色板/字体常量,与战报视觉一致。
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_battle_report import (  # noqa: E402
    CJK_FONT, MONO_FONT,
    GAME_BG, GAME_PANEL, GAME_PANEL_ALT,
    GAME_TEXT, GAME_DIM, GAME_GREEN, GAME_RED, GAME_BORDER,
)
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

# bot 元信息 (跟 plugin/version.py 的内容保持口径一致 — CLI 模式下读不到 plugin,所以 hardcode)
AUTHOR = "[NUIST]___Ciallo___"

# 4 个 feature 必须跟 plugin/permissions.FEATURES 顺序一致
FEATURES = ["视频", "战报", "复盘", "分析"]
FEATURE_DESC = {
    "视频":  "MP4 战斗回放",
    "战报":  "全队成绩单",
    "复盘":  "主角伤害分布",
    "分析":  "埃酱复盘文本",
}

# 规划中功能;在这里追加: ("名字", "一句话简介")
PLANNED_FEATURES: list[tuple[str, str]] = [
    ("战犯系统", "自动选出败方四名战犯,按严重程度分甲/乙/丙/丁"),
]

W = 1100
PAD = 24
HEADER_H = 90
ROW_H = 42
SECTION_GAP = 18
FOOTER_H = 36


def _font(path, size):
    return ImageFont.truetype(path, size)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x3000 <= cp <= 0x303F or       # CJK Symbols and Punctuation
        0x3040 <= cp <= 0x30FF or       # Hiragana + Katakana
        0x3400 <= cp <= 0x4DBF or       # CJK Extension A
        0x4E00 <= cp <= 0x9FFF or       # CJK Unified Ideographs
        0xF900 <= cp <= 0xFAFF or       # CJK Compatibility Ideographs
        0xFF00 <= cp <= 0xFFEF          # Halfwidth & Fullwidth Forms
    )


def _draw_mixed(draw, xy, text, fill, mono_font, cjk_font):
    """ASCII 段用 mono_font, CJK 段用 cjk_font, 水平依次画。
    解决 Menlo / DejaVuSansMono 缺 CJK 字形导致的方框 (tofu) 问题。
    若 mono_font 与 cjk_font 相同 (MONO_FONT fallback 到 CJK_FONT),
    行为等价于一次性 draw.text(),没有任何视觉差。"""
    if not text:
        return
    x, y = xy
    runs: list[tuple[str, bool]] = []
    buf = [text[0]]
    cur = _is_cjk(text[0])
    for ch in text[1:]:
        new = _is_cjk(ch)
        if new == cur:
            buf.append(ch)
        else:
            runs.append(("".join(buf), cur))
            buf = [ch]
            cur = new
    runs.append(("".join(buf), cur))
    for s, is_cjk in runs:
        f = cjk_font if is_cjk else mono_font
        draw.text((x, y), s, fill=fill, font=f)
        x += int(f.getlength(s))


def _draw_status_dot(draw: ImageDraw.ImageDraw, x: int, y: int,
                     status: str) -> None:
    """status ∈ {'on', 'off', 'banned'} — 画 ●开 / ○关 / ✕禁。"""
    r = 9
    box = [x - r, y - r, x + r, y + r]
    if status == "on":
        draw.ellipse(box, fill=GAME_GREEN, outline=GAME_GREEN)
        label, color = "开", GAME_GREEN
    elif status == "off":
        draw.ellipse(box, outline=GAME_RED, width=2)
        label, color = "关", GAME_RED
    else:  # banned
        # 用两条对角线画 ✕,避免字体缺 U+2715 字形被渲成方框
        d = r - 2
        draw.line([(x - d, y - d), (x + d, y + d)], fill=GAME_DIM, width=2)
        draw.line([(x - d, y + d), (x + d, y - d)], fill=GAME_DIM, width=2)
        label, color = "禁", GAME_DIM
    draw.text((x + r + 6, y - 10), label, fill=color, font=_font(CJK_FONT, 16))


def _feature_status(state: dict, scope: str, ident: str, feature: str) -> str:
    if feature in state.get("global_blacklist", []):
        return "banned"
    bucket = state["groups" if scope == "group" else "private"]
    val = bucket.get(str(ident), {}).get(feature, True)  # DEFAULT_ON
    return "on" if val else "off"


def render_menu_png(out_path: str, *, scope: str, ident: str,
                    state_snapshot: dict, is_super: bool,
                    version: str = "v0.4.0") -> str:
    """渲染一张菜单 PNG 到 out_path,返回 out_path。
    state_snapshot 是 permissions.snapshot() 的输出。"""
    f_title   = _font(CJK_FONT, 30)
    f_meta    = _font(CJK_FONT, 15)
    f_section = _font(CJK_FONT, 20)
    f_row     = _font(CJK_FONT, 17)
    f_desc    = _font(CJK_FONT, 14)
    f_mono    = _font(MONO_FONT, 14)
    f_dim     = _font(CJK_FONT, 12)

    # 先估高度
    n_features = len(FEATURES)
    n_planned = len(PLANNED_FEATURES)
    sa_visible = is_super

    height = (
        HEADER_H + PAD
        + 30 + n_features * ROW_H + SECTION_GAP                  # 当前功能
        + 30 + 2 * ROW_H + SECTION_GAP                           # 使用方法
        + 30 + (4 if sa_visible else 3) * 28 + SECTION_GAP       # 全部指令
        + 30 + max(1, n_planned) * 24 + SECTION_GAP              # 规划中
        + FOOTER_H + PAD
    )

    img = Image.new("RGB", (W, height), GAME_BG)
    draw = ImageDraw.Draw(img)

    # ----- Header -----
    draw.rectangle([0, 0, W, HEADER_H], fill=GAME_PANEL)
    draw.text((PAD, 18), "战舰世界助手 · EssexBot", GAME_TEXT, f_title)
    draw.text((PAD, 58), f"{version}  ·  作者 {AUTHOR}", GAME_DIM, f_meta)

    y = HEADER_H + PAD

    # ----- 当前功能 -----
    draw.text((PAD, y), "【当前功能】", GAME_TEXT, f_section); y += 30
    name_x, desc_x, cmd_x, dot_x = PAD + 12, PAD + 110, PAD + 360, W - PAD - 80
    for feat in FEATURES:
        draw.rectangle([PAD, y, W - PAD, y + ROW_H - 2], fill=GAME_PANEL_ALT)
        draw.text((name_x, y + 10), feat, GAME_TEXT, f_row)
        draw.text((desc_x, y + 12), FEATURE_DESC[feat], GAME_DIM, f_desc)
        _draw_mixed(draw, (cmd_x, y + 10), f"/{feat} 开|关|状态",
                    GAME_TEXT, f_mono, f_desc)
        status = _feature_status(state_snapshot, scope, ident, feat)
        _draw_status_dot(draw, dot_x, y + ROW_H // 2, status)
        y += ROW_H
    y += SECTION_GAP

    # ----- 使用方法 -----
    draw.text((PAD, y), "【使用方法】", GAME_TEXT, f_section); y += 30
    draw.text((PAD + 12, y), "把 .wowsreplay 拖进群里 / 私聊我", GAME_TEXT, f_row); y += ROW_H
    draw.text((PAD + 12, y), "开着的输出会自动产生并发回", GAME_DIM, f_row); y += ROW_H
    y += SECTION_GAP

    # ----- 全部指令 -----
    draw.text((PAD, y), "【全部指令】", GAME_TEXT, f_section); y += 30
    cmds = [
        ("/菜单  /menu  /help", "打开本面板"),
        ("/<功能> 开|关|状态",   "切换或查看本群开关"),
        ("/<功能> 状态",         "看自己当前生效状态"),
    ]
    if sa_visible:
        cmds.append(("/sa ban|unban <功能>", "超管:全局禁/解禁"))
    for cmd, desc in cmds:
        _draw_mixed(draw, (PAD + 12, y), cmd, GAME_TEXT, f_mono, f_desc)
        draw.text((PAD + 320, y), desc, GAME_DIM, f_row)
        y += 28
    y += SECTION_GAP

    # ----- 规划中 -----
    draw.text((PAD, y), "【规划中】", GAME_DIM, f_section); y += 30
    if not PLANNED_FEATURES:
        draw.text((PAD + 12, y), "敬请期待…", GAME_DIM, f_row); y += 24
    else:
        for name, desc in PLANNED_FEATURES:
            draw.text((PAD + 12, y), f"· {name} — {desc}", GAME_DIM, f_row)
            y += 24
    y += SECTION_GAP

    # ----- Footer -----
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    draw.rectangle([0, height - FOOTER_H, W, height], fill=GAME_PANEL)
    draw.text((PAD, height - FOOTER_H + 10),
              f"本面板由 EssexBot 渲染 · {ts}", GAME_DIM, f_dim)

    img.save(out_path)
    return out_path


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", help="output PNG path")
    ap.add_argument("--scope", choices=["group", "private"], default="private")
    ap.add_argument("--ident", default="0")
    ap.add_argument("--super", action="store_true", dest="is_super",
                    help="渲染超管视角(显示 /sa 行)")
    ap.add_argument("--state-json",
                    help="可选:从该 JSON 读 state_snapshot;不给就用空 state")
    ap.add_argument("--version", default="v0.4.0",
                    help="版本字符串显示用")
    args = ap.parse_args()

    if args.state_json:
        with open(args.state_json, "r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {"version": 1, "global_blacklist": [], "groups": {}, "private": {}}

    render_menu_png(
        args.out, scope=args.scope, ident=args.ident,
        state_snapshot=state, is_super=args.is_super, version=args.version,
    )
    print(args.out)


if __name__ == "__main__":
    _cli()
