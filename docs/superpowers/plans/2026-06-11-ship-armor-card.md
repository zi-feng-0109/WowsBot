# `/船 <名> 装甲` 完整分面装甲图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 bot 加 `/船 <中文舰名> 装甲`,从本地客户端 GameParams 解析每船完整分面装甲厚度,渲成单独一张 PNG。

**Architecture:** 新增 Rust 子命令 `replayshark armor-dump` 复用 wowsunpack 已有的 `collision_material_name` / `zone_from_material_name` / `Vehicle::armor()` / 炮塔 `mount_armor()`,导出 `report/data/armor.json`(key=短 index,跟 ships.json 对齐)。新增 `report/bin/render_armor.py` 按装甲区分组渲图。`plugin/minimap.py` 的 `/船` handler 识别末位 `装甲` 子参数后分流到装甲渲染。`armor.json` 独立存储,`/船` 主数值卡零改动。

**Tech Stack:** Rust(replayshark/wowsunpack,clap + serde_json)、Python(Pillow 渲染,nonebot2 插件)、本地 GameParams.data。

**Spec:** `docs/superpowers/specs/2026-06-11-ship-armor-card-design.md`

---

## 文件结构

| 文件 | 职责 | 动作 |
|---|---|---|
| `wows-toolkit/crates/replayshark/src/armor_dump.rs` | 装甲 dump 逻辑 + 纯转换函数 + 单测 | 新建 |
| `wows-toolkit/crates/replayshark/src/main.rs` | 注册 `ArmorDump` 子命令并分发 | 改 |
| `wows-bot-review/report/data/armor.json` | 每船分面装甲数据(dump 产物) | 生成 |
| `wows-bot-review/report/bin/render_armor.py` | 装甲图渲染库 + CLI + 中文标签表 | 新建 |
| `wows-bot-review/tests/test_render_armor.py` | render_armor 单测 + 烟囱测 | 新建 |
| `wows-bot-review/plugin/minimap.py` | `/船` handler 加 `装甲` 子参数分流 | 改 |
| `wows-bot-review/report/bin/render_menu.py` | 【全部指令】补装甲用法行 | 改 |
| `wows-bot-review/docs/UPDATE.md` | 刷新流程加 armor-dump 一步 | 改 |
| `wows-bot-review/docs/DEPLOY.md` | 文件清单 +render_armor.py/armor.json | 改 |

> **路径约定**:Rust 在 `C:/Users/29801/Desktop/minimap/wows-toolkit`;Python/bot 在 `C:/Users/29801/Desktop/wows-bot-review`。下面命令注明在哪个目录跑。

---

## Task 1: Rust — `armor_dump` 模块(纯转换 + 单测)

**Files:**
- Create: `wows-toolkit/crates/replayshark/src/armor_dump.rs`

复用接口(已核实存在,均为 `pub`):
- `wowsunpack::export::gltf_export::collision_material_name(id: u8) -> &'static str`
- `wowsunpack::export::gltf_export::zone_from_material_name(name: &str) -> &'static str`
- `ArmorMap = HashMap<u32 material_id, BTreeMap<u32 layer, f32 厚度mm>>`(`wowsunpack::game_params::types::ArmorMap`)

- [ ] **Step 1: 写两个纯转换函数 + 失败单测**

把整个文件写出来(转换函数 + `resolve_vfs_dir` + `run_armor_dump` 留到 Step 3,先写转换 + 测试让它能编译失败/测试失败)。先写这部分:

```rust
// crates/replayshark/src/armor_dump.rs
//! `armor-dump` 子命令:从 GameParams 导出每船分面装甲厚度到 JSON。
//! 复用 wowsunpack 的 collision_material_name / zone_from_material_name /
//! Vehicle::armor() / 炮塔 mount_armor(),给 bot 的 /船 <名> 装甲 图用。

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use anyhow::anyhow;
use serde_json::{json, Value};

use wowsunpack::export::gltf_export::{collision_material_name, zone_from_material_name};
use wowsunpack::game_params::keys::ComponentType;
use wowsunpack::game_params::provider::GameMetadataProvider;
use wowsunpack::game_params::types::{ArmorMap, GameParamProvider, MountSpecies, ParamData};
use wowsunpack::vfs::{PhysicalFS, VfsPath};

/// 把一张 ArmorMap 拍平成 `[{face, mm:[...]}]`,按 material_id 升序,过滤 0mm 层。
/// 纯函数,不依赖 GameParams,可单测。
fn armor_faces(armor: &ArmorMap) -> Vec<Value> {
    let mut ids: Vec<&u32> = armor.keys().collect();
    ids.sort();
    let mut faces = Vec::new();
    for id in ids {
        let mm: Vec<i64> = armor[id]
            .values()
            .filter(|&&v| v > 0.0)
            .map(|&v| v.round() as i64)
            .collect();
        if mm.is_empty() {
            continue;
        }
        let name = collision_material_name(*id as u8);
        faces.push(json!({ "face": name, "mm": mm }));
    }
    faces
}

/// 把船体 ArmorMap 按装甲区分组:`{zone: [{face, mm:[...]}]}`(zone 名按字母序)。
fn hull_zones(armor: &ArmorMap) -> Value {
    let mut zones: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for face in armor_faces(armor) {
        let name = face["face"].as_str().unwrap_or("").to_string();
        let zone = zone_from_material_name(&name).to_string();
        zones.entry(zone).or_default().push(face);
    }
    json!(zones)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn one_layer(v: f32) -> BTreeMap<u32, f32> {
        let mut b = BTreeMap::new();
        b.insert(1, v);
        b
    }

    #[test]
    fn faces_filter_zero_and_name() {
        let mut armor: ArmorMap = HashMap::new();
        // material id 32 = "TurretSide";第二层 0mm 必须被过滤
        let mut layers = BTreeMap::new();
        layers.insert(1, 350.0);
        layers.insert(2, 0.0);
        armor.insert(32, layers);
        let faces = armor_faces(&armor);
        assert_eq!(faces.len(), 1);
        assert_eq!(faces[0]["face"], "TurretSide");
        assert_eq!(faces[0]["mm"], json!([350]));
    }

    #[test]
    fn hull_groups_into_turret_zone() {
        let mut armor: ArmorMap = HashMap::new();
        armor.insert(32, one_layer(350.0)); // TurretSide -> 区 "Turret"
        let zones = hull_zones(&armor);
        assert!(zones.get("Turret").is_some(), "TurretSide 应归入 Turret 区");
    }
}
```

- [ ] **Step 2: 跑测试确认失败(模块还没被 main.rs 引入,编译失败即可)**

Run(在 `wows-toolkit`):
```bash
cargo test -p replayshark armor_dump 2>&1 | tail -20
```
Expected: 编译错误(`armor_dump` 未在 crate 中声明)或测试未被发现 —— 因为还没在 `main.rs` 加 `mod armor_dump;`。下一步加。

- [ ] **Step 3: 在 main.rs 引入模块**

在 `crates/replayshark/src/main.rs` 顶部、其它 `mod`/`use` 附近加一行:
```rust
mod armor_dump;
```
(放在 `fn main()` 之前任意位置;若文件没有其它 `mod` 声明,放在最后一个 `use` 之后。)

- [ ] **Step 4: 跑测试确认通过**

Run(在 `wows-toolkit`):
```bash
cargo test -p replayshark armor_dump 2>&1 | tail -20
```
Expected: `test armor_dump::tests::faces_filter_zero_and_name ... ok`、`test armor_dump::tests::hull_groups_into_turret_zone ... ok`,2 passed。

- [ ] **Step 5: Commit**

Run(在 `wows-toolkit`):
```bash
git add crates/replayshark/src/armor_dump.rs crates/replayshark/src/main.rs
git commit -m "feat(replayshark): armor_dump 纯转换 (armor_faces/hull_zones) + 单测"
```

---

## Task 2: Rust — `armor-dump` 子命令(读 GameParams 产 armor.json)

**Files:**
- Modify: `wows-toolkit/crates/replayshark/src/armor_dump.rs`(加 `resolve_vfs_dir` + `run_armor_dump`)
- Modify: `wows-toolkit/crates/replayshark/src/main.rs`(注册 `ArmorDump` 子命令 + 分发)

- [ ] **Step 1: 在 armor_dump.rs 末尾(`#[cfg(test)]` 之前)加入 vfs 解析 + dump 主函数**

```rust
/// 解析 --extracted 目录到含 content/GameParams.data 的 vfs 根。
/// 支持三种布局(同 run_consumables_dump):
///   a) <path>/content/GameParams.data
///   b) <path>/vfs/content/...
///   c) <path>/<ver_build>/vfs/content/...
fn resolve_vfs_dir(path: &Path) -> anyhow::Result<PathBuf> {
    if path.join("content").join("GameParams.data").is_file() {
        return Ok(path.to_path_buf());
    }
    if path.join("vfs").join("content").is_dir() {
        return Ok(path.join("vfs"));
    }
    if let Ok(entries) = std::fs::read_dir(path) {
        for entry in entries.flatten() {
            let sub = entry.path();
            if sub.join("vfs").join("content").is_dir() {
                return Ok(sub.join("vfs"));
            }
        }
    }
    Err(anyhow!("没在 {} 下找到 content/GameParams.data", path.display()))
}

/// 主炮塔装甲:取任一 hull 配置的 Artillery mounts,filter 主炮(MountSpecies::Main),
/// 按装甲内容去重(同型号炮塔只输出一次)。
fn turret_armors(v: &wowsunpack::game_params::types::Vehicle) -> Vec<Value> {
    let mut turrets: Vec<Value> = Vec::new();
    let mut seen: Vec<String> = Vec::new();
    let Some(hulls) = v.hull_upgrades() else {
        return turrets;
    };
    let Some(hc) = hulls.values().next() else {
        return turrets;
    };
    let Some(mounts) = hc.mounts(ComponentType::Artillery) else {
        return turrets;
    };
    for m in mounts {
        if m.species() != Some(MountSpecies::Main) {
            continue;
        }
        let Some(am) = m.mount_armor() else {
            continue;
        };
        let faces = armor_faces(am);
        if faces.is_empty() {
            continue;
        }
        let key = serde_json::to_string(&faces).unwrap_or_default();
        if seen.contains(&key) {
            continue;
        }
        seen.push(key);
        turrets.push(json!({ "name": "主炮", "faces": faces }));
    }
    turrets
}

pub fn run_armor_dump(extracted_dir: Option<&str>, output: Option<&Path>) -> anyhow::Result<()> {
    let extracted = extracted_dir.ok_or_else(|| anyhow!("--extracted is required"))?;
    let vfs_dir = resolve_vfs_dir(Path::new(extracted))?;
    eprintln!("loading GameParams.data from {} ...", vfs_dir.display());
    let vfs: VfsPath = VfsPath::new(PhysicalFS::new(&vfs_dir));
    let provider = GameMetadataProvider::from_vfs(&vfs).map_err(|e| anyhow!("{}", e))?;

    let mut out = serde_json::Map::new();
    for param in provider.params() {
        let ParamData::Vehicle(v) = param.data() else {
            continue;
        };
        let hull = v.armor().map(hull_zones);
        let turrets = turret_armors(v);
        if hull.is_none() && turrets.is_empty() {
            continue;
        }
        out.insert(
            param.index().to_string(),
            json!({
                "hull": hull.unwrap_or_else(|| json!({})),
                "turrets": turrets,
            }),
        );
    }

    eprintln!("dumped armor for {} ships", out.len());
    let text = serde_json::to_string_pretty(&Value::Object(out))?;
    if let Some(o) = output {
        std::fs::write(o, text)?;
        eprintln!("wrote to {}", o.display());
    } else {
        println!("{}", text);
    }
    Ok(())
}
```

> 注:`turret_armors` 入参用全限定类型 `wowsunpack::game_params::types::Vehicle`,无需在 `use` 里单列。

- [ ] **Step 2: 在 main.rs 的 `enum Commands` 里加子命令**

定位 `enum Commands {`(约 main.rs:44),在 `ConsumablesDump { ... }` 那一项后面加:
```rust
    /// Dump per-ship faceted armor thickness from GameParams to JSON.
    /// Requires --extracted. Outputs JSON.
    ArmorDump {
        /// Optional output file (default: stdout)
        #[arg(short, long)]
        output: Option<PathBuf>,
    },
```

- [ ] **Step 3: 在 main.rs 的 `match` 分发里加分支**

定位 `Commands::ConsumablesDump { output } => {`(约 main.rs:686),在其后加:
```rust
        Commands::ArmorDump { output } => {
            armor_dump::run_armor_dump(extracted, output.as_deref()).unwrap();
        }
```
(`extracted` 与 `output.as_deref()` 用法跟 ConsumablesDump 完全一致。)

- [ ] **Step 4: 编译 release**

Run(在 `wows-toolkit`):
```bash
cargo build --release -p replayshark 2>&1 | tail -15
```
Expected: `Finished release [optimized]`,产出 `target/release/replayshark.exe`。

- [ ] **Step 5: 生成 armor.json**

Run(在 `wows-toolkit`):
```bash
./target/release/replayshark.exe \
  --extracted "C:/Users/29801/Desktop/minimap/extracted/15.4.0_12506899" \
  armor-dump -o "C:/Users/29801/Desktop/wows-bot-review/report/data/armor.json" 2>&1 | tail -5
```
Expected: `dumped armor for <数百> ships`、`wrote to .../armor.json`。

- [ ] **Step 6: 校验已知值(大和 PJSB018)**

Run(在 `wows-bot-review`):
```bash
python -X utf8 -c "
import json
d=json.load(open('report/data/armor.json',encoding='utf-8'))
print('total ships:', len(d))
y=d.get('PJSB018'); assert y, '大和 PJSB018 缺失'
print('大和 hull 区:', list(y['hull'].keys()))
print('大和 turrets:', len(y['turrets']))
assert 'Citadel' in y['hull'], '大和应有 Citadel 区'
assert y['turrets'], '大和应有主炮塔装甲'
mx=max(v for f in y['turrets'][0]['faces'] for v in f['mm'])
print('大和主炮塔最大厚度 mm:', mx)
assert 300 <= mx <= 800, f'炮塔厚度 {mx} 不合理'
print('OK')
"
```
Expected: total > 200;大和有 `Citadel` 区、≥1 个炮塔、炮塔最大厚度在 300–800mm(大和主炮塔正面 650mm 量级);打印 `OK`。

- [ ] **Step 7: Commit**

Run(在 `wows-toolkit`):
```bash
git add crates/replayshark/src/armor_dump.rs crates/replayshark/src/main.rs
git commit -m "feat(replayshark): armor-dump 子命令 — 导出每船分面装甲到 JSON"
```
Run(在 `wows-bot-review`):
```bash
git add report/data/armor.json
git commit -m "data: 生成 armor.json (15.4.0 分面装甲)"
```

---

## Task 3: Python — `render_armor.py` 装甲图渲染

**Files:**
- Create: `wows-bot-review/report/bin/render_armor.py`
- Create: `wows-bot-review/tests/test_render_armor.py`

复用(已核实):`render_ship._draw_panel(img, draw, x, y, w, title, kvs, cols, fonts)`、`render_ship._panel_height(n_rows, cols)`、`render_ship._load_ship_img(index, max_h)`、`render_ship._HEADER_H`、`render_ship._PANEL_GAP`;调色板/字体来自 `render_query`。

- [ ] **Step 1: 写 render_armor.py(库 + 标签表 + CLI)**

```python
# report/bin/render_armor.py
"""render_armor.py — /船 <名> 装甲 完整分面装甲图 PNG。

库用法 (bot 直接 import):
    from render_armor import render_armor_png
    render_armor_png(out_path, ship=<ships.json 一条>, armor=<armor.json 一条>)

CLI (调试):
    python render_armor.py <out.png> --ship-id PJSB018

数据来自 report/data/armor.json (replayshark armor-dump 预构建)。
视觉复用 render_ship / render_query 的面板与调色板。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_query import (  # noqa: E402
    GAME_BG, GAME_PANEL, GAME_TEXT, GAME_DIM, GAME_GOLD,
    CJK_FONT, MONO_FONT, W, PAD, FOOTER_H, _font, _draw_footer,
)
from render_ship import (  # noqa: E402
    _draw_panel, _panel_height, _load_ship_img, _HEADER_H, _PANEL_GAP,
)
from PIL import Image, ImageDraw  # noqa: E402

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_ARMOR_PATH = _DATA_DIR / "armor.json"
_SHIPS_PATH = _DATA_DIR / "ships.json"

# 装甲区英文 → 中文
ZONE_ZH = {
    "Citadel": "装甲核心", "Casemate": "炮郭", "Superstructure": "上层建筑",
    "Bow": "舰艏", "Stern": "舰艉", "Turret": "主炮塔", "SteeringGear": "操舵室",
    "TorpedoProtection": "防雷", "Hull": "船体", "Other": "其他", "unknown": "未知",
}
# 装甲区显示顺序(未列到的排最后,按字母序)
_ZONE_ORDER = ["Citadel", "Hull", "Bow", "Stern", "Casemate", "Superstructure",
               "TorpedoProtection", "SteeringGear", "Turret", "Other", "unknown"]

# 分面 material 名 → 中文。只精确映射常见名;未命中退化原英文(保证不丢分面、不撞名)。
_FACE_EXACT = {
    "Belt": "舷侧装甲带", "Deck": "甲板", "Bottom": "船底",
    "Trans": "横向隔壁", "Inclin": "倾斜装甲",
    "TurretFront": "炮塔正面", "TurretFwd": "炮塔正面", "TurretSide": "炮塔侧面",
    "TurretTop": "炮塔顶部", "TurretAft": "炮塔背面", "TurretDown": "炮塔底部",
    "TurretBarbette": "座圈",
}


def face_zh(name: str) -> str:
    """分面中文名;未精确命中则原样返回英文 material 名(完整分面、零丢失)。"""
    return _FACE_EXACT.get(name, name)


def _fmt_mm(mm: list) -> str:
    """[370, 350] -> '370 / 350 mm';[410] -> '410 mm'。"""
    if not mm:
        return "-"
    return " / ".join(str(int(v)) for v in mm) + " mm"


def _armor_sections(armor: dict) -> list:
    """armor.json 一条 → [(title, kvs, cols)],喂 render_ship._draw_panel。"""
    secs = []
    hull = armor.get("hull") or {}

    def _zkey(z):
        return (_ZONE_ORDER.index(z) if z in _ZONE_ORDER else 99, z)

    for z in sorted(hull.keys(), key=_zkey):
        kvs = [(face_zh(f["face"]), _fmt_mm(f.get("mm") or [])) for f in hull[z]]
        if kvs:
            secs.append((ZONE_ZH.get(z, z), kvs, 2))
    for t in armor.get("turrets") or []:
        kvs = [(face_zh(f["face"]), _fmt_mm(f.get("mm") or [])) for f in t.get("faces") or []]
        if kvs:
            secs.append((f"{t.get('name', '主炮')}装甲", kvs, 2))
    return secs


def render_armor_png(out_path: str, *, ship: dict, armor: dict) -> str:
    """渲一张装甲分面图。ship = ships.json 一条;armor = armor.json 一条。"""
    fonts = {
        "tier":  _font(MONO_FONT, 34),
        "name":  _font(CJK_FONT, 32),
        "sub":   _font(CJK_FONT, 20),
        "title": _font(CJK_FONT, 18),
        "label": _font(CJK_FONT, 15),
        "value": _font(CJK_FONT, 21),
    }
    sections = _armor_sections(armor)
    if not sections:
        sections = [("装甲", [("无数据", "-")], 2)]

    body_h = 12
    for _, kvs, cols in sections:
        body_h += _panel_height(len(kvs), cols) + _PANEL_GAP
    H = _HEADER_H + body_h + FOOTER_H

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)

    # ----- Header(同 render_ship 风格) -----
    draw.rectangle([0, 0, W, _HEADER_H], fill=GAME_PANEL)
    draw.line([0, _HEADER_H, W, _HEADER_H], fill=GAME_GOLD, width=2)
    tier_txt = f"T{ship.get('tier', '?')}"
    bw = int(fonts["tier"].getlength(tier_txt)) + 28
    draw.rounded_rectangle([PAD, 20, PAD + bw, 20 + 64], radius=10, fill=GAME_GOLD)
    draw.text((PAD + 14, 28), tier_txt, (10, 16, 28), fonts["tier"])
    tx = PAD + bw + 24
    draw.text((tx, 22), ship.get("name_zh", "?"), GAME_TEXT, fonts["name"])
    sub_line = "  ·  ".join(x for x in [
        ship.get("name_en", ""),
        ship.get("species_zh") or ship.get("species", ""),
        ship.get("nation_zh") or ship.get("nation", ""),
        "装甲",
    ] if x)
    draw.text((tx, 66), sub_line, GAME_DIM, fonts["sub"])
    pic = _load_ship_img(ship.get("icon") or ship.get("index", ""), _HEADER_H - 28)
    if pic is not None:
        img.paste(pic, (W - PAD - pic.width, max(8, (_HEADER_H - pic.height) // 2)), pic)

    # ----- 装甲区面板(单列) -----
    y = _HEADER_H + 12
    for title, kvs, cols in sections:
        used = _draw_panel(img, draw, PAD, y, W - 2 * PAD, title, kvs, cols, fonts)
        y += used + _PANEL_GAP

    _draw_footer(draw, 0, H - FOOTER_H, W, FOOTER_H)
    img.save(out_path)
    return out_path


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--ship-id", required=True, help="短 index,如 PJSB018")
    args = ap.parse_args()
    ships = json.loads(_SHIPS_PATH.read_text("utf-8"))
    ships = ships.get("ships") or ships
    ship = ships.get(args.ship_id)
    if not ship:
        sys.exit(f"ship-id {args.ship_id} 不在 ships.json")
    armor = json.loads(_ARMOR_PATH.read_text("utf-8")).get(args.ship_id)
    if not armor:
        sys.exit(f"ship-id {args.ship_id} 不在 armor.json")
    render_armor_png(args.out, ship=ship, armor=armor)
    print(args.out)


if __name__ == "__main__":
    _cli()
```

- [ ] **Step 2: 写测试(纯逻辑单测 + 烟囱渲染)**

```python
# tests/test_render_armor.py
"""render_armor 测试:纯逻辑(标签/格式/分组)+ 烟囱渲染(PNG 写出且 >5KB)。
用法: python tests/test_render_armor.py"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "report" / "bin"))
os.environ.setdefault("WOWS_CJK_FONT", "C:/Windows/Fonts/msyh.ttc")

from render_armor import face_zh, _fmt_mm, _armor_sections, render_armor_png  # noqa: E402


def test_face_zh_exact_and_fallback():
    assert face_zh("TurretFront") == "炮塔正面"
    assert face_zh("SideCit") == "SideCit"   # 未精确命中 → 退化原名,不丢
    print("  face_zh PASS")


def test_fmt_mm_multilayer():
    assert _fmt_mm([370, 350]) == "370 / 350 mm"
    assert _fmt_mm([410]) == "410 mm"
    assert _fmt_mm([]) == "-"
    print("  _fmt_mm PASS")


def test_sections_zone_order_and_turret():
    armor = {
        "hull": {
            "Bow": [{"face": "Bow_Belt", "mm": [60]}],
            "Citadel": [{"face": "Belt", "mm": [410]}, {"face": "Deck", "mm": [200]}],
        },
        "turrets": [{"name": "主炮", "faces": [{"face": "TurretFront", "mm": [650]}]}],
    }
    secs = _armor_sections(armor)
    titles = [t for t, _, _ in secs]
    # Citadel(装甲核心)在 Bow(舰艏)之前(_ZONE_ORDER),主炮塔在最后
    assert titles[0] == "装甲核心", titles
    assert "舰艏" in titles
    assert titles[-1] == "主炮装甲", titles
    print("  _armor_sections PASS")


def test_render_smoke():
    ship = {"tier": 10, "name_zh": "大和", "name_en": "Yamato",
            "species_zh": "战列舰", "nation_zh": "日本", "index": "PJSB018"}
    armor = {
        "hull": {"Citadel": [{"face": "Belt", "mm": [410]}, {"face": "Deck", "mm": [200]}],
                 "Bow": [{"face": "Bow_Belt", "mm": [60]}]},
        "turrets": [{"name": "主炮", "faces": [
            {"face": "TurretFront", "mm": [650]}, {"face": "TurretSide", "mm": [250]}]}],
    }
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "armor.png"
        render_armor_png(str(out), ship=ship, armor=armor)
        assert out.is_file(), "PNG 没写出来"
        size = out.stat().st_size
        assert size > 5_000, f"PNG 才 {size} 字节,太小"
        print(f"  render_smoke PASS ({size} bytes)")


if __name__ == "__main__":
    test_face_zh_exact_and_fallback()
    test_fmt_mm_multilayer()
    test_sections_zone_order_and_turret()
    test_render_smoke()
    print("ALL PASS")
```

- [ ] **Step 3: 跑测试(确认通过)**

Run(在 `wows-bot-review`):
```bash
python -X utf8 tests/test_render_armor.py
```
Expected:
```
  face_zh PASS
  _fmt_mm PASS
  _armor_sections PASS
  render_smoke PASS (XXXXX bytes)
ALL PASS
```

- [ ] **Step 4: 真数据出图肉眼验(大和 / 一艘驱逐)**

Run(在 `wows-bot-review`):
```bash
python -X utf8 report/bin/render_armor.py /tmp/armor_yamato.png --ship-id PJSB018 && echo "大和 OK"
```
Expected: 打印路径;打开 `/tmp/armor_yamato.png` 看:Header 有 T10 大和 + 预览图;装甲核心/船体/舰艏…各面板;主炮塔面板含正面/侧面;无错位。

- [ ] **Step 5: Commit**

Run(在 `wows-bot-review`):
```bash
git add report/bin/render_armor.py tests/test_render_armor.py
git commit -m "feat: render_armor.py /船 装甲 分面图渲染 + 测试"
```

---

## Task 4: Python — `/船 <名> 装甲` 命令分流

**Files:**
- Modify: `wows-bot-review/plugin/minimap.py`(`_ship` handler:`plugin/minimap.py:403-445`)

- [ ] **Step 1: 加 armor.json 路径常量 + 懒加载帮手**

在 `SHIPS_JSON` 定义(`plugin/minimap.py:54-55`)之后插入:
```python
ARMOR_JSON       = os.environ.get("WOWS_ARMOR_JSON",
                                  str(Path(SHIPS_JSON).parent / "armor.json"))
_armor_data = None  # 懒加载缓存:index -> {hull, turrets}


def _armor_for(index: str):
    """读 armor.json 取一条;文件缺失/无该船返回 None。"""
    global _armor_data
    if _armor_data is None:
        try:
            _armor_data = json.loads(Path(ARMOR_JSON).read_text("utf-8"))
        except Exception:
            _armor_data = {}
    return _armor_data.get(index)
```

- [ ] **Step 2: 改 `_ship` handler 识别末位 `装甲` 子参数并分流**

把 `_ship`(`plugin/minimap.py:403-435`)整体替换为:
```python
@ship_cmd.handle()
async def _ship(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    raw = args.extract_plain_text().strip()
    armor_mode = raw.endswith("装甲") and raw != "装甲"
    name = raw[:-2].strip() if armor_mode else raw
    if not name:
        await ship_cmd.finish("用法: /船 <中文舰名>\n示例: /船 大和  ·  /船 岛风  ·  /船 大和 装甲")

    if not ship_index.is_ready():
        await ship_cmd.finish("战舰数据未生成 (ships.json 缺失)。请管理员跑 tools/build_ships_json.py")

    kind, payload = ship_index.find(name)
    if kind == "none":
        if payload:
            sug = "  ".join(payload[:8])
            await ship_cmd.finish(f"没找到「{name}」。你是不是想查:{sug}")
        await ship_cmd.finish(f"没找到「{name}」,换个名字试试 (支持中文名 / 英文名)")
    if kind == "multi":
        lines = "\n".join(
            f"  · {s['name_zh']} ({s['name_en']} T{s['tier']} {s.get('species_zh','')})"
            for s in payload
        )
        await ship_cmd.finish(f"「{name}」匹配到多艘,请发完整舰名:\n{lines}")

    ship = payload[0]
    out_dir = Path(BASE_DIR) / "_ship_cache"
    out_dir.mkdir(parents=True, exist_ok=True)

    if armor_mode:
        armor = _armor_for(ship.get("index", ""))
        if not armor:
            await ship_cmd.finish(f"「{ship.get('name_zh', name)}」暂无装甲数据")
        out_png = out_dir / f"armor_{ship.get('index', 'x')}.png"
        try:
            await asyncio.to_thread(_render_armor_sync, str(out_png), ship, armor)
        except Exception as e:
            logger.error(f"渲染 /船 装甲图失败: {e}")
            await ship_cmd.finish(f"⚠️ 渲染失败: {e}")
        await ship_cmd.finish(MessageSegment.image(f"file://{out_png}"))

    out_png = out_dir / f"ship_{ship.get('index', ship.get('name_en', 'x'))}.png"
    try:
        await asyncio.to_thread(_render_ship_sync, str(out_png), ship)
    except Exception as e:
        logger.error(f"渲染 /船 卡失败: {e}")
        await ship_cmd.finish(f"⚠️ 渲染失败: {e}")

    await ship_cmd.finish(MessageSegment.image(f"file://{out_png}"))
```
> `ship_cmd.finish` 内部抛 `FinishedException`,装甲分支命中后不会落到下面的数值卡分支(跟现有 none/multi 早退一致)。

- [ ] **Step 3: 加 `_render_armor_sync` thread wrapper**

在 `_render_ship_sync`(`plugin/minimap.py:438-445`)之后加:
```python
def _render_armor_sync(out_path: str, ship: dict, armor: dict):
    """thread wrapper — render_armor 没 async 接口。"""
    import sys as _sys
    bin_path = str(Path(REPORT_FULL_CMD).parent)
    if bin_path not in _sys.path:
        _sys.path.insert(0, bin_path)
    from render_armor import render_armor_png
    render_armor_png(out_path, ship=ship, armor=armor)
```

- [ ] **Step 4: 语法自检(import 不炸)**

Run(在 `wows-bot-review`):
```bash
python -X utf8 -c "import ast; ast.parse(open('plugin/minimap.py',encoding='utf-8').read()); print('syntax OK')"
```
Expected: `syntax OK`。
(完整 import 依赖 nonebot 运行时,这里只做语法解析;handler 行为在部署联调验。)

- [ ] **Step 5: Commit**

Run(在 `wows-bot-review`):
```bash
git add plugin/minimap.py
git commit -m "feat: /船 <名> 装甲 子参数分流到装甲分面图"
```

---

## Task 5: 菜单用法 + 文档

**Files:**
- Modify: `wows-bot-review/report/bin/render_menu.py`(命令表 `report/bin/render_menu.py:310-316`,高度 `:226`)
- Modify: `wows-bot-review/docs/UPDATE.md`
- Modify: `wows-bot-review/docs/DEPLOY.md`

- [ ] **Step 1: 菜单【全部指令】加装甲用法行**

在 `report/bin/render_menu.py` 的 `cmds = [ ... ]` 里,`("/船 <中文舰名>", "查战舰数值卡", "任何人"),`(约 :315)之后加一行:
```python
        ("/船 <名> 装甲",         "查装甲分面厚度",         "任何人"),
```

- [ ] **Step 2: 同步【全部指令】section 高度行数 +1**

在 `report/bin/render_menu.py:226`,把
```python
        + 30 + 22 + (7 if sa_visible else 6) * 28 + SECTION_GAP  # 全部指令 (含表头 22px)
```
改为(各 +1):
```python
        + 30 + 22 + (8 if sa_visible else 7) * 28 + SECTION_GAP  # 全部指令 (含表头 22px)
```

- [ ] **Step 3: 菜单烟囱测确认不崩**

Run(在 `wows-bot-review`):
```bash
python -X utf8 tests/test_render_menu.py
```
Expected: 三个 state 全 PASS,无报错(新增行不越界)。

- [ ] **Step 4: UPDATE.md 加 armor-dump 刷新步骤**

在 `docs/UPDATE.md` 里 ConsumablesDump / ships.json 刷新那节之后,加一小节:
```markdown
### 2.x 刷新 armor.json (/船 <名> 装甲 装甲分面图用)

装甲厚度只能从本地客户端 GameParams 解析(WG API 无此数据),用 replayshark
的 armor-dump 子命令产出:

​```bash
replayshark.exe --extracted <GameParams 目录,如 extracted/15.4.0_xxxx> \
  armor-dump -o report/data/armor.json
​```

缺这步只影响 `/船 <名> 装甲`(会回「暂无装甲数据」);`/船 <名>` 数值卡不受影响。
```
> 注:上面代码块围栏里的 `​```bash` 用了零宽字符占位以免破坏本计划文档的外层围栏;落地写入 UPDATE.md 时用普通三反引号。

- [ ] **Step 5: DEPLOY.md 文件清单补两项**

在 `docs/DEPLOY.md` 列 `report/bin/*` 渲染脚本 / `report/data/*` 数据文件的清单处,各加一行:
- `report/bin/render_armor.py` — `/船 <名> 装甲` 装甲分面图渲染
- `report/data/armor.json` — 每船分面装甲厚度(replayshark armor-dump 产出)

- [ ] **Step 6: Commit**

Run(在 `wows-bot-review`):
```bash
git add report/bin/render_menu.py docs/UPDATE.md docs/DEPLOY.md
git commit -m "docs+menu: /船 装甲 用法行 + armor.json 刷新/部署说明"
```

---

## 部署(用户手动,联调验收)

> 服务器需密码,scp/ssh 由用户自己跑(见项目约定)。本计划只在本地完成代码+数据+测试。

部署 `/船 装甲` 到 EssexBot(用户执行):
1. `armor.json` + 新渲染脚本随 `/opt/wows-bot` git pull 上去。
2. `cp /opt/wows-bot/plugin/minimap.py /home/zifeng/桌面/bot/EssexBot/src/plugins/`(插件代码要拷过去,render 脚本走 sys.path import)。
3. 重启 EssexBot,群里发 `/船 大和 装甲` 验图;`/船 大和` 验数值卡未受影响;`/船 <无数据船> 装甲` 验兜底文案。

---

## Self-Review

**Spec 覆盖**:
- §2 数据来源(GameParams `.armor`/material 表/zone)→ Task 1+2 复用 `collision_material_name`/`zone_from_material_name`/`armor()`/`mount_armor()`。✓
- §3 数据流(独立 armor.json)→ Task 2 产出 `report/data/armor.json`,不动 ships.json。✓
- §4 Rust 子命令(replayshark,过滤 0mm,炮塔去重,key=短 index)→ Task 1(过滤/分组)+ Task 2(子命令/炮塔 Main 过滤/去重/`param.index()`)。✓
- §5 构建侧(build_ships_json 不改,UPDATE.md 加步)→ Task 5 Step 4。✓
- §6 渲染(render_armor.py、按区分组、多层 `370 / 350`、中文标签不命中退化英文、复用 render_ship 面板)→ Task 3。✓
- §7 命令解析(末位 `装甲` 分流、兜底「暂无装甲数据」、文件缺失兜底、菜单补用法)→ Task 4 + Task 5 Step 1。✓
- §8 文件清单 → 各 Task 对应。✓
- §9 测试(Rust 已知值 + Python 出图)→ Task 2 Step 6 + Task 3 Step 3/4。✓
- §10 边界(多层全列/0mm 丢弃/标签退化/只主炮塔)→ Task 1(0mm、`armor_faces`)+ Task 2(`MountSpecies::Main` 仅主炮)+ Task 3(退化英文)。✓

**占位符扫描**:无 TBD/TODO;每个改代码的 step 都给了完整代码块与确切命令/预期。✓

**类型一致性**:
- armor.json schema 三处一致 —— Rust 产 `{index:{hull:{zone:[{face,mm:[i64]}]}, turrets:[{name,faces:[{face,mm}]}]}}`;`render_armor._armor_sections` 读 `armor["hull"][zone]`/`f["face"]`/`f["mm"]` 与 `armor["turrets"]`/`t["faces"]`;`minimap._armor_for(index)` 按短 index 取条 —— 字段名/层级吻合。✓
- key 全程用短 index(`param.index()` ↔ `ship["index"]` ↔ `armor.json` key)。✓
- `_draw_panel`/`_panel_height`/`_PANEL_GAP`/`_HEADER_H`/`_load_ship_img` 签名与 render_ship 现有定义一致(已核实)。✓
- `MountSpecies::Main`(已核实枚举变体名,非 `Artillery`)。✓
