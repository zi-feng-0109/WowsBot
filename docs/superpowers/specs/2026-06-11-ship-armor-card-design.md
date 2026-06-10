# `/船 <名> 装甲` 完整分面装甲图 — 实现设计

> 状态:**设计已确认**(2026-06-11),待实现。
> 数据只能从**本地客户端 GameParams 解析**,WG public API 拿不到装甲厚度
> (Mac 时已验证)。现已切到 Windows,客户端 + wows-toolkit 在手边。

## 1. 目标

新增 `/船 <中文舰名> 装甲` → 返回该船**完整分面装甲图** PNG:按装甲区
(装甲核心 / 舰艏 / 舰艉 / 上层建筑 / 主炮塔 / 操舵室 / 防雷 / 船体)分组,每区
逐个列出分面(舷侧 / 甲板 / 横向 / 倾斜…)和毫米厚度,多层厚度并列显示。

`/船 <名>` 仍是现有数值卡(火力/鱼雷/生存/消耗品),**主卡零改动**;装甲是
单独一张图,只在带 `装甲` 子参数时出。

## 2. 数据来源(已实测)

装甲厚度在 GameParams 的 `.armor` dict 里,**不是**顶层 `armour` 字段
(后者 `citadel/extremities` 全是 `[-1,-1]`,废字段,ships.json 现有的就是它)。

- `A_Hull.armor` —— 船体全船装甲(装甲带/甲板/核心/首尾各分面)。
- `A_Artillery.HP_xxx.armor` —— 每个主炮塔的炮塔装甲(正面/侧/顶/座圈/背)。
- 类型:`ArmorMap = HashMap<material_id(u32 0–254), BTreeMap<model_index(层), 厚度mm f32>>`。
- `material_id → 名字`:255 项 `COLLISION_MATERIAL_NAMES` 表(逆向自客户端,
  **版本相关**),`collision_material_name(id)`。
- `名字 → 装甲区`:`zone_from_material_name(name)` → Citadel / Casemate /
  Superstructure / Bow / Stern / Turret / SteeringGear / TorpedoProtection / Hull。

以上 `parse_armor_dict` / `collision_material_name` / `zone_from_material_name` /
per-ship `armor_map()` / per-turret `mount_armor()` 在 wows-toolkit 里**都是现成
的 `pub` 接口**(`crates/wowsunpack/src/...`),本设计直接复用,不重写解析。

### 数据完整性局限(必须知晓)

`.armor` dict 是**按命名 material 的厚度**(大和 71 项 / 36 项非零),覆盖所有
**有名字的分面**——正是分面图要的。但游戏极细的逐三角默认蒙皮厚度走加密
Python 脚本,不在 dict 里,本装甲图**不含这部分**。口径与 wows-toolkit 自带
装甲查看器、社区工具一致。

## 3. 数据流

```
本地 GameParams.data
   │  replayshark armor-dump   (新 Rust 子命令)
   ▼
report/data/armor.json         ← 新文件,只给装甲图用
   │  render_armor.py 读取
   ▼
/船 <名> 装甲  →  装甲分面 PNG
```

**决定:装甲数据单独存 `report/data/armor.json`,不并进 ships.json。**
数据量大且 `/船` 主卡用不到;分开后主卡路径零改动、ships.json 保持精简。
ships.json 里废掉的 `armour:{-1}` 字段维持原样(不在本次范围内处理)。

## 4. Rust 侧:`replayshark armor-dump` 子命令

放在 `crates/replayshark/src/main.rs`,照已有 `BattleReport` / `ConsumablesDump`
的「读 GameParams → 输出 JSON」模式(`--extracted` 指 GameParams,`-o` 输出,
默认 stdout)。

逻辑:
1. 加载 GameParams,遍历所有船(同 ConsumablesDump 的 provider 用法)。
2. 每船取 `armor_map()`(船体)+ 各主炮塔 `mount_armor()`(炮塔)。
3. 每个 `material_id` → `collision_material_name(id)` → `zone_from_material_name(name)`。
4. 多层厚度 = 内层 `BTreeMap` 的各 value;**过滤掉 0mm**(如 TurretDown 第二层=0)。
5. 跳过完全无装甲数据的船(航母/潜艇等可能没 hull armor)。

输出 schema(key = 短 index `PJSB018`,跟 ships.json 的 `index` 字段一致 ——
**不是**内部名 `PJSB018_Yamato`;渲染侧 `armor.json[ship["index"]]` 直接查):
```jsonc
{
  "PJSB018": {
    "hull": {
      "Citadel":  [ {"face": "Cit_Belt", "mm": [410]}, {"face": "Cit_Deck", "mm": [200]} ],
      "Bow":      [ {"face": "Bow_Belt", "mm": [60]} ]
      // ... 其余装甲区
    },
    "turrets": [
      { "name": "主炮", "faces": [ {"face": "TurretFront", "mm": [650]},
                                   {"face": "TurretSide",  "mm": [250]} ] }
    ]
  }
}
```
- `face` 用英文 material 名(语言无关);中文化在渲染侧做。
- 同一 zone 内多个 material → 数组多项;同名多层 → `mm` 多元素。
- 同口径/同型号炮塔去重(只输出一种主炮,不每个 mount 重复)。

## 5. Python 构建侧

`armor.json` 由 `armor-dump` 直接产出,**build_ships_json.py 不改动**。
数据刷新流程加一步(写进 `docs/UPDATE.md`,紧跟现有 ConsumablesDump 那步):
```
replayshark.exe --extracted <GameParams 目录> armor-dump -o report/data/armor.json
```

## 6. 渲染侧:`report/bin/render_armor.py`(新建,库 + CLI)

复用 `render_query` 的调色板 / 字体 / `_draw_footer` / `_font`,风格同 `render_ship`。

库用法:
```python
from render_armor import render_armor_png
render_armor_png(out_path, ship=<ships.json 一条>, armor=<armor.json 一条>)
```
CLI(调试):
```
python render_armor.py <out.png> --ship-id <index>        # 从 ships.json + armor.json 查
```

**布局**:
- Header:复用 `/船` 卡的 `Txx` 徽标 + 中文名 + 英文/舰种/国家 + 右侧预览图。
- 主体:每个**装甲区**一个圆角面板(同 `render_ship._draw_panel` 风格),面板标题
  = 中文区名,面板内逐行列「分面中文名 + 厚度」。多层厚度显示成 `370 / 350`。
- 主炮塔单独成区(每种主炮一个面板:正面 / 侧面 / 顶部 / 座圈 / 背面)。
- 动态高度(同 `render_ship`,按区数/分面数累加)。

**中文标签表**(放渲染侧,Rust 输出保持英文):
- 装甲区:`Citadel→装甲核心`、`Casemate→炮郭`、`Superstructure→上层建筑`、
  `Bow→舰艏`、`Stern→舰艉`、`Turret→主炮塔`、`SteeringGear→操舵室`、
  `TorpedoProtection→防雷`、`Hull→船体`。
- 分面:`*Belt→舷侧`、`*Deck→甲板`、`*Trans→横向`、`*Inclin→倾斜`、
  `*Bottom→底部`、`TurretFront→正面`、`TurretSide→侧面`、`TurretTop→顶部`、
  `*Barbette→座圈`、`TurretAft→背面` 等。映射不命中时**退化显示原英文名**
  (保证新版本加的 material 不会丢,只是没中文)。

## 7. 命令解析(`plugin/minimap.py`)

现有 `/船` handler 解析参数:若**末位参数 == `装甲`**,分流到装甲渲染,
其余参数当舰名(`/船 大和 装甲`)。**不新增独立指令、不加别名**(已确认)。

- 装甲渲染:舰名走现有 `/船` 的消歧/查找逻辑定位 index → 读 `armor.json[index]`
  → `to_thread` 渲染 → 发图。
- 兜底:`armor.json` 无该船 → 「该船暂无装甲数据」;舰名识别失败 → 复用 `/船`
  现有消歧文案。
- `armor.json` 文件缺失(没跑过 dump)→ 「装甲数据未生成」(类比 ships.json 缺失文案)。

菜单(`render_menu.py`【全部指令】)`/船` 那行补用法:`/船 <名> 装甲 查装甲分面`。

## 8. 文件清单

- 新 `crates/replayshark/src/main.rs`:加 `ArmorDump` 子命令(+ 装甲 dump 逻辑,
  可单列一个 `armor_dump.rs` 模块保持 main 精简)。重编 `replayshark.exe`。
- 新 `report/data/armor.json`:`armor-dump` 产出。
- 新 `report/bin/render_armor.py`:`render_armor_png` 库 + CLI + 中文标签表。
- 改 `plugin/minimap.py`:`/船` handler 加 `装甲` 子参数分流 + 兜底文案。
- 改 `report/bin/render_menu.py`:`/船` 行补装甲用法。
- 改 `docs/UPDATE.md`:刷新流程加 `armor-dump` 一步。
- 改 `docs/DEPLOY.md`:插件/数据文件清单 +`render_armor.py`、`armor.json`。

## 9. 测试与验证

- **Rust**:`armor-dump` 对大和/依阿华跑通,核对已知值(文档 Patrie 炮塔
  TurretFront 590、Slava `Cit_Belt` 370、大和约 71 项);0mm 已过滤;炮塔去重生效。
- **Python**:`render_armor.py` CLI 出图肉眼验 ——
  1. 大和(满分面,多区多层)布局不错位;
  2. 某驱逐(薄甲、分面少)正常;
  3. 某航母/无 hull armor 船 → 渲染兜底或被命令层挡掉。
- **端到端**:`/船 大和 装甲` 群里出图;`/船 <无数据船> 装甲` 出兜底文案;
  `/船 大和`(无子参数)仍是原数值卡、未受影响;`/菜单` 新用法行不错位。

## 10. 边界

- 多层厚度全列(不只取最大),`370 / 350` 形式。
- 0mm 分面丢弃。
- 中文标签不命中 → 退化英文,不崩、不丢数据。
- 255 material 表版本相关:由 wows-toolkit 单一维护(不在 Python 复刻),
  随客户端 RE 更新。
- 仅主炮塔装甲入图(`A_Artillery`);副炮(`A_ATBA`)装甲本次不做(YAGNI)。
