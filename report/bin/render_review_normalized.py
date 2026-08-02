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


def _ribbon_display(r, is_lesta):
    """(label, icon basename).

    Lesta ships a full per-ribbon "detailed" set (`subribbon_*`, its post-battle
    art) covering every ribbon type. For a Lesta report use that set for EVERY
    ribbon so the source is uniform (all Lesta post-battle art), keying by the
    ribbon name (`RIBBON_FRAG` → `subribbon_frag`). For WG, keep the legacy
    behaviour: collapse via RIBBON_DISPLAY onto the flat parent banner.
    """
    raw = r.get("name", "")
    if raw.startswith("RIBBON_"):
        raw = raw[len("RIBBON_"):]
    label = r.get("display_name") or (dc.RIBBON_DISPLAY.get(raw, (raw,))[0])
    if is_lesta:
        return label, "subribbon_" + raw.lower()
    entry = dc.RIBBON_DISPLAY.get(raw)
    if entry:
        return label, entry[1]
    key = r.get("icon_key", "")
    return label, (f"sub{key}" if r.get("is_subribbon") else key)


def _is_lesta(raw_json):
    return ((raw_json.get("metadata") or {}).get("version") or {}).get("major", 0) >= 16


def _ribbon_dirs(is_lesta):
    """Icon dirs to try, in order. Lesta reports prefer Lesta's own post-battle
    ribbon set; WG's shared set is the fallback."""
    dirs = [dc.RIBBON_ICON_DIR]
    if is_lesta:
        lesta = Path(__file__).resolve().parent.parent / "data" / "ribbon_icons_lesta"
        if lesta.is_dir():
            dirs.insert(0, str(lesta))
    return dirs


def _center_num(draw, value, cx, cy, font):
    """Draw the donut total centered in the hole at (cx, cy)."""
    s = f"{int(value):,}".replace(",", " ")
    b = font.getbbox(s)
    w, h = b[2] - b[0], b[3] - b[1]
    draw.text((cx - w // 2, cy - h // 2 - b[1]), s, GAME_GOLD, font)


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

    # Layout heights (ribbon grid mirrors the legacy render_damage_chart).
    RIBBON_BANNER_W, RIBBON_PER_ROW, RIBBON_ROW_H, RIBBON_TITLE_BAND = 180, 8, 110, 50
    pie_block_h = 460
    ribbon_rows = max(1, (len(ribbons) + RIBBON_PER_ROW - 1) // RIBBON_PER_ROW)
    ribbon_h = RIBBON_TITLE_BAND + ribbon_rows * RIBBON_ROW_H + 16
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
    _center_num(draw, total, cx, cy, fm(28))
    dc.draw_legend(draw, PAD + 420, y0 + 90, half - 440, slices, total, f_lab, f_num)

    # ── received-damage panel (right): by SOURCE ship (packet-derived) ────────
    # Lesta carries no server damage-TYPE breakdown, but DamageReceived gives who
    # dealt the damage, so we show 受伤来源 by attacker ship instead.
    rx = PAD + half + PAD
    draw.rectangle([rx, y0, rx + half, y0 + pie_block_h], fill=GAME_PANEL, outline=GAME_BORDER)
    draw.text((rx + 20, y0 + 14), "受伤来源分布", GAME_TEXT, f_h2)
    _SRC_COLORS = [
        (74, 144, 226), (226, 86, 86), (240, 180, 90), (120, 200, 130), (180, 120, 220),
        (90, 200, 210), (230, 130, 180), (200, 180, 100), (150, 160, 180), (200, 120, 90),
    ]
    recv = selfp.get("self_received_by_source") or []
    recv_slices = [(lbl, _SRC_COLORS[i % len(_SRC_COLORS)], int(val)) for i, (lbl, val) in enumerate(recv)]
    recv_total = sum(v for _, _, v in recv_slices)
    if recv_slices:
        draw.text((rx + 20, y0 + 50), f"累计承伤 {recv_total:,}".replace(",", " ") + "  (按来源舰船)", GAME_DIM, f_h3)
        rcx, rcy, rr = rx + 200, y0 + 260, 150
        dc.draw_pie(img, draw, (rcx, rcy), rr, recv_slices)
        _center_num(draw, recv_total, rcx, rcy, fm(28))
        dc.draw_legend(draw, rx + 420, y0 + 90, half - 440, recv_slices, recv_total, f_lab, f_num)
    else:
        draw.text((rx + 20, y0 + pie_block_h // 2 - 10), "本场无承伤记录。", GAME_DIM, f_h3)

    # ── ribbons row ───────────────────────────────────────────────────────────
    ry = y0 + pie_block_h + 20
    draw.rectangle([PAD, ry, W - PAD, ry + ribbon_h], fill=GAME_PANEL, outline=GAME_BORDER)
    draw.text((PAD + 20, ry + 14), "勋带", GAME_TEXT, f_h2)
    if not ribbons:
        draw.text((PAD + 20, ry + 56), "本场无勋带数据", GAME_DIM, f_h3)
    else:
        # 8-per-row grid. Scale each icon to a fixed HEIGHT (not width): WG/Lesta
        # main ribbons are wide flat banners (~2.6:1) while Lesta subribbons are
        # near-square angled icons — a fixed width would blow the square ones up
        # and break the grid. Count goes to the right of the icon, label below.
        from PIL import Image as _Image
        icon_h = 64
        inner_w = W - 2 * PAD - 32
        item_w = inner_w // RIBBON_PER_ROW
        row_y0 = ry + RIBBON_TITLE_BAND
        f_cnt = fm(20)
        f_lbl = f(16)

        is_lesta = _is_lesta(raw)
        ribbon_dirs = _ribbon_dirs(is_lesta)

        def _ribbon_img(basename):
            for d in ribbon_dirs:
                p = Path(d) / f"{basename}.png"
                if not p.is_file():
                    continue
                try:
                    src = _Image.open(p).convert("RGBA")
                    w, h = src.size
                    tw = max(1, round(icon_h * w / h))
                    return src.resize((min(tw, RIBBON_BANNER_W), icon_h), _Image.LANCZOS)
                except Exception:
                    continue
            return None

        for i, r in enumerate(ribbons):
            row, col = divmod(i, RIBBON_PER_ROW)
            ax = PAD + 16 + col * item_w
            ay = row_y0 + row * RIBBON_ROW_H + 6
            label, basename = _ribbon_display(r, is_lesta)
            icon = _ribbon_img(basename)
            if icon:
                img.paste(icon, (ax, ay), icon)
                bw = icon.width
            else:
                bw = int(icon_h * 133 / 51)
            cnt = f"x{r.get('count', 0)}"
            draw.text((ax + bw + 8, ay + icon_h // 2 - 12), cnt, GAME_GOLD, f_cnt)
            draw.text((ax, ay + icon_h + 6), label[:8], GAME_TEXT, f_lbl)

    dc._draw_footer(draw, PAD, H - 34, W - 2 * PAD, 28)
    img.save(out_path)
    print(out_path)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: render_review_normalized.py <normalized.json> <out.png>", file=sys.stderr)
        sys.exit(2)
    render(sys.argv[1], sys.argv[2])
