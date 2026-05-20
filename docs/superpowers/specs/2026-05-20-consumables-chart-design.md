# 双方消耗品使用记录图 — 设计

日期: 2026-05-20
状态: 待审

## 目标

从 replayshark 输出的战报 JSON 渲染单张 PNG，展示一局 12v12 双方全员的**所有消耗品 slot** 的实际使用次数与总充能数。用于复盘"谁带了却不开""谁打满""谁损管疯狂吃"等战术行为。

非目标:
- 不做精细时间轴可视化（开了几次 + 总数即可）
- 不做战术评价 / 评分（这是数据可视化，不是战犯判定）
- 不替代现有 `render_criminals.py`（那是负面榜单，本图是中性全员表）

## 输入

`<battle.json>` — `replayshark battle-report` 的输出。需要的字段:

- `players[]`: `team_id`, `vehicle_entity_id`, `relation`, `name`, `ship.{index, name, level, species, consumable_slots}`
- `consumable_uses[]`: `{user_entity_id, consumable_name, time_secs}`

**新增依赖**: `players[].ship.consumable_slots` 的 schema 需扩展以包含每个 ability 的 `num_consumables`（详见 §"Rust 端改动"）。

## 输出

`<out.png>`，宽度 2200px（与现有 `render_battle_report` 对齐，便于潜在拼接）。

## 布局

```
┌────────────────────────────────────────────────────────────────────────────┐
│  红方（敌方）                                                              │
│ ┌────────────────────────────────────────────────────────────────────────┐│
│ │ 岛风   L10 驱逐  UncleBigBadBill │ 烟 2/4 损管 5/∞ 引擎增压 3/3 ...   ││
│ │ ...（DD 全部先列 → CA → BB → CV → SS）                                ││
│ └────────────────────────────────────────────────────────────────────────┘│
│                                                                            │
│  绿方（友方）                                                              │
│ ┌────────────────────────────────────────────────────────────────────────┐│
│ │ ...                                                                     ││
│ └────────────────────────────────────────────────────────────────────────┘│
└────────────────────────────────────────────────────────────────────────────┘
```

- **垂直布局**: 上半屏红方，下半屏绿方
- **主视角判断**: 用 `players[].relation` (0=self, 1=ally, 2=enemy)。relation∈{0,1} 的 team_id 即"友方"，另一边即"敌方"
- **行排序**: 按船种分组 DD(Destroyer) → CA/CL(Cruiser，JSON 中统一为 Cruiser) → BB(Battleship) → CV(AirCarrier) → SS(Submarine)，组内按 player name 字母序
- **每行**: 左侧船名 + 等级 + 船种 + 玩家名（与 `_ship_label` 风格一致）；右侧水平排列所有 slot 单元

## 每个 slot 单元

```
┌──────────────────┐
│ 维修小组 III      │   ← 消耗品中文名 (consumable_display 查 .mo)
│      3/4         │   ← used/total，浅色字
└──────────────────┘   ← 整个 cell 背景色按色码规则
```

**色码规则**（具体色值复用 `render_battle_report.py` 的 GAME_RED / GAME_GOLD / GAME_GREEN / GAME_PANEL 常量，下方仅为语义示意）:

| 条件 | 语义色 | 说明 |
|---|---|---|
| `total != ∞` 且 `used == 0` | 红（GAME_RED 调暗） | 带了完全没开，强烈警告 |
| `total != ∞` 且 `0 < used/total < 0.5` | 黄（GAME_GOLD 调暗） | 用了一部分 |
| `total != ∞` 且 `0.5 ≤ used/total < 1.0` | 浅绿 | 用了一大半 |
| `total != ∞` 且 `used == total` | 深绿（GAME_GREEN 调暗） | 点满 |
| `total == ∞`（损管/抢救小队） | 中性灰（GAME_PANEL_ALT） | 不参与"没开"判定，仅显示 `used/∞` |

**无限次冷却消耗品**: 通过 `num_consumables = -1` 标记（GameParams 中 `numConsumables=-1` 即无限次）。显示 `used/∞`，色块永远中性。

**CV 飞机消耗品**: 飞机上的 ForsageBooster / ActiveManeuvering / PlaneSmokeGenerator / PlaneTacticalFighters 等通过 `Aircraft.abilities` 链下游获取，与船本身的 slot 并列在同一行。CV 行会比其他船种长 30-50%，整张图宽度按最长行扩展。

**单 slot 多备选**: replayshark 当前每个 slot 通常只有 1 个 ability_name（玩家已选择）。若出现多个（旧/边缘情况），用 `/` 连接所有名字，`num_consumables` 取首项。

## 数据流

1. **Rust 改动** — `crates/replayshark/src/main.rs::run_battle_report`:
   - `consumable_slots` schema 从 `Vec<Vec<String>>` 改为 `Vec<Vec<AbilityRef>>`，其中 `AbilityRef = {ability_name: String, num_consumables: i64}`
   - 查表通过 `GameMetadataProvider` 的 `provider().param_by_name(ability_name)` → `ParamData::Ability` → 第一个 `AbilityCategory.num_consumables()`
   - `cargo build --release -p replayshark` 重新编译

2. **Python 兼容** — `render_criminals.py::strong_consumable_slots`:
   - 接受新 schema：slot 内每项可能是 `str`（旧）或 `dict`（新）。统一抽 `ability_name`
   - 现有 criminal 检测逻辑不变（只需要 ability_name）

3. **新脚本** — `report/bin/render_consumables_chart.py`:
   - 入口: `render_consumables_chart.py <battle.json> <out.png>`
   - 复用 `render_battle_report` 的 font / 颜色常量 + `consumable_display` helper
   - 按 §"每个 slot 单元" 规则渲染
   - 退出码: 0 = 成功; 2 = 参数错误; 3 = JSON 缺字段（新 schema 未生效）

## CLI 集成

**不**默认拼进 `wows_full_report`。独立调用:

```bash
python bin/render_consumables_chart.py <battle.json> <out.png>
```

`wows_full_report` 本次**不**修改。后续若有需求再单独评估是否加 env var 开关。

## 验证

跑测试 replay (`_test_out/pobeda.json`)，检查:

- [ ] 双方共 24 船全部出现
- [ ] 各船 slot 总数与 wiki 上 T10 船数据对得上（如 Moskva 烟 4 次、Pobeda 维修小组 4 次）
- [ ] 损管/抢救小队显示 `N/∞` 中性色
- [ ] CV 行包含飞机消耗品
- [ ] 排序 DD→CA→BB→CV→SS 在两边都正确
- [ ] 至少一个 0/N 红色 cell 实际对应已知"带了没开"的玩家
- [ ] 现有 `render_criminals.py` 仍正常出图（向后兼容验证）

## 失败模式与回滚

- **Rust 改动破坏现有 render_criminals.py / render_battle_report.py**: 在 Python 解析处加 `if isinstance(slot_item, dict): name = slot_item['ability_name'] else: name = slot_item`，向后兼容
- **某些 ability 在 GameParams 里查不到**（边缘情况，比如打了一半的事件 ability）: Rust 端 `num_consumables` 输出 `null`，Python 端 `null → "?"` 显示
- **WG 版本更新导致 GameParams 解析失败**: replayshark 已有错误，与本次设计正交

## 不在范围内

- 时间轴可视化（开了几次 + 总数足够）
- 消耗品 cooldown / preparation_time 信息
- 不同 variant 的细节（Premium vs Standard 用 ability_name 后缀已隐含）
- 自动判断"该开没开"的策略评价（这归 `render_criminals.py`）
