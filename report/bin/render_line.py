# report/bin/render_line.py
"""render_line.py — /线 科技树整线 PNG。

库用法 (bot 直接 import):
    from render_line import render_line_png
    render_line_png(out_path, tree)        # tree = tech_tree.build_tree(...)

CLI 用法 (调试):
    render_line.py <out.png> --nation 美国 --species 巡洋舰 [--ships report/data/ships.json]

布局:tier 当横轴(每 tier 一列,跨 tier 跳级留空列),分支当纵轴(每支一行,
主干续在同一行,分叉下沉新行)。复用 /查询 的调色板/字体/footer。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_query import (  # noqa: E402
    GAME_BG, GAME_PANEL, GAME_PANEL_ALT, GAME_TEXT, GAME_DIM, GAME_BORDER,
    GAME_GREEN, GAME_GOLD, CJK_FONT, MONO_FONT, FOOTER_H, _font, _draw_footer, _fmt_int,
)
from PIL import Image, ImageDraw  # noqa: E402

_ICON_DIR = Path(__file__).resolve().parent.parent / "data" / "ship_icons"

# 布局常量
PAD = 28
HEADER_H = 64
TIER_HDR_H = 28
ROW_HDR_W = 78    # 左侧行首:舰种类别(行号),跟顶部 tier(列号)对应
COL_W = 142
ROW_H = 120
ICON_W = 98
_ICON_HALF = 30   # 连线用的近似半高(竖向同 tier 连线)

_icon_cache = {}


def _load_icon(name, width):
    key = (name, width)
    if key in _icon_cache:
        return _icon_cache[key]
    im = None
    p = _ICON_DIR / f"{name}.png"
    if p.is_file():
        try:
            im = Image.open(p).convert("RGBA")
            r = width / im.width
            im = im.resize((width, max(1, int(im.height * r))), Image.LANCZOS)
        except Exception:
            im = None
    _icon_cache[key] = im
    return im


def _fmt_credit(n):
    """银币价 → 紧凑中文(万)。0/空返回空串。"""
    if not n:
        return ""
    if n >= 10000:
        w = n / 10000
        return f"{int(w)}万" if w == int(w) else f"{w:.1f}万"
    return str(n)


def render_line_png(out_path: str, tree: dict) -> str:
    """把 tech_tree.build_tree 的结果渲成 PNG。tree 为 None 时调用方自己兜底。"""
    nodes = tree["nodes"]
    edges = tree["edges"]
    min_t, max_t = tree["min_tier"], tree["max_tier"]
    n_rows = tree["n_rows"]
    n_cols = max_t - min_t + 1

    W = PAD * 2 + ROW_HDR_W + n_cols * COL_W
    H = HEADER_H + TIER_HDR_H + n_rows * ROW_H + FOOTER_H + 8

    img = Image.new("RGB", (W, H), GAME_BG)
    d = ImageDraw.Draw(img)
    f_title = _font(CJK_FONT, 28)
    f_name = _font(CJK_FONT, 16)
    f_xp = _font(CJK_FONT, 12)
    f_col = _font(MONO_FONT, 16)
    f_rowhdr = _font(CJK_FONT, 17)

    def col_x(t):
        return PAD + ROW_HDR_W + (t - min_t) * COL_W

    def cell_cx(t):
        return col_x(t) + ICON_W // 2

    def row_cy(r):
        return HEADER_H + TIER_HDR_H + r * ROW_H + ROW_H // 2

    # ---- header ----
    d.rectangle([0, 0, W, HEADER_H], fill=GAME_PANEL)
    d.text((PAD, 18), f"科技树 · {tree['nation_zh']} {tree['species_zh']}",
           font=f_title, fill=GAME_TEXT)

    # ---- tier 列头 + 淡列底 ----
    for i, t in enumerate(range(min_t, max_t + 1)):
        if i % 2 == 1:
            d.rectangle([col_x(t) - (COL_W - ICON_W) // 2, HEADER_H + TIER_HDR_H,
                         col_x(t) - (COL_W - ICON_W) // 2 + COL_W, H - FOOTER_H],
                        fill=GAME_PANEL_ALT)
        lbl = f"T{t}"
        d.text((cell_cx(t) - d.textlength(lbl, font=f_col) / 2, HEADER_H + 5),
               lbl, font=f_col, fill=GAME_DIM)

    # ---- 行首:每行舰种类别(行号);纯共享前段(异舰种)行用金色标出 ----
    main_sp = tree.get("species")
    row_kinds = {}   # row -> {kind: is_off}
    for n in nodes.values():
        row_kinds.setdefault(n["row"], {})
        row_kinds[n["row"]][n.get("kind", "")] = (n.get("species") != main_sp)
    hx = PAD + ROW_HDR_W // 2
    for r in range(n_rows):
        kinds = row_kinds.get(r)
        if not kinds:
            continue
        label = "/".join(k for k in kinds if k)
        color = GAME_GOLD if all(kinds.values()) else GAME_DIM   # 整行都是异舰种=前段
        ty = row_cy(r)
        d.text((hx - d.textlength(label, font=f_rowhdr) / 2, ty - 10), label,
               font=f_rowhdr, fill=color)

    # ---- 连线(节点下层);标注研发经验(绿) + 购买银币(银) ----
    for p, c in edges:
        pt, ct = nodes[p], nodes[c]
        xp = _fmt_int(ct["xp"]) if ct.get("xp") else ""
        cr = _fmt_credit(ct.get("credit"))
        if pt["tier"] == ct["tier"]:
            # 同 tier 同列:父底 → 子顶 竖向
            x = cell_cx(pt["tier"])
            y0, y1 = row_cy(pt["row"]) + _ICON_HALF, row_cy(ct["row"]) - _ICON_HALF
            d.line([(x, y0), (x, y1)], fill=GAME_BORDER, width=2)
            my = (y0 + y1) // 2
            if xp:
                d.text((x + 6, my - 14), xp, font=f_xp, fill=GAME_GREEN)
            if cr:
                d.text((x + 6, my + 1), cr, font=f_xp, fill=GAME_DIM)
        else:
            px, py = col_x(pt["tier"]) + ICON_W, row_cy(pt["row"])
            cx, cy = col_x(ct["tier"]), row_cy(ct["row"])
            midx = (px + cx) // 2
            d.line([(px, py), (midx, py), (midx, cy), (cx, cy)],
                   fill=GAME_BORDER, width=2, joint="curve")
            if xp:
                d.text((cx - d.textlength(xp, font=f_xp) - 4, cy - 30), xp, font=f_xp, fill=GAME_GREEN)
            if cr:
                d.text((cx - d.textlength(cr, font=f_xp) - 4, cy - 16), cr, font=f_xp, fill=GAME_DIM)

    # ---- 节点(图标 + 名字) ----
    for sid, n in nodes.items():
        t, r = n["tier"], n["row"]
        cx, cy = cell_cx(t), row_cy(r)
        ic = _load_icon(n["icon"], ICON_W)
        if ic:
            img.paste(ic, (col_x(t), cy - ic.height // 2 - 6), ic)
        else:
            d.rectangle([col_x(t), cy - 20, col_x(t) + ICON_W, cy + 14], outline=GAME_BORDER)
        name = n["name"]
        # 线尾(T11 超级船)名字描金
        color = GAME_GOLD if t >= 11 else GAME_TEXT
        d.text((cx - d.textlength(name, font=f_name) / 2, cy + 26), name, font=f_name, fill=color)

    _draw_footer(d, 0, H - FOOTER_H, W, FOOTER_H)
    img.save(out_path)
    return out_path


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--nation", required=True, help="国家中文,如 美国")
    ap.add_argument("--species", required=True, help="舰种中文,如 巡洋舰")
    ap.add_argument("--ships", default=str(Path(__file__).resolve().parent.parent / "data" / "ships.json"))
    args = ap.parse_args()

    # tech_tree 在 plugin/ 下
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "plugin"))
    import tech_tree

    ships = json.loads(Path(args.ships).read_text(encoding="utf-8"))["ships"]
    nc = tech_tree.resolve_nation(args.nation)
    sc = tech_tree.resolve_species(args.species)
    if not nc or not sc:
        sys.exit(f"无法识别 国家={args.nation} 舰种={args.species}")
    tree = tech_tree.build_tree(ships, nc, sc)
    if not tree:
        sys.exit(f"{args.nation} {args.species} 没有科技线")
    render_line_png(args.out, tree)
    print(args.out)


if __name__ == "__main__":
    _cli()
