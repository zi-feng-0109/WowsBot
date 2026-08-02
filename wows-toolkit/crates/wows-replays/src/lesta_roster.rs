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

// Field indices within a Lesta roster player record.
const IDX_ACCOUNT: i64 = 0;
const IDX_AVATAR: i64 = 2; // avatar entity id (voiceline sender id space)
const IDX_CLAN: i64 = 7;
const IDX_ACCOUNT_ID: i64 = 13; // accountId — the `onChatMessageRegular` sender id (≠ accountDBID at idx0)
const IDX_NAME: i64 = 28;
const IDX_TEAM_MAP: i64 = 29; // { playerModeType, observedTeamId }
const IDX_SHIP_CONFIG: i64 = 35; // base64-encoded shipConfig blob
const IDX_SHIP_ENTITY: i64 = 36; // the player's ship (vehicle) entity id

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
    let mut i = 0usize;
    while i + 2 < packet_data.len() {
        if packet_data[i] == 0x78 && matches!(packet_data[i + 1], 0x01 | 0x9c | 0xda) {
            if let Some(inflated) = inflate_zlib(&packet_data[i..]) {
                if let Some(roster) = try_decode_roster(&inflated, version) {
                    return roster;
                }
            }
        }
        i += 1;
    }
    Vec::new()
}

fn inflate_zlib(data: &[u8]) -> Option<Vec<u8>> {
    let mut out = Vec::new();
    flate2::read::ZlibDecoder::new(data).read_to_end(&mut out).ok()?;
    if out.len() < 32 { None } else { Some(out) }
}

fn try_decode_roster(inflated: &[u8], version: &Version) -> Option<Vec<RosterEntry>> {
    let root = rmpv::decode::read_value(&mut &inflated[..]).ok()?;
    let players = root.as_array()?;
    if players.len() < 2 {
        return None;
    }
    let mut out = Vec::with_capacity(players.len());
    for p in players {
        let pairs = p.as_array()?;
        let entry = decode_player(pairs, version);
        // Every roster player carries a name; a nameless entry means we matched a
        // different (non-roster) zlib blob — reject the whole candidate.
        if entry.name.is_empty() {
            return None;
        }
        out.push(entry);
    }
    Some(out)
}

fn decode_player(pairs: &[rmpv::Value], version: &Version) -> RosterEntry {
    let mut e = RosterEntry {
        account_id: 0,
        avatar_id: 0,
        chat_account_id: 0,
        ship_entity_id: 0,
        name: String::new(),
        clan: String::new(),
        team_id: 0,
        ship_params_id: None,
    };
    for pair in pairs {
        let Some(kv) = pair.as_array() else { continue };
        if kv.len() != 2 {
            continue;
        }
        let Some(idx) = kv[0].as_i64() else { continue };
        let v = &kv[1];
        match idx {
            IDX_ACCOUNT => e.account_id = v.as_u64().unwrap_or(0) as u32,
            IDX_AVATAR => e.avatar_id = v.as_u64().unwrap_or(0) as u32,
            IDX_ACCOUNT_ID => e.chat_account_id = v.as_u64().unwrap_or(0) as u32,
            IDX_SHIP_ENTITY => e.ship_entity_id = v.as_u64().unwrap_or(0) as u32,
            IDX_NAME => e.name = value_to_string(v),
            IDX_CLAN => e.clan = value_to_string(v),
            IDX_TEAM_MAP => {
                if let Some(map) = v.as_map() {
                    for (k, mv) in map {
                        // map keys are binary utf-8, not str
                        let is_team = k.as_str() == Some("observedTeamId")
                            || matches!(k, rmpv::Value::Binary(b) if b.as_slice() == b"observedTeamId");
                        if is_team {
                            e.team_id = mv.as_i64().unwrap_or(0);
                        }
                    }
                }
            }
            IDX_SHIP_CONFIG => {
                let b64 = value_to_string(v);
                if let Ok(bin) = base64::engine::general_purpose::STANDARD.decode(b64.trim()) {
                    e.ship_params_id = parse_ship_config(&bin, version).ok().map(|c| c.ship_params_id());
                }
            }
            _ => {}
        }
    }
    e
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
