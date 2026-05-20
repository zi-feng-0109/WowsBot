"""render_consumables_chart.py — 双方消耗品使用记录图。

用法:
    render_consumables_chart.py <battle.json> <out.png>

设计文档: docs/superpowers/specs/2026-05-20-consumables-chart-design.md
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_battle_report import (  # noqa: E402
    t, load_translations, strip_known, strip_id, clean_ship_name,
    CJK_FONT, MONO_FONT, GAME_BG, GAME_PANEL, GAME_PANEL_ALT, GAME_GREEN,
    GAME_RED, GAME_TEXT, GAME_DIM, GAME_BORDER,
)
from render_criminals import consumable_display  # noqa: E402
from PIL import Image, ImageDraw, ImageFont


SPECIES_ORDER = ["Destroyer", "Cruiser", "Battleship", "AirCarrier", "Submarine"]
SPECIES_CN = {
    "Destroyer": "驱逐",
    "Cruiser": "巡洋",
    "Battleship": "战列",
    "AirCarrier": "航母",
    "Submarine": "潜艇",
}

ABILITY_KEYWORD_TO_ENUM = [
    ("RLSSearch",             "Radar"),
    ("SonarSearch",           "HydroacousticSearch"),
    ("Hydrophone",            "Hydrophone"),
    ("PlaneTacticalFighters", "CatapultFighter"),
    ("Fighter",               "CatapultFighter"),
    ("ForsageBooster",        "SpeedBoost"),
    ("ActiveManeuvering",     "EnhancedRudders"),
    ("PlaneSmokeGenerator",   "PlaneSmokeGenerator"),
    ("Spotter",               "SpottingAircraft"),
    ("AirDefenseDisp",        "DefensiveAntiAircraft"),
    ("SmokeGenerator",        "Smoke"),
    ("SubmarineLocator",      "SubmarineSurveillance"),
    ("CrashCrew",             "DamageControl"),
    ("RegenCrew",             "RepairParty"),
    ("RepairParty",           "RepairParty"),
    ("ArtilleryBooster",      "MainBatteryReloadBooster"),
    ("TorpedoReloader",       "TorpedoReloadBooster"),
    ("SpeedBoosterPremium",   "SpeedBoost"),
    ("SpeedBooster",          "SpeedBoost"),
    ("ReserveBattery",        "ReserveBattery"),
    ("SubmarineSurveillance", "SubmarineSurveillance"),
    ("FastDeepRudders",       "FastDeepRudders"),
    ("SubmarineEnergyFreeze", "SubmarineEnergyFreeze"),
]


W = 2200
PAD = 16
TITLE_H = 60
TEAM_HEADER_H = 36
ROW_H = 56
CELL_W = 150
CELL_H = 48
CELL_GAP = 6
LEFT_COL_W = 360


CELL_INFINITE = GAME_PANEL_ALT
CELL_ZERO     = (139, 40, 40)
CELL_LOW      = (168, 129, 40)
CELL_MID      = (58, 110, 58)
CELL_FULL     = (31, 93, 31)
CELL_UNKNOWN  = (60, 60, 80)


def cell_bg_color(used, total):
    if total is None:
        return CELL_UNKNOWN
    if total == -1:
        return CELL_INFINITE
    if total <= 0:
        return CELL_UNKNOWN
    if used == 0:
        return CELL_ZERO
    ratio = used / total
    if ratio < 0.5:
        return CELL_LOW
    if ratio < 1.0:
        return CELL_MID
    return CELL_FULL


def fmt_total(total):
    if total == -1:
        return "∞"
    if total is None:
        return "?"
    return str(total)


def species_sort_key(p):
    sp = strip_known((p.get("ship") or {}).get("species") or "")
    try:
        idx = SPECIES_ORDER.index(sp)
    except ValueError:
        idx = len(SPECIES_ORDER)
    return (idx, (p.get("name") or "").lower())


def ability_name_of(slot_entry):
    if isinstance(slot_entry, dict):
        return slot_entry.get("ability_name", "")
    return slot_entry or ""


def num_consumables_of(slot_entry):
    if isinstance(slot_entry, dict):
        return slot_entry.get("num_consumables")
    return None


def collect_slot_info(slot):
    if not slot:
        return ("", None, [])
    names = [ability_name_of(e) for e in slot if ability_name_of(e)]
    displays = []
    for n in names:
        d = consumable_display(n)
        if d not in displays:
            displays.append(d)
    total = num_consumables_of(slot[0])
    return ("/".join(displays), total, names)


def count_uses_for_ability(consumable_uses, user_eid, ability_name):
    target_enum = None
    for keyword, enum_name in ABILITY_KEYWORD_TO_ENUM:
        if keyword in ability_name:
            target_enum = enum_name
            break
    if target_enum is None:
        return 0
    return sum(
        1 for u in consumable_uses
        if strip_id(u.get("user_entity_id") or "") == user_eid
        and u.get("consumable_name") == target_enum
    )


def font_at(path, size):
    return ImageFont.truetype(path, size)


def _ship_label(p):
    sp = (p.get("ship") or {})
    idx = sp.get("index", "")
    raw_name = clean_ship_name(sp.get("name", ""))
    zh = t(f"IDS_{idx}", raw_name) if idx else raw_name
    species = strip_known(sp.get("species", "")) or "?"
    species_cn = SPECIES_CN.get(species, species)
    return f"{zh}  L{sp.get('level', '?')} {species_cn}"


def _draw_ship_row(draw, p, y, consumable_uses, fonts):
    f_ship, f_player, f_slot_name, f_slot_num = fonts
    draw.rectangle([PAD, y, W - PAD, y + ROW_H - 2], fill=GAME_PANEL)

    ship_txt = _ship_label(p)
    player_txt = p.get("name", "?")
    draw.text((PAD + 12, y + 6), ship_txt, GAME_TEXT, f_ship)
    draw.text((PAD + 12, y + 30), player_txt, GAME_DIM, f_player)

    cell_x = PAD + LEFT_COL_W
    ship = p.get("ship") or {}
    eid = strip_id(p.get("vehicle_entity_id") or "")
    for slot in ship.get("consumable_slots") or []:
        disp, total, names = collect_slot_info(slot)
        if not names:
            continue
        used = max(count_uses_for_ability(consumable_uses, eid, n) for n in names)
        bg = cell_bg_color(used, total)
        cy = y + (ROW_H - CELL_H) // 2
        draw.rounded_rectangle(
            [cell_x, cy, cell_x + CELL_W, cy + CELL_H],
            radius=6, fill=bg, outline=GAME_BORDER, width=1,
        )
        name_text = disp
        if len(name_text) > 9:
            name_text = name_text[:8] + "…"
        draw.text((cell_x + 8, cy + 4), name_text, GAME_TEXT, f_slot_name)
        ut = f"{used}/{fmt_total(total)}"
        bbox = f_slot_num.getbbox(ut)
        ut_w = bbox[2] - bbox[0]
        draw.text((cell_x + (CELL_W - ut_w) // 2, cy + 24), ut, GAME_TEXT, f_slot_num)
        cell_x += CELL_W + CELL_GAP


def render(json_path, out_path):
    load_translations()
    raw = json.load(open(json_path, encoding="utf-8"))
    consumable_uses = raw.get("consumable_uses") or []

    self_team = None
    for p in raw.get("players", []):
        if p.get("relation") in (0, 1):
            self_team = p.get("team_id")
            break
    if self_team is None:
        self_team = 0

    teams = {0: [], 1: []}
    for p in raw.get("players", []):
        tid = p.get("team_id")
        if tid in teams:
            teams[tid].append(p)
    for tid in teams:
        teams[tid].sort(key=species_sort_key)

    enemy_team = 1 - self_team
    team_order = [(enemy_team, "敌方", GAME_RED), (self_team, "友方", GAME_GREEN)]

    total_h = TITLE_H + PAD
    for tid, _, _ in team_order:
        total_h += TEAM_HEADER_H + len(teams[tid]) * ROW_H + PAD

    img = Image.new("RGB", (W, total_h), GAME_BG)
    draw = ImageDraw.Draw(img)

    f_title = font_at(CJK_FONT, 28)
    f_team = font_at(CJK_FONT, 22)
    f_ship = font_at(CJK_FONT, 18)
    f_player = font_at(CJK_FONT, 15)
    f_slot_name = font_at(CJK_FONT, 14)
    f_slot_num = font_at(MONO_FONT, 16)

    draw.rectangle([0, 0, W, TITLE_H], fill=(14, 19, 30))
    draw.text((24, 14), "消耗品使用记录", GAME_TEXT, f_title)
    draw.text((24 + 240, 22), "12v12 全员 · used/total · 色块=使用率",
              GAME_DIM, f_ship)

    y = TITLE_H + PAD
    fonts = (f_ship, f_player, f_slot_name, f_slot_num)
    for tid, label, color in team_order:
        draw.rectangle([PAD, y, W - PAD, y + TEAM_HEADER_H], fill=GAME_PANEL_ALT)
        draw.line([PAD, y + TEAM_HEADER_H, W - PAD, y + TEAM_HEADER_H],
                  fill=color, width=2)
        draw.text((PAD + 12, y + 6), f"{label}  ({len(teams[tid])} 船)", color, f_team)
        y += TEAM_HEADER_H

        for p in teams[tid]:
            _draw_ship_row(draw, p, y, consumable_uses, fonts)
            y += ROW_H
        y += PAD

    img.save(out_path)
    print(f"saved: {out_path}", file=sys.stderr)
    print(out_path)


def main():
    if len(sys.argv) < 3:
        print("usage: render_consumables_chart.py <battle.json> <out.png>",
              file=sys.stderr)
        sys.exit(2)
    render(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
