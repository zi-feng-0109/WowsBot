"""render_criminals.py — 败方战犯检测 + 卡片 PNG 渲染。

用法:
    render_criminals.py <battle.json> <out.png>

阈值表(按船种,T10 视角):
    BB   战列   死<6min  伤<60k  潜在<1.0M
    CV   航母   死<6min  伤<60k  侦查<15k
    CA/CL 巡洋  死<6min  伤<50k  潜在<800k  侦查<15k
    DD   驱逐   死<8min  伤<25k             侦查<20k
    SS   潜艇   死<8min  伤<20k             侦查<30k

裸经验(raw_exp): <700 上榜 / <500 头号战犯加重。

事件级精确指标(读 damage_events 时间轴):
- 集火走位错: 死亡前 60s, HP 还 >= 80% max_hp -> 1 分钟内被打穿
- 装甲区暴毙: 任意单次受伤 >= 30% max_hp -> 一发被点核心

判定: 命中阈值 >= 2 条上榜; raw_exp < 500 强制头号战犯。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_battle_report import (  # noqa: E402
    t, result_field, load_translations, load_result_indices,
    fmt_time, strip_known, strip_id, clean_ship_name,
    CJK_FONT, MONO_FONT, GAME_BG, GAME_PANEL, GAME_PANEL_ALT, GAME_GREEN,
    GAME_RED, GAME_GOLD, GAME_TEXT, GAME_DIM, GAME_BORDER,
)
from PIL import Image, ImageDraw, ImageFont


# ---- 阈值 (T10) ----
# 同 species 共用一套(JSON 里只给 "Cruiser",CA/CL 不分)。
THRESHOLDS = {
    "Battleship": {
        "early_lived_secs": 6 * 60,
        "low_damage": 60_000,
        "low_potential": 1_000_000,
        "low_scouting": None,
    },
    "AirCarrier": {
        "early_lived_secs": 6 * 60,
        "low_damage": 60_000,
        "low_potential": None,
        "low_scouting": 15_000,
    },
    "Cruiser": {
        "early_lived_secs": 6 * 60,
        "low_damage": 50_000,
        "low_potential": 800_000,
        "low_scouting": 15_000,
    },
    "Destroyer": {
        "early_lived_secs": 8 * 60,
        "low_damage": 25_000,
        "low_potential": None,
        "low_scouting": 20_000,
    },
    "Submarine": {
        "early_lived_secs": 8 * 60,
        "low_damage": 20_000,
        "low_potential": None,
        "low_scouting": 30_000,
    },
}

LOW_RAW_XP = 700
VERY_LOW_RAW_XP = 500

# 事件级阈值
BURST_LOOKBACK_SECS = 60          # 1 分钟前还满血就算"集火暴毙"
BURST_HP_RATIO = 0.80             # 1 分钟前 HP >= 80% max_hp
BURST_MIN_TEAMMATES_ALIVE = 3     # 1 分钟前还需要至少 N 个**其他**队友活着,
                                  # 不然队伍已经崩了,自己被集火是无解,不算走位错
CITADEL_SINGLE_HIT_RATIO = 0.30   # 单次受伤 >= 30% max_hp

# 消耗品使用检测。
# 精确指标: 用 ship.consumables (Rust 端 dump 的 ability_name 列表) 知道玩家带了什么,
# 用 consumable_uses 时间轴知道实际开了几次,如果"带了强相关消耗品但 0 次使用"=> 战犯。
# 粗指标: 全场消耗品使用次数过低也算挂机型战犯(双保险,不依赖船种识别)。
CONSUMABLE_MIN_LIVED_SECS = 5 * 60  # 存活 >5min 才评判(避免误伤开局秒退)
CONSUMABLE_LOW_USES_THRESHOLD = 1   # 全场使用 <=1 次 = 严重不开消耗品

# 强相关消耗品: 带了就该用,不用扣分。
# 字段 = (ability_name 内的关键字, consumable_uses 里对应的 enum 名)。
# 一个玩家可能带多个强相关消耗品,每个 0 次使用各扣 1 分。
# 中文显示名直接查 .mo 里的 IDS_DOCK_CONSUME_TITLE_<UPPER(ability_name)>,
# 拿到的是 WG 官方游戏内名(比如带 I/II/III 罗马数字, 或"短程对海搜索"等变体)。
STRONG_CONSUMABLES = [
    # (ability_name 关键字, consumable_uses enum 名)
    # 只列 Vehicle.onConsumableUsed 广播的舰船消耗品 (所有玩家都能可靠捕获)。
    ("RLSSearch",             "Radar"),
    ("SonarSearch",           "HydroacousticSearch"),
    ("Hydrophone",            "Hydrophone"),
    ("Fighter",               "CatapultFighter"),       # 弹射巡逻战斗机 (航战/航巡/航驱)
    ("Spotter",               "SpottingAircraft"),       # 弹射侦察机
    ("AirDefenseDisp",        "DefensiveAntiAircraft"),
    ("SmokeGenerator",        "Smoke"),                  # 船舰烟雾 (DD)
    ("SubmarineLocator",      "SubmarineSurveillance"),
]

# CV 飞机级消耗品 — 走 Avatar.squadronConsumableUsed 单播,
# 只有当被评判的 CV 就是录制者本人时才能拿到使用次数。
# (ability_name 关键字, squadron_consumable_uses 里 consumable_name)
PLANE_CONSUMABLES = [
    ("PlaneTacticalFighters", "planeTacticalFighters"),   # 飞机自带巡逻战斗机
    ("PlaneSmokeGenerator",   "PlaneSmokeGenerator"),     # 飞机喷烟自掩护
    # ForsageBooster / ActiveManeuvering 排除:虽然也能拿到,但属于手感按钮,
    # 没按不必然=战犯;只评"战略级"的两项: 拉烟 + 放战斗机。
]


def consumable_display(ability_name):
    """ability_name (如 PCY034_ForsageBooster) 查 WoWs 官方中文。
    Pattern: IDS_DOCK_CONSUME_TITLE_<UPPER>。查不到就用 ability_name 兜底。"""
    if not ability_name:
        return ability_name
    return t(f"IDS_DOCK_CONSUME_TITLE_{ability_name.upper()}", ability_name)


# ---- 数据加载 ----

def potential_total(ri):
    """潜在伤害 = agro_art + agro_air + agro_tpd + agro_dbomb (与战报渲染口径一致)"""
    return sum((result_field(ri, k, 0) or 0)
               for k in ("agro_art", "agro_air", "agro_tpd", "agro_dbomb"))


def collect_received_events(events, victim_id):
    """返回该 victim 收到的所有事件 [(time_secs, amount)], 按时间升序。"""
    out = []
    for e in events:
        vid = strip_id(e.get("victim_entity_id") or "")
        if vid == victim_id:
            out.append((float(e.get("time_secs") or 0), float(e.get("amount") or 0)))
    out.sort(key=lambda x: x[0])
    return out


def hp_at_time(received_events, max_hp, query_time):
    """HP at time T = max_hp - sum(amount for events strictly before T)."""
    taken = sum(amt for ts, amt in received_events if ts < query_time)
    return max(0.0, max_hp - taken)


def teammates_alive_at(all_players, team_id, t, exclude_eid):
    """在时间 t 时 team_id 中除 exclude_eid 之外还活着的玩家数。
    "活着" = 全场未死(is_alive=true) 或 time_lived_secs > t。"""
    n = 0
    for p in all_players:
        if p.get("team_id") != team_id:
            continue
        if strip_id(p.get("vehicle_entity_id") or "") == exclude_eid:
            continue
        st = p.get("stats") or {}
        if st.get("is_alive"):
            n += 1
        else:
            tl = st.get("time_lived_secs")
            if tl is not None and tl > t:
                n += 1
    return n


def count_consumable_uses(consumable_uses, user_entity_id, enum_names=None):
    """该 entity 全场使用消耗品总次数 (enum_names=None) 或 enum_names 集合内总次数。"""
    if not user_entity_id:
        return 0
    if enum_names is None:
        return sum(
            1 for u in consumable_uses
            if strip_id(u.get("user_entity_id") or "") == user_entity_id
        )
    name_set = set(enum_names)
    return sum(
        1 for u in consumable_uses
        if strip_id(u.get("user_entity_id") or "") == user_entity_id
        and u.get("consumable_name") in name_set
    )


def strong_consumable_slots(consumable_slots):
    """返回该船带的强相关消耗品 slot 列表 [(display_names_in_slot, enum_names_in_slot)]。
    consumable_slots 是嵌套结构: 外层 slot, 内层 ability_name 候选(玩家二选一)。
    一个 slot 内的所有强相关 variant 算作一组 (用斜杠 join 显示, enum 名集合用于查使用)。
    显示名从 .mo 里查官方中文,不再用手工硬编码表。"""
    out = []
    for slot in consumable_slots or []:
        slot_displays = []
        slot_enums = []
        for entry in slot:
            if isinstance(entry, dict):
                ab_name = entry.get("ability_name", "")
            else:
                ab_name = entry
            if not ab_name:
                continue
            for keyword, enum_name in STRONG_CONSUMABLES:
                if keyword in ab_name:
                    display = consumable_display(ab_name)
                    if display not in slot_displays:
                        slot_displays.append(display)
                    if enum_name not in slot_enums:
                        slot_enums.append(enum_name)
                    break
        if slot_displays:  # 此 slot 至少有一个强相关 variant
            out.append((slot_displays, slot_enums))
    return out


def _ship_plane_consumables(p):
    """从 ship.plane_refs 链路读出此船带的飞机消耗品集合。
    返回 [(display_name, enum_name)],去重。
    要求 ship 数据里有 'plane_consumables' 字段 (replayshark 输出)。"""
    sp = p.get("ship") or {}
    pc = sp.get("plane_consumables") or []
    out = []
    seen = set()
    for ab_name in pc:
        for keyword, enum_name in PLANE_CONSUMABLES:
            if keyword in ab_name and enum_name not in seen:
                out.append((consumable_display(ab_name), enum_name))
                seen.add(enum_name)
                break
    return out


def analyze_player(p, damage_events, match_duration_secs, all_players=None,
                   consumable_uses=None, squadron_consumable_uses=None,
                   self_avatar_eid=None):
    """对一个玩家算所有触发条件,返回 (score, reasons[], is_ringleader_bool)。

    self_avatar_eid: 录制者 avatar EID,只有 p 对应的 CV 是 self 时,才能用
    squadron_consumable_uses 评判飞机消耗品 (Avatar 单播限制)。"""
    st = p.get("stats") or {}
    ri = p.get("results_info") or []
    species_raw = strip_known((p.get("ship") or {}).get("species") or "")
    thr = THRESHOLDS.get(species_raw)
    if thr is None:
        return 0, [], False  # 未知船种跳过

    name = p.get("name", "?")
    eid = strip_id(p.get("vehicle_entity_id") or "")

    damage = int(st.get("damage_dealt") or 0)
    max_hp = int(st.get("max_health") or 0) or 1
    time_lived = st.get("time_lived_secs")
    is_alive = bool(st.get("is_alive"))

    scouting = int(result_field(ri, "scouting_damage", 0) or 0)
    potential = int(potential_total(ri))
    raw_xp = int(result_field(ri, "raw_exp", 0) or 0)

    reasons = []
    score = 0

    # --- 早死 (只对阵亡玩家触发) ---
    if not is_alive and time_lived is not None and time_lived < thr["early_lived_secs"]:
        reasons.append(f"早死 {fmt_time(int(time_lived))}")
        score += 1

    # --- 低输出 ---
    if damage < thr["low_damage"]:
        reasons.append(f"击伤 {damage:,}".replace(",", " "))
        score += 1

    # --- 低潜在 (抗线船) ---
    if thr["low_potential"] is not None and potential < thr["low_potential"]:
        reasons.append(f"潜在 {potential:,}".replace(",", " "))
        score += 1

    # --- 低侦查 (侦查船) ---
    if thr["low_scouting"] is not None and scouting < thr["low_scouting"]:
        reasons.append(f"侦查 {scouting:,}".replace(",", " "))
        score += 1

    # --- 低裸经验 ---
    is_ringleader = False
    if raw_xp < VERY_LOW_RAW_XP:
        reasons.append(f"裸经验 {raw_xp} (败方垫底)")
        score += 2
        is_ringleader = True
    elif raw_xp < LOW_RAW_XP:
        reasons.append(f"裸经验 {raw_xp} (偏低)")
        score += 1

    # --- 事件级:集火走位错 + 装甲区 ---
    if not is_alive and time_lived is not None and damage_events and eid:
        received = collect_received_events(damage_events, eid)
        if received:
            # 1) 集火走位错: 死亡时间 - 60s 时 HP 还满,且队伍尚未崩
            #    (如果队伍只剩自己 + 寥寥几人,被多人集火是无解,不算走位错)
            death_t = float(time_lived)
            t_back = death_t - BURST_LOOKBACK_SECS
            if t_back >= 0:
                hp_then = hp_at_time(received, max_hp, t_back)
                if hp_then >= max_hp * BURST_HP_RATIO:
                    teammates = (
                        teammates_alive_at(all_players, p.get("team_id"), t_back, eid)
                        if all_players is not None else BURST_MIN_TEAMMATES_ALIVE
                    )
                    if teammates >= BURST_MIN_TEAMMATES_ALIVE:
                        pct_hp = int(hp_then / max_hp * 100)
                        reasons.append(
                            f"集火走位错: 死前 60s 还有 {pct_hp}% HP, 一分钟内被打穿"
                        )
                        score += 2
                    # 否则: 队伍已崩,无视该规则

            # 2) 装甲区暴毙: 任意单次 >= 30% max_hp
            #    (装甲区是受害者,不自动升级"头号";头号只看裸经验 <500)
            max_single = max(amt for _, amt in received) if received else 0
            if max_single >= max_hp * CITADEL_SINGLE_HIT_RATIO:
                pct = int(max_single / max_hp * 100)
                reasons.append(
                    f"装甲区暴毙: 单发吃 {int(max_single):,} ({pct}% max HP)".replace(",", " ")
                )
                score += 2

    # --- 消耗品检测 ---
    effective_lived = (
        time_lived if time_lived is not None else
        (match_duration_secs if is_alive else 0)
    )
    if effective_lived >= CONSUMABLE_MIN_LIVED_SECS and consumable_uses is not None and eid:
        # 精确:按 slot 整体判断,slot 内任何 variant 用过都算 slot 用过。
        # slot 内所有 alternatives 0 次使用 -> +1 分(显示斜杠拼接的备选名)。
        ship_slots = (p.get("ship") or {}).get("consumable_slots") or []
        for displays, enums in strong_consumable_slots(ship_slots):
            uses_n = count_consumable_uses(consumable_uses, eid, enums)
            if uses_n == 0:
                label_str = "/".join(displays)
                reasons.append(f"{label_str}带了但全程 0 次使用")
                score += 1

        # 粗指标:全场总使用过低(即使没有强相关消耗品也兜底)
        total_uses = count_consumable_uses(consumable_uses, eid)
        if total_uses <= CONSUMABLE_LOW_USES_THRESHOLD:
            reasons.append(
                f"消耗品基本没开: 存活 {fmt_time(int(effective_lived))} 全场仅 {total_uses} 次"
            )
            score += 1

    # --- CV 飞机消耗品 (仅录制者本人为该 CV 时可评) ---
    # Avatar.squadronConsumableUsed 是单播,只对 self 玩家有数据。
    # 关系判断: p['relation'] == 'Relation(0)' 即 self。
    if (species_raw == "AirCarrier"
            and effective_lived >= CONSUMABLE_MIN_LIVED_SECS
            and squadron_consumable_uses is not None
            and str(p.get("relation", "")) == "Relation(0)"):
        # 对所有定义的飞机消耗品类型查 0 次使用 → 战犯加分。
        # 此处不依赖 ship.plane_consumables (字段可能不存在),
        # 直接按 enum_name 在 squadron_consumable_uses 里查计数。
        for ab_keyword, enum_name in PLANE_CONSUMABLES:
            uses = sum(1 for u in squadron_consumable_uses
                       if u.get("consumable_name") == enum_name)
            if uses == 0:
                zh = {
                    "planeTacticalFighters": "飞机巡逻战斗机",
                    "PlaneSmokeGenerator":   "飞机烟雾",
                }.get(enum_name, enum_name)
                reasons.append(f"{zh}全程 0 次使用")
                score += 1

    return score, reasons, is_ringleader


def find_criminals(raw):
    """返回 [(player, score, reasons, is_ringleader)] 按 score 降序, 仅败方且 score>=2。"""
    m = raw["match"]
    br = m.get("battle_result") or {}
    win_team = br.get("team_id")
    if win_team is None:
        return []  # 平局或未结束,不评战犯

    # 全部玩家中胜方剔除,留败方
    loser_team = 1 - win_team if win_team in (0, 1) else None
    if loser_team is None:
        return []

    losers = [p for p in raw.get("players", []) if p.get("team_id") == loser_team]
    if not losers:
        return []

    damage_events = raw.get("damage_events") or []
    match_dur = m.get("duration_seconds_played") or m.get("duration_seconds_max") or 0

    all_players = raw.get("players", [])
    consumable_uses = raw.get("consumable_uses") or []
    squadron_consumable_uses = raw.get("squadron_consumable_uses") or []
    scored = []
    for p in losers:
        score, reasons, is_ring = analyze_player(
            p, damage_events, match_dur, all_players, consumable_uses,
            squadron_consumable_uses=squadron_consumable_uses,
        )
        if score >= 2 and reasons:
            scored.append((p, score, reasons, is_ring))

    scored.sort(key=lambda x: -x[1])
    return scored


# ---- 渲染 ----

def font(path, size):
    return ImageFont.truetype(path, size)


def _ship_label(p):
    sp = (p.get("ship") or {})
    idx = sp.get("index", "")
    raw_name = clean_ship_name(sp.get("name", ""))
    zh = t(f"IDS_{idx}", raw_name) if idx else raw_name
    species = strip_known(sp.get("species", "")) or "?"
    species_cn = {
        "Battleship": "战列",
        "Cruiser": "巡洋",
        "Destroyer": "驱逐",
        "Submarine": "潜艇",
        "AirCarrier": "航母",
    }.get(species, species)
    return f"{zh}  L{sp.get('level', '?')} {species_cn}"


CRIMINAL_GRADES = [
    ("甲级战犯", GAME_RED),
    ("乙级战犯", GAME_GOLD),
    ("丙级战犯", (220, 160, 60)),
    ("丁级战犯", GAME_DIM),
]


def _draw_rest_card(draw, x0, y0, w, h, item, grade_idx, fonts):
    """乙/丙/丁 卡 (普通大小)。"""
    p, score, reasons, _ = item
    f_badge, f_name, f_ship, f_reason, f_score = fonts
    g_label, g_color = CRIMINAL_GRADES[min(grade_idx, len(CRIMINAL_GRADES) - 1)]
    x1, y1 = x0 + w, y0 + h
    bg = GAME_PANEL if (grade_idx % 2 == 1) else GAME_PANEL_ALT
    draw.rounded_rectangle([x0, y0, x1, y1], radius=10, fill=bg, outline=g_color, width=2)

    bw = f_badge.getbbox(g_label)[2] + 16
    draw.rounded_rectangle([x0 + 14, y0 + 12, x0 + 14 + bw, y0 + 12 + 28],
                           radius=6, fill=g_color)
    draw.text((x0 + 22, y0 + 16), g_label, (12, 16, 26), f_badge)

    s_txt = f"score {score}"
    draw.text((x1 - f_score.getbbox(s_txt)[2] - 14, y0 + 18),
              s_txt, GAME_DIM, f_score)
    draw.text((x0 + 14, y0 + 52), p.get("name", "?"), GAME_TEXT, f_name)
    draw.text((x0 + 14, y0 + 82), _ship_label(p), GAME_DIM, f_ship)
    draw.line([x0 + 14, y0 + 112, x1 - 14, y0 + 112], fill=GAME_BORDER, width=1)

    ry = y0 + 124
    for reason in reasons:
        draw.text((x0 + 14, ry), f"• {reason}", GAME_TEXT, f_reason)
        ry += 26


def _draw_head_card(draw, x0, y0, w, h, head, fonts):
    """甲级战犯 卡 (放大, 全宽)。"""
    p, score, reasons, _ = head
    f_badge, f_name, f_ship, f_reason, f_score = fonts
    g_label, g_color = CRIMINAL_GRADES[0]
    x1, y1 = x0 + w, y0 + h
    draw.rounded_rectangle([x0, y0, x1, y1],
                           radius=14, fill=GAME_PANEL, outline=g_color, width=3)

    bw = f_badge.getbbox(g_label)[2] + 24
    draw.rounded_rectangle([x0 + 20, y0 + 16, x0 + 20 + bw, y0 + 16 + 44],
                           radius=8, fill=g_color)
    draw.text((x0 + 32, y0 + 24), g_label, (12, 16, 26), f_badge)

    s_txt = f"score {score}"
    draw.text((x1 - f_score.getbbox(s_txt)[2] - 24, y0 + 28),
              s_txt, GAME_DIM, f_score)

    draw.text((x0 + 24, y0 + 78), p.get("name", "?"), GAME_TEXT, f_name)
    draw.text((x0 + 24, y0 + 124), _ship_label(p), GAME_DIM, f_ship)

    sep_y = y0 + 160
    draw.line([x0 + 24, sep_y, x1 - 24, sep_y], fill=GAME_BORDER, width=1)

    ry = sep_y + 18
    for reason in reasons:
        draw.text((x0 + 24, ry), f"• {reason}", GAME_TEXT, f_reason)
        ry += 36


def render(json_path: str, out_path: str, max_cards: int = 4):
    load_translations()
    load_result_indices()

    raw = json.load(open(json_path, encoding="utf-8"))
    criminals = find_criminals(raw)

    if not criminals:
        print("no criminals detected, skipping render", file=sys.stderr)
        sys.exit(3)

    criminals = criminals[:max_cards]
    head = criminals[0]
    rest = criminals[1:]
    n_rest = len(rest)

    W = 2200
    pad = 16
    title_h = 60

    f_title  = font(CJK_FONT, 32)
    # head (甲级放大版)
    head_fonts = (
        font(CJK_FONT, 28),   # badge
        font(CJK_FONT, 34),   # name
        font(CJK_FONT, 24),   # ship
        font(CJK_FONT, 22),   # reason
        font(MONO_FONT, 22),  # score
    )
    # rest (普通)
    rest_fonts = (
        font(CJK_FONT, 18),   # badge
        font(CJK_FONT, 22),   # name
        font(CJK_FONT, 18),   # ship
        font(CJK_FONT, 15),   # reason
        font(MONO_FONT, 16),  # score
    )

    # 高度
    head_card_h = 178 + max(len(head[2]), 1) * 36 + 20
    rest_card_h = (
        230 + max(0, max(len(r[2]) for r in rest) - 4) * 28
        if n_rest > 0 else 0
    )

    # 是否有 CV 上榜 → 决定要不要画"飞机消耗品仅对录制者评判"的脚注
    has_cv = any(
        strip_known((c[0].get("ship") or {}).get("species") or "") == "AirCarrier"
        for c in criminals
    )
    footer_h = 38 if has_cv else 0

    H = title_h + pad + head_card_h
    if n_rest > 0:
        H += pad + rest_card_h
    H += footer_h + pad

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)

    # 标题
    draw.rectangle([0, 0, W, title_h], fill=(14, 19, 30))
    draw.line([0, title_h, W, title_h], fill=GAME_RED, width=2)
    title = f"战犯榜  (败方 {len(criminals)} 名上榜)"
    draw.text((24, 14), title, GAME_RED, f_title)
    sub = "按规则评分 + 事件级时间轴(集火/装甲区)综合判定"
    draw.text((24 + f_title.getbbox(title)[2] + 32, 22),
              sub, GAME_DIM, font(CJK_FONT, 18))

    # 行 1: 甲级 (全宽)
    head_y0 = title_h + pad
    _draw_head_card(draw, pad, head_y0, W - 2 * pad, head_card_h, head, head_fonts)

    # 行 2: 乙/丙/丁 并排
    last_y1 = head_y0 + head_card_h
    if n_rest > 0:
        row2_y0 = last_y1 + pad
        rest_card_w = (W - pad * (n_rest + 1)) // n_rest
        for i, item in enumerate(rest):
            x0 = pad + i * (rest_card_w + pad)
            _draw_rest_card(draw, x0, row2_y0, rest_card_w, rest_card_h,
                            item, grade_idx=i + 1, fonts=rest_fonts)
        last_y1 = row2_y0 + rest_card_h

    # 脚注: 解释 CV 飞机消耗品评判的协议限制
    if has_cv:
        footer_y = last_y1 + 14
        note = ("ℹ️ CV 飞机消耗品(飞机巡逻战斗机/飞机烟雾)仅当被评 CV 是本次回放的录制者本人时才能检测; "
                "其他 CV 由于 WoWs 协议限制无数据,本项不参与评分。")
        draw.text((24, footer_y), note, GAME_DIM, font(CJK_FONT, 16))

    img.save(out_path)
    print(f"saved: {out_path}", file=sys.stderr)
    print(out_path)


def main():
    if len(sys.argv) < 3:
        print("usage: render_criminals.py <battle.json> <out.png>", file=sys.stderr)
        sys.exit(2)
    render(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
