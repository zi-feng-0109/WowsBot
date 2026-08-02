#!/usr/bin/env python3
"""Recover per-player public battle results from a Lesta (.korablireplay) file.

Lesta replays carry NO server-results packet (0x22) in the packet stream, so the
Rust `battle-results` pipeline reports base XP / planes as absent. But the replay
FILE has a second metadata block (block 1) holding the full battle results —
`playersPublicInfo`, a dict keyed by account id whose value is a flat array of
per-player public fields. The client renders the end-of-battle team scoreboard
(团队战绩: base XP / planes / ships) from exactly this block when you watch a replay.

The array's field→index layout is version-specific and differs from WG's. These
indices were reverse-engineered against ground truth (the in-client scoreboard of
a known Lesta game) AND cross-checked here at runtime: `frag[FRAG]` must equal the
packet-derived kill count. If that check fails (a future Lesta build shifted the
layout), we return {} so the report omits the columns rather than showing wrong
numbers.

    playersPublicInfo[account][*]:
      [0]  account id  (== NormalizedPlayer.db_id)
      [23] planes destroyed (击落飞机)
      [26] ships destroyed (击杀 / frags)   -- used only to self-validate the layout
      [31] base XP (裸经验)

Damage dealt, spotting, potential and total received damage are NOT in the public
array. Damage dealt is already packet-derived (all players); spotting/potential
live only in the self player's `fullDataList` (verified: others' are absent from
the whole file, and the in-client 详细报告 shows only the recorder's detail); the
client's per-player received-damage total (受到伤害量) isn't here either — index 15
looked close but is a subset that doesn't match the client's total, so it's dropped
rather than mislabeled.
"""
import json
import struct

IDX_ACCOUNT = 0
IDX_PLANES = 23
IDX_FRAGS = 26
IDX_BASE_XP = 31
_MIN_LEN = IDX_BASE_XP + 1


def _read_block1(path):
    """Return the parsed JSON of the replay's block 1 (battle results), or None.

    Replay layout: u32 magic, u32 blockCount, then per block [u32 len][bytes];
    block 0 is arena metadata, block 1 is the results JSON."""
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 12:
        return None
    off = 8  # skip magic + blockCount
    ln0 = struct.unpack("<I", data[off:off + 4])[0]
    off += 4 + ln0                      # skip block 0 (metadata)
    if off + 4 > len(data):
        return None
    ln1 = struct.unpack("<I", data[off:off + 4])[0]
    off += 4
    blk = data[off:off + ln1]
    try:
        return json.loads(blk.decode("utf-8"))
    except Exception:
        return None


def extract(replay_path, normalized):
    """{account_id: {'base_xp','planes','frags','received'}} for all players, or {}.

    `normalized` is the parsed normalized report; used only to validate the index
    layout (frags must match packet kills). Returns {} on any parse failure, on a
    non-Lesta replay, or on a failed validation — callers then simply skip the
    extra columns."""
    try:
        block1 = _read_block1(replay_path)
        if not block1:
            return {}
        ppi = block1.get("playersPublicInfo")
        if not isinstance(ppi, dict) or not ppi:
            return {}

        out = {}
        for arr in ppi.values():
            if not isinstance(arr, list) or len(arr) < _MIN_LEN:
                return {}
            acc = arr[IDX_ACCOUNT]
            out[int(acc)] = {
                "base_xp": int(arr[IDX_BASE_XP]),
                "planes": int(arr[IDX_PLANES]),
                "frags": int(arr[IDX_FRAGS]),
            }

        # Self-validation: block-1 frags must equal packet-derived kills. If the
        # layout ever shifts, this diverges and we bail (omit > wrong).
        checked = matched = 0
        for p in normalized.get("players", []):
            db = p.get("db_id")
            if db is None or int(db) not in out:
                continue
            checked += 1
            if out[int(db)]["frags"] == int((p.get("observed_results") or {}).get("kills") or 0):
                matched += 1
        if checked == 0 or matched < checked:
            return {}
        return out
    except Exception:
        return {}


def enrich(normalized, replay_path):
    """Mutate `normalized` in place, adding `lesta_base_xp` / `lesta_planes` to each
    player when the replay carries a valid results block. No-op (leaves the report
    as-is) for WG replays or on any failure."""
    stats = extract(replay_path, normalized)
    if not stats:
        return False
    for p in normalized.get("players", []):
        s = stats.get(int(p["db_id"])) if p.get("db_id") is not None else None
        if not s:
            continue
        p["lesta_base_xp"] = s["base_xp"]
        p["lesta_planes"] = s["planes"]
    return True
