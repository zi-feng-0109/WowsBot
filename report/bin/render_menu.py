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
    GAME_GREEN, GAME_RED,
)
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

# 菜单专属调色板 — 比战报亮一档,适合"信息面板"风;不影响战报渲染。
GAME_BG        = (38, 52, 78)
GAME_PANEL     = (58, 74, 106)
GAME_PANEL_ALT = (50, 64, 92)
GAME_TEXT      = (245, 248, 255)
GAME_DIM       = (190, 205, 225)
GAME_BORDER    = (105, 125, 155)

# bot 元信息 (跟 plugin/version.py 的内容保持口径一致 — CLI 模式下读不到 plugin,所以 hardcode)
AUTHOR = "[NUIST]___Ciallo___"

# Feature 列表必须跟 plugin/permissions.FEATURES 顺序一致
FEATURES = ["视频", "战报", "复盘", "分析", "战犯"]
FEATURE_DESC = {
    "视频":  "MP4 战斗回放",
    "战报":  "全队成绩单",
    "复盘":  "主角伤害分布",
    "分析":  "埃酱复盘文本 [测试中...]",
    "战犯":  "败方战犯榜 [测试中...]",
}
# 跟 plugin/permissions.DEFAULT_ENABLED 同步;CLI 模式下读不到 plugin,本地硬编码。
DEFAULT_ENABLED = {
    "视频": True,
    "战报": True,
    "复盘": True,
    "分析": False,
    "战犯": False,
}

# 规划中功能;在这里追加: ("名字", "一句话简介")
PLANNED_FEATURES: list[tuple[str, str]] = [
    ("莱斯塔服务器 replay 渲染", "支持莱斯塔(Lesta)服务器战斗回放的渲染"),
    ("私聊渲染 replay", "私聊直接拖 .wowsreplay 渲染(修复中)"),
]

# 【游戏】section — 命令驱动的游戏类指令,跟 replay-toggle 不同源,单独一栏。
# (指令, 作用, 谁可用) — 复用 【全部指令】 的三列格式
GAME_COMMANDS: list[tuple[str, str, str]] = [
    ("/开始猜船 [最低级 最高级 舰种]", "按条件随机一艘船开猜", "任何人"),
    ("/一起猜 [最低级 最高级 舰种]",   "全群一起猜,先猜对获胜", "任何人"),
    ("/排位猜船",                    "6-11 级全舰种排位赛",   "任何人"),
    ("/查看答案",                    "投降并显示答案",        "任何人"),
    ("/排名  /我的排名",              "查看排位榜",            "任何人"),
    ("/玩法 [普通|排位]",             "猜船详细规则",          "任何人"),
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
    # 统一按 CJK 字体的基线对齐:mono 与 CJK 字体 ascent 不同,若都按顶部 (y) 画,
    # ASCII 符号 (/ | [ ]) 的基线会和中文错开,底部不齐平。改用 anchor="ls"
    # (左对齐 + 基线对齐),所有 run 共享同一基线。CJK 段位置与原来完全一致。
    ascent, _ = cjk_font.getmetrics()
    baseline = y + ascent
    for s, is_cjk in runs:
        f = cjk_font if is_cjk else mono_font
        draw.text((x, baseline), s, fill=fill, font=f, anchor="ls")
        x += int(f.getlength(s))


def _draw_status_dot(draw: ImageDraw.ImageDraw, x: int, y: int,
                     status: str) -> None:
    """iOS 风格 toggle switch — pill + 白圆 knob。x,y 是 pill 中心。"""
    pill_w = 62
    pill_h = 28
    knob_r = 11
    inset = 3
    x0, x1 = x - pill_w // 2, x + pill_w // 2
    y0, y1 = y - pill_h // 2, y + pill_h // 2

    f_pill = _font(MONO_FONT, 12)
    label = "ON" if status == "on" else "OFF"
    label_w = int(f_pill.getlength(label))
    text_pad = 4   # 文本与 knob / pill 边的间隙

    if status == "on":
        bg = GAME_GREEN
        knob_cx = x1 - knob_r - inset
        # 文字在 knob 左侧空白区居中
        text_area_l = x0 + text_pad
        text_area_r = knob_cx - knob_r - text_pad
    else:
        bg = (130, 145, 165)
        knob_cx = x0 + knob_r + inset
        # 文字在 knob 右侧空白区居中
        text_area_l = knob_cx + knob_r + text_pad
        text_area_r = x1 - text_pad

    label_x = (text_area_l + text_area_r - label_w) // 2

    draw.rounded_rectangle([x0, y0, x1, y1], radius=pill_h // 2, fill=bg)
    draw.ellipse(
        [knob_cx - knob_r, y - knob_r, knob_cx + knob_r, y + knob_r],
        fill=(248, 248, 250),
    )
    draw.text((label_x, y - 7), label, fill=(255, 255, 255), font=f_pill)


def _feature_status(state: dict, scope: str, ident: str, feature: str) -> str:
    """本群/本会话的实际开关 (开/关),不考虑超管黑名单。
    黑名单状态由 _super_status 单独显示。"""
    bucket = state["groups" if scope == "group" else "private"]
    default = DEFAULT_ENABLED.get(feature, True)
    val = bucket.get(str(ident), {}).get(feature, default)
    return "on" if val else "off"


def _super_status(state: dict, feature: str) -> str:
    """超管全局状态: enabled / banned。"""
    return "banned" if feature in state.get("global_blacklist", []) else "enabled"


def _draw_super_indicator(draw, x, y, status, f_label):
    """画"全局: 启用 / 禁用"小标记。位置 x = 文本起始。"""
    if status == "banned":
        # 红色 ✕ + 全局禁用
        d = 6
        cy = y + 8
        draw.line([(x, cy - d), (x + d * 2, cy + d)], fill=GAME_RED, width=2)
        draw.line([(x, cy + d), (x + d * 2, cy - d)], fill=GAME_RED, width=2)
        draw.text((x + d * 2 + 6, y), "全局禁用", GAME_RED, f_label)
    else:
        # 绿色 ✓ + 全局启用
        d = 6
        cy = y + 8
        draw.line([(x, cy + 2), (x + d, cy + d + 2)], fill=GAME_GREEN, width=2)
        draw.line([(x + d, cy + d + 2), (x + d * 2 + 2, cy - d)], fill=GAME_GREEN, width=2)
        draw.text((x + d * 2 + 8, y), "全局启用", GAME_DIM, f_label)


def render_menu_png(out_path: str, *, scope: str, ident: str,
                    state_snapshot: dict, is_super: bool,
                    version: str = "v0.4.0", guess_enabled=None) -> str:
    """渲染一张菜单 PNG 到 out_path,返回 out_path。
    state_snapshot 是 permissions.snapshot() 的输出。
    guess_enabled: 本群「猜船」开关状态 (True/False)；None 表示不显示该行
    (如私聊作用域)。猜船开关由 EssexBot 维护,这里只负责显示。"""
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
    n_games = len(GAME_COMMANDS)
    n_guess_row = 1 if guess_enabled is not None else 0  # 猜船开关行
    sa_visible = is_super

    height = (
        HEADER_H + PAD
        + 30 + 22 + (n_features + n_guess_row) * ROW_H + SECTION_GAP  # 当前功能 (含列头 22px)
        + 30 + 2 * ROW_H + SECTION_GAP                           # 使用方法
        + 30 + 22 + n_games * 28 + SECTION_GAP                   # 游戏 (含表头 22px)
        + 30 + 22 + (7 if sa_visible else 6) * 28 + SECTION_GAP  # 全部指令 (含表头 22px)
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
    name_x  = PAD + 12
    desc_x  = PAD + 110
    cmd_x   = PAD + 360
    super_x = PAD + 700   # 超管全局状态列
    dot_x   = W - PAD - 80
    # 列头
    draw.text((name_x,  y + 4), "功能", GAME_DIM, f_desc)
    draw.text((desc_x,  y + 4), "说明", GAME_DIM, f_desc)
    draw.text((cmd_x,   y + 4), "指令", GAME_DIM, f_desc)
    draw.text((super_x, y + 4), "超管", GAME_DIM, f_desc)
    draw.text((dot_x - 4, y + 4), "本群", GAME_DIM, f_desc)
    y += 22
    for feat in FEATURES:
        super_st = _super_status(state_snapshot, feat)
        toggle_st = _feature_status(state_snapshot, scope, ident, feat)
        draw.rectangle([PAD, y, W - PAD, y + ROW_H - 2], fill=GAME_PANEL_ALT)
        draw.text((name_x, y + 10), feat, GAME_TEXT, f_row)
        draw.text((desc_x, y + 12), FEATURE_DESC[feat], GAME_DIM, f_desc)
        if super_st == "banned":
            # 全局禁用时命令列改红字提示, 跟"全局禁用"标记呼应
            draw.text((cmd_x, y + 12), "本功能暂时关闭", GAME_RED, f_desc)
        else:
            _draw_mixed(draw, (cmd_x, y + 10), f"/{feat} 开|关|状态",
                        GAME_TEXT, f_mono, f_desc)
        # 中间: 超管全局状态 (✓ 启用 / ✕ 禁用)
        _draw_super_indicator(draw, super_x, y + 12, super_st, f_desc)
        # 右边: 本群/本会话 toggle (开/关)
        _draw_status_dot(draw, dot_x, y + ROW_H // 2, toggle_st)
        y += ROW_H
    # 猜船开关行(由 EssexBot 维护,无超管全局禁用概念)
    if guess_enabled is not None:
        guess_st = "on" if guess_enabled else "off"
        draw.rectangle([PAD, y, W - PAD, y + ROW_H - 2], fill=GAME_PANEL_ALT)
        draw.text((name_x, y + 10), "猜船", GAME_TEXT, f_row)
        draw.text((desc_x, y + 12), "猜船小游戏 (默认关)", GAME_DIM, f_desc)
        _draw_mixed(draw, (cmd_x, y + 10), "/猜船 开|关|状态", GAME_TEXT, f_mono, f_desc)
        draw.text((super_x, y + 12), "—", GAME_DIM, f_desc)
        _draw_status_dot(draw, dot_x, y + ROW_H // 2, guess_st)
        y += ROW_H
    y += SECTION_GAP

    # ----- 使用方法 -----
    draw.text((PAD, y), "【使用方法】", GAME_TEXT, f_section); y += 30
    draw.text((PAD + 12, y), "把 .wowsreplay 拖进群里", GAME_TEXT, f_row); y += ROW_H
    draw.text((PAD + 12, y), "开着的输出会自动产生并发回", GAME_DIM, f_row); y += ROW_H
    y += SECTION_GAP

    # ----- 游戏 -----
    draw.text((PAD, y), "【游戏】", GAME_TEXT, f_section); y += 30
    draw.text((PAD + 12, y),  "指令",   GAME_DIM, f_desc)
    draw.text((PAD + 360, y), "作用",   GAME_DIM, f_desc)
    draw.text((PAD + 640, y), "谁可用", GAME_DIM, f_desc)
    y += 22
    for cmd, desc, perm in GAME_COMMANDS:
        _draw_mixed(draw, (PAD + 12, y), cmd, GAME_TEXT, f_mono, f_desc)
        draw.text((PAD + 360, y), desc, GAME_DIM, f_row)
        draw.text((PAD + 640, y), perm, GAME_DIM, f_row)
        y += 28
    y += SECTION_GAP

    # ----- 全部指令 -----
    draw.text((PAD, y), "【全部指令】", GAME_TEXT, f_section); y += 30
    # 表头
    draw.text((PAD + 12, y),  "指令",   GAME_DIM, f_desc)
    draw.text((PAD + 320, y), "作用",   GAME_DIM, f_desc)
    draw.text((PAD + 640, y), "谁可用", GAME_DIM, f_desc)
    y += 22
    cmds = [
        ("/菜单  /menu  /help", "打开本面板",      "任何人"),
        ("/<功能> 开|关",        "切换本群开关",    "群主/群管/超管"),
        ("/<功能> 状态",         "查看本群当前开关", "任何人"),
        ("/查询 <编号>",         "引用战报查玩家生涯水平", "任何人"),
        ("/船 <中文舰名>",        "查战舰数值卡 + 装甲分面",  "任何人"),
        ("/线 <国家> <舰种>",     "查整条科技树线路",       "任何人"),
    ]
    if sa_visible:
        cmds.append(("/sa ban|unban <功能>", "全局禁用/解禁", "仅超管"))
    for cmd, desc, perm in cmds:
        _draw_mixed(draw, (PAD + 12, y), cmd, GAME_TEXT, f_mono, f_desc)
        draw.text((PAD + 320, y), desc, GAME_DIM, f_row)
        draw.text((PAD + 640, y), perm, GAME_DIM, f_row)
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
    ap.add_argument("--guess", choices=["on", "off", "none"], default="none",
                    help="猜船开关显示:on/off 显示对应状态,none 不显示该行")
    args = ap.parse_args()

    if args.state_json:
        with open(args.state_json, "r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {"version": 1, "global_blacklist": [], "groups": {}, "private": {}}

    guess_enabled = {"on": True, "off": False, "none": None}[args.guess]
    render_menu_png(
        args.out, scope=args.scope, ident=args.ident,
        state_snapshot=state, is_super=args.is_super, version=args.version,
        guess_enabled=guess_enabled,
    )
    print(args.out)


if __name__ == "__main__":
    _cli()
