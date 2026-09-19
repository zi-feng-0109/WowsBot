# wows-bot

战舰世界 (WoWs) 的 QQ 机器人:接收玩家发来的 `.wowsreplay` 回放文件,
并行渲染 **小地图 MP4** + **战报 / 复盘 PNG** 一起发回 QQ;顺带一堆战舰数据
查询命令(`/船` `/线` `/查询` 等)。

![full](docs/images/example_full.png)

## 功能一览

### 回放自动渲染(收到 `.wowsreplay` 就跑)

| 产物 | 来自 | 群级开关 |
|---|---|---|
| **视频** — 小地图 MP4 | [wows-toolkit](https://github.com/landaire/wows-toolkit) 的 `minimap_renderer` (Rust) | `/视频 开\|关` |
| **战报** — 全队成绩 PNG | `report/bin/wows_report` (PIL + 自带 `replayshark`) | `/战报 开\|关` |
| **复盘** — 主角伤害分布 PNG | `report/bin/wows_damage_report` | `/复盘 开\|关` |
| **分析** — DeepSeek 中文战后复盘文本 | `report/bin/wows_analyze` | `/分析 开\|关`(需 DeepSeek key) |
| **战犯** — 败方战犯榜 PNG | `report/bin/render_criminals.py` | `/战犯 开\|关` |
| **聊天** — 本局聊天+击杀时间轴 PNG | `report/bin/render_chat.py` | `/聊天 开\|关` |

多个渲染并行跑,结果合并发出。子功能失败降级不阻塞其它,PNG 失败不影响 MP4。

### 数据查询命令(离线,无外网依赖或走 vortex)

| 命令 | 作用 |
|---|---|
| `/菜单` `/help` | 图形化功能面板 + 当前群开关状态 |
| `/查询 <#编号>` | 引用战报回复 → 查该玩家生涯战绩 PNG(走 vortex,无需 key) |
| `/船 <中文舰名>` | 战舰数值卡(火力/鱼雷/机动/隐蔽/消耗品) + 分面装甲厚度 PNG |
| `/线 <国家> <舰种>` | 整条科技树 T1→T11 PNG(含分叉、研发经验/银币价) |

### 超管命令

| 命令 | 作用 |
|---|---|
| `/sa ban\|unban <功能>` | 全局禁用/解禁某功能(高于本群开关) |
| `/渲染模式 cpu\|gpu\|状态` | MP4 渲染后端切换 |
| `/用户统计` | 触发过非菜单功能的用户榜 PNG(排除超管自身) |
| `/全群公告` `/定向公告` | 超管向所有/指定群广播 |

`/<功能> 开|关|状态` 由**群主 / 群管 / 超管**改本群开关;普通群员可查状态。

## 仓库结构

```
wows-bot/
├── README.md                       这份文档
├── docs/
│   ├── DEPLOY.md                   Linux 一站式部署
│   ├── UPDATE.md                   WoWs 大版本更新后刷新数据 / 生成 ships.json + armor.json
│   ├── REPLAYSHARK_BUILD.md        战报二进制的构建配方(基线 commit + 两个 patch)与换装闸门
│   └── images/                     示例样图
├── plugin/                         NoneBot 插件 (整个目录 cp 到你 bot 的 plugins/)
│   ├── minimap.py                  主入口 (replay → 渲染 + 命令 handler)
│   ├── permissions.py              群级开关 / 全局黑名单 / 超管识别
│   ├── query_index.py              /查询 索引 (战报 msg_id → 玩家列表)
│   ├── ship_index.py               /船 战舰名 → 数值查找 (读 ships.json)
│   ├── tech_tree.py                /线 科技树重建 (从 ships.json 的 next_ships)
│   ├── render_mode.py              /sa 渲染模式 (普通/极简/详细)
│   ├── render_backend.py           /渲染模式 CPU/GPU 切换
│   ├── user_stats.py               /用户统计 数据层
│   ├── version.py                  版本号 (env WOWS_BOT_VERSION 优先)
│   ├── wg_api.py                   vortex 接口封装 (/查询 拉生涯数据)
│   └── announcement.py             /全群公告 /定向公告
├── report/                         战报 & 战舰卡 PNG 渲染器
│   ├── bin/                        wows_full_report / wows_report / wows_damage_report / wows_analyze
│   │                               + 各种 render_*.py (船/装甲/线/穿透/战犯/聊天/用户统计)
│   ├── data/                       zh_sg.mo / ships.json / armor.json / builds.json / 图标
│   └── prebuilt/                   replayshark Linux x86_64 预编译
├── minimap/
│   └── render.sh                   MP4 渲染 wrapper (调 wows-toolkit 的 minimap_renderer)
└── tools/                          打版本数据管线 (UPDATE.md 会跑)
    ├── build_ships_json.py         GameParams + WG API + zh_sg.mo → ships.json
    ├── build_builds_json.py        舰长/技能/升级 → builds.json
    ├── fetch_ship_icons.py         下战舰预览图 → report/data/ship_icons/
    ├── fetch_build_icons.py        下升级/技能图标
    ├── render_armor_3d.py          GLB → 装甲 3D 多视角 PNG + 转圈 GIF (软件光栅)
    ├── enrich_ships_next.py        增量补 next_ships 到 ships.json
    ├── link_specs.sh               软链 report/specs → extracted/<ver>(必须传版本目录参数)
    ├── build_replayshark.sh        重建战报二进制(套两个 patch + cargo build + 自检)
    ├── verify_replayshark_equiv.sh 换装闸门:新旧二进制逐局比 JSON 与战报 PNG
    ├── rs_compare_report.py        闸门用的 JSON 比较器(规范化 + 浮点容差)
    ├── replayshark_float64.patch   给基线补 FLOAT64 实体类型支持
    └── replayshark_battle_report.patch
```

## 数据流

```
QQ 用户发 .wowsreplay
    └─> plugin/minimap.py 入队 (可并行/串行,/sa 切)
            ├─> minimap/render.sh ──> wows-toolkit minimap_renderer ──> MP4
            └─> report/bin/wows_full_report ──> replayshark + PIL ──> 战报 + 复盘 PNG
                                                                       ↓
                                       + (可选) render_criminals.py ──> 战犯 PNG
                                       + (可选) render_chat.py ──────> 聊天 PNG
                                       + (可选) wows_analyze ────────> DeepSeek 复盘文本
                                                                       ↓
                              合并成一条消息发回 QQ (MP4 上传为文件,其它作图片附下)

用户发 /船 大和 / /查询 5 / /线 美国 巡洋舰
    └─> plugin/minimap.py handler
            └─> to_thread → report/bin/render_*.py (读 ships.json/armor.json)
                                                              ↓
                                                    单张 PNG 回复
```

## 快速开始

完整部署见 [docs/DEPLOY.md](docs/DEPLOY.md);游戏大版本后刷数据见 [docs/UPDATE.md](docs/UPDATE.md)。

版本号:见 `plugin/version.py::_DEFAULT_VERSION`,当前 `1.3.0`。运行时可用 env `WOWS_BOT_VERSION` 覆盖(菜单/战报 footer 共用同一变量)。

## 上游依赖与二次开发

- **MP4 渲染** — 直接用 [landaire/wows-toolkit](https://github.com/landaire/wows-toolkit) 的 `minimap_renderer` 二进制,本仓库没改其源码,只写 `minimap/render.sh` wrapper
- **数据解包** — 用 wows-toolkit 的 `wows-data-mgr` CLI 从 WoWs 客户端 dump 出 `extracted/<ver>_<build>/`,MP4 渲染器 + 战报渲染器 + `build_ships_json.py` 共用这一份
- **战报 PNG 用的 `replayshark`** 是基于 wows-toolkit 二次开发的,补丁 `tools/replayshark_battle_report.patch` 在上游 commit 之上加了:
  - `battle-report` 子命令:replay → 结构化 JSON(玩家清单 / 伤害 / 击杀 / 消耗品 / 成就 / 结算)
  - `builds-dump` 子命令:导 GameParams 的舰长/技能/升级(给 `build_builds_json.py` 消费)
  - `Avatar.squadronConsumableUsed` 事件解析(战犯识别航母飞机消耗品)
  - 预编译在 `report/prebuilt/`,Linux x86_64 直接用;要自己编见 [REPLAYSHARK_BUILD.md](docs/REPLAYSHARK_BUILD.md)
  - ⚠️ **这个 patch 不能套在当前上游源码上**:上游 2026-06-05 的重构删掉了它挂靠的
    `BattleController`。必须切到基线 commit `2effcd31` 并且套**两个** patch
    (`replayshark_float64.patch` 在前)。一条命令:`bash tools/build_replayshark.sh`
- **`ships.json` / `armor.json`** — 打版本时预构建,运行时零外部 API。`ships.json` 每船带 数值 / 消耗品 / 科技树链 / AP 弹道参数,`armor.json` 每船带分面厚度。生成流程见 [UPDATE.md §2.6](docs/UPDATE.md)
- **Lesta 服 (.korablireplay)** — 上游 wows-toolkit 不支持,本项目也不打算适配(协议分叉)

## License

MIT — 见 [LICENSE](LICENSE)。
