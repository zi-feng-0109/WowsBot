# P2:bot 公共层(标准化 + 简洁化)

日期:2026-09-17
状态:设计已确认,待实施

## 背景

bot 仓库(`/opt/wows-bot`)的 Python 代码没有公共层,同一类知识散落在多处:

- **路径/配置常量 78 处**,分布在 12 个文件里各写各的 `os.environ.get(...)`
  (`plugin/minimap.py` 一个人 20 处)。其中有脆弱写法:
  `SHIPS_JSON = Path(REPORT_FULL_CMD).parent.parent / "data" / "ships.json"`
  —— 从**命令路径**推**数据路径**;还有个 `REPORT_CMD` 旧 alias 注释写着"后续清理"。
  `tools/build_builds_json.py` / `fetch_build_icons.py` 的默认路径**错了一层**
  (指向 `/opt/wows-bot/replayshark` 和 `/opt/wows-bot/specs`,真实位置在 `report/` 下),
  所以每次刷 builds.json 都得手动带 `--specs` 和 `WOWS_REPLAYSHARK=`。
- **"读 replay 头拿 build" 有 3 份手写实现**:`report/bin/wows_report`、
  `plugin/minimap.py`、以及网站的 `replay_jobs.py`(网站属 P1 范围,本次不动)。
- **`render_battle_report.py`(887 行渲染器)被当公共库用**:6 个 render 脚本从它
  import 两类东西 —— theme 常量(字体 + 调色板)和 8 个文本/数据 helper。

后果:改一处要记得改多处(2026-09-10 把「聊天」默认值改开时就被迫改两个文件);
知识没有单一真源,新增 consumer 只能靠抄。

## 目标

1. 路径/配置有唯一声明表,代码不再散着读 env。
2. 回放元数据解析只有一份实现,且有测试。
3. `render_battle_report.py` 不再兼职公共库 —— 其它脚本零依赖它。
4. **行为完全不变**:渲染出的图逐字节一致;env 变量名全部保持兼容。

## 非目标(明确不做)

- 不改表现形式:渲染逻辑、图像外观、消息文案一行不动。
- 不改使用方式:**现有 env 变量名全部继续生效**(含 deprecated 的 `WOWS_REPORT_CMD`),
  部署时 `.env` 一行不用改。
- 不做性能优化。
- 不动 `permissions.FEATURES` / `DEFAULT_ENABLED` 与 `render_menu.py` 的重复
  —— `render_menu` 需要脱离 nonebot 独立运行,当初复制是有理由的(经确认保留)。
- 不动 Rust 侧:`wows-toolkit` 等基本是上游代码,我们的改动很小,没有标准化空间。
- 不动网站:bot↔web 的 6 处手抄重复是 P1,独立一份 spec。

## 架构

```
report/lib/wowsbot/
├── __init__.py
├── paths.py    env/路径唯一声明表
├── replay.py   回放元数据
├── theme.py    字体 + 调色板
├── text.py     纯字符串处理
├── i18n.py     翻译(读 .mo,有全局缓存)
└── results.py  结算字段访问(读 constants.json)
```

### 为什么放 `report/lib/` 而不是别处

- **不能做 pip 可安装包**:`wows_report::find_python()` 证明运行时存在多个 Python
  环境(`WOWS_PYTHON` 覆盖 / `WOWS_PY_VENV` / `BOT_HOME/venv` / 系统 `python3`),
  可安装包要往每个环境各装一份,部署复杂且易漏。纯 `sys.path` 方案对所有环境一致生效。
- **不平铺进 `report/bin/`**:那里混着可执行脚本(`wows_report` 等无扩展名文件)。
  独立目录让库与可执行物理分离,而且 **P1 给网站共享时可以 submodule/vendor 一整个目录**,
  不必从 `bin/` 里挑文件。

### 模块边界

| 模块 | 职责 | 导出 |
|---|---|---|
| `paths` | 所有路径/开关的声明与派生 | `BOT_HOME` + 分组常量(见下) |
| `replay` | 回放文件头解析 | `read_meta(p)` `build_of(p)` `version_of(p)` `is_lesta(p)` `available_builds(root)` |
| `theme` | 视觉常量 | `CJK_FONT` `MONO_FONT` `GAME_BG/PANEL/PANEL_ALT/GREEN/RED/GOLD/PURPLE/TEXT/DIM/BORDER` |
| `text` | 纯字符串函数 | `strip_known` `strip_id` `clean_ship_name` `fmt_time` |
| `i18n` | 翻译加载与查询 | `load_translations()` `t(key)` |
| `results` | 结算数组按名取值 | `load_result_indices()` `result_field(...)` |

**硬约束**:`wowsbot/` 内不得 import `nonebot`、不得 `subprocess`、不得做 PIL 绘图。
只放纯函数、常量、以及必要的只读文件加载。理由:三类 consumer(nonebot 环境的
`plugin/*`、venv 环境的 `report/bin/*`、以及将来 P1 的网站)必须都能 import 同一份。

`i18n` 和 `results` 有 I/O + 全局缓存,所以跟纯函数的 `text` 分开,避免测试互相牵连。

### `paths.py` 的形态

一张声明表,每项写清「env 名 + 默认值 + 用途」,按用途分组:

- **根**:`BOT_HOME`(env `WOWS_BOT_HOME`,默认 `/opt/wows-bot`)
- **二进制**:`replayshark` / `replayshark-lesta` / minimap(`WOWS_TOOLKIT_BIN`)
- **目录**:`specs` / `extracted`(`WOWS_DATA_DIR`) / `specs-patched` / 回放工作目录
- **命令**:`report/bin/*` 各入口
- **数据文件**:`ships.json` / `armor.json` / `builds.json` / `constants.json` / `zh_sg.mo`

规则:**数据路径一律从 `BOT_HOME` 派生**,禁止从命令路径 `.parent.parent` 反推。
现有 env 名全部保留读取(包括 deprecated 的),值与现状逐一对齐。

### bootstrap 惯例

三类 consumer 各一行,且都不新增样板量(它们原本就有 `sys.path.insert`):

- `report/bin/*`:`sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))`
- `plugin/*`:被 `cp` 到 EssexBot 目录,`Path(__file__)` 找不到仓库,只能用
  `os.environ.get("WOWS_BOT_HOME", "/opt/wows-bot") + "/report/lib"`(与现状硬编码
  `/opt/wows-bot` 一致,不是新增假设)
- `tools/*`:`Path(__file__).resolve().parent.parent / "report" / "lib"`

顺手把 `plugin/minimap.py` 里 7 处重复的 `sys.path.insert(<report/bin>)` 收成一个 helper。

## 改动清单

| 类型 | 文件 | 内容 |
|---|---|---|
| 新增 | `report/lib/wowsbot/*.py` | 6 模块 + `__init__.py` |
| 新增 | `tests/test_wowsbot_*.py` | 见下「验证」 |
| 收路径 | `plugin/minimap.py`(20) | 删常量声明,改用 `paths`;删自写 build 解析,改用 `replay.build_of`;7 处 sys.path 样板收成 helper |
| 收路径 | `report/bin/wows_report`(10) | 同上(含 build 解析) |
| 收路径 | `report/bin/wows_full_report_normalized`(8) `wows_full_report`(5) `wows_damage_report`(5) `wows_menu`(3) | 改用 `paths` |
| 抽库 | `report/bin/render_battle_report.py`(11 处路径) | theme/text/i18n/results 搬进 `wowsbot`,本文件改为 import;**绘图逻辑一行不动** |
| 换 import | `render_chat` `render_criminals` `render_damage_chart` `render_menu` `render_query` `render_consumables_chart` | `from render_battle_report import ...` → `from wowsbot import ...` |

**不保留兼容 re-export**:`render_battle_report.py` 搬走后不再从自身导出这些符号,
所有 6 个 consumer 的 import 一次改净(靠验证第 6 条的零残留 grep 兜底)。留 shim 会让
依赖关系继续隐形存在,与本 spec 目标相反。
| 收路径 | `tools/build_builds_json.py` `fetch_build_icons.py` `build_ships_json.py` `fetch_ship_icons.py`(各 2) | 改用 `paths`,**顺手修掉默认路径错一层**的老坑 |

## 验证(逐条都要有证据)

1. **渲染图逐字节比对(核心证据)**:重构前先跑一批 fixture 存基线 PNG 的 sha256;
   重构后重跑,**sha256 必须完全一致**。任何不一致都视为回归,不允许"看起来一样"就放过。
   - 输入固定:**同一份 WG 回放**(15.8 build 13187581 那场)跑战报 / 复盘 / 战犯 / 聊天;
     菜单用固定的 state 快照(复用 `tests/test_render_menu.py` 里那三种);查询用固定
     player JSON。图像里若含时间戳等易变量,先固定环境变量或时间源再取基线。
   - 基线与结果都落在 `/tmp`,不入库;spec 实施时把 sha256 对照表贴进 PR/提交说明。
2. **现有 3 个测试全过**:`test_permissions` / `test_render_armor` / `test_render_menu`。
3. **新增单测**:
   - `replay.build_of` / `version_of` / `is_lesta`:用真实回放验(本机有 15.7 build
     13015811、15.8 build 13187581、Lesta build 8857866,build 号已知);
     损坏文件与空文件返回 `None` 而不抛异常。
   - `replay.available_builds`:临时目录造 `<ver>_<build>/` 与噪声目录(`common`、
     `vfs_common`),断言只认版本目录。
   - `paths`:断言 env 覆盖生效、未设时取默认值、数据路径由 `BOT_HOME` 派生。
4. **依赖纯净性**:grep 断言 `report/lib/wowsbot/` 内不出现 `nonebot`、`subprocess`、
   `ImageDraw`。
5. **多环境冒烟**:nonebot venv 与 report venv 各 `import wowsbot` 一次。
6. **零残留**:`grep -r 'from render_battle_report import' report/ plugin/` 必须为空。

## 风险与对策

| 风险 | 对策 |
|---|---|
| 搬迁过程中悄悄改了行为(最大风险) | 第 1 条的 sha256 比对是硬门槛;搬迁只做机械移动,不顺手"改进"逻辑 |
| 漏改某个 consumer 的 import | 第 6 条零残留 grep + 现有测试 |
| `plugin/*` 被 cp 后找不到 lib | bootstrap 用 `WOWS_BOT_HOME`(与现状硬编码一致);部署后冒烟一次 |
| 某个 env 名对齐时抄错默认值 | 逐项对照原文件写进声明表,并在 spec 实施阶段列一张「旧值 → 新表」核对表 |

## 部署

只改 Python:`git pull` → `cp plugin/*.py <EssexBot>/src/plugins/` → 重启 nonebot。
`report/bin/*` 与 `report/lib/*` 是 subprocess 现拉,不需重启。**`.env` 一行不用改。**

## 后续(不在本 spec 内)

- **P1**:消灭 bot↔web 6 处手抄重复(网站 `replay_jobs.py` / `report_cooked.py` /
  `damage_categories.py` / `ribbons.py` / `ap_curve.py` / `constants_data.py`)。
  本 spec 的 `wowsbot` 目录就是 P1 的共享载体。
- **P3**:`plugin/minimap.py`(1658 行、约 15 个职责)按域拆分。
- **P4**:更新流程自动化(FLOAT64 手术 + link_specs + builds.json 刷新)。
- **P5**:统一报告管线、弃用旧预编译 replayshark —— ⚠️ 会改变战报外观,与"不涉及
  表现形式"冲突,需单独决策。
