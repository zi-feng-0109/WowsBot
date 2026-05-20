# 双方消耗品使用记录图 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 渲染一张 PNG，展示 12v12 双方全员每个消耗品 slot 的 `used/total` 与使用率色码，独立脚本 `render_consumables_chart.py`。

**Architecture:** Rust 侧扩展 `replayshark battle-report` 的 `consumable_slots` schema，把 `num_consumables` 从 `GameParams` 查出来塞进 JSON；Python 侧加一个新渲染脚本，按船种分组，每行水平铺 slot cell。

**Tech Stack:** Rust (wowsunpack + replayshark) for data extraction, Python (PIL/Pillow) for rendering. 两个 git 仓库——Rust 在 `C:\Users\29801\Desktop\minimap\wows-toolkit`，Python 在 `C:\Users\29801\Desktop\wows-bot-review`。

**Test replay (golden):** `C:\Users\29801\Desktop\Steam\steamapps\common\World of Warships\replays\20260517_205434_PRSA108-Pobeda_19_OC_prey.wowsreplay`

**关键路径变量** (适用全计划):

```bash
WOWS_TOOLKIT=/c/Users/29801/Desktop/minimap/wows-toolkit
WOWS_BOT=/c/Users/29801/Desktop/wows-bot-review
SPECS=$WOWS_BOT/report/specs
REPLAY="/c/Users/29801/Desktop/Steam/steamapps/common/World of Warships/replays/20260517_205434_PRSA108-Pobeda_19_OC_prey.wowsreplay"
TEST_OUT=$WOWS_BOT/_test_out
REPLAYSHARK=$WOWS_TOOLKIT/target/release/replayshark.exe
export WOWS_CJK_FONT="C:/Windows/Fonts/msyh.ttc"
```

---

## File Structure

**新增 (Python):**
- `report/bin/render_consumables_chart.py` — 主渲染脚本，~250 行

**修改 (Rust, wows-toolkit 仓):**
- `crates/wowsunpack/src/game_params/types.rs` — 给 `AbilityCategory` 加 `num_consumables()` accessor (~5 行)
- `crates/replayshark/src/main.rs` — `run_battle_report` 输出 schema 改成 `Vec<Vec<{ability_name, num_consumables}>>` (~30 行)

**修改 (Python, wows-bot-review 仓):**
- `report/bin/render_criminals.py` — `strong_consumable_slots()` 兼容新 schema (~10 行)

---

## Task 1: Rust 侧 — 加 `num_consumables()` accessor + 扩展 battle-report schema

**Files:**
- Modify: `C:\Users\29801\Desktop\minimap\wows-toolkit\crates\wowsunpack\src\game_params\types.rs:1442-1460` (在 `impl AbilityCategory` 块中加方法)
- Modify: `C:\Users\29801\Desktop\minimap\wows-toolkit\crates\replayshark\src\main.rs:916-963` (`run_battle_report` 中 vehicle consumable_slots 构造逻辑)

- [ ] **Step 1.1: 在 `AbilityCategory` 加 `num_consumables()` accessor**

打开 `crates/wowsunpack/src/game_params/types.rs`，在 `impl AbilityCategory` 块（约第 1442 行开始）中，紧跟 `pub fn icon_id()` 后面插入：

```rust
    pub fn num_consumables(&self) -> isize {
        self.num_consumables
    }
```

- [ ] **Step 1.2: 改 `run_battle_report` 的 consumable_slots 构造**

在 `crates/replayshark/src/main.rs` 约 931-960 行，把 `Vec<Vec<String>>` 改为 `Vec<Vec<serde_json::Value>>`，每个 entry 是 `{"ability_name": ..., "num_consumables": ...}`。完整替换块（原行 931-960）：

```rust
                let mut consumable_slots: Vec<Vec<serde_json::Value>> = Vec::new();
                if let Some(slots) = v.abilities() {
                    for slot in slots {
                        if slot.is_empty() {
                            continue;
                        }
                        let alternatives: Vec<serde_json::Value> = slot.iter()
                            .map(|(ab_name, _variant)| {
                                let num = lookup_num_consumables(&provider, ab_name);
                                serde_json::json!({
                                    "ability_name": ab_name,
                                    "num_consumables": num,
                                })
                            })
                            .collect();
                        consumable_slots.push(alternatives);
                    }
                }
                // CV: 把每个挂载飞机的 PlaneAbilities 也并入 slot 列表(去重),
                // 这样 Python 端检测时能识别"巡逻战斗机/引擎冷却带了但 0 次使用"。
                use wowsunpack::game_params::types::GameParamProvider as GPP;
                for plane_idx in v.plane_refs() {
                    let Some(plane_param) = GPP::game_param_by_name(&provider, plane_idx) else { continue };
                    let ParamData::Aircraft(plane) = plane_param.data() else { continue };
                    let Some(plane_slots) = plane.abilities() else { continue };
                    for slot in plane_slots {
                        if slot.is_empty() { continue; }
                        let alternatives: Vec<serde_json::Value> = slot.iter()
                            .map(|(ab_name, _variant)| {
                                let num = lookup_num_consumables(&provider, ab_name);
                                serde_json::json!({
                                    "ability_name": ab_name,
                                    "num_consumables": num,
                                })
                            })
                            .collect();
                        // 去重: 按 ability_names 集合比较
                        let names: Vec<&str> = alternatives.iter()
                            .filter_map(|v| v.get("ability_name").and_then(|x| x.as_str()))
                            .collect();
                        let already = consumable_slots.iter().any(|s| {
                            let existing: Vec<&str> = s.iter()
                                .filter_map(|v| v.get("ability_name").and_then(|x| x.as_str()))
                                .collect();
                            existing == names
                        });
                        if !already {
                            consumable_slots.push(alternatives);
                        }
                    }
                }
                (v.level() as i64, species.unwrap_or_else(|| "?".to_string()), consumable_slots)
            }
            _ => (0i64, "?".to_string(), Vec::<Vec<serde_json::Value>>::new()),
```

- [ ] **Step 1.3: 加 `lookup_num_consumables` helper 函数**

在 `crates/replayshark/src/main.rs` 文件最末（在 `main()` 函数之外、`fn run_consumables_dump` 之前或之后），加：

```rust
fn lookup_num_consumables(
    provider: &wowsunpack::game_params::provider::GameMetadataProvider,
    ability_name: &str,
) -> serde_json::Value {
    use wowsunpack::game_params::types::{GameParamProvider, ParamData};
    // 与文件其他地方一致, 用 trait 的 qualified syntax 调用
    let Some(param) = GameParamProvider::game_param_by_name(provider, ability_name) else {
        return serde_json::Value::Null;
    };
    let ParamData::Ability(ab) = param.data() else {
        return serde_json::Value::Null;
    };
    // 取第一个 category 的 num_consumables (同一 ability 所有 category 通常相同)
    // categories() 返回 &HashMap<String, AbilityCategory>, 用 iter().next() 取任意一项
    let Some((_variant_name, cat)) = ab.categories().iter().next() else {
        return serde_json::Value::Null;
    };
    serde_json::json!(cat.num_consumables() as i64)
}
```

- [ ] **Step 1.4: 编译**

```bash
cd $WOWS_TOOLKIT
cargo build --release -p replayshark 2>&1 | tail -20
```

Expected: `Finished release [optimized] target(s) in X.YZs`（exit 0）。如果报"method not found"或"trait not in scope"，按编译器提示加 `use` 即可。

- [ ] **Step 1.5: Smoke test — 用新二进制跑一次 battle-report**

```bash
cd $WOWS_TOOLKIT
mkdir -p $TEST_OUT
$REPLAYSHARK battle-report \
    --extracted $SPECS \
    "$REPLAY" \
    --output $TEST_OUT/pobeda.json
```

Expected: 退出 0，文件大小 >100KB。

- [ ] **Step 1.6: 验证新 schema**

```bash
python -c "
import json
data = json.load(open(r'$TEST_OUT/pobeda.json', encoding='utf-8'))
p0 = data['players'][0]
slots = p0['ship']['consumable_slots']
print('first ship:', p0['ship'].get('index'))
print('first slot first ability:', slots[0][0] if slots and slots[0] else 'empty')
assert isinstance(slots[0][0], dict), f'expected dict, got {type(slots[0][0])}'
assert 'ability_name' in slots[0][0]
assert 'num_consumables' in slots[0][0]
print('OK: schema is {ability_name, num_consumables}')
print('sample num:', slots[0][0]['num_consumables'])
"
```

Expected: `OK: schema is {ability_name, num_consumables}` + 一个整数（>0 = 有限次, -1 = 无限次, null = 查不到）。

- [ ] **Step 1.7: 提交 Rust 改动**

```bash
cd $WOWS_TOOLKIT
git add crates/wowsunpack/src/game_params/types.rs crates/replayshark/src/main.rs
git commit -m "feat(replayshark): consumable_slots 附带 num_consumables (供 Python 渲染消耗品图)

- AbilityCategory 加 num_consumables() accessor
- run_battle_report 输出 schema: Vec<Vec<{ability_name, num_consumables}>>
- 通过 GameMetadataProvider 查表, ability 找不到时输出 null"
```

---

## Task 2: Python — `render_criminals.py` 兼容新 schema + 回归验证

**Files:**
- Modify: `C:\Users\29801\Desktop\wows-bot-review\report\bin\render_criminals.py:180-200` (`strong_consumable_slots` 函数)

- [ ] **Step 2.1: 改 `strong_consumable_slots` 兼容 dict / str**

打开 `report/bin/render_criminals.py`，找到 `def strong_consumable_slots(consumable_slots):` (约 180 行)。把 `for ab_name in slot:` 这一行的循环体改为兼容：

替换原代码（约 187-189 行）:

```python
    for slot in consumable_slots or []:
        slot_displays = []
        slot_enums = []
        for ab_name in slot:
```

为:

```python
    for slot in consumable_slots or []:
        slot_displays = []
        slot_enums = []
        for entry in slot:
            # 兼容新 schema (dict) 和旧 schema (str)
            if isinstance(entry, dict):
                ab_name = entry.get("ability_name", "")
            else:
                ab_name = entry
            if not ab_name:
                continue
```

- [ ] **Step 2.2: 回归测试 — 跑一遍 criminals 渲染**

```bash
cd $WOWS_BOT
py report/bin/render_criminals.py $TEST_OUT/pobeda.json $TEST_OUT/pobeda.criminals.png
```

Expected: 退出 0（有战犯）或 3（无战犯）。如果是 0，输出文件应存在。**绝对不能**报 `'str' object has no attribute 'get'` 之类的类型错误。

- [ ] **Step 2.3: 用既有的 moskva 测试样本再验一遍向后兼容**

`moskva.json` 是用**旧版** replayshark 生成的（slot 内是字符串）。新 Python 代码必须仍能处理：

```bash
cd $WOWS_BOT
py report/bin/render_criminals.py $TEST_OUT/moskva.json $TEST_OUT/moskva.criminals.png
```

Expected: 退出 0 或 3，无类型错误。这是验证 isinstance 兜底真的生效。

- [ ] **Step 2.4: 提交 Python compat**

```bash
cd $WOWS_BOT
git add report/bin/render_criminals.py
git commit -m "fix(criminals): consumable_slots 兼容新旧 schema (dict 含 num_consumables / 旧版 str)

为下一步的 render_consumables_chart.py 准备 num_consumables 字段,
旧版 JSON 仍正常解析。"
```

---

## Task 3: 新建 `render_consumables_chart.py` — 数据加载 + 排序

**Files:**
- Create: `C:\Users\29801\Desktop\wows-bot-review\report\bin\render_consumables_chart.py`

- [ ] **Step 3.1: 写脚本骨架 + 数据收集**

创建 `report/bin/render_consumables_chart.py`，内容如下（这一步**不**渲染图，仅打印数据结构验证逻辑）:

```python
"""render_consumables_chart.py — 双方消耗品使用记录图。

用法:
    render_consumables_chart.py <battle.json> <out.png>

设计文档: docs/superpowers/specs/2026-05-20-consumables-chart-design.md
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_battle_report import (  # noqa: E402
    t, load_translations, strip_known, strip_id, clean_ship_name,
    CJK_FONT, MONO_FONT, GAME_BG, GAME_PANEL, GAME_PANEL_ALT, GAME_GREEN,
    GAME_RED, GAME_GOLD, GAME_TEXT, GAME_DIM, GAME_BORDER,
)
from render_criminals import consumable_display  # noqa: E402
from PIL import Image, ImageDraw, ImageFont


# 船种排序顺序 (DD 先, SS 最后)
SPECIES_ORDER = ["Destroyer", "Cruiser", "Battleship", "AirCarrier", "Submarine"]
SPECIES_CN = {
    "Destroyer": "驱逐",
    "Cruiser": "巡洋",
    "Battleship": "战列",
    "AirCarrier": "航母",
    "Submarine": "潜艇",
}


def species_sort_key(p):
    sp = strip_known((p.get("ship") or {}).get("species") or "")
    try:
        idx = SPECIES_ORDER.index(sp)
    except ValueError:
        idx = len(SPECIES_ORDER)
    return (idx, (p.get("name") or "").lower())


def ability_name_of(slot_entry):
    """新 schema (dict) 或旧 schema (str) 统一抽 ability_name。"""
    if isinstance(slot_entry, dict):
        return slot_entry.get("ability_name", "")
    return slot_entry or ""


def num_consumables_of(slot_entry):
    """新 schema 拿 num_consumables, 旧 schema 返回 None (未知)。"""
    if isinstance(slot_entry, dict):
        return slot_entry.get("num_consumables")
    return None


def collect_slot_info(slot):
    """对一个 slot (可能多备选), 返回 (display_name_str, total, ability_names_list)。
    多备选用 '/' 连接 display, total 取首项。"""
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


def build_consumable_enum_to_keyword():
    """从 render_criminals.STRONG_CONSUMABLES 反向: enum_name → keyword。
    用于 consumable_uses (consumable_name=enum) 反查匹配 ability_name (含 keyword)。"""
    from render_criminals import STRONG_CONSUMABLES
    out = {}
    for keyword, enum_name in STRONG_CONSUMABLES:
        out.setdefault(enum_name, []).append(keyword)
    return out


def count_uses_for_ability(consumable_uses, user_eid, ability_name):
    """同 render_criminals.count_consumable_uses 的精神, 但按 ability_name 匹配。
    consumable_uses 里只记 enum (SpeedBoost / Smoke 等), 不记 ability_name,
    所以要用 STRONG_CONSUMABLES 的 (keyword, enum) 反向匹配:
    ability_name 含 keyword K → 找 enum E, 然后数 user 触发 E 的次数。"""
    from render_criminals import STRONG_CONSUMABLES
    target_enum = None
    for keyword, enum_name in STRONG_CONSUMABLES:
        if keyword in ability_name:
            target_enum = enum_name
            break
    if target_enum is None:
        # 不在 STRONG 表里 (如 CrashCrew / RepairParty / RegenCrew), 直接按 ability_name 关键字
        # 兜底: 这些 enum 名一般等于 ability_name 的中段
        # 简单策略: 在 consumable_uses 里找跟 ability_name 共享子串的 enum
        return 0  # 占位, Step 3.2 用更鲁棒的方法补
    return sum(
        1 for u in consumable_uses
        if strip_id(u.get("user_entity_id") or "") == user_eid
        and u.get("consumable_name") == target_enum
    )


def main():
    if len(sys.argv) < 3:
        print("usage: render_consumables_chart.py <battle.json> <out.png>", file=sys.stderr)
        sys.exit(2)
    json_path = sys.argv[1]
    out_path = sys.argv[2]

    load_translations()
    raw = json.load(open(json_path, encoding="utf-8"))

    # 检查 schema
    p0 = raw["players"][0]
    slots = (p0.get("ship") or {}).get("consumable_slots") or []
    if slots and not isinstance(slots[0][0] if slots[0] else None, dict):
        print("WARNING: 旧 schema, num_consumables 不可用, 总数将显示为 '?'", file=sys.stderr)

    # 主视角 → 友方 team_id
    self_team = None
    for p in raw.get("players", []):
        if p.get("relation") in (0, 1):
            self_team = p.get("team_id")
            break
    if self_team is None:
        self_team = 0  # 兜底

    # 双方分组
    teams = {0: [], 1: []}
    for p in raw.get("players", []):
        tid = p.get("team_id")
        if tid in teams:
            teams[tid].append(p)
    for tid in teams:
        teams[tid].sort(key=species_sort_key)

    # 打印数据结构(本步骤不渲染图)
    for tid in (1 - self_team, self_team):  # 敌方先, 友方后
        label = "敌方" if tid != self_team else "友方"
        print(f"=== team {tid} ({label}) ===")
        for p in teams[tid]:
            ship = p.get("ship") or {}
            print(f"  {p.get('name')} - {clean_ship_name(ship.get('name', ''))} ({strip_known(ship.get('species', ''))})")
            for slot in ship.get("consumable_slots") or []:
                disp, total, names = collect_slot_info(slot)
                print(f"    {disp} total={total} abilities={names}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3.2: 跑一次, 验证结构**

```bash
cd $WOWS_BOT
py report/bin/render_consumables_chart.py $TEST_OUT/pobeda.json /tmp/dummy.png 2>&1 | head -40
```

Expected: 输出按队分组、按船种排序的玩家+船+slot 列表，每个 slot 有显示名 + total (整数或 -1)。如果第一行就是 WARNING，说明 Task 1 没生效，回去检查。

- [ ] **Step 3.3: 把 use_count 算对**

`count_uses_for_ability` 当前用了 STRONG_CONSUMABLES 反查 enum——这只覆盖 8 类强相关消耗品。完整方案是建立 ability_name keyword → enum 的全表。把以下常量加到 `render_consumables_chart.py` 顶部 (在 import 之后):

```python
# ability_name 关键字 → consumable_uses 中的 enum 名 (覆盖所有常见 slot 类型,
# 不只是 STRONG_CONSUMABLES)。如果 ability_name 不含任何关键字, use 数显示 0。
ABILITY_KEYWORD_TO_ENUM = [
    ("RLSSearch",             "Radar"),
    ("SonarSearch",           "HydroacousticSearch"),
    ("Hydrophone",            "Hydrophone"),
    ("Fighter",               "CatapultFighter"),
    ("PlaneTacticalFighters", "CatapultFighter"),
    ("ForsageBooster",        "SpeedBoost"),
    ("ActiveManeuvering",     "EnhancedRudders"),
    ("PlaneSmokeGenerator",   "PlaneSmokeGenerator"),
    ("Spotter",               "SpottingAircraft"),
    ("AirDefenseDisp",        "DefensiveAntiAircraft"),
    ("SmokeGenerator",        "Smoke"),
    ("SubmarineLocator",      "SubmarineSurveillance"),
    # 被动型/无限次
    ("CrashCrew",             "CrashCrew"),
    ("RegenCrew",             "RegenCrew"),
    ("RepairParty",           "RepairParty"),
    ("SpeedBoosterPremium",   "SpeedBoost"),
    ("SpeedBooster",          "SpeedBoost"),
    # 潜艇专属
    ("ReserveBattery",        "ReserveBattery"),
    ("SubmarineSurveillance", "SubmarineSurveillance"),
    # 兜底: ability_name 的关键中段就是 enum
]
```

然后把 `count_uses_for_ability` 整段替换为：

```python
def count_uses_for_ability(consumable_uses, user_eid, ability_name):
    """ability_name → enum → 数 user 触发次数。"""
    target_enum = None
    for keyword, enum_name in ABILITY_KEYWORD_TO_ENUM:
        if keyword in ability_name:
            target_enum = enum_name
            break
    if target_enum is None:
        return 0  # 没匹配上, 兜底 0 (色块会显示红, 用户能察觉到漏配)
    return sum(
        1 for u in consumable_uses
        if strip_id(u.get("user_entity_id") or "") == user_eid
        and u.get("consumable_name") == target_enum
    )
```

- [ ] **Step 3.4: 在 main 里打印 used/total**

把 `main()` 末尾的打印循环改为:

```python
    consumable_uses = raw.get("consumable_uses") or []
    for tid in (1 - self_team, self_team):
        label = "敌方" if tid != self_team else "友方"
        print(f"=== team {tid} ({label}) ===")
        for p in teams[tid]:
            ship = p.get("ship") or {}
            eid = strip_id(p.get("vehicle_entity_id") or "")
            print(f"  {p.get('name')} - {clean_ship_name(ship.get('name', ''))} ({strip_known(ship.get('species', ''))})")
            for slot in ship.get("consumable_slots") or []:
                disp, total, names = collect_slot_info(slot)
                if not names:
                    continue
                # 任一 alt 用过都算 slot 用过 (与 render_criminals 一致)
                used = max(
                    count_uses_for_ability(consumable_uses, eid, n) for n in names
                )
                tot_str = "∞" if total == -1 else (str(total) if total is not None else "?")
                print(f"    {disp:30s} {used:>2}/{tot_str}")
```

- [ ] **Step 3.5: 跑一次验证 used 数对得上**

```bash
py $WOWS_BOT/report/bin/render_consumables_chart.py $TEST_OUT/pobeda.json /tmp/dummy.png 2>&1 | head -60
```

Expected: 每行显示船 + 每个 slot 的 `中文名 used/total`。**对 1-2 个 slot 做 sanity check** — 比如 Pobeda 的维修小组 (RegenCrew/RepairParty) 应该 total=4，used 在 0-4 之间。

- [ ] **Step 3.6: 提交骨架**

```bash
cd $WOWS_BOT
git add report/bin/render_consumables_chart.py
git commit -m "feat(consumables-chart): scaffold + 数据采集 (打印模式,未渲染图)

- 按船种 DD→CA→BB→CV→SS 分组双方船只
- 主视角通过 player.relation 判断
- ability_name → enum 关键字映射表覆盖常见 slot
- 此 commit 仅 print, 下一 commit 加 PIL 渲染"
```

---

## Task 4: 渲染 — 整体布局 + 左侧船名列

**Files:**
- Modify: `C:\Users\29801\Desktop\wows-bot-review\report\bin\render_consumables_chart.py` (替换 main 中的 print 循环为绘图)

- [ ] **Step 4.1: 加渲染常量 + 布局函数骨架**

在文件顶部 (consumable mapping 表之后) 加常量:

```python
# 渲染常量
W = 2200
PAD = 16
TITLE_H = 60
TEAM_HEADER_H = 36
ROW_H = 56
CELL_W = 150
CELL_H = 48
CELL_GAP = 6
LEFT_COL_W = 360  # 船名+玩家区
```

- [ ] **Step 4.2: 加 `font()` helper + 主渲染函数**

把 `main()` 全部替换为 (保留参数处理):

```python
def font(path, size):
    return ImageFont.truetype(path, size)


def _ship_label(p):
    """复制自 render_criminals._ship_label, 风格一致。"""
    sp = (p.get("ship") or {})
    idx = sp.get("index", "")
    raw_name = clean_ship_name(sp.get("name", ""))
    zh = t(f"IDS_{idx}", raw_name) if idx else raw_name
    species = strip_known(sp.get("species", "")) or "?"
    species_cn = SPECIES_CN.get(species, species)
    return f"{zh}  L{sp.get('level', '?')} {species_cn}"


def render(json_path, out_path):
    load_translations()
    raw = json.load(open(json_path, encoding="utf-8"))
    consumable_uses = raw.get("consumable_uses") or []

    # 主视角 → 友方 team_id (同 Step 3.1)
    self_team = None
    for p in raw.get("players", []):
        if p.get("relation") in (0, 1):
            self_team = p.get("team_id"); break
    if self_team is None:
        self_team = 0

    teams = {0: [], 1: []}
    for p in raw.get("players", []):
        tid = p.get("team_id")
        if tid in teams:
            teams[tid].append(p)
    for tid in teams:
        teams[tid].sort(key=species_sort_key)

    # 顺序: 敌方上, 友方下
    enemy_team = 1 - self_team
    team_order = [(enemy_team, "敌方", GAME_RED), (self_team, "友方", GAME_GREEN)]

    # 算图高: title + 2 × (team_header + N_ships × ROW_H + PAD)
    total_h = TITLE_H + PAD
    for tid, _, _ in team_order:
        total_h += TEAM_HEADER_H + len(teams[tid]) * ROW_H + PAD

    img = Image.new("RGB", (W, total_h), GAME_BG)
    draw = ImageDraw.Draw(img)

    f_title = font(CJK_FONT, 28)
    f_team = font(CJK_FONT, 22)
    f_ship = font(CJK_FONT, 18)
    f_player = font(CJK_FONT, 15)
    f_slot_name = font(CJK_FONT, 14)
    f_slot_num = font(MONO_FONT, 16)

    # 标题
    draw.rectangle([0, 0, W, TITLE_H], fill=(14, 19, 30))
    draw.text((24, 14), "消耗品使用记录", GAME_TEXT, f_title)
    draw.text((24 + 240, 22), "12v12 全员 · used/total · 色块=使用率",
              GAME_DIM, f_ship)

    y = TITLE_H + PAD
    for tid, label, color in team_order:
        # 队头
        draw.rectangle([PAD, y, W - PAD, y + TEAM_HEADER_H], fill=GAME_PANEL_ALT)
        draw.line([PAD, y + TEAM_HEADER_H, W - PAD, y + TEAM_HEADER_H], fill=color, width=2)
        draw.text((PAD + 12, y + 6), f"{label}  ({len(teams[tid])} 船)", color, f_team)
        y += TEAM_HEADER_H

        # 每船一行
        for p in teams[tid]:
            _draw_ship_row(draw, p, y, consumable_uses, f_ship, f_player, f_slot_name, f_slot_num)
            y += ROW_H
        y += PAD

    img.save(out_path)
    print(f"saved: {out_path}", file=sys.stderr)
    print(out_path)


def _draw_ship_row(draw, p, y, consumable_uses, f_ship, f_player, f_slot_name, f_slot_num):
    """画一行: 左 = 船名+玩家, 右 = 各 slot cell。本步骤先只画左半。"""
    # 行底色 (斑马纹由调用者控制? 此处简化: 统一 PANEL)
    draw.rectangle([PAD, y, W - PAD, y + ROW_H - 2], fill=GAME_PANEL)

    # 左侧船名列
    ship_txt = _ship_label(p)
    player_txt = p.get("name", "?")
    draw.text((PAD + 12, y + 6), ship_txt, GAME_TEXT, f_ship)
    draw.text((PAD + 12, y + 30), player_txt, GAME_DIM, f_player)

    # TODO Step 5: slot cells
```

更新 `main()`:

```python
def main():
    if len(sys.argv) < 3:
        print("usage: render_consumables_chart.py <battle.json> <out.png>", file=sys.stderr)
        sys.exit(2)
    render(sys.argv[1], sys.argv[2])
```

- [ ] **Step 4.3: 跑一次, 应该看到只有船名/玩家、没有 slot 的雏形**

```bash
py $WOWS_BOT/report/bin/render_consumables_chart.py $TEST_OUT/pobeda.json $TEST_OUT/pobeda.consumables.png
```

Expected: 输出 `saved: ...`，打开 `pobeda.consumables.png` 能看到标题、两个队头、每队 12 行船名+玩家名，右侧全空白。

- [ ] **Step 4.4: 提交骨架渲染**

```bash
cd $WOWS_BOT
git add report/bin/render_consumables_chart.py
git commit -m "feat(consumables-chart): 渲染骨架 + 左侧船名列 (slot 暂留空)

下一 commit 加 slot cell 与色码。"
```

---

## Task 5: 渲染 — slot cell + 色码 + 特殊情况

**Files:**
- Modify: `C:\Users\29801\Desktop\wows-bot-review\report\bin\render_consumables_chart.py` (`_draw_ship_row` 把 TODO 改成 cell 绘制)

- [ ] **Step 5.1: 写色码函数**

在文件顶部 (常量之后) 加:

```python
# 色码: (R, G, B), 与 GAME_RED/GOLD/GREEN 同色系但调暗用作 cell 背景
CELL_INFINITE = GAME_PANEL_ALT      # 损管/抢救小队 (num=-1) 中性灰
CELL_ZERO     = (139, 40, 40)       # 0 使用 → 暗红
CELL_LOW      = (168, 129, 40)      # <50% → 暗黄
CELL_MID      = (58, 110, 58)       # 50-99% → 浅绿
CELL_FULL     = (31, 93, 31)        # 100% → 深绿
CELL_UNKNOWN  = (60, 60, 80)        # total 未知 (旧 schema 或查不到)


def cell_bg_color(used, total):
    if total is None:
        return CELL_UNKNOWN
    if total == -1:
        return CELL_INFINITE
    if total <= 0:
        return CELL_UNKNOWN
    ratio = used / total
    if used == 0:
        return CELL_ZERO
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
```

- [ ] **Step 5.2: 替换 `_draw_ship_row` 中的 TODO 为 cell 绘制**

把 `_draw_ship_row` 最后那行 `# TODO Step 5: slot cells` 替换为:

```python
    # 右侧 slot cells
    cell_x = PAD + LEFT_COL_W
    ship = p.get("ship") or {}
    eid = strip_id(p.get("vehicle_entity_id") or "")
    for slot in ship.get("consumable_slots") or []:
        disp, total, names = collect_slot_info(slot)
        if not names:
            continue
        used = max(count_uses_for_ability(consumable_uses, eid, n) for n in names)
        # cell 背景
        bg = cell_bg_color(used, total)
        cy = y + (ROW_H - CELL_H) // 2
        draw.rounded_rectangle([cell_x, cy, cell_x + CELL_W, cy + CELL_H],
                                radius=6, fill=bg, outline=GAME_BORDER, width=1)
        # 名字 (顶行, 自动截断)
        name_text = disp
        if len(name_text) > 9:  # 中文 9 字大约能填满 cell 宽度
            name_text = name_text[:8] + "…"
        draw.text((cell_x + 8, cy + 4), name_text, GAME_TEXT, f_slot_name)
        # used/total (底行, 等宽字体)
        ut = f"{used}/{fmt_total(total)}"
        bbox = f_slot_num.getbbox(ut)
        ut_w = bbox[2] - bbox[0]
        draw.text((cell_x + (CELL_W - ut_w) // 2, cy + 24), ut, GAME_TEXT, f_slot_num)
        cell_x += CELL_W + CELL_GAP
```

- [ ] **Step 5.3: 出图**

```bash
py $WOWS_BOT/report/bin/render_consumables_chart.py $TEST_OUT/pobeda.json $TEST_OUT/pobeda.consumables.png
```

Expected: PNG 打开后能看到双方 24 船每行右侧一连串色块 cell，cell 内"中文名 + N/total"，颜色按使用率不同。

- [ ] **Step 5.4: 把 PNG 给用户看**

把 `$TEST_OUT/pobeda.consumables.png` 的路径告诉用户, 让肉眼检查 §"验证" checklist:
- 双方 24 船全在
- 损管显示 `N/∞` 中性灰
- CV 行有飞机消耗品 (ForsageBooster / ActiveManeuvering / PlaneSmokeGenerator)
- 至少看到 1 个红色 0/N cell
- 排序 DD→CA→BB→CV→SS 在两队都正确

**如果**用户验收发现问题, 不要急着提交, 先回到对应 Step 修。

- [ ] **Step 5.5: 提交完整渲染**

```bash
cd $WOWS_BOT
git add report/bin/render_consumables_chart.py
git commit -m "feat(consumables-chart): slot cell 渲染 + 五级色码 + ∞ 处理

色码:
- 0/N = 暗红
- <50% = 暗黄
- 50-99% = 浅绿
- 100% = 深绿
- ∞ (损管/抢救小队) = 中性灰
- total 未知 = 灰
单 cell 150×48, 中文名顶行 + used/total 底行等宽字体居中。"
```

---

## Task 6: 收尾 — 文档 + 残留清理

- [ ] **Step 6.1: 检查两个 repo 都没有未提交**

```bash
cd $WOWS_TOOLKIT && git status --short
cd $WOWS_BOT && git status --short
```

Expected: 都空 (除了 `_test_out/` 和 `report/specs/` 这些已知未跟踪)。

- [ ] **Step 6.2: 给计划末尾加完成标记**

把 `docs/superpowers/plans/2026-05-20-consumables-chart.md` 第 3 行的状态从 `[ ]` 进度改为 `[x]` (此 Step 之后所有 checkbox 都应 checked)，并加一行：

```markdown
**完成日期:** 2026-05-20
**最终产物:** `$TEST_OUT/pobeda.consumables.png` (golden), `report/bin/render_consumables_chart.py`
```

- [ ] **Step 6.3: 提交计划完成状态**

```bash
cd $WOWS_BOT
git add docs/superpowers/plans/
git commit -m "docs(plan): 消耗品图实现完成"
```

---

## 验收 (跨 Task 检查)

完成所有 Task 后, 跑这个验证脚本:

```bash
cd $WOWS_BOT
# 1. 新 schema 生效
py -c "
import json
d = json.load(open(r'$TEST_OUT/pobeda.json', encoding='utf-8'))
s = d['players'][0]['ship']['consumable_slots']
assert isinstance(s[0][0], dict) and 'num_consumables' in s[0][0]
print('schema OK')
"

# 2. criminals 回归
py report/bin/render_criminals.py $TEST_OUT/pobeda.json $TEST_OUT/pobeda.criminals.png

# 3. consumables chart 出图
py report/bin/render_consumables_chart.py $TEST_OUT/pobeda.json $TEST_OUT/pobeda.consumables.png

# 4. 文件存在
ls -la $TEST_OUT/pobeda.consumables.png
```

全 4 步 exit 0 + 文件 > 0 字节 = 任务完成。

---

## 不在范围内 (避免 scope creep)

- 时间轴可视化
- 拼进 wows_full_report
- 部署到 Linux 服务器 (本计划只在 Windows 本地完成出图与验证)
- num_consumables 查不到时的回退查表 (null → "?" 即可)
