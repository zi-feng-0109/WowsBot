#!/usr/bin/env python3
"""复盘 (damage review) image from the `battle-results --format normalized` JSON,
in the EssexBot style — imitates render_damage_chart.py but reads the new schema.

Renders the self player's **output-damage donut** (packet-derived, by weapon kind)
and the **ribbons** row. The received-damage donut is server-only data that Lesta
replays don't carry, so its panel shows an "unavailable" note rather than fake
numbers. Reuses render_damage_chart's draw helpers + palette for identical style.

Usage:
    python render_review_normalized.py <normalized.json> <out.png>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_battle_report as rb  # noqa: E402
import render_damage_chart as dc  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

W = 2200
PAD = 24
GAME_BG = rb.GAME_BG
GAME_PANEL = rb.GAME_PANEL
GAME_TEXT = rb.GAME_TEXT
GAME_DIM = rb.GAME_DIM
GAME_GOLD = rb.GAME_GOLD
GAME_BORDER = rb.GAME_BORDER

# Rust DamageStatWeapon kind -> (donut label, palette key).
_KIND = {
    "MainAp": ("主炮 AP", "ap"), "MainAiAp": ("主炮 AP", "ap"),
    "MainHe": ("主炮 HE", "he"), "MainAiHe": ("主炮 HE", "he"),
    "MainCs": ("主炮 CS", "cs"),
    "AtbaAp": ("副炮", "atba"), "AtbaHe": ("副炮", "atba"), "AtbaCs": ("副炮", "atba"),
    "Torpedo": ("鱼雷", "tpd"), "TorpedoAcc": ("鱼雷", "tpd"), "TorpedoMag": ("鱼雷", "tpd"),
    "Burn": ("火灾", "fire"), "Flood": ("进水", "flood"),
    "TBomber": ("鱼雷机", "tbomb"),
    "BomberHe": ("炸弹", "bomb"), "BomberAp": ("炸弹", "bomb"),
    "SkipHe": ("跳炸", "skip"), "SkipAp": ("跳炸", "skip"),
    "RocketHe": ("火箭机", "rocket"), "RocketAp": ("火箭机", "rocket"),
    "DepthCharge": ("深弹", "dbomb"), "AerialDepthCharge": ("空袭深弹", "adbomb"),
    "SeaMine": ("水雷", "sea_mine"), "Ram": ("撞击", "ram"), "Terrain": ("撞礁", "event"),
    "Missile": ("导弹", "missile"),
}


def _output_slices(self_damage_by_type):
    """[(label, color, value)] aggregated + sorted desc."""
    agg = {}
    for kind, val in self_damage_by_type or []:
        label, pkey = _KIND.get(kind, ("其他", "event"))
        color = dc._PALETTE.get(pkey, GAME_DIM)
        cur = agg.get(label)
        agg[label] = (color, (cur[1] if cur else 0) + int(val))
    slices = [(label, color, value) for label, (color, value) in agg.items() if value > 0]
    slices.sort(key=lambda s: -s[2])
    return slices


def _ribbon_basename(r):
    key = r.get("icon_key", "")
    return f"sub{key}" if r.get("is_subribbon") else key


def render(json_path: str, out_path: str):
    rb.load_translations()
    raw = json.load(open(json_path, encoding="utf-8"))
    selfp = next((p for p in raw["players"] if p.get("is_self")), None)
    if selfp is None:
        raise RuntimeError("normalized JSON has no self player")

    slices = _output_slices(selfp.get("self_damage_by_type"))
    total = sum(v for _, _, v in slices)
    ribbons = selfp.get("ribbons") or []

    f = lambda s: rb.font(rb.CJK_FONT, s)
    fm = lambda s: rb.font(rb.MONO_FONT, s)
    f_h1, f_h2, f_h3, f_lab, f_num, f_small = f(30), f(22), f(17), f(18), fm(18), f(14)

    # Layout heights.
    pie_block_h = 460
    ribbon_rows = (len(ribbons) + 7) // 8
    ribbon_h = 60 + max(ribbon_rows, 1) * 120
    H = PAD + 50 + pie_block_h + 20 + ribbon_h + 40

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)

    draw.text((PAD, PAD), f"复盘 — {selfp.get('name','')} ({selfp.get('ship_name','')})", GAME_TEXT, f_h1)

    # ── output-damage donut (left) ────────────────────────────────────────────
    y0 = PAD + 56
    half = (W - 3 * PAD) // 2
    draw.rectangle([PAD, y0, PAD + half, y0 + pie_block_h], fill=GAME_PANEL, outline=GAME_BORDER)
    draw.text((PAD + 20, y0 + 14), "输出伤害分布", GAME_TEXT, f_h2)
    draw.text((PAD + 20, y0 + 50), f"总击伤 {total:,}".replace(",", " "), GAME_DIM, f_h3)
    cx, cy, r = PAD + 200, y0 + 260, 150
    dc.draw_pie(img, draw, (cx, cy), r, slices)
    draw.text((cx - r + 10, cy - 20), f"{total:,}".replace(",", " "), GAME_GOLD, f_h2)
    dc.draw_legend(draw, PAD + 420, y0 + 90, half - 440, slices, total, f_lab, f_num)

    # ── received-damage panel (right): unavailable for Lesta ──────────────────
    rx = PAD + half + PAD
    draw.rectangle([rx, y0, rx + half, y0 + pie_block_h], fill=GAME_PANEL, outline=GAME_BORDER)
    draw.text((rx + 20, y0 + 14), "受伤来源分布", GAME_TEXT, f_h2)
    note = "Lesta 回放不含服务端承伤明细,无法拆分来源。"
    draw.text((rx + 20, y0 + pie_block_h // 2 - 10), note, GAME_DIM, f_h3)

    # ── ribbons row ───────────────────────────────────────────────────────────
    ry = y0 + pie_block_h + 20
    draw.rectangle([PAD, ry, W - PAD, ry + ribbon_h], fill=GAME_PANEL, outline=GAME_BORDER)
    draw.text((PAD + 20, ry + 14), "勋带", GAME_TEXT, f_h2)
    if not ribbons:
        draw.text((PAD + 20, ry + 56), "本场无勋带数据", GAME_DIM, f_h3)
    else:
        banner_w = 150
        col_w = (W - 2 * PAD - 40) // 8
        for i, rb_item in enumerate(ribbons):
            col = i % 8
            row = i // 8
            bx = PAD + 30 + col * col_w
            by = ry + 60 + row * 120
            icon = dc.load_ribbon_icon(_ribbon_basename(rb_item), banner_w)
            if icon is not None:
                img.paste(icon, (bx, by), icon)
                cnt_x, cnt_y = bx + banner_w - 6, by
            else:
                cnt_x, cnt_y = bx, by
            draw.text((cnt_x, cnt_y), f"x{rb_item.get('count', 0)}", GAME_GOLD, f_num)
            draw.text((bx, by + 62), rb_item.get("display_name", "")[:8], GAME_TEXT, f_small)

    dc._draw_footer(draw, PAD, H - 34, W - 2 * PAD, 28)
    img.save(out_path)
    print(out_path)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: render_review_normalized.py <normalized.json> <out.png>", file=sys.stderr)
        sys.exit(2)
    render(sys.argv[1], sys.argv[2])
