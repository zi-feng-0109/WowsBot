use std::sync::LazyLock;

#[cfg(feature = "parsing")]
use std::borrow::Cow;
pub use wowsunpack::game_constants::BattleConstants;
pub use wowsunpack::game_constants::ChannelConstants;
pub use wowsunpack::game_constants::CommonConstants;
pub use wowsunpack::game_constants::ShipsConstants;
pub use wowsunpack::game_constants::WeaponsConstants;
#[cfg(feature = "vfs")]
use wowsunpack::vfs::VfsPath;

pub static DEFAULT_GAME_CONSTANTS: LazyLock<GameConstants> = LazyLock::new(GameConstants::defaults);

/// Composed game constants that knows which sub-constants are needed.
#[derive(Clone)]
pub struct GameConstants {
    battle: BattleConstants,
    ships: ShipsConstants,
    weapons: WeaponsConstants,
    common: CommonConstants,
    channel: ChannelConstants,
}

impl GameConstants {
    /// Load all constants from game files via VFS.
    #[cfg(feature = "vfs")]
    pub fn from_vfs(vfs: &VfsPath) -> Self {
        use wowsunpack::game_constants::load_battle_constants;
        use wowsunpack::game_constants::load_channel_constants;
        use wowsunpack::game_constants::load_common_constants;
        use wowsunpack::game_constants::load_ships_constants;
        use wowsunpack::game_constants::load_weapons_constants;
        Self {
            battle: load_battle_constants(vfs),
            ships: load_ships_constants(vfs),
            weapons: load_weapons_constants(vfs),
            common: load_common_constants(vfs),
            channel: load_channel_constants(vfs),
        }
    }

    /// Hardcoded defaults (no game files needed).
    pub fn defaults() -> Self {
        Self {
            battle: BattleConstants::defaults(),
            ships: ShipsConstants::defaults(),
            weapons: WeaponsConstants::defaults(),
            common: CommonConstants::defaults(),
            channel: ChannelConstants::defaults(),
        }
    }

    pub fn battle(&self) -> &BattleConstants {
        &self.battle
    }

    pub fn ships(&self) -> &ShipsConstants {
        &self.ships
    }

    pub fn weapons(&self) -> &WeaponsConstants {
        &self.weapons
    }

    pub fn common(&self) -> &CommonConstants {
        &self.common
    }

    pub fn channel(&self) -> &ChannelConstants {
        &self.channel
    }

    pub fn game_mode_name(&self, id: i32) -> Option<&str> {
        self.battle.game_mode(id)
    }

    pub fn death_reason_name(&self, id: i32) -> Option<&str> {
        self.battle.death_reason(id)
    }

    pub fn camera_mode_name(&self, id: i32) -> Option<&str> {
        self.battle.camera_mode(id)
    }

    pub fn battle_mut(&mut self) -> &mut BattleConstants {
        &mut self.battle
    }

    pub fn ships_mut(&mut self) -> &mut ShipsConstants {
        &mut self.ships
    }

    pub fn weapons_mut(&mut self) -> &mut WeaponsConstants {
        &mut self.weapons
    }

    pub fn common_mut(&mut self) -> &mut CommonConstants {
        &mut self.common
    }

    pub fn channel_mut(&mut self) -> &mut ChannelConstants {
        &mut self.channel
    }

    /// Merge replay constants JSON (from wows-constants repo) into this instance.
    ///
    /// Overrides `CONSUMABLE_IDS` and `BATTLE_STAGES` mappings from the JSON data.
    /// The `version` is forwarded to version-aware battle stage parsing.
    #[cfg(feature = "parsing")]
    pub fn merge_replay_constants(&mut self, replay_constants: &serde_json::Value, version: wowsunpack::data::Version) {
        if let Some(consumable_ids) = replay_constants.pointer("/CONSUMABLE_IDS").and_then(|ids| ids.as_object()) {
            let types = self.common.consumable_types_mut();
            for (key, value) in consumable_ids {
                if let Some(id) = value.as_i64() {
                    types.insert(id as i32, Cow::Owned(key.clone()));
                }
            }
        }
        if let Some(battle_stages) = replay_constants.pointer("/BATTLE_STAGES").and_then(|s| s.as_object()) {
            let stages = self.common.battle_stages_mut();
            for (key, value) in battle_stages {
                if let Some(id) = value.as_i64()
                    && let Some(stage) = wowsunpack::game_types::BattleStage::from_name(key, version).into_known()
                {
                    stages.insert(id as i32, stage);
                }
            }
        }
    }

    /// Lesta («Мир кораблей») reassigned `DamageStatCategory` ids relative to WG:
    /// its SPOT (spotting) and AGRO (potential) totals land on the opposite ids, so
    /// with WG's default table the report shows potential-as-spotting and vice
    /// versa. Detect a Lesta replay by its roster blob and swap the two labels so
    /// `DamageStatCategory::from_id` resolves them correctly. No-op for WG replays.
    #[cfg(feature = "parsing")]
    pub fn apply_lesta_fixups(&mut self, packet_data: &[u8], version: wowsunpack::data::Version) {
        if crate::lesta_roster::entity_ship_params(packet_data, &version).is_empty() {
            return; // WG replay — leave the default table untouched.
        }
        let cats = self.battle.damage_stat_categories_mut();
        let spot = cats.iter().find(|(_, v)| v.as_ref() == "SPOT").map(|(k, _)| *k);
        let agro = cats.iter().find(|(_, v)| v.as_ref() == "AGRO").map(|(k, _)| *k);
        if let (Some(s), Some(a)) = (spot, agro) {
            cats.insert(s, Cow::Borrowed("AGRO"));
            cats.insert(a, Cow::Borrowed("SPOT"));
        }

        // Lesta's client XML reorders the DEATH_REASON_NAME enum around the shell
        // causes (AP/HE/CS/FEL, ids 17–20), so parsing it positionally shifts those
        // ids by one: an AP-shell death decodes as HE, HE as CS, CS as FEL. The
        // replay packets still use WG's death-id numbering (the protocol is shared),
        // so the WG default table is the correct decoder — verified against killer
        // ship types (DD→HE, 意大利巡洋→SAP/CS, BB→AP). Restore the default table;
        // non-shell causes already match, so only the shell region actually changes.
        let default_deaths = DEFAULT_GAME_CONSTANTS.battle().death_reasons().clone();
        *self.battle.death_reasons_mut() = default_deaths;
    }
}
