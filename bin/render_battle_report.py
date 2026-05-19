"""Render a dark game-style battle report PNG from replayshark JSON output.

Usage:
    python render_battle_report.py <battle_report.json> <out.png>
"""
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# --- locate bot home (parent of this script's dir) --------------------------
import os as _os
_BOT_HOME = Path(__file__).resolve().parent.parent
_DATA = _BOT_HOME / "data"

# Fonts: per-OS lookup with env-var override (CJK + monospace required).
# On Linux, install fonts-noto-cjk + fonts-dejavu (or set WOWS_CJK_FONT).
_CJK_CANDIDATES = [
    _os.environ.get("WOWS_CJK_FONT"),
    "/System/Library/Fonts/Hiragino Sans GB.ttc",                  # macOS
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",      # Debian/Ubuntu (Noto)
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",    # Fedora
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",                # WenQuanYi fallback
]
_MONO_CANDIDATES = [
    _os.environ.get("WOWS_MONO_FONT"),
    "/System/Library/Fonts/Menlo.ttc",                             # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",         # Debian/Ubuntu
    "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",  # Fedora
]


def _first_existing(paths):
    for p in paths:
        if p and _os.path.exists(p):
            return p
    return None


CJK_FONT = _first_existing(_CJK_CANDIDATES)
MONO_FONT = _first_existing(_MONO_CANDIDATES) or CJK_FONT
if not CJK_FONT:
    raise RuntimeError(
        "No CJK font found. Install fonts-noto-cjk on Linux, "
        "or set WOWS_CJK_FONT env var to a .ttc/.ttf path."
    )

# Data files (overridable via env vars; defaults inside the deploy bundle)
TRANSLATIONS_MO      = _os.environ.get("WOWS_TRANSLATIONS_MO",   str(_DATA / "zh_sg.mo"))
CONSTANTS_JSON       = _os.environ.get("WOWS_CONSTANTS_JSON",    str(_DATA / "constants.json"))
ACHIEVEMENTS_JSON    = _os.environ.get("WOWS_ACHIEVEMENTS_JSON", str(_DATA / "achievements.json"))
ACHIEVEMENT_ICON_DIR = _os.environ.get("WOWS_ACHIEVEMENT_ICONS", str(_DATA / "achievement_icons"))

_RESULT_INDICES: dict[str, int] = {}
_ACH_ID_TO_INDEX: dict[int, str] = {}
_ACH_ICON_CACHE: dict[str, Image.Image] = {}


def achievement_icon(index_name: str, size: int = 26) -> Optional[Image.Image]:
    """Load (and cache) achievement icon by its index name (e.g. 'FIRST_BLOOD')."""
    key = f"{index_name}@{size}"
    if key in _ACH_ICON_CACHE:
        return _ACH_ICON_CACHE[key]
    path = f"{ACHIEVEMENT_ICON_DIR}/icon_achievement_{index_name}.png"
    try:
        img = Image.open(path).convert("RGBA")
        img.thumbnail((size, size))
        _ACH_ICON_CACHE[key] = img
        return img
    except Exception:
        # Fallback to default
        try:
            img = Image.open(f"{ACHIEVEMENT_ICON_DIR}/default.png").convert("RGBA")
            img.thumbnail((size, size))
            _ACH_ICON_CACHE[key] = img
            return img
        except Exception:
            return None


def load_achievements(path: str = ACHIEVEMENTS_JSON):
    global _ACH_ID_TO_INDEX
    if _ACH_ID_TO_INDEX:
        return
    try:
        raw = json.load(open(path))
        _ACH_ID_TO_INDEX = {int(k): v for k, v in raw.items()}
    except Exception as e:
        print(f"warn: failed to load achievements: {e}", file=sys.stderr)


def achievement_name(ach_id: int) -> str:
    """ID -> Chinese name (via achievements.json -> gettext catalog)."""
    load_achievements()
    idx = _ACH_ID_TO_INDEX.get(int(ach_id))
    if idx is None:
        return f"#{ach_id}"
    return t(f"IDS_ACHIEVEMENT_{idx}", idx)


def load_result_indices(path: str = CONSTANTS_JSON):
    global _RESULT_INDICES
    if _RESULT_INDICES:
        return
    try:
        c = json.load(open(path))
        _RESULT_INDICES = {k: int(v) for k, v in c.get("CLIENT_PUBLIC_RESULTS_INDICES", {}).items()}
    except Exception as e:
        print(f"warn: failed to load constants: {e}", file=sys.stderr)


def result_field(arr, name: str, default=None):
    """Look up a named field from a raw results_info array."""
    load_result_indices()
    idx = _RESULT_INDICES.get(name)
    if idx is None or arr is None or not isinstance(arr, list) or idx >= len(arr):
        return default
    return arr[idx]

_TRANSLATIONS: dict[str, str] = {}


def load_translations(mo_path: str = TRANSLATIONS_MO):
    """Load WoWs gettext catalog into a dict, on demand."""
    global _TRANSLATIONS
    if _TRANSLATIONS:
        return
    try:
        import polib
        mo = polib.mofile(mo_path)
        _TRANSLATIONS = {e.msgid: e.msgstr for e in mo if e.msgstr}
    except Exception as e:
        print(f"warn: failed to load translations from {mo_path}: {e}", file=sys.stderr)


def t(key: str, default: Optional[str] = None) -> str:
    """Translate an IDS_* key. Returns default (or key itself) if not found."""
    load_translations()
    return _TRANSLATIONS.get(key, default if default is not None else key)


# Hardcoded fallback for things not keyed as IDS_*
MATCH_GROUP_CN = {
    "pvp": "随机战",
    "ranked": "排位赛",
    "cooperative": "合作战斗",
    "training": "训练房",
    "clan": "战队战",
    "brawl": "乱斗",
    "scenario": "战役",
}


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


# ---------- data normalization ----------

ID_RE = re.compile(r"(?:AccountId|EntityId|GameParamId)\((\d+)\)")
KNOWN_RE = re.compile(r"Known\(([A-Za-z]+)\)")
RELATION_RE = re.compile(r"Relation\((\d+)\)")

SPECIES_SHORT = {
    "Battleship": "BB",
    "Cruiser": "CL",
    "Destroyer": "DD",
    "AirCarrier": "CV",
    "Submarine": "SS",
    "Auxiliary": "AUX",
}

DEATH_CAUSE_CN = {
    "ApShell": "AP",
    "HeShell": "HE",
    "CsShell": "CS",
    "Torpedo": "鱼雷",
    "AerialTorpedo": "机雷",
    "AerialRocket": "火箭",
    "AerialBomb": "炸弹",
    "DiveBomber": "俯冲",
    "SkipBomber": "跳炸",
    "AerialDepthCharge": "深弹",
    "DepthCharge": "深弹",
    "Fire": "燃烧",
    "Flooding": "进水",
    "Ram": "撞击",
    "Terrain": "撞礁",
    "Detonate": "弹药库",
    "SecondaryCaliber": "副炮",
    "AntiAir": "副炮",
    "SeaMine": "水雷",
    "Health": "血量",
}


def strip_id(s: str) -> int:
    m = ID_RE.match(s or "")
    return int(m.group(1)) if m else 0


def strip_known(s: str) -> str:
    if not s:
        return ""
    m = KNOWN_RE.match(s)
    return m.group(1) if m else s


def relation_name(s: str) -> str:
    # 0 = Self, 1 = Friendly, 2 = Enemy (BigWorld convention)
    m = RELATION_RE.match(s or "")
    n = int(m.group(1)) if m else -1
    return {0: "self", 1: "friendly", 2: "enemy"}.get(n, "?")


def clean_ship_name(raw: str) -> str:
    """PASS208_Salmon -> Salmon, PASC108_Baltimore_1944 -> Baltimore."""
    if not raw:
        return "?"
    # Drop prefix segment (e.g. PASS208, PASC108)
    parts = raw.split("_")
    if len(parts) >= 2:
        parts = parts[1:]
    # Drop trailing year-like segments (4-digit numbers)
    while parts and parts[-1].isdigit() and len(parts[-1]) == 4:
        parts.pop()
    return "_".join(parts) or raw


# ---------- data extraction ----------

@dataclass
class PlayerStats:
    account_id: int
    entity_id: int
    name: str
    clan: str
    team_id: int
    relation: str  # "self" | "friendly" | "enemy"
    ship_name: str
    ship_index: str  # e.g. "PASS208" — used to look up zh name
    ship_level: int
    ship_species: str
    max_hp: float
    final_hp: float
    is_alive: bool
    damage_dealt: float
    frags: int
    time_lived_secs: Optional[float]
    killer_entity_id: Optional[int]
    death_cause: Optional[str]
    raw_exp: Optional[int] = None  # 裸经验
    exp: Optional[int] = None       # 含 buff 经验
    scouting_damage: Optional[int] = None
    potential_damage: Optional[int] = None  # agro_art + agro_air + agro_tpd + agro_dbomb
    planes_killed: Optional[int] = None     # planes_killed_by_ship + planes_killed_by_plane
    achievements: list[tuple[int, int]] = None  # list of (achievement_id, count)


@dataclass
class MatchReport:
    map_name: str
    mode: str
    date: str
    duration_played: int
    duration_max: int
    win_team: int
    win_type: str  # "Win" | "Loss" | "Draw"
    self_team: int
    final_score: dict
    self_player_name: str
    players: list[PlayerStats]
    deaths: list  # (time, victim_entity_id, killer_account_id, killer_name, cause_str)


def load(json_path: str) -> MatchReport:
    raw = json.load(open(json_path))
    m = raw["match"]

    players = []
    for p in raw["players"]:
        stats = p["stats"]
        players.append(PlayerStats(
            account_id=strip_id(p["account_id"]),
            entity_id=strip_id(p.get("vehicle_entity_id") or p.get("entity_id") or ""),
            name=p["name"],
            clan=p.get("clan", ""),
            team_id=p.get("team_id", -1),
            relation=relation_name(p["relation"]),
            ship_name=clean_ship_name(p["ship"]["name"]),
            ship_index=p["ship"].get("index", ""),
            ship_level=p["ship"]["level"],
            ship_species=strip_known(p["ship"]["species"]),
            max_hp=float(stats["max_health"]),
            final_hp=float(stats["final_health"]),
            is_alive=bool(stats["is_alive"]),
            # Server-authoritative damage (index 426) when available — covers
            # damage dealt outside owner's fog-of-war. Falls back to the
            # BattleController-rebuilt value (owner-visible events only).
            damage_dealt=float(
                result_field(p.get("results_info"), "damage")
                if result_field(p.get("results_info"), "damage") is not None
                else stats["damage_dealt"]
            ),
            frags=int(stats["frags"]),
            time_lived_secs=stats["time_lived_secs"],
            killer_entity_id=strip_id(stats["killer_entity_id"]) if stats["killer_entity_id"] else None,
            death_cause=strip_known(stats["death_cause"]) if stats["death_cause"] else None,
            raw_exp=result_field(p.get("results_info"), "raw_exp"),
            exp=result_field(p.get("results_info"), "exp"),
            scouting_damage=result_field(p.get("results_info"), "scouting_damage"),
            potential_damage=sum(
                result_field(p.get("results_info"), k, 0) or 0
                for k in ("agro_art", "agro_air", "agro_tpd", "agro_dbomb")
            ) or None,
            planes_killed=(
                (result_field(p.get("results_info"), "planes_killed_by_ship", 0) or 0)
                + (result_field(p.get("results_info"), "planes_killed_by_plane", 0) or 0)
            ) or None,
            achievements=[
                (int(aid), int(cnt))
                for aid, cnt in (result_field(p.get("results_info"), "achievements") or [])
            ],
        ))

    deaths = []
    for d in raw["deaths"]:
        deaths.append((
            float(d["time_secs"]),
            strip_id(d["victim_entity_id"]),
            strip_id(d.get("killer_entity_id") or ""),
            d.get("victim_name", ""),
            strip_known(d["cause"]),
        ))
    deaths.sort(key=lambda x: x[0])

    # determine self team and win/loss
    self_player = next((p for p in players if p.name == m["self_player_name"]), None)
    self_team = self_player.team_id if self_player else 0
    br = m.get("battle_result") or {}
    win_type = br.get("type", "Draw")
    win_team = br.get("team_id", -1)

    scores = {ts["team_index"]: ts["score"] for ts in m["team_scores"]}

    # map name pretty
    map_name = m["map_name"].split("/")[-1]

    # duration: use played if available, else max
    dur_played = m.get("duration_seconds_played")
    duration_played = int(dur_played) if dur_played else m.get("duration_seconds_max", 0)

    return MatchReport(
        map_name=map_name,
        mode=f"{m.get('match_group','?')}·{m.get('game_mode','?')}",
        date=m.get("date_time", "?"),
        duration_played=duration_played,
        duration_max=m.get("duration_seconds_max", 0),
        win_team=win_team,
        win_type=win_type,
        self_team=self_team,
        final_score=scores,
        self_player_name=m.get("self_player_name", "?"),
        players=players,
        deaths=deaths,
    )


# ---------- rendering ----------

GAME_BG = (18, 24, 38)
GAME_PANEL = (32, 42, 64)
GAME_PANEL_ALT = (28, 36, 56)
GAME_GREEN = (74, 200, 132)
GAME_RED = (235, 86, 75)
GAME_GOLD = (242, 196, 87)
GAME_PURPLE = (188, 122, 232)  # tier color above gold (顶级)
GAME_TEXT = (228, 233, 245)
GAME_DIM = (140, 155, 180)
GAME_BORDER = (60, 75, 100)


def fmt_time(secs: int) -> str:
    secs = int(secs)
    return f"{secs//60:02d}:{secs%60:02d}"


def hp_pct(p: PlayerStats) -> float:
    if not p.max_hp:
        return 0
    return max(0.0, min(1.0, p.final_hp / p.max_hp))


def render(report: MatchReport, out_path: str):
    W = 2200
    row_h = 40
    team0_n = sum(1 for p in report.players if p.team_id == 0)
    team1_n = sum(1 for p in report.players if p.team_id == 1)
    team_panel_h_0 = 56 + team0_n * row_h + 14
    team_panel_h_1 = 56 + team1_n * row_h + 14
    header_h = 110
    timeline_h = 220
    owner_box_h = 110
    pad = 16
    skip_personal = _os.environ.get("WOWS_SKIP_PERSONAL") == "1"
    H = (header_h + pad + team_panel_h_0 + pad + team_panel_h_1 + pad
         + timeline_h + pad)
    if not skip_personal:
        H += owner_box_h + pad

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)

    f_title = font(CJK_FONT, 34)
    f_h2 = font(CJK_FONT, 20)
    f_row = font(CJK_FONT, 16)
    f_num = font(MONO_FONT, 16)
    f_small = font(CJK_FONT, 13)
    f_col_hdr = font(CJK_FONT, 15)  # column headers (玩家/战舰/...)
    f_tiny = font(CJK_FONT, 11)
    f_tiny_mono = font(MONO_FONT, 11)
    f_score = font(MONO_FONT, 30)
    f_big_num = font(MONO_FONT, 24)
    f_big_cjk = font(CJK_FONT, 22)  # for stat values that may contain Chinese

    # ---- HEADER ----
    draw.rectangle([0, 0, W, header_h], fill=(14, 19, 30))
    draw.line([0, header_h, W, header_h], fill=GAME_GOLD, width=2)

    map_zh = t(f"IDS_SPACES/{report.map_name.upper()}", report.map_name)
    draw.text((28, 14), map_zh, GAME_TEXT, f_title)

    # mode pretty: match_group · game_mode
    mg_raw, gm_raw = report.mode.split("·", 1) if "·" in report.mode else (report.mode, "")
    mg_zh = MATCH_GROUP_CN.get(mg_raw, mg_raw)
    # Try SCENARIO_* first (covers 3POINT, ARMSRACE, etc.), then plain IDS_*
    gm_zh = t(f"IDS_SCENARIO_{gm_raw.upper()}",
              t(f"IDS_{gm_raw.upper()}", gm_raw))
    mode_zh = f"{mg_zh}·{gm_zh}" if gm_zh else mg_zh
    draw.text((28, 60),
              f"{mode_zh}   {report.date}   时长 {fmt_time(report.duration_played)}",
              GAME_DIM, f_h2)

    # result badge (from self_team perspective) — far right
    is_win = (report.win_type == "Win")
    is_draw = (report.win_type == "Draw")
    badge_text = "胜利" if is_win else ("平局" if is_draw else "失败")
    badge_color = GAME_GREEN if is_win else (GAME_GOLD if is_draw else GAME_RED)
    bb = f_title.getbbox(badge_text)
    bw = bb[2] - bb[0]
    bh = bb[3] - bb[1]
    badge_right = W - 36
    badge_left = badge_right - bw - 36
    badge_top = (header_h - bh - 22) // 2
    badge_bot = badge_top + bh + 22
    draw.rounded_rectangle([badge_left, badge_top, badge_right, badge_bot],
                           radius=8, fill=badge_color)
    draw.text((badge_left + 18, badge_top + 6), badge_text, (10, 16, 28), f_title)

    # score — to the LEFT of the badge, vertically centered with it
    score_text = f"{report.final_score.get(0,0)} : {report.final_score.get(1,0)}"
    sb = f_score.getbbox(score_text)
    sw = sb[2] - sb[0]
    sh = sb[3] - sb[1]
    gap = 28
    score_x = badge_left - gap - sw
    score_y = (header_h - sh) // 2 - 4
    draw.text((score_x, score_y), score_text, GAME_GOLD, f_score)

    y = header_h + pad

    # ---- TEAM PANELS (stacked vertically, full width) ----
    panel_w = W - 2 * pad
    eid_to_player_panel = {p.entity_id: p for p in report.players}

    def ship_zh_panel(p: PlayerStats) -> str:
        if p.ship_index:
            return t(f"IDS_{p.ship_index}", p.ship_name)
        return p.ship_name

    def draw_team_panel(team: int, y_top: int) -> int:
        x = pad
        is_self_team = team == report.self_team
        color = GAME_GREEN if is_self_team else GAME_RED
        draw.rectangle([x, y_top, x + panel_w, y_top + 36], fill=color)
        team_label = "己方阵营" if is_self_team else "敌方阵营"
        draw.text((x + 12, y_top + 7), team_label, (10, 16, 28), f_h2)
        members = [p for p in report.players if p.team_id == team]
        alive = sum(1 for p in members if p.is_alive)
        total_dmg = sum(int(p.damage_dealt) for p in members)
        total_frags = sum(p.frags for p in members)
        count_str = (f"{alive}/{len(members)} 存活   "
                     f"总击伤 {total_dmg//1000}k   总击杀 {total_frags}")
        cb = f_h2.getbbox(count_str)
        draw.text((x + panel_w - (cb[2] - cb[0]) - 12, y_top + 7),
                  count_str, (10, 16, 28), f_h2)

        # column layout (panel_w = ~2168)
        cols = [
            (16,   "玩家",     None),
            (340,  "战舰",     None),
            (540,  "类型",     None),
            (600,  "击杀",     None),
            (680,  "击伤",     None),
            (790,  "飞机",     None),
            (870,  "侦查",     None),
            (970,  "潜在",     None),
            (1090, "裸经验",   None),
            (1190, "血量",     None),
            (1350, "存活时长", None),
            (1450, "结局",     None),
            (1610, "凶手",     None),
            (1840, "成就",     None),
        ]
        ry = y_top + 36 + 8
        for cx, label, _ in cols:
            draw.text((x + cx, ry), label, GAME_TEXT, f_col_hdr)
        ry += 26
        draw.line([x + 6, ry - 2, x + panel_w - 6, ry - 2], fill=GAME_BORDER)

        members_sorted = sorted(members, key=lambda p: -p.damage_dealt)
        for i, p in enumerate(members_sorted):
            bg = GAME_PANEL_ALT if i % 2 else GAME_PANEL
            draw.rectangle([x + 4, ry - 2, x + panel_w - 4, ry + row_h - 4], fill=bg)
            # vertical centering helpers for this row
            ty = ry + (row_h - 16) // 2 - 2  # text baseline (for f_row size 16)
            bar_y = ry + (row_h - 10) // 2 - 1
            is_self_player = (p.name == report.self_player_name)
            name_color = GAME_GOLD if is_self_player else GAME_TEXT
            marker = "★ " if is_self_player else "  "
            clan = f"[{p.clan}] " if p.clan else ""
            name_str = f"{marker}{clan}{p.name}"
            while f_row.getbbox(name_str)[2] > 310:
                name_str = name_str[:-2] + "…"
            draw.text((x + 16, ty), name_str, name_color, f_row)
            ship_zh = ship_zh_panel(p)
            draw.text((x + 340, ty),
                      f"L{p.ship_level}  {ship_zh}", GAME_TEXT, f_row)
            draw.text((x + 540, ty),
                      SPECIES_SHORT.get(p.ship_species, "?"), GAME_DIM, f_row)
            # frags (number, colored by tier)
            if p.frags == 0:
                draw.text((x + 600, ty), "—", GAME_DIM, f_row)
            else:
                fcol = (GAME_PURPLE if p.frags >= 5 else
                        GAME_GOLD if p.frags >= 3 else GAME_TEXT)
                draw.text((x + 600, ty), str(p.frags), fcol, f_num)
            # damage dealt
            dmg = int(p.damage_dealt)
            dmg_color = (GAME_PURPLE if dmg >= 200_000 else
                         GAME_GOLD if dmg >= 100_000 else
                         GAME_TEXT if dmg >= 30_000 else GAME_DIM)
            draw.text((x + 680, ty), f"{dmg:>6,}".replace(",", " "), dmg_color, f_num)
            # planes shot down (own AA + own planes)
            if p.planes_killed is not None and p.planes_killed > 0:
                pk = int(p.planes_killed)
                pk_color = (GAME_PURPLE if pk >= 35 else
                            GAME_GOLD if pk >= 20 else GAME_TEXT)
                draw.text((x + 790, ty), str(pk), pk_color, f_num)
            else:
                draw.text((x + 790, ty), "—", GAME_DIM, f_row)
            # scouting (spotting) damage
            if p.scouting_damage is not None and p.scouting_damage > 0:
                sd = int(p.scouting_damage)
                sd_color = GAME_GOLD if sd >= 50000 else GAME_TEXT
                draw.text((x + 870, ty), f"{sd:>5,}".replace(",", " "), sd_color, f_num)
            else:
                draw.text((x + 870, ty), "—", GAME_DIM, f_row)
            # potential damage (fall back to actual damage taken if not available)
            if p.potential_damage is not None and p.potential_damage > 0:
                pot = int(p.potential_damage)
                pot_color = (GAME_PURPLE if pot >= 3_000_000 else
                             GAME_GOLD if pot >= 1_500_000 else GAME_TEXT)
                draw.text((x + 970, ty), f"{pot:>7,}".replace(",", " "), pot_color, f_num)
            else:
                taken = int(p.max_hp - p.final_hp)
                draw.text((x + 970, ty), f"{taken:>7,}".replace(",", " "), GAME_DIM, f_num)
            # raw xp
            if p.exp is not None:
                xp_color = GAME_GOLD if p.exp >= 1500 else GAME_TEXT
                draw.text((x + 1090, ty), f"{int(p.exp):>5,}".replace(",", " "), xp_color, f_num)
            else:
                draw.text((x + 1090, ty), "—", GAME_DIM, f_row)
            # hp bar
            pct = hp_pct(p)
            bar_w = 130
            draw.rectangle([x + 1190, bar_y, x + 1190 + bar_w, bar_y + 10],
                           fill=(40, 50, 70))
            if pct > 0:
                hp_col = GAME_GREEN if pct > 0.5 else (GAME_GOLD if pct > 0.25 else GAME_RED)
                draw.rectangle([x + 1190, bar_y,
                                x + 1190 + int(bar_w * pct), bar_y + 10], fill=hp_col)
            # time lived
            if p.is_alive:
                draw.text((x + 1350, ty), "全程", GAME_GREEN, f_row)
            else:
                draw.text((x + 1350, ty),
                          fmt_time(p.time_lived_secs or 0), GAME_TEXT, f_num)
            # outcome / cause
            if p.is_alive:
                draw.text((x + 1450, ty), "存活", GAME_GREEN, f_row)
            else:
                cause_cn = DEATH_CAUSE_CN.get(p.death_cause or "", p.death_cause or "?")
                draw.text((x + 1450, ty), f"亡于 {cause_cn}", GAME_DIM, f_row)
            # killer
            if p.is_alive:
                draw.text((x + 1610, ty), "—", GAME_DIM, f_row)
            else:
                killer = eid_to_player_panel.get(p.killer_entity_id) if p.killer_entity_id else None
                if killer is None:
                    killer_txt = "环境"
                elif killer.entity_id == p.entity_id:
                    killer_txt = "自损"
                else:
                    k_ship = ship_zh_panel(killer)
                    killer_txt = f"{k_ship} ({killer.name[:10]})"
                # truncate killer column to keep room for 成就
                while f_row.getbbox(killer_txt)[2] > 220:
                    killer_txt = killer_txt[:-2] + "…"
                draw.text((x + 1610, ty), killer_txt, GAME_DIM, f_row)
            # achievements — icons
            if p.achievements:
                icon_size = 32
                gap = 5
                max_width = 320  # column width budget (W=2200 gives more room)
                ax = x + 1840
                ay = ry + (row_h - icon_size) // 2 - 1
                # cap icons; rest summarized as "+N"
                MAX_ICONS = max_width // (icon_size + gap)
                shown = p.achievements[:MAX_ICONS]
                hidden = len(p.achievements) - len(shown)
                for aid, cnt in shown:
                    idx_name = _ACH_ID_TO_INDEX.get(int(aid)) if (load_achievements() or True) else None
                    icon = achievement_icon(idx_name, icon_size) if idx_name else None
                    if icon:
                        img.paste(icon, (ax, ay), icon)
                    else:
                        draw.rectangle([ax, ay, ax + icon_size, ay + icon_size],
                                       outline=GAME_GOLD)
                    if cnt > 1:
                        # small count badge bottom-right of the icon
                        cw = f_tiny_mono.getbbox(f"x{cnt}")[2]
                        bx0 = ax + icon_size - cw - 2
                        by0 = ay + icon_size - 12
                        draw.rectangle([bx0 - 1, by0, ax + icon_size, ay + icon_size],
                                       fill=(0, 0, 0))
                        draw.text((bx0, by0 - 1), f"x{cnt}", GAME_GOLD, f_tiny_mono)
                    ax += icon_size + gap
                if hidden > 0:
                    draw.text((ax + 2, ty), f"+{hidden}", GAME_GOLD, f_tiny)
            else:
                draw.text((x + 1840, ty), "—", GAME_DIM, f_row)
            ry += row_h
        return y_top + 56 + len(members) * row_h + 14

    # Draw self team first (so user sees it immediately)
    if report.self_team == 0:
        end_y = draw_team_panel(0, y)
        y = end_y + pad
        end_y = draw_team_panel(1, y)
        y = end_y + pad
    else:
        end_y = draw_team_panel(1, y)
        y = end_y + pad
        end_y = draw_team_panel(0, y)
        y = end_y + pad

    # ---- DEATH TIMELINE (with names + times) ----
    draw.rectangle([pad, y, W - pad, y + timeline_h], fill=GAME_PANEL)
    draw.text((pad + 16, y + 10), "死亡时间轴", GAME_TEXT, f_h2)
    # legend
    draw.ellipse([pad + 16, y + 42, pad + 24, y + 50], fill=GAME_GREEN)
    draw.text((pad + 30, y + 40), "己方阵亡 (下方)", GAME_DIM, f_small)
    draw.ellipse([pad + 16 + 130, y + 42, pad + 24 + 130, y + 50], fill=GAME_RED)
    draw.text((pad + 30 + 130, y + 40), "敌方阵亡 (上方)", GAME_DIM, f_small)

    # Build entity_id -> player map for victim & killer lookup
    eid_to_player = {p.entity_id: p for p in report.players}

    def ship_zh_of(p: PlayerStats) -> str:
        if p.ship_index:
            return t(f"IDS_{p.ship_index}", p.ship_name)
        return p.ship_name

    tl_x0 = pad + 60
    tl_x1 = W - pad - 60
    tl_y = y + timeline_h - 70
    tl_w = tl_x1 - tl_x0

    # axis line
    draw.line([tl_x0, tl_y, tl_x1, tl_y], fill=GAME_BORDER, width=2)
    # time ticks every 2 minutes
    dur = max(report.duration_played, 1)
    for sec in range(0, dur + 60, 120):
        if sec > dur:
            break
        mx = int(tl_x0 + tl_w * (sec / dur))
        draw.line([mx, tl_y - 4, mx, tl_y + 4], fill=GAME_BORDER, width=1)
        draw.text((mx - 14, tl_y + 8), fmt_time(sec), GAME_DIM, f_tiny_mono)

    # Determine, for each death event, the X position and which side
    events = []
    for t_sec, vid, kid, kname, cause in report.deaths:
        victim = eid_to_player.get(vid)
        if not victim:
            continue
        mx = int(tl_x0 + tl_w * (min(t_sec, dur) / dur))
        is_self_team = (victim.team_id == report.self_team)
        side = "down" if is_self_team else "up"
        color = GAME_GREEN if is_self_team else GAME_RED
        victim_ship = ship_zh_of(victim)[:6]
        killer = eid_to_player.get(kid) if kid else None
        if killer and killer.entity_id == victim.entity_id:
            killer_ship = "自损"  # self-inflicted (fire/flood spread without a killer)
        elif killer:
            killer_ship = ship_zh_of(killer)[:6]
        else:
            killer_ship = "环境"  # terrain / sea mine / detonate etc.
        time_str = fmt_time(t_sec)
        events.append({
            "x": mx,
            "side": side,
            "victim_ship": victim_ship,
            "killer_ship": killer_ship,
            "time": time_str,
            "color": color,
        })

    # Group events by side
    def stagger_labels(side_events):
        side_events.sort(key=lambda e: e["x"])
        min_gap = 80
        rows_last_x = []
        for e in side_events:
            placed = False
            for r, last_x in enumerate(rows_last_x):
                if e["x"] - last_x >= min_gap:
                    e["row"] = r
                    rows_last_x[r] = e["x"]
                    placed = True
                    break
            if not placed:
                e["row"] = len(rows_last_x)
                rows_last_x.append(e["x"])
        return len(rows_last_x)

    up_events = [e for e in events if e["side"] == "up"]
    down_events = [e for e in events if e["side"] == "down"]
    stagger_labels(up_events)
    stagger_labels(down_events)

    label_h = 28

    for e in events:
        offset = -8 if e["side"] == "up" else 8
        cx, cy = e["x"], tl_y + offset
        draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6],
                     fill=e["color"], outline=GAME_TEXT)

    def draw_label(e, above: bool):
        cx = e["x"]
        row = e["row"]
        if above:
            label_y = tl_y - 16 - (row + 1) * label_h
            stem_top = label_y + label_h - 4
            stem_bot = tl_y - 14
        else:
            label_y = tl_y + 18 + row * label_h
            stem_top = tl_y + 14
            stem_bot = label_y - 2
        draw.line([cx, stem_top, cx, stem_bot], fill=GAME_BORDER, width=1)
        vw = f_tiny.getbbox(e["victim_ship"])[2]
        draw.text((cx - vw // 2, label_y), e["victim_ship"], e["color"], f_tiny)
        tw = f_tiny_mono.getbbox(e["time"])[2]
        draw.text((cx - tw // 2, label_y + 13), e["time"], GAME_DIM, f_tiny_mono)

    for e in up_events:
        draw_label(e, above=True)
    for e in down_events:
        draw_label(e, above=False)

    y += timeline_h + pad

    # ---- Self player stats ----
    self_p = next((p for p in report.players if p.name == report.self_player_name), None)
    if self_p and not skip_personal:
        draw.rounded_rectangle([pad, y, W - pad, y + owner_box_h], radius=8,
                               fill=GAME_PANEL)
        self_ship_zh = t(f"IDS_{self_p.ship_index}", self_p.ship_name) if self_p.ship_index else self_p.ship_name
        draw.text((pad + 20, y + 12),
                  f"个人战绩 — {self_p.name} ({self_ship_zh})",
                  GAME_TEXT, f_h2)
        # (label, value, color, is_cjk) — Menlo can't render Chinese, use CJK font for text values
        pot_self = int(self_p.potential_damage) if self_p.potential_damage else None
        sd_self = int(self_p.scouting_damage) if self_p.scouting_damage else None
        if self_p.achievements:
            ach_self_str = " · ".join(
                (achievement_name(aid) + (f"×{cnt}" if cnt > 1 else ""))
                for aid, cnt in self_p.achievements
            )
        else:
            ach_self_str = "—"
        boxes = [
            ("击伤",    f"{int(self_p.damage_dealt):,}", GAME_GOLD, False),
            ("击杀",    str(self_p.frags),               GAME_GOLD, False),
            ("飞机",    str(self_p.planes_killed) if self_p.planes_killed else "0", GAME_TEXT, False),
            ("侦查伤害", f"{sd_self:,}" if sd_self else "—", GAME_TEXT, False),
            ("潜在伤害", f"{pot_self:,}" if pot_self else "—", GAME_TEXT, False),
            ("实际承伤", f"{int(self_p.max_hp - self_p.final_hp):,}", GAME_TEXT, False),
            ("裸经验",   f"{self_p.exp:,}" if self_p.exp is not None else "—", GAME_GOLD, False),
            ("存活",    fmt_time(self_p.time_lived_secs if self_p.time_lived_secs is not None else report.duration_played), GAME_TEXT, False),
            ("结局",
             "存活" if self_p.is_alive else f"亡于 {DEATH_CAUSE_CN.get(self_p.death_cause or '', self_p.death_cause or '?')}",
             GAME_GREEN if self_p.is_alive else GAME_RED,
             True),
            ("成就", ach_self_str, GAME_GOLD if self_p.achievements else GAME_DIM, True),
        ]
        bx = pad + 20
        by = y + 50
        box_w = (W - 2 * pad - 80) // len(boxes)
        for label, value, col, is_cjk in boxes:
            draw.text((bx, by), label, GAME_DIM, f_small)
            draw.text((bx, by + 22), value, col, f_big_cjk if is_cjk else f_big_num)
            bx += box_w

    img.save(out_path)
    print(f"saved: {out_path}")


def main(json_path: str, out_png: str):
    report = load(json_path)
    print(f"map={report.map_name} self={report.self_player_name} "
          f"team={report.self_team} result={report.win_type} "
          f"score={report.final_score} duration={report.duration_played}s")
    render(report, out_png)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
