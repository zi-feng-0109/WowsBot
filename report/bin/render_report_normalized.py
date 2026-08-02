#!/usr/bin/env python3
"""Render the WG-style battle report PNG from the CURRENT replayshark
`battle-results --format normalized` JSON (the upstream schema), reusing the
exact visuals of render_battle_report.py.

The legacy `render_battle_report.py` consumes the old `battle-report` schema
(`match`/`players[stats,results_info]`/`deaths`). Upstream replaced that command
with `battle-results --format normalized` (`{metadata, players[observed_results,
ribbons, achievements, ...]}`), which is the one that carries the Lesta
(«Мир кораблей») fixes — including the self player's packet-derived ribbons and
achievements. This script bridges that new schema into the legacy renderer's
`PlayerStats`/`MatchReport` dataclasses and calls its `render()`, so the output
is pixel-identical in style while working for both WG and Lesta replays.

Usage:
    python render_report_normalized.py <normalized.json> <out.png>

Only the self player carries ribbons/achievements (packet stream is
self-scoped); other players show none — same as WG's own report.
"""
import json
import os
import sys
from pathlib import Path

# This renderer never wires non-self potential damage (packet stream is self-scoped),
# so blank that column for others instead of the HP-lost fallback (see
# render_battle_report's 潜在 block). Set before importing/calling rb.render.
os.environ["WOWS_NO_POTENTIAL_FALLBACK"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_battle_report as rb  # noqa: E402

# The new schema emits Rust `DeathCause` enum variant names, some of which differ
# from the legacy server-result cause strings the shared map keys on. Extend the
# shared map with the enum names (unknown/Lesta-only ones like `Fel` are left
# untranslated rather than guessed).
rb.DEATH_CAUSE_CN.update({
    "Artillery": "主炮",
    "Secondaries": "副炮",
    "Ramming": "撞击",
    "Detonation": "弹药库",
    "SkipBombs": "跳炸",
    "SeaMine": "水雷",
    "AerialDepthCharge": "深弹",
})


def _species_short(ship_class: str) -> str:
    return ship_class or ""


def _reverse_achievement_index():
    """`icon_key` (index name, e.g. VANGUARD) -> numeric id from achievements.json,
    so the legacy renderer resolves the icon/name. For Lesta-only achievements
    absent from that map, we synthesize an id and register it so the icon still
    loads by its key."""
    rb.load_achievements()
    rev = {}
    for aid, idx_name in rb._ACH_ID_TO_INDEX.items():
        rev.setdefault(idx_name, aid)
    return rev


def _ach_id_for(icon_key: str, rev: dict, synth_counter: list) -> int:
    aid = rev.get(icon_key)
    if aid is not None:
        return aid
    # Synthesize a stable-ish negative id and register it so achievement_icon()
    # (keyed by index name) resolves; achievement_name() falls back to the key.
    synth_counter[0] -= 1
    sid = synth_counter[0]
    rb._ACH_ID_TO_INDEX[sid] = icon_key
    return sid


def load_normalized(json_path: str) -> "rb.MatchReport":
    raw = json.load(open(json_path, encoding="utf-8"))
    m = raw["metadata"]
    br = m.get("battle_result") or {}
    win_type = br.get("type", "Draw")
    win_team = br.get("team_id", -1)

    self_name = next((p["name"] for p in raw["players"] if p.get("is_self")), "")
    self_team = next((p["team_id"] for p in raw["players"] if p.get("is_self")), 0)

    rev = _reverse_achievement_index()
    synth = [0]
    max_dur = int(m.get("max_duration", 0) or 0)

    # Pass 1: build players + name→entity map (for killer resolution).
    players = []
    name_to_eid = {}
    killer_names = {}  # eid -> killer player name (from normalized)
    for i, p in enumerate(raw["players"]):
        eid = i + 1
        obs = p.get("observed_results") or {}
        tl = p.get("time_lived_secs")
        is_self = bool(p.get("is_self"))
        team_id = p.get("team_id", -1)
        max_hp = float(p.get("max_health") or 0.0)
        final_hp = float(p.get("final_health") or 0.0)
        # A ship is alive if it kept HP and there's no recorded death cause.
        is_alive = (p.get("death_cause") is None) and (tl is None or (max_dur and tl >= max_dur - 2))
        name = p.get("name", "?")
        name_to_eid[name] = eid
        if p.get("killer_name"):
            killer_names[eid] = p["killer_name"]

        achievements = []
        for a in (p.get("achievements") or []):
            achievements.append((_ach_id_for(a.get("icon_key", ""), rev, synth), int(a.get("count", 1))))

        # Base XP + planes shot down for ALL players come from the replay file's
        # results block (see lesta_public_results.enrich), merged upstream. Fall
        # back to the self-only RIBBON_PLANE count for planes if that merge didn't
        # run (e.g. render_report called standalone without enrichment).
        base_xp = p.get("lesta_base_xp")
        planes_killed = p.get("lesta_planes")
        if planes_killed is None and is_self:
            pk = sum(int(r.get("count", 0) or 0)
                     for r in (p.get("ribbons") or []) if r.get("name") == "RIBBON_PLANE")
            planes_killed = pk if pk > 0 else None

        ship_zh = p.get("ship_name", "")  # already localized by the Rust side
        players.append(rb.PlayerStats(
            account_id=int(p.get("db_id") or 0),
            entity_id=eid,
            name=name,
            clan=p.get("clan", ""),
            team_id=team_id,
            relation=("self" if is_self else ("friendly" if team_id == self_team else "enemy")),
            ship_name=ship_zh,
            ship_index="",  # force t() to fall back to the already-localized ship_name
            ship_level=int(p.get("ship_tier") or 0),
            ship_species=_species_short(p.get("ship_class", "")),
            max_hp=max_hp,
            final_hp=final_hp,
            is_alive=bool(is_alive),
            damage_dealt=float(obs.get("damage") or 0),
            frags=int(obs.get("kills") or 0),
            time_lived_secs=tl,
            killer_entity_id=None,  # filled in pass 2
            death_cause=p.get("death_cause"),
            raw_exp=base_xp,
            exp=base_xp,
            scouting_damage=(p.get("controller_spotting_damage") if is_self else None),
            potential_damage=(p.get("controller_potential_damage") if is_self else None),
            planes_killed=planes_killed,
            achievements=achievements,
        ))

    # Pass 2: resolve killer names → entity ids, build death list for the timeline.
    deaths = []
    for ps in players:
        kname = killer_names.get(ps.entity_id)
        ps.killer_entity_id = name_to_eid.get(kname) if kname else None
        if not ps.is_alive and ps.time_lived_secs is not None:
            deaths.append((
                float(ps.time_lived_secs),
                ps.entity_id,
                ps.killer_entity_id or 0,
                ps.ship_name,
                ps.death_cause or "",
            ))
    deaths.sort(key=lambda x: x[0])

    group = m.get("match_group", "?")
    mode = f"{rb.MATCH_GROUP_CN.get(group, group)}·{m.get('game_mode', '?')}"

    return rb.MatchReport(
        map_name=m.get("map", "?"),
        mode=mode,
        date=(m.get("timestamp") or "?").replace("T", " ").replace("Z", ""),
        duration_played=int(m.get("played_duration") or m.get("max_duration") or 0),
        duration_max=max_dur,
        win_team=win_team,
        win_type=win_type,
        self_team=self_team,
        final_score={int(ts[0]): int(ts[1]) for ts in (m.get("team_scores") or [])},
        self_player_name=self_name,
        players=players,
        deaths=deaths,
    )


def main(json_path: str, out_png: str):
    rb.load_translations()
    report = load_normalized(json_path)
    rb.render(report, out_png)
    print(out_png)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: render_report_normalized.py <normalized.json> <out.png>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
