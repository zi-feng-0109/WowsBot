//! Lesta («Мир кораблей») roster extraction.
//!
//! WG replays list the roster in `ReplayMeta.vehicles` and link map entities to
//! players via `onArenaStateReceived`. Lesta omits both and instead ships the full
//! roster (names/clans/teams/ship configs/entity ids for all players) as a nested
//! zlib+msgpack blob near the start of the packet stream. This module decodes it
//! and exposes it two ways:
//!   - [`synthesize_vehicles`] → a WG-style `VehicleInfoMeta` list (for metadata).
//!   - [`extract_lesta_player_states`] → `PlayerStateData` with entity ids (to seed
//!     the entity↔player index the way `onArenaStateReceived` would).
//!
//! Field indices verified against Lesta client build 26.7 (2026-08).

use std::io::Read;

use base64::Engine as _;
use wowsunpack::data::ship_config::parse_ship_config;
use wowsunpack::data::Version;
use wowsunpack::game_types::AccountId;
use wowsunpack::game_types::EntityId;
use wowsunpack::game_types::GameParamId;

use crate::analyzer::decoder::PlayerStateData;
use crate::wowsreplay::VehicleInfoMeta;

// Lesta ships TWO record layouts, keyed by whether the record is a real
// account or an AI (bot). Both appear in the same replay, in SEPARATE zlib+msgpack
// blobs: the human blob (local player + real players) comes first, the bot blob
// (low-tier random / co-op AI, negative account ids) second. A low-tier battle
// can have a 1-entry human blob (you alone among bots), so both layouts and both
// blobs must be decoded and merged. Indices verified against build 26.7 (2026-08).

// HUMAN record layout.
const H_ACCOUNT: i64 = 0;
const H_AVATAR: i64 = 2; // scalar avatar entity id (voiceline sender id space)
const H_CLAN: i64 = 7;
const H_ACCOUNT_ID: i64 = 13; // accountId — the `onChatMessageRegular` sender id (≠ accountDBID at idx0)
const H_NAME: i64 = 28;
const H_TEAM_MAP: i64 = 29; // { playerModeType, observedTeamId }
const H_SHIP_CONFIG: i64 = 35; // base64-encoded shipConfig blob
const H_SHIP_ENTITY: i64 = 36; // the player's ship (vehicle) entity id

// BOT (AI) record layout — different field positions from the human record.
const B_ACCOUNT: i64 = 0; // negative i32 bot id (as_u64 → 0, which is fine: bots share id 0)
const B_AVATAR: i64 = 2; // [avatar entity id, 0]
const B_NAME: i64 = 22;
const B_SHIP_CONFIG: i64 = 25; // base64-encoded shipConfig blob
const B_SHIP_ENTITY: i64 = 26; // the bot's ship (vehicle) entity id
const B_TEAM: i64 = 29; // scalar team id (NOT a map, unlike the human record)

struct RosterEntry {
    account_id: u32,
    avatar_id: u32,
    chat_account_id: u32,
    ship_entity_id: u32,
    name: String,
    clan: String,
    team_id: i64,
    ship_params_id: Option<GameParamId>,
}

/// WG-style `vehicles` roster from the Lesta blob. Empty for WG replays.
pub fn synthesize_vehicles(packet_data: &[u8], player_name: &str, version: &Version) -> Vec<VehicleInfoMeta> {
    let roster = extract_roster(packet_data, version);
    let self_team = roster.iter().find(|e| e.name == player_name).map(|e| e.team_id);
    roster
        .into_iter()
        .filter_map(|e| {
            let ship = e.ship_params_id?;
            let relation = relation_for(&e.name, e.team_id, player_name, self_team);
            Some(VehicleInfoMeta { shipId: ship, relation, id: AccountId::from(e.account_id), name: e.name })
        })
        .collect()
}

/// `PlayerStateData` list with entity ids, mirroring what `onArenaStateReceived`
/// would produce, so the entity↔player index can be seeded. Empty for WG replays.
pub fn extract_lesta_player_states(packet_data: &[u8], version: &Version) -> Vec<PlayerStateData> {
    extract_roster(packet_data, version)
        .into_iter()
        .filter(|e| e.ship_entity_id != 0)
        .map(|e| {
            PlayerStateData::synthetic(
                EntityId::from(e.ship_entity_id),
                AccountId::from(e.account_id),
                e.name,
                e.clan,
                e.team_id,
            )
        })
        .collect()
}

fn relation_for(name: &str, team_id: i64, player_name: &str, self_team: Option<i64>) -> u32 {
    if name == player_name {
        0
    } else {
        match self_team {
            Some(st) if team_id == st => 1,
            Some(_) => 2,
            None if team_id == 0 => 1,
            None => 2,
        }
    }
}

/// `(sender id, username)` pairs for resolving chat/voiceline senders in Lesta
/// replays (which carry no `onArenaStateReceived`, so `ChatLogger` can't build its
/// username map the normal way). A player's name is keyed by BOTH its `accountId`
/// (idx13 — the `onChatMessageRegular` sender) and its avatar entity id (idx2 —
/// the voiceline sender); the two id spaces are disjoint, so one map serves both.
/// Empty for WG replays (no roster blob).
pub fn chat_usernames(packet_data: &[u8], version: &Version) -> Vec<(u32, String)> {
    let mut out = Vec::new();
    for e in extract_roster(packet_data, version) {
        if e.name.is_empty() {
            continue;
        }
        if e.chat_account_id != 0 {
            out.push((e.chat_account_id, e.name.clone()));
        }
        if e.avatar_id != 0 {
            out.push((e.avatar_id, e.name.clone()));
        }
    }
    out
}

/// `(ship entity id, ship GameParams id)` for every roster player whose ship
/// config resolved. Empty for WG replays (no roster blob). Lets callers key
/// in-battle ship entities to their GameParams vehicle — e.g. to reverse-engineer
/// Lesta's consumable id → type table from each ship's own ability slots.
pub fn entity_ship_params(packet_data: &[u8], version: &Version) -> Vec<(EntityId, GameParamId)> {
    extract_roster(packet_data, version)
        .into_iter()
        .filter(|e| e.ship_entity_id != 0)
        .filter_map(|e| e.ship_params_id.map(|s| (EntityId::from(e.ship_entity_id), s)))
        .collect()
}

fn extract_roster(packet_data: &[u8], version: &Version) -> Vec<RosterEntry> {
    // Merge every roster blob found (human blob + bot blob), deduping by ship
    // entity id. Both blobs must be collected: the human blob has self + real
    // players, the bot blob has the AI. Returning only the first (as before)
    // dropped one or the other, and rejecting <2-entry blobs dropped the whole
    // roster in low-tier battles where you are the only human.
    let mut merged: Vec<RosterEntry> = Vec::new();
    let mut seen_ship: std::collections::HashSet<u32> = std::collections::HashSet::new();
    let mut seen_avatar: std::collections::HashSet<u32> = std::collections::HashSet::new();
    let mut i = 0usize;
    while i + 2 < packet_data.len() {
        if packet_data[i] == 0x78 && matches!(packet_data[i + 1], 0x01 | 0x9c | 0xda) {
            if let Some(inflated) = inflate_zlib(&packet_data[i..]) {
                if let Some(roster) = try_decode_roster(&inflated, version) {
                    for e in roster {
                        // Dedup: the same roster can be recompressed at several
                        // offsets; keep the first sighting of each ship/avatar.
                        if e.ship_entity_id != 0 && !seen_ship.insert(e.ship_entity_id) {
                            continue;
                        }
                        if e.ship_entity_id == 0 && e.avatar_id != 0 && !seen_avatar.insert(e.avatar_id) {
                            continue;
                        }
                        merged.push(e);
                    }
                }
            }
        }
        i += 1;
    }
    merged
}

fn inflate_zlib(data: &[u8]) -> Option<Vec<u8>> {
    let mut out = Vec::new();
    flate2::read::ZlibDecoder::new(data).read_to_end(&mut out).ok()?;
    if out.len() < 32 { None } else { Some(out) }
}

fn try_decode_roster(inflated: &[u8], version: &Version) -> Option<Vec<RosterEntry>> {
    let root = rmpv::decode::read_value(&mut &inflated[..]).ok()?;
    let players = root.as_array()?;
    // A roster blob can have a single entry (low-tier battle where you are the
    // only human), so >=1. Emptiness or any nameless entry means this is a
    // different (non-roster) zlib blob — reject the whole candidate.
    if players.is_empty() {
        return None;
    }
    let mut out = Vec::with_capacity(players.len());
    for p in players {
        let pairs = p.as_array()?;
        let entry = decode_player(pairs, version);
        if entry.name.is_empty() {
            return None;
        }
        out.push(entry);
    }
    Some(out)
}

fn decode_player(pairs: &[rmpv::Value], version: &Version) -> RosterEntry {
    // Index -> value map for random access (fields aren't in a fixed order and
    // the two layouts share some indices with different meanings).
    let mut m: std::collections::HashMap<i64, &rmpv::Value> = std::collections::HashMap::new();
    for pair in pairs {
        let Some(kv) = pair.as_array() else { continue };
        if kv.len() != 2 {
            continue;
        }
        if let Some(idx) = kv[0].as_i64() {
            m.insert(idx, &kv[1]);
        }
    }

    let text = |idx: i64| -> String { m.get(&idx).map(|v| value_to_string(v)).unwrap_or_default() };
    // Account/entity ids: bots store a NEGATIVE i32 account id, so read signed and
    // wrap to u32. `as_u64` alone returns 0 for negatives, collapsing every bot to
    // account 0 — which then collides on metadata lookup (all bots inherit one
    // player's relation, marking allied bots as enemies). The low 32 bits are the
    // stable per-bot id both the roster (meta) and player-state sides agree on.
    let u32_at = |idx: i64| -> u32 {
        match m.get(&idx) {
            Some(v) => v.as_u64().map(|x| x as u32).or_else(|| v.as_i64().map(|x| x as u32)).unwrap_or(0),
            None => 0,
        }
    };
    // Avatar can be a scalar (human) or `[avatar_id, 0]` (bot).
    let avatar_at = |idx: i64| -> u32 {
        match m.get(&idx) {
            Some(rmpv::Value::Array(a)) => a.first().and_then(|v| v.as_u64()).unwrap_or(0) as u32,
            Some(v) => v.as_u64().unwrap_or(0) as u32,
            None => 0,
        }
    };
    let ship_params = |idx: i64| -> Option<GameParamId> {
        let b64 = text(idx);
        let bin = base64::engine::general_purpose::STANDARD.decode(b64.trim()).ok()?;
        parse_ship_config(&bin, version).ok().map(|c| c.ship_params_id())
    };

    // A human record carries its name at H_NAME; a bot at B_NAME. Pick the layout
    // by which one holds a non-empty string.
    let human_name = text(H_NAME);
    if !human_name.is_empty() {
        let mut team_id = 0i64;
        if let Some(v) = m.get(&H_TEAM_MAP) {
            if let Some(map) = v.as_map() {
                for (k, mv) in map {
                    // map keys are binary utf-8, not str
                    let is_team = k.as_str() == Some("observedTeamId")
                        || matches!(k, rmpv::Value::Binary(b) if b.as_slice() == b"observedTeamId");
                    if is_team {
                        team_id = mv.as_i64().unwrap_or(0);
                    }
                }
            }
        }
        RosterEntry {
            account_id: u32_at(H_ACCOUNT),
            avatar_id: avatar_at(H_AVATAR),
            chat_account_id: u32_at(H_ACCOUNT_ID),
            ship_entity_id: u32_at(H_SHIP_ENTITY),
            name: human_name,
            clan: text(H_CLAN),
            team_id,
            ship_params_id: ship_params(H_SHIP_CONFIG),
        }
    } else {
        RosterEntry {
            account_id: u32_at(B_ACCOUNT),
            avatar_id: avatar_at(B_AVATAR),
            chat_account_id: 0, // bots never chat
            ship_entity_id: u32_at(B_SHIP_ENTITY),
            name: text(B_NAME),
            clan: String::new(),
            team_id: m.get(&B_TEAM).and_then(|v| v.as_i64()).unwrap_or(0),
            ship_params_id: ship_params(B_SHIP_CONFIG),
        }
    }
}

fn value_to_string(v: &rmpv::Value) -> String {
    if let Some(s) = v.as_str() {
        return s.to_string();
    }
    if let rmpv::Value::Binary(b) = v {
        return String::from_utf8_lossy(b).into_owned();
    }
    String::new()
}
