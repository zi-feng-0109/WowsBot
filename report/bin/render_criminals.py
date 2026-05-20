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
CITADEL_SINGLE_HIT_RATIO = 0.30   # 单次受伤 >= 30% max_hp


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


def analyze_player(p, damage_events, match_duration_secs):
    """对一个玩家算所有触发条件,返回 (score, reasons[], is_ringleader_bool)。"""
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
        reasons.append(f"击伤 {damage:,} (该船种 {thr['low_damage']:,}+ 才合格)".replace(",", " "))
        score += 1

    # --- 低潜在 (抗线船) ---
    if thr["low_potential"] is not None and potential < thr["low_potential"]:
        reasons.append(f"潜在 {potential:,} (抗线船 {thr['low_potential']:,}+)".replace(",", " "))
        score += 1

    # --- 低侦查 (侦查船) ---
    if thr["low_scouting"] is not None and scouting < thr["low_scouting"]:
        reasons.append(f"侦查 {scouting:,} (该船种 {thr['low_scouting']:,}+)".replace(",", " "))
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
            # 1) 集火走位错: 死亡时间 - 60s 时 HP 还满
            death_t = float(time_lived)
            t_back = death_t - BURST_LOOKBACK_SECS
            if t_back >= 0:
                hp_then = hp_at_time(received, max_hp, t_back)
                if hp_then >= max_hp * BURST_HP_RATIO:
                    pct_hp = int(hp_then / max_hp * 100)
                    reasons.append(
                        f"集火走位错: 死前 60s 还有 {pct_hp}% HP, 一分钟内被打穿"
                    )
                    score += 2

            # 2) 装甲区暴毙: 任意单次 >= 30% max_hp
            #    (装甲区是受害者,不自动升级"头号";头号只看裸经验 <500)
            max_single = max(amt for _, amt in received) if received else 0
            if max_single >= max_hp * CITADEL_SINGLE_HIT_RATIO:
                pct = int(max_single / max_hp * 100)
                reasons.append(
                    f"装甲区暴毙: 单发吃 {int(max_single):,} ({pct}% max HP)".replace(",", " ")
                )
                score += 2

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

    scored = []
    for p in losers:
        score, reasons, is_ring = analyze_player(p, damage_events, match_dur)
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


def render(json_path: str, out_path: str, max_cards: int = 4):
    load_translations()
    load_result_indices()

    raw = json.load(open(json_path, encoding="utf-8"))
    criminals = find_criminals(raw)

    # 没战犯就不出图(让上层决定怎么处理)
    if not criminals:
        print("no criminals detected, skipping render", file=sys.stderr)
        # 仍然写一张占位图? 不,直接退出非 0 让 wows_full_report 判断
        sys.exit(3)

    criminals = criminals[:max_cards]
    n = len(criminals)

    W = 2200
    pad = 16
    title_h = 60
    card_w = (W - pad * (n + 1)) // n
    card_h = 230 + max(0, max(len(r[2]) for r in criminals) - 4) * 28
    H = title_h + pad + card_h + pad

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)

    f_title = font(CJK_FONT, 32)
    f_card_name = font(CJK_FONT, 22)
    f_card_ship = font(CJK_FONT, 18)
    f_reason = font(CJK_FONT, 15)
    f_badge = font(CJK_FONT, 18)
    f_score = font(MONO_FONT, 16)

    # 标题
    draw.rectangle([0, 0, W, title_h], fill=(14, 19, 30))
    draw.line([0, title_h, W, title_h], fill=GAME_RED, width=2)
    title = f"战犯榜  (败方 {n} 名上榜)"
    draw.text((24, 14), title, GAME_RED, f_title)
    sub = "按规则评分 + 事件级时间轴(集火/装甲区)综合判定"
    draw.text((24 + f_title.getbbox(title)[2] + 32, 22), sub, GAME_DIM, f_card_ship)

    # 卡片
    y0 = title_h + pad
    for i, (p, score, reasons, is_ring) in enumerate(criminals):
        x0 = pad + i * (card_w + pad)
        x1 = x0 + card_w
        y1 = y0 + card_h
        # 卡片背景
        bg = GAME_PANEL if (i % 2 == 0) else GAME_PANEL_ALT
        border = GAME_RED if is_ring else GAME_GOLD
        draw.rounded_rectangle([x0, y0, x1, y1], radius=10, fill=bg, outline=border, width=2)

        # 头号战犯角标
        badge_text = "头号战犯" if is_ring else "战犯"
        badge_color = GAME_RED if is_ring else GAME_GOLD
        bw = f_badge.getbbox(badge_text)[2] + 16
        draw.rounded_rectangle([x0 + 14, y0 + 12, x0 + 14 + bw, y0 + 12 + 28],
                               radius=6, fill=badge_color)
        draw.text((x0 + 22, y0 + 16), badge_text, (12, 16, 26), f_badge)

        # 分数
        score_txt = f"score {score}"
        draw.text((x1 - f_score.getbbox(score_txt)[2] - 14, y0 + 18),
                  score_txt, GAME_DIM, f_score)

        # 玩家名
        name = p.get("name", "?")
        draw.text((x0 + 14, y0 + 52), name, GAME_TEXT, f_card_name)

        # 船 + 船种
        ship_txt = _ship_label(p)
        draw.text((x0 + 14, y0 + 82), ship_txt, GAME_DIM, f_card_ship)

        # 分割线
        draw.line([x0 + 14, y0 + 112, x1 - 14, y0 + 112], fill=GAME_BORDER, width=1)

        # 原因列表
        ry = y0 + 124
        for reason in reasons:
            draw.text((x0 + 14, ry), f"• {reason}", GAME_TEXT, f_reason)
            ry += 26

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
