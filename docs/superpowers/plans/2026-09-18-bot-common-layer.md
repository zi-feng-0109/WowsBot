# bot 公共层(P2)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 bot 仓散在 12 个文件里的 78 处路径/配置常量、3 份重复的 replay build 解析、以及 `render_battle_report.py` 兼职的公共库(theme + 文本/数据 helper + 中文标签表)收进 `report/lib/wowsbot/` 下 6 个单一职责模块,行为与渲染结果完全不变。

**Architecture:** 纯 `sys.path` 共享库(不做 pip 包 —— 运行时存在多个 Python 环境)。`wowsbot/` 只放常量与纯函数,禁止 import `nonebot` / `subprocess` / PIL 绘图,以便 nonebot 环境的 `plugin/*`、venv 环境的 `report/bin/*`、以及将来 P1 的网站都能 import 同一份。env 变量名全部保持兼容,部署时 `.env` 一行不用改。

**Tech Stack:** Python 3.11+、PIL(仅渲染器侧)、polib(翻译)。测试沿用仓库现有风格:**纯 assert + print + `__main__` 块,不引入 pytest**(仓库无依赖声明文件,现有 3 个测试都是 `python tests/test_x.py` 直接跑)。

**Spec:** `docs/superpowers/specs/2026-09-17-bot-common-layer-design.md`

---

## 关键背景(实施前必读)

### 1. `BOT_HOME` 同名不同义 —— 要修的核心混乱

| 位置 | `Path(__file__).resolve().parent.parent` 实际指向 |
|---|---|
| `report/bin/wows_report` 等 | **`<repo>/report/`** → `BOT_HOME / "replayshark"` = `report/replayshark` ✅ |
| `tools/build_builds_json.py` 等 | **`<repo>/`(仓库根)** → `BOT_HOME / "replayshark"` = `<repo>/replayshark` ❌ |

后果:`tools/build_builds_json.py` 的 `DEFAULT_SPECS` / `DEFAULT_REPLAYSHARK` 少了一层 `report/`,而同一文件里的 `DEFAULT_MO` / `DEFAULT_OUT` 又写对了(`BOT_HOME / "report" / "data" / ...`)。所以刷 builds.json 必须手动带 `WOWS_REPLAYSHARK=... --specs ...`。

**本计划用两个不会混淆的名字取代它:`REPO_ROOT`(仓库根)/ `REPORT_ROOT`(= `REPO_ROOT/report`)。**

### 2. 同一目录被两个 env 名读取

`/var/lib/wows-data/extracted` 在 `plugin/minimap.py` 与 `render_chat.py` 里走 `WOWS_DATA_DIR`,在 `report/bin/wows_report` 里走 `WOWS_EXTRACTED_ROOT`,默认值相同。`paths.py` 两个都读(前者优先级低),并在 Task 0 Step 2 验证生产 `.env` 没把两者设成不同值。

### 3. 类型必须逐项对齐

原常量有 `str`、有 `Path`、有 `int`(`int(os.environ.get("WOWS_MP4_TIMEOUT", "600"))`),`BASE_DIR` 还过了 `os.path.expanduser`。`paths.py` **保持与原常量相同的值和类型**,consumer 只删声明换 import,不做类型转换。

### 4. 空字符串语义

必须用 `os.environ.get(name, default)`,**不要**写 `os.environ.get(name) or default` —— 前者在 env 设为空串时返回空串,后者返回默认值。

### 5. footer 里有分钟级时间戳 —— sha256 比对必须跳过 footer

`render_battle_report.py::_draw_footer` 画了 `datetime.now().strftime("%Y-%m-%d %H:%M")`,
所以**隔一分钟渲染同一份输入,PNG 的 sha256 就不同**。Task 0 执行时实测踩到:两次紧挨着
渲染哈希相同(同一分钟),隔几分钟再渲就变了。

已严格验证差异只来自 footer:两次相隔数分钟的渲染,各裁掉底部 48px 后**正文逐字节一致**,
仅 footer 区不同;而 `datetime` 在三个渲染器里**只出现在 footer**
(`render_battle_report.py` 第 858/869 行),所以关掉 footer 后整图完全确定。

因此**所有 fixture 渲染统一走 `tools/p2_render_fixtures.sh`**,它固定
`WOWS_SKIP_FOOTER=1` + 字体 + `WOWS_BOT_VERSION`。基线与后续每次检查必须用**完全相同的
调用**,抄多份命令必然漂移 —— 这是脚本存在的理由,不是风格偏好。
该脚本是重构期脚手架,Task 11 删除。

### 6. 两种 import 形式都要处理

- 6 个脚本用 `from render_battle_report import (...)` —— 全部改为从 `wowsbot` 取。
- 2 个脚本用 `import render_battle_report as rb`(`render_report_normalized.py` / `render_review_normalized.py`),它们既取 theme 常量/标签表(要改),又用 `rb.render` `rb.load` `rb.MatchReport` `rb.PlayerStats` `rb.font` `rb.load_achievements` `rb._ACH_ID_TO_INDEX`(**合法保留,不动**)。

---

## File Structure

**新增**

| 文件 | 职责 |
|---|---|
| `report/lib/wowsbot/__init__.py` | 空(仅标记包);不 re-export,避免 import 一个模块牵连有 I/O 的模块 |
| `report/lib/wowsbot/paths.py` | 所有路径/开关的唯一声明表 |
| `report/lib/wowsbot/replay.py` | 回放文件头解析:`read_meta` `build_of` `version_of` `is_lesta` `available_builds` |
| `report/lib/wowsbot/theme.py` | `CJK_FONT` `MONO_FONT` + `GAME_*` 调色板(**无 PIL 依赖**) |
| `report/lib/wowsbot/text.py` | 纯字符串:`strip_id` `strip_known` `relation_name` `clean_ship_name` `fmt_time` |
| `report/lib/wowsbot/i18n.py` | `load_translations` `t` + `SPECIES_SHORT` `DEATH_CAUSE_CN` `MATCH_GROUP_CN` |
| `report/lib/wowsbot/results.py` | `load_result_indices` `result_field` |
| `tests/test_wowsbot_paths.py` | paths 的 env 覆盖 / 默认值 / 派生规则 |
| `tests/test_wowsbot_replay.py` | 真实回放的 build/version/lesta 判定 + 边界 |
| `tests/test_wowsbot_lib.py` | theme / text / i18n / results 行为 |

**修改**

| 文件 | 改什么 |
|---|---|
| `report/bin/render_battle_report.py` | 搬出 theme/text/i18n/results;**绘图逻辑一行不动** |
| `render_chat.py` `render_criminals.py` `render_damage_chart.py` `render_menu.py` `render_query.py` `render_consumables_chart.py` | `from render_battle_report import ...` → `from wowsbot...` |
| `render_report_normalized.py` `render_review_normalized.py` | 只换 `rb.` 取的 theme 常量与标签表 |
| `wows_report` `wows_full_report` `wows_full_report_normalized` `wows_damage_report` `wows_menu` | 常量收进 `paths`;`wows_report` 的 build 解析换 `replay` |
| `plugin/minimap.py` | 常量收进 `paths`;build 解析换 `replay`;7 处 `sys.path.insert` 收成 helper |
| `tools/build_builds_json.py` `fetch_build_icons.py` `build_ships_json.py` `fetch_ship_icons.py` | 常量收进 `paths`,**顺带修掉默认路径错一层** |

---

## Task 0: 建立渲染基线(必须最先做)

没有基线就无法证明"行为不变"。本任务不改任何代码。

**Files:** Create `/tmp/p2_baseline/`(不入库)+ `docs/superpowers/plans/2026-09-18-p2-baseline.sha256`

- [ ] **Step 1: 固定测试输入**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
mkdir -p /tmp/p2_baseline
ls -la "/c/Program Files (x86)/Steam/steamapps/common/World of Warships/replays/"*.wowsreplay | tail -3
```

挑一场 15.8 回放,路径写进文件供后续任务复用:

```bash
echo '/c/Program Files (x86)/Steam/steamapps/common/World of Warships/replays/20260910_201307_PVSD016-Cervantes_46_Estuary.wowsreplay' > /tmp/p2_baseline/replay.txt
test -f "$(cat /tmp/p2_baseline/replay.txt)" && echo REPLAY_OK
```

Expected: 打印 `REPLAY_OK`。若该回放已不存在,换任意一场 15.8 回放并更新此文件。

- [ ] **Step 2: 核对生产 .env(风险 2 的验证,在 bot 服务器上跑)**

```bash
grep -nE 'WOWS_(DATA_DIR|EXTRACTED_ROOT|SPECS_DIR|SPECS_PATCHED_ROOT|REPLAYSHARK|REPLAYSHARK_LESTA|REPORT_CMD|REPORT_FULL_CMD|REPORT_BATTLE_CMD|REPORT_DAMAGE_CMD|REPORT_FULL_LESTA_CMD|ANALYZE_CMD|RENDER_SH|RENDER_PY|RENDER_CHAT|RENDER_CRIMINALS|SHIPS_JSON|ARMOR_JSON|BUILDS_JSON|CONSTANTS_JSON|ACHIEVEMENTS_JSON|ACHIEVEMENT_ICONS|TRANSLATIONS_MO|CJK_FONT|MONO_FONT|OUT_DIR|REPLAY_BASEDIR|BOT_HOME|PYTHON|PY_VENV|TOOLKIT_BIN|MP4_TIMEOUT|PNG_TIMEOUT|ANALYZE_TIMEOUT)' ~zifeng/桌面/bot/EssexBot/.env
```

Expected: 列出生产实际设置。**判据:若 `WOWS_DATA_DIR` 与 `WOWS_EXTRACTED_ROOT` 同时出现且值不同,停下来找用户确认**(合并优先级会改变其中一方行为)。只出现一个或都没有 → 安全。把输出贴进执行记录。

- [ ] **Step 3: 产出 fixture 输入 JSON**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
T="$(python -c 'import tempfile;print(tempfile.gettempdir())')"
mkdir -p "$T/p2_baseline"
RS=/c/Users/29801/Desktop/minimap/wows-toolkit/target/release/replayshark.exe
EX=/c/Users/29801/Desktop/minimap/wows-toolkit/extracted
"$RS" -e "$EX" battle-results --format normalized --allow-approximate-constants   --out-file "$T/p2_baseline/report.json" "$(cat /tmp/p2_baseline/replay.txt)"
ls -la "$T/p2_baseline/report.json"
```

Expected: JSON 生成(约 260KB)。**注意本机 Python 是 Windows 版,认不了 `/tmp`,所以
路径用 `tempfile.gettempdir()` 取真实 TEMP;Bash 侧的 `/tmp` 与它指向同一处。**

- [ ] **Step 4: 用统一脚本渲染基线并记录 sha256**

渲染一律走 `tools/p2_render_fixtures.sh`(理由见「关键背景 5」)。

```bash
cd /c/Users/29801/Desktop/wows-bot-review
T="$(python -c 'import tempfile;print(tempfile.gettempdir())')"
bash tools/p2_render_fixtures.sh "$T/p2_baseline_fix"
```

Expected: 打印两行 sha256,两个 PNG 都 > 5KB。

再验确定性(渲到另一个目录,哈希必须一致):

```bash
bash tools/p2_render_fixtures.sh "$T/p2_det_check" >/dev/null
diff "$T/p2_baseline_fix/fixtures.sha256" "$T/p2_det_check/fixtures.sha256" && echo DETERMINISTIC_OK
```

Expected: `DETERMINISTIC_OK`。**这是后续每个改动任务的验收凭据。**


- [ ] **Step 5: 记录改动前的测试状态**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
python tests/test_permissions.py && python tests/test_render_menu.py && python tests/test_render_armor.py
```

Expected: 三个都打印 `== ALL PASS ==`。本来就红的记录下来,不算本次回归。

- [ ] **Step 6: 提交基线清单**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
T="$(python -c 'import tempfile;print(tempfile.gettempdir())')"
cp "$T/p2_baseline_fix/fixtures.sha256" docs/superpowers/plans/2026-09-18-p2-baseline.sha256
git add docs/superpowers/plans/2026-09-18-p2-baseline.sha256 tools/p2_render_fixtures.sh
git commit -m "test(p2): 记录重构前渲染基线 sha256 + 确定性渲染脚本"
```

---

## Task 1: `wowsbot` 包骨架 + `paths.py`

**Files:**
- Create: `report/lib/wowsbot/__init__.py`, `report/lib/wowsbot/paths.py`
- Test: `tests/test_wowsbot_paths.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_wowsbot_paths.py
"""wowsbot.paths 测试 —— env 覆盖 / 默认值 / 派生规则。
无 pytest 依赖,纯 assert + print。用法: python tests/test_wowsbot_paths.py"""
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "report" / "lib"))


def _fresh(**env):
    """在指定 env 下重新导入 paths(模块级常量只在 import 时求值)。

    传 None 表示删除该 env。调用结束恢复原值,避免测试互相污染。
    """
    saved = {k: os.environ.get(k) for k in env}
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        import wowsbot.paths as p
        return importlib.reload(p)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


_ALL = dict(WOWS_BOT_HOME=None, WOWS_DATA_DIR=None, WOWS_EXTRACTED_ROOT=None,
            WOWS_REPLAYSHARK=None, WOWS_SPECS_DIR=None, WOWS_SHIPS_JSON=None,
            WOWS_MP4_TIMEOUT=None, WOWS_PNG_TIMEOUT=None)


def test_defaults_derive_from_repo_root():
    """断言派生规则,而不是硬编码字符串 —— Windows 上 Path 产出反斜杠,
    硬编码 "/opt/..." 的断言在开发机上必然失败。"""
    p = _fresh(**_ALL)
    root = p.REPO_ROOT
    # 未设 WOWS_BOT_HOME 时,根从库自身位置推导,应指向本仓库
    assert (root / "report" / "lib" / "wowsbot" / "paths.py").is_file(), root
    assert p.REPORT_ROOT == root / "report", p.REPORT_ROOT
    # 数据路径从 REPORT_ROOT 派生,不从命令路径反推
    assert p.SHIPS_JSON == str(root / "report" / "data" / "ships.json"), p.SHIPS_JSON
    assert p.ARMOR_JSON == str(root / "report" / "data" / "armor.json"), p.ARMOR_JSON
    # 二进制/specs 在 report/ 下 —— 修掉 tools/ 里错一层的老坑
    assert p.REPLAYSHARK == str(root / "report" / "replayshark"), p.REPLAYSHARK
    assert p.SPECS_DIR == str(root / "report" / "specs"), p.SPECS_DIR
    assert p.REPORT_FULL_CMD == str(root / "report" / "bin" / "wows_full_report"), p.REPORT_FULL_CMD
    # extracted 是绝对路径常量,与仓库位置无关
    assert p.EXTRACTED_ROOT == "/var/lib/wows-data/extracted", p.EXTRACTED_ROOT
    print("  test_defaults_derive_from_repo_root PASS")


def test_bot_home_override_moves_everything():
    p = _fresh(**{**_ALL, "WOWS_BOT_HOME": "/srv/bot"})
    root = Path("/srv/bot")
    assert p.REPO_ROOT == root, p.REPO_ROOT
    assert p.REPLAYSHARK == str(root / "report" / "replayshark"), p.REPLAYSHARK
    assert p.SHIPS_JSON == str(root / "report" / "data" / "ships.json"), p.SHIPS_JSON
    print("  test_bot_home_override_moves_everything PASS")


def test_explicit_env_beats_derived():
    p = _fresh(**{**_ALL, "WOWS_REPLAYSHARK": "/custom/rs",
                 "WOWS_SHIPS_JSON": "/custom/ships.json"})
    assert p.REPLAYSHARK == "/custom/rs"
    assert p.SHIPS_JSON == "/custom/ships.json"
    print("  test_explicit_env_beats_derived PASS")


def test_extracted_root_reads_both_names():
    # 老名字 WOWS_DATA_DIR 仍生效(minimap.py / render_chat.py 一直用它)
    p = _fresh(**{**_ALL, "WOWS_DATA_DIR": "/data/a"})
    assert p.EXTRACTED_ROOT == "/data/a", p.EXTRACTED_ROOT
    # 两者同时存在时新名字优先
    p = _fresh(**{**_ALL, "WOWS_DATA_DIR": "/data/a", "WOWS_EXTRACTED_ROOT": "/data/b"})
    assert p.EXTRACTED_ROOT == "/data/b", p.EXTRACTED_ROOT
    print("  test_extracted_root_reads_both_names PASS")


def test_empty_string_env_is_kept():
    # os.environ.get(name, default) 语义:设成空串就是空串,不回落默认值
    p = _fresh(**{**_ALL, "WOWS_REPLAYSHARK": ""})
    assert p.REPLAYSHARK == "", repr(p.REPLAYSHARK)
    print("  test_empty_string_env_is_kept PASS")


def test_timeouts_are_ints():
    p = _fresh(**{**_ALL, "WOWS_PNG_TIMEOUT": "123"})
    assert p.MP4_TIMEOUT == 600 and isinstance(p.MP4_TIMEOUT, int)
    assert p.PNG_TIMEOUT == 123 and isinstance(p.PNG_TIMEOUT, int)
    print("  test_timeouts_are_ints PASS")


def test_no_forbidden_imports():
    src = (ROOT / "report" / "lib" / "wowsbot" / "paths.py").read_text(encoding="utf-8")
    for bad in ("nonebot", "subprocess", "ImageDraw"):
        assert bad not in src, f"paths.py 不该出现 {bad}"
    print("  test_no_forbidden_imports PASS")


if __name__ == "__main__":
    print("== test_wowsbot_paths ==")
    test_defaults_derive_from_repo_root()
    test_bot_home_override_moves_everything()
    test_explicit_env_beats_derived()
    test_extracted_root_reads_both_names()
    test_empty_string_env_is_kept()
    test_timeouts_are_ints()
    test_no_forbidden_imports()
    print("== ALL PASS ==")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /c/Users/29801/Desktop/wows-bot-review && python tests/test_wowsbot_paths.py`
Expected: `ModuleNotFoundError: No module named 'wowsbot'`

- [ ] **Step 3: 建包 + 写 paths.py**

`report/lib/wowsbot/__init__.py`:

```python
"""wowsbot —— bot 的公共层(路径/回放元数据/主题/文本/翻译/结算字段)。

故意留空:不在这里 re-export 子模块,避免 `from wowsbot import paths` 牵连加载
i18n(要读 .mo)、results(要读 constants.json)等有 I/O 的模块。
用法一律 `from wowsbot import paths` / `from wowsbot.theme import GAME_BG`。
"""
```

`report/lib/wowsbot/paths.py`:

```python
"""所有路径/开关的唯一声明表。

为什么需要它:重构前 78 处 os.environ.get 散在 12 个文件里,而且 `BOT_HOME` 这个
名字在两处含义不同 —— report/bin/* 里指 `report/`,tools/* 里指仓库根。同名不同义
直接造成 tools/build_builds_json.py 的 --specs / --replayshark 默认值少一层
`report/`(同文件的 DEFAULT_MO / DEFAULT_OUT 又是对的),所以刷 builds.json 每次
都得手动带参数。这里改用两个不会混淆的名字:REPO_ROOT / REPORT_ROOT。

约束:只放常量与纯派生。不 import nonebot、不 subprocess、不碰 PIL —— 三类
consumer(nonebot 环境的 plugin/*、venv 环境的 report/bin/*、将来 P1 的网站)
都要能 import 同一份。

兼容:env 变量名与重构前完全一致(含已弃用的 WOWS_REPORT_CMD),部署不需改 .env。
一律用 os.environ.get(name, default) —— 不要写成 `get(name) or default`,后者在
env 被设为空串时行为不同。
"""
import os
from pathlib import Path

# ---------- 根 ----------
# 默认从本文件自身位置推导:<repo>/report/lib/wowsbot/paths.py -> parents[3] = <repo>。
# 这样服务器上自然是 /opt/wows-bot,开发机上是本地 checkout —— 否则硬编码
# /opt/wows-bot 会让开发机找不到 data/ 下的 zh_sg.mo、constants.json,
# 而 Task 0 的基线与后续 sha256 比对全靠开发机渲染。
# WOWS_BOT_HOME 仍可覆盖(plugin/* 被 cp 到别处时用它 bootstrap 找到本目录)。
_SELF_REPO = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("WOWS_BOT_HOME", str(_SELF_REPO)))
REPORT_ROOT = REPO_ROOT / "report"      # 旧代码里 report/bin/* 的 "BOT_HOME"
BIN_DIR = REPORT_ROOT / "bin"
DATA_DIR = REPORT_ROOT / "data"
LIB_DIR = REPORT_ROOT / "lib"

# ---------- 二进制 ----------
REPLAYSHARK = os.environ.get("WOWS_REPLAYSHARK", str(REPORT_ROOT / "replayshark"))
REPLAYSHARK_LESTA = os.environ.get("WOWS_REPLAYSHARK_LESTA",
                                   str(REPORT_ROOT / "replayshark-lesta"))
# 小地图二进制由 minimap/render.sh 自己按 WOWS_TOOLKIT_BIN 找;这里声明同样的默认值
# 供需要引用它的 consumer 复用。
TOOLKIT_BIN = os.environ.get("WOWS_TOOLKIT_BIN",
                             "/opt/wows-toolkit/target/release/minimap_renderer")
RENDER_SH = os.environ.get("WOWS_RENDER_SH", str(REPO_ROOT / "minimap" / "render.sh"))

# ---------- 目录 ----------
# 同一目录历史上有两个 env 名:WOWS_DATA_DIR(plugin/minimap.py、render_chat.py)与
# WOWS_EXTRACTED_ROOT(report/bin/wows_report)。两个都读,老名字为兼容保留。
EXTRACTED_ROOT = os.environ.get(
    "WOWS_EXTRACTED_ROOT",
    os.environ.get("WOWS_DATA_DIR", "/var/lib/wows-data/extracted"),
)
SPECS_DIR = os.environ.get("WOWS_SPECS_DIR", str(REPORT_ROOT / "specs"))
SPECS_PATCHED_ROOT = os.environ.get("WOWS_SPECS_PATCHED_ROOT",
                                    "/var/lib/wows-data/specs-patched")
OUT_DIR = os.environ.get("WOWS_OUT_DIR", "/tmp/wows_report")
REPLAY_BASEDIR = os.path.expanduser(
    os.environ.get("WOWS_REPLAY_BASEDIR", "~/wows-bot-replay"))

# ---------- 命令(report/bin 下的入口) ----------
REPORT_FULL_CMD = os.environ.get("WOWS_REPORT_FULL_CMD", str(BIN_DIR / "wows_full_report"))
REPORT_BATTLE_CMD = os.environ.get("WOWS_REPORT_BATTLE_CMD", str(BIN_DIR / "wows_report"))
REPORT_DAMAGE_CMD = os.environ.get("WOWS_REPORT_DAMAGE_CMD",
                                   str(BIN_DIR / "wows_damage_report"))
REPORT_FULL_LESTA_CMD = os.environ.get("WOWS_REPORT_FULL_LESTA_CMD",
                                       str(BIN_DIR / "wows_full_report_normalized"))
ANALYZE_CMD = os.environ.get("WOWS_ANALYZE_CMD", str(BIN_DIR / "wows_analyze"))
RENDER_CRIMINALS_PY = os.environ.get("WOWS_RENDER_CRIMINALS",
                                     str(BIN_DIR / "render_criminals.py"))
RENDER_CHAT_PY = os.environ.get("WOWS_RENDER_CHAT", str(BIN_DIR / "render_chat.py"))
RENDER_BATTLE_PY = os.environ.get("WOWS_RENDER_PY",
                                  str(BIN_DIR / "render_battle_report.py"))
RENDER_DAMAGE_PY = str(BIN_DIR / "render_damage_chart.py")
RENDER_MENU_PY = str(BIN_DIR / "render_menu.py")
# 已弃用:早期只有一条报告命令时的名字,.env 里可能还有。保留读取,值同 REPORT_FULL_CMD。
REPORT_CMD = os.environ.get("WOWS_REPORT_CMD", REPORT_FULL_CMD)

# ---------- 数据文件 ----------
SHIPS_JSON = os.environ.get("WOWS_SHIPS_JSON", str(DATA_DIR / "ships.json"))
ARMOR_JSON = os.environ.get("WOWS_ARMOR_JSON", str(DATA_DIR / "armor.json"))
BUILDS_JSON = os.environ.get("WOWS_BUILDS_JSON", str(DATA_DIR / "builds.json"))
CONSTANTS_JSON = os.environ.get("WOWS_CONSTANTS_JSON", str(DATA_DIR / "constants.json"))
ACHIEVEMENTS_JSON = os.environ.get("WOWS_ACHIEVEMENTS_JSON",
                                   str(DATA_DIR / "achievements.json"))
ACHIEVEMENT_ICON_DIR = os.environ.get("WOWS_ACHIEVEMENT_ICONS",
                                      str(DATA_DIR / "achievement_icons"))
TRANSLATIONS_MO = os.environ.get("WOWS_TRANSLATIONS_MO", str(DATA_DIR / "zh_sg.mo"))
UPGRADE_ICON_DIR = str(DATA_DIR / "upgrade_icons")
SKILL_ICON_DIR = str(DATA_DIR / "skill_icons")
RIBBON_ICON_DIR = str(DATA_DIR / "ribbon_icons")
SHIP_ICON_DIR = str(DATA_DIR / "ship_icons")
# tools/build_ships_json.py 要读的 GameParams(在 specs 里,不在 data 里)
GAME_PARAMS_DATA = str(Path(SPECS_DIR) / "content" / "GameParams.data")

# ---------- 超时(秒) ----------
MP4_TIMEOUT = int(os.environ.get("WOWS_MP4_TIMEOUT", "600"))
PNG_TIMEOUT = int(os.environ.get("WOWS_PNG_TIMEOUT", "300"))
ANALYZE_TIMEOUT = int(os.environ.get("WOWS_ANALYZE_TIMEOUT", "120"))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python tests/test_wowsbot_paths.py`
Expected: 7 个 `PASS` + `== ALL PASS ==`

- [ ] **Step 5: 提交**

```bash
git add report/lib/wowsbot/__init__.py report/lib/wowsbot/paths.py tests/test_wowsbot_paths.py
git commit -m "feat(lib): wowsbot.paths —— 路径/配置唯一声明表

REPO_ROOT / REPORT_ROOT 取代含义冲突的 BOT_HOME(report/bin 里指 report/,tools/
里指仓库根,正是 tools 默认路径少一层的根因)。数据路径一律从 REPORT_ROOT 派生,
不再从命令路径反推。env 名全部保持兼容,EXTRACTED_ROOT 同时读 WOWS_EXTRACTED_ROOT
与老名字 WOWS_DATA_DIR。"
```

---

## Task 2: `replay.py` —— 收掉 3 份重复的回放头解析

现有 3 份实现:`report/bin/wows_report::read_replay_meta`+`parse_build`、`plugin/minimap.py::_replay_build`+`_available_builds`、网站的 `_read_replay_build_and_version`(网站属 P1,本次不动)。

**Files:**
- Create: `report/lib/wowsbot/replay.py`
- Test: `tests/test_wowsbot_replay.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_wowsbot_replay.py
"""wowsbot.replay 测试 —— 用真实回放验 build/version/服务器判定 + 边界。
无 pytest 依赖。用法: python tests/test_wowsbot_replay.py

真实回放是可选的:环境里找不到就跳过那几项(打印 SKIP),其余边界用例照跑。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "report" / "lib"))
from wowsbot import replay  # noqa: E402

WG_REPLAY_DIR = Path("C:/Program Files (x86)/Steam/steamapps/common/World of Warships/replays")
LESTA_REPLAY_DIR = Path("C:/Games/Korabli/replays")


def _any(d: Path, pattern: str):
    return next(iter(sorted(d.glob(pattern))), None) if d.is_dir() else None


def test_wg_replay_build_and_version():
    f = _any(WG_REPLAY_DIR, "*.wowsreplay")
    if f is None:
        print("  test_wg_replay_build_and_version SKIP (无 WG 回放)")
        return
    b = replay.build_of(str(f))
    v = replay.version_of(str(f))
    assert isinstance(b, int) and b > 1_000_000, (f.name, b)
    # version_of 形如 "15.8.0"
    parts = v.split(".")
    assert len(parts) == 3 and all(x.isdigit() for x in parts), (f.name, v)
    assert replay.is_lesta(str(f)) is False
    print(f"  test_wg_replay_build_and_version PASS (build={b} ver={v})")


def test_lesta_replay_detected():
    f = _any(LESTA_REPLAY_DIR, "*.korablireplay")
    if f is None:
        print("  test_lesta_replay_detected SKIP (无 Lesta 回放)")
        return
    assert replay.is_lesta(str(f)) is True
    assert isinstance(replay.build_of(str(f)), int)
    print("  test_lesta_replay_detected PASS")


def test_corrupt_and_missing_return_none():
    d = Path(tempfile.mkdtemp())
    broken = d / "broken.wowsreplay"
    broken.write_bytes(b"garbage")
    assert replay.build_of(str(broken)) is None
    assert replay.version_of(str(broken)) == "0.0.0"
    empty = d / "empty.wowsreplay"
    empty.write_bytes(b"")
    assert replay.build_of(str(empty)) is None
    assert replay.build_of(str(d / "nope.wowsreplay")) is None
    print("  test_corrupt_and_missing_return_none PASS")


def test_absurd_meta_len_rejected():
    # meta_len 超过 5MB 上限视为损坏,不尝试读
    d = Path(tempfile.mkdtemp())
    f = d / "huge.wowsreplay"
    f.write_bytes(b"\x12\x32\x34\x11" + b"\x01\x00\x00\x00" + (99_000_000).to_bytes(4, "little"))
    assert replay.build_of(str(f)) is None
    print("  test_absurd_meta_len_rejected PASS")


def test_available_builds_only_version_dirs():
    root = Path(tempfile.mkdtemp())
    for name in ("15.8.0_13187581", "26.8.0_8861049", "15.3.0_12267945"):
        (root / name).mkdir()
    for noise in ("common", "vfs_common", "not_a_version", "15.8.0"):
        (root / noise).mkdir()
    (root / "15.9.0_99999999").write_text("file not dir")
    got = replay.available_builds(str(root))
    assert got == {13187581, 8861049, 12267945}, got
    print("  test_available_builds_only_version_dirs PASS")


def test_available_builds_unreadable_root_is_empty():
    # 目录读不到时返回空集合,由调用方决定放行(不能因此把所有回放拦死)
    assert replay.available_builds("/definitely/not/here") == set()
    print("  test_available_builds_unreadable_root_is_empty PASS")


def test_no_forbidden_imports():
    src = (ROOT / "report" / "lib" / "wowsbot" / "replay.py").read_text(encoding="utf-8")
    for bad in ("nonebot", "subprocess", "ImageDraw"):
        assert bad not in src, f"replay.py 不该出现 {bad}"
    print("  test_no_forbidden_imports PASS")


if __name__ == "__main__":
    print("== test_wowsbot_replay ==")
    test_wg_replay_build_and_version()
    test_lesta_replay_detected()
    test_corrupt_and_missing_return_none()
    test_absurd_meta_len_rejected()
    test_available_builds_only_version_dirs()
    test_available_builds_unreadable_root_is_empty()
    test_no_forbidden_imports()
    print("== ALL PASS ==")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python tests/test_wowsbot_replay.py`
Expected: `ImportError: cannot import name 'replay' from 'wowsbot'`

- [ ] **Step 3: 写 `replay.py`**

```python
# report/lib/wowsbot/replay.py
"""回放文件元数据 —— 重构前有 3 份各自手写的二进制头解析。

文件头布局(WG 与 Lesta 相同):
    u32 magic | u32 blockCount | u32 meta_len | UTF-8 JSON meta
meta 里的 clientVersionFromExe 形如 "15,8,0,13187581" —— 末段是 build,前三段是版本。

约束:只做只读解析。不 import nonebot、不 subprocess、不碰 PIL。
所有函数对损坏/缺失输入返回 None 或空值,不抛异常 —— 调用方据此决定放行还是拦下。
"""
import json
import os
import re
from typing import Optional

# extracted 根目录下的版本子目录名,如 15.8.0_13187581 / 26.8.0_8861049
_VERSION_DIR_RE = re.compile(r"^\d+(?:\.\d+)+_(\d+)$")

_MAX_META_LEN = 5 * 1024 * 1024   # 超过这个视为损坏,不尝试读


def read_meta(path: str) -> Optional[dict]:
    """读回放头部的 JSON meta。读不出返回 None(不抛异常)。"""
    try:
        with open(path, "rb") as f:
            head = f.read(12)
            if len(head) < 12:
                return None
            meta_len = int.from_bytes(head[8:12], "little")
            if not 0 < meta_len <= _MAX_META_LEN:
                return None
            raw = f.read(meta_len)
        return json.loads(raw.decode("utf-8", errors="ignore"))
    except (OSError, ValueError):
        return None


def build_of(path: str) -> Optional[int]:
    """回放的 build 号。读不出返回 None。"""
    meta = read_meta(path)
    if not meta:
        return None
    parts = str(meta.get("clientVersionFromExe", "")).split(",")
    if len(parts) < 4:
        return None
    try:
        return int(parts[3].strip())
    except ValueError:
        return None


def version_of(path: str) -> str:
    """回放的版本串,如 "15.8.0"。读不出返回 "0.0.0"(沿用重构前 wows_report 的约定)。"""
    meta = read_meta(path)
    if not meta:
        return "0.0.0"
    parts = [p.strip() for p in str(meta.get("clientVersionFromExe", "")).split(",")]
    return ".".join(parts[:3]) if len(parts) >= 3 else "0.0.0"


def is_lesta(path: str) -> bool:
    """是否 Lesta(«Мир кораблей»)回放 —— 按扩展名判,与重构前一致。

    不按版本号判:Lesta 是 26.x、WG 是 15.x,但扩展名更直接且不会随版本漂移。
    """
    return str(path).endswith(".korablireplay")


def available_builds(extracted_root: str) -> set:
    """扫 extracted 根目录,收集可用的 build 号。

    只认 `<版本>_<build>/` 形式的**目录**,忽略 common / vfs_common 等 CAS 存储池。
    目录读不到时返回空集合 —— 调用方应据此放行,不能因为一时读不到就把所有回放拦死。
    """
    builds = set()
    try:
        for name in os.listdir(extracted_root):
            m = _VERSION_DIR_RE.match(name)
            if m and os.path.isdir(os.path.join(extracted_root, name)):
                builds.add(int(m.group(1)))
    except OSError:
        return set()
    return builds
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python tests/test_wowsbot_replay.py`
Expected: 全部 `PASS`(真实回放缺失时对应项显示 SKIP)+ `== ALL PASS ==`

- [ ] **Step 5: 提交**

```bash
git add report/lib/wowsbot/replay.py tests/test_wowsbot_replay.py
git commit -m "feat(lib): wowsbot.replay —— 回放元数据解析收成一份

重构前 wows_report / plugin/minimap.py 各自手写二进制头解析(网站还有第三份,
属 P1)。统一为 read_meta / build_of / version_of / is_lesta / available_builds,
对损坏与缺失输入一律返回 None/空值而不抛异常。"
```

---

## Task 3: `theme.py` + `text.py` —— 从渲染器搬出纯常量与纯函数

**机械搬迁,不改一个字符的逻辑。** 源文件 `report/bin/render_battle_report.py`:字体候选表与 `_first_existing`(第 20-46 行附近)、`GAME_*`(第 381-390 行)、正则与 strip 系列(第 164-215 行附近)。

**Files:**
- Create: `report/lib/wowsbot/theme.py`, `report/lib/wowsbot/text.py`
- Test: `tests/test_wowsbot_lib.py`(本任务只加 theme/text 部分,Task 4 再补 i18n/results)

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_wowsbot_lib.py
"""wowsbot 的 theme / text / i18n / results 测试。无 pytest 依赖。
用法: python tests/test_wowsbot_lib.py"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "report" / "lib"))

LIB = ROOT / "report" / "lib" / "wowsbot"


def test_theme_palette_values_unchanged():
    """调色板必须与重构前 render_battle_report.py 里的值逐一相同 —— 改了就是改了外观。"""
    from wowsbot import theme
    assert theme.GAME_BG == (18, 24, 38)
    assert theme.GAME_PANEL == (32, 42, 64)
    assert theme.GAME_PANEL_ALT == (28, 36, 56)
    assert theme.GAME_GREEN == (74, 200, 132)
    assert theme.GAME_RED == (235, 86, 75)
    assert theme.GAME_GOLD == (242, 196, 87)
    assert theme.GAME_PURPLE == (188, 122, 232)
    assert theme.GAME_TEXT == (228, 233, 245)
    assert theme.GAME_DIM == (140, 155, 180)
    assert theme.GAME_BORDER == (60, 75, 100)
    print("  test_theme_palette_values_unchanged PASS")


def test_theme_font_env_override_wins():
    import importlib
    from wowsbot import theme
    saved = os.environ.get("WOWS_CJK_FONT")
    # 用一个确实存在的文件当字体路径(内容不重要,theme 只做存在性检查)
    probe = str(ROOT / "README.md") if (ROOT / "README.md").is_file() else __file__
    os.environ["WOWS_CJK_FONT"] = probe
    try:
        t = importlib.reload(theme)
        assert t.CJK_FONT == probe, t.CJK_FONT
        # MONO 未设时回落到 CJK
        assert t.MONO_FONT is not None
    finally:
        if saved is None:
            os.environ.pop("WOWS_CJK_FONT", None)
        else:
            os.environ["WOWS_CJK_FONT"] = saved
        importlib.reload(theme)
    print("  test_theme_font_env_override_wins PASS")


def test_theme_has_no_pil_dependency():
    src = (LIB / "theme.py").read_text(encoding="utf-8")
    for bad in ("PIL", "ImageFont", "ImageDraw", "nonebot", "subprocess"):
        assert bad not in src, f"theme.py 不该出现 {bad}(font() 留在渲染器里)"
    print("  test_theme_has_no_pil_dependency PASS")


def test_text_helpers():
    from wowsbot import text
    assert text.strip_id("AccountId(12345)") == 12345
    assert text.strip_id("EntityId(7)") == 7
    assert text.strip_id("GameParamId(42)") == 42
    assert text.strip_id("") == 0
    assert text.strip_id("garbage") == 0
    assert text.strip_known("Known(Battleship)") == "Battleship"
    assert text.strip_known("Battleship") == "Battleship"
    assert text.strip_known("") == ""
    assert text.relation_name("Relation(0)") == "self"
    assert text.relation_name("Relation(1)") == "friendly"
    assert text.relation_name("Relation(2)") == "enemy"
    assert text.relation_name("") == "?"
    assert text.clean_ship_name("PASS208_Salmon") == "Salmon"
    assert text.clean_ship_name("PASC108_Baltimore_1944") == "Baltimore"
    assert text.clean_ship_name("") == "?"
    assert text.fmt_time(0) == "00:00"
    assert text.fmt_time(65) == "01:05"
    assert text.fmt_time(600) == "10:00"
    print("  test_text_helpers PASS")


def test_i18n_labels_present():
    from wowsbot import i18n
    assert i18n.SPECIES_SHORT["Battleship"] == "BB"
    assert i18n.SPECIES_SHORT["AirCarrier"] == "CV"
    assert i18n.DEATH_CAUSE_CN["ApShell"] == "AP"
    assert i18n.DEATH_CAUSE_CN["Flooding"] == "进水"
    assert i18n.MATCH_GROUP_CN["pvp"] == "随机战"
    print("  test_i18n_labels_present PASS")


def test_i18n_t_falls_back_to_key():
    from wowsbot import i18n
    # 不存在的键返回自身;给了 default 就返回 default
    assert i18n.t("IDS_DEFINITELY_NOT_A_KEY") == "IDS_DEFINITELY_NOT_A_KEY"
    assert i18n.t("IDS_DEFINITELY_NOT_A_KEY", "回退") == "回退"
    print("  test_i18n_t_falls_back_to_key PASS")


def test_results_field_bounds():
    from wowsbot import results
    # 索引表可能加载失败(缺 constants.json),此时一律返回 default 而不抛
    assert results.result_field(None, "damage", "D") == "D"
    assert results.result_field([], "damage", "D") == "D"
    assert results.result_field("not a list", "damage", "D") == "D"
    assert results.result_field([1, 2, 3], "definitely_not_a_field", "D") == "D"
    print("  test_results_field_bounds PASS")


def test_lib_modules_have_no_forbidden_imports():
    for name in ("theme.py", "text.py", "i18n.py", "results.py"):
        src = (LIB / name).read_text(encoding="utf-8")
        for bad in ("nonebot", "subprocess", "ImageDraw"):
            assert bad not in src, f"{name} 不该出现 {bad}"
    print("  test_lib_modules_have_no_forbidden_imports PASS")


if __name__ == "__main__":
    print("== test_wowsbot_lib ==")
    test_theme_palette_values_unchanged()
    test_theme_font_env_override_wins()
    test_theme_has_no_pil_dependency()
    test_text_helpers()
    test_i18n_labels_present()
    test_i18n_t_falls_back_to_key()
    test_results_field_bounds()
    test_lib_modules_have_no_forbidden_imports()
    print("== ALL PASS ==")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python tests/test_wowsbot_lib.py`
Expected: `ImportError: cannot import name 'theme' from 'wowsbot'`(i18n/results 的用例在 Task 4 才会转绿,本步允许它们仍失败)

- [ ] **Step 3: 写 `theme.py`(值与原文件逐字相同)**

```python
# report/lib/wowsbot/theme.py
"""视觉常量:字体路径 + 调色板。原本长在 render_battle_report.py 里,被 6 个渲染
脚本 import —— 那个 887 行渲染器实际兼职了公共库。搬出来后它只管渲染。

**这里的值必须与重构前逐一相同**,否则渲染结果会变(验收靠渲染图 sha256 比对)。

不 import PIL:font(path, size)(ImageFont.truetype 的两行包装)留在渲染器里,
以保住"三类 Python 环境都能 import 这个包"的硬约束。
"""
import os

# Fonts: per-OS lookup with env-var override (CJK + monospace required).
# On Linux, install fonts-noto-cjk + fonts-dejavu (or set WOWS_CJK_FONT).
_CJK_CANDIDATES = [
    os.environ.get("WOWS_CJK_FONT"),
    "/System/Library/Fonts/Hiragino Sans GB.ttc",                  # macOS
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",      # Debian/Ubuntu (Noto)
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",    # Fedora
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",                # WenQuanYi fallback
]
_MONO_CANDIDATES = [
    os.environ.get("WOWS_MONO_FONT"),
    "/System/Library/Fonts/Menlo.ttc",                             # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",         # Debian/Ubuntu
    "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",  # Fedora
]


def _first_existing(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


CJK_FONT = _first_existing(_CJK_CANDIDATES)
MONO_FONT = _first_existing(_MONO_CANDIDATES) or CJK_FONT
if not CJK_FONT:
    raise RuntimeError(
        "No CJK font found. Install fonts-noto-cjk on Linux, "
        "or set WOWS_CJK_FONT env var to a .ttc/.ttf path."
    )

# ---------- 调色板(改这里就是改外观) ----------
GAME_BG = (18, 24, 38)
GAME_PANEL = (32, 42, 64)
GAME_PANEL_ALT = (28, 36, 56)
GAME_GREEN = (74, 200, 132)
GAME_RED = (235, 86, 75)
GAME_GOLD = (242, 196, 87)
GAME_PURPLE = (188, 122, 232)  # tier color above gold (顶级)
GAME_TEXT = (228, 233, 245)
GAME_DIM = (140, 155, 180)
GAME_BORDER = (60, 75, 100)
```

- [ ] **Step 4: 写 `text.py`(实现与原文件逐字相同)**

```python
# report/lib/wowsbot/text.py
"""纯字符串处理 —— replayshark JSON 里的包装值拆解、船名清理、时长格式化。

原本长在 render_battle_report.py 里,被 render_criminals / render_damage_chart /
render_consumables_chart import。纯函数、无 I/O、无状态,所以单独一个模块,
跟要读 .mo 的 i18n、要读 constants.json 的 results 分开(测试互不牵连)。
"""
import re

ID_RE = re.compile(r"(?:AccountId|EntityId|GameParamId)\((\d+)\)")
KNOWN_RE = re.compile(r"Known\(([A-Za-z]+)\)")
RELATION_RE = re.compile(r"Relation\((\d+)\)")


def strip_id(s: str) -> int:
    m = ID_RE.match(s or "")
    return int(m.group(1)) if m else 0


def strip_known(s: str) -> str:
    if not s:
        return ""
    m = KNOWN_RE.match(s)
    return m.group(1) if m else s


def relation_name(s: str) -> str:
    # 0 = Self, 1 = Friendly, 2 = Enemy (BigWorld convention)
    m = RELATION_RE.match(s or "")
    n = int(m.group(1)) if m else -1
    return {0: "self", 1: "friendly", 2: "enemy"}.get(n, "?")


def clean_ship_name(raw: str) -> str:
    """PASS208_Salmon -> Salmon, PASC108_Baltimore_1944 -> Baltimore."""
    if not raw:
        return "?"
    # Drop prefix segment (e.g. PASS208, PASC108)
    parts = raw.split("_")
    if len(parts) >= 2:
        parts = parts[1:]
    # Drop trailing year-like segments (4-digit numbers)
    while parts and parts[-1].isdigit() and len(parts[-1]) == 4:
        parts.pop()
    return "_".join(parts) or raw


def fmt_time(secs: int) -> str:
    secs = int(secs)
    return f"{secs//60:02d}:{secs%60:02d}"
```

- [ ] **Step 5: 跑测试(theme/text 部分应转绿)**

Run: `python tests/test_wowsbot_lib.py 2>&1 | head -20`
Expected: `test_theme_*` 与 `test_text_helpers` 打印 PASS;`test_i18n_*` / `test_results_*` 仍失败(Task 4 处理)。

- [ ] **Step 6: 提交**

```bash
git add report/lib/wowsbot/theme.py report/lib/wowsbot/text.py tests/test_wowsbot_lib.py
git commit -m "feat(lib): wowsbot.theme + wowsbot.text —— 从渲染器搬出常量与纯函数

机械搬迁,值与实现逐字未改(调色板有断言逐项钉住)。theme 刻意不 import PIL:
font() 仍留在 render_battle_report.py,以保住三类 Python 环境都能 import 的约束。"
```

---

## Task 4: `i18n.py` + `results.py` —— 搬出有 I/O 的部分

**Files:**
- Create: `report/lib/wowsbot/i18n.py`, `report/lib/wowsbot/results.py`
- Test: `tests/test_wowsbot_lib.py`(Task 3 已写好用例,本任务让它们转绿)

- [ ] **Step 1: 确认目标用例当前是红的**

Run: `python tests/test_wowsbot_lib.py 2>&1 | tail -5`
Expected: 在 `test_i18n_labels_present` 处报 `ImportError: cannot import name 'i18n'`

- [ ] **Step 2: 写 `i18n.py`**

```python
# report/lib/wowsbot/i18n.py
"""翻译:WoWs gettext 目录(.mo)加载 + 硬编码中文标签表。

原本长在 render_battle_report.py 里。三张标签表(SPECIES_SHORT / DEATH_CAUSE_CN /
MATCH_GROUP_CN)也被别的脚本跨文件引用,原注释就写着 "Hardcoded fallback for
things not keyed as IDS_*",所以跟翻译放一起。

有 I/O 和模块级缓存,所以跟纯函数的 text.py 分开。
"""
from typing import Optional

from . import paths

_TRANSLATIONS: dict = {}


def load_translations(mo_path: str = None):
    """Load WoWs gettext catalog into a dict, on demand.

    默认路径来自 paths.TRANSLATIONS_MO(env WOWS_TRANSLATIONS_MO 可覆盖)。
    加载失败只打警告不抛 —— 缺翻译时退化成显示原始 IDS_* 键,不该让渲染整体失败。
    """
    global _TRANSLATIONS
    if _TRANSLATIONS:
        return
    path = mo_path or paths.TRANSLATIONS_MO
    try:
        import polib
        mo = polib.mofile(path)
        _TRANSLATIONS = {e.msgid: e.msgstr for e in mo if e.msgstr}
    except Exception as e:
        import sys
        print(f"warn: failed to load translations from {path}: {e}", file=sys.stderr)


def t(key: str, default: Optional[str] = None) -> str:
    """Translate an IDS_* key. Returns default (or key itself) if not found."""
    load_translations()
    return _TRANSLATIONS.get(key, default if default is not None else key)


SPECIES_SHORT = {
    "Battleship": "BB",
    "Cruiser": "CL",
    "Destroyer": "DD",
    "AirCarrier": "CV",
    "Submarine": "SS",
    "Auxiliary": "AUX",
}

DEATH_CAUSE_CN = {
    "ApShell": "AP",
    "HeShell": "HE",
    "CsShell": "CS",
    "Torpedo": "鱼雷",
    "AerialTorpedo": "机雷",
    "AerialRocket": "火箭",
    "AerialBomb": "炸弹",
    "DiveBomber": "俯冲",
    "SkipBomber": "跳炸",
    "AerialDepthCharge": "深弹",
    "DepthCharge": "深弹",
    "Fire": "燃烧",
    "Flooding": "进水",
    "Ram": "撞击",
    "Terrain": "撞礁",
    "Detonate": "弹药库",
    "SecondaryCaliber": "副炮",
    "AntiAir": "副炮",
    "SeaMine": "水雷",
    "Health": "血量",
}

# Hardcoded fallback for things not keyed as IDS_*
MATCH_GROUP_CN = {
    "pvp": "随机战",
    "ranked": "排位赛",
    "cooperative": "合作战斗",
    "training": "训练房",
    "clan": "战队战",
    "brawl": "乱斗",
    "scenario": "战役",
}
```

- [ ] **Step 3: 写 `results.py`**

原实现(已核对,注意 `int(v)` 转换与 `json.load(open(path))` 的写法):

```python
def load_result_indices(path: str = CONSTANTS_JSON):
    global _RESULT_INDICES
    if _RESULT_INDICES:
        return
    try:
        c = json.load(open(path))
        _RESULT_INDICES = {k: int(v) for k, v in c.get("CLIENT_PUBLIC_RESULTS_INDICES", {}).items()}
    except Exception as e:
        print(f"warn: failed to load constants: {e}", file=sys.stderr)
```

搬迁后(只把默认路径换成 `paths.CONSTANTS_JSON`,其余逐字保留):

```python
# report/lib/wowsbot/results.py
"""结算数组按字段名取值。

replayshark 的 results_info 是一个扁平数组,字段名到下标的映射在 constants.json 的
CLIENT_PUBLIC_RESULTS_INDICES 里。原本长在 render_battle_report.py 里。

有 I/O 和模块级缓存,所以跟纯函数的 text.py 分开。索引表加载失败时 result_field
一律返回 default —— 缺 constants.json 应退化成"少几列",不该让渲染整体失败。
"""
import json
import sys

from . import paths

_RESULT_INDICES: dict = {}


def load_result_indices(path: str = None):
    """按需加载 字段名 -> 下标 映射。默认路径来自 paths.CONSTANTS_JSON。"""
    global _RESULT_INDICES
    if _RESULT_INDICES:
        return
    try:
        c = json.load(open(path or paths.CONSTANTS_JSON))
        _RESULT_INDICES = {k: int(v) for k, v in c.get("CLIENT_PUBLIC_RESULTS_INDICES", {}).items()}
    except Exception as e:
        print(f"warn: failed to load constants: {e}", file=sys.stderr)


def result_field(arr, name: str, default=None):
    """Look up a named field from a raw results_info array."""
    load_result_indices()
    idx = _RESULT_INDICES.get(name)
    if idx is None or arr is None or not isinstance(arr, list) or idx >= len(arr):
        return default
    return arr[idx]
```

**注意**:若 Step 3 的 awk 显示原实现的 JSON 键名或错误处理与上面不同,**以原实现为准**照抄,只把默认路径换成 `paths.CONSTANTS_JSON`。

- [ ] **Step 4: 跑测试确认全绿**

Run: `python tests/test_wowsbot_lib.py`
Expected: 8 个 `PASS` + `== ALL PASS ==`

- [ ] **Step 5: 提交**

```bash
git add report/lib/wowsbot/i18n.py report/lib/wowsbot/results.py
git commit -m "feat(lib): wowsbot.i18n + wowsbot.results —— 搬出有 I/O 的公共部分

翻译(.mo)与结算索引(constants.json)各自带模块级缓存,所以跟纯函数的 text.py
分开;三张跨文件引用的中文标签表随 i18n 一起搬。默认路径改从 paths 取。
加载失败一律退化(打警告 / 返回 default),不让渲染整体失败。"
```

---

## Task 5: `render_battle_report.py` 改用 `wowsbot`(第一次基线比对)

**这是最关键的一步** —— 渲染器换源后,输出必须逐字节不变。

**Files:** Modify `report/bin/render_battle_report.py`

- [ ] **Step 1: 加 bootstrap 与 import,删掉已搬走的定义**

在文件顶部现有 `sys.path` 处理附近加入(该文件在 `report/bin/`,`parent.parent` = `report/`):

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from wowsbot import paths as _paths                                    # noqa: E402
from wowsbot.i18n import (                                             # noqa: E402
    DEATH_CAUSE_CN, MATCH_GROUP_CN, SPECIES_SHORT, load_translations, t,
)
from wowsbot.results import load_result_indices, result_field          # noqa: E402
from wowsbot.text import (                                             # noqa: E402
    clean_ship_name, fmt_time, ID_RE, KNOWN_RE, RELATION_RE,
    relation_name, strip_id, strip_known,
)
from wowsbot.theme import (                                            # noqa: E402
    CJK_FONT, GAME_BG, GAME_BORDER, GAME_DIM, GAME_GOLD, GAME_GREEN,
    GAME_PANEL, GAME_PANEL_ALT, GAME_PURPLE, GAME_RED, GAME_TEXT, MONO_FONT,
)
```

删除本文件里这些已搬走的定义(其余一行不动):
- 字体候选 `_CJK_CANDIDATES` / `_MONO_CANDIDATES` / `_first_existing` / `CJK_FONT` / `MONO_FONT` 及那段 `raise RuntimeError`
- `GAME_BG` … `GAME_BORDER` 共 10 个颜色常量
- `ID_RE` / `KNOWN_RE` / `RELATION_RE` / `SPECIES_SHORT` / `DEATH_CAUSE_CN` / `MATCH_GROUP_CN`
- `strip_id` / `strip_known` / `relation_name` / `clean_ship_name` / `fmt_time`
- `_TRANSLATIONS` / `load_translations` / `t`
- `_RESULT_INDICES` / `load_result_indices` / `result_field`

**保留不动**:`font()`、`achievement_icon()`、`load_achievements()`、`_ACH_ID_TO_INDEX`、`_ACH_ICON_CACHE`、`PlayerStats` / `MatchReport` / `load()` / `render()` 及全部绘图代码。

数据文件常量改为从 `paths` 取(其余引用它们的地方不用改,名字保持不变):

```python
TRANSLATIONS_MO      = _paths.TRANSLATIONS_MO
CONSTANTS_JSON       = _paths.CONSTANTS_JSON
ACHIEVEMENTS_JSON    = _paths.ACHIEVEMENTS_JSON
ACHIEVEMENT_ICON_DIR = _paths.ACHIEVEMENT_ICON_DIR
```

- [ ] **Step 2: 语法检查**

Run: `cd /c/Users/29801/Desktop/wows-bot-review && python -m py_compile report/bin/render_battle_report.py && echo OK`
Expected: `OK`

- [ ] **Step 3: 重跑渲染并比对基线 sha256(硬门槛)**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
T="$(python -c 'import tempfile;print(tempfile.gettempdir())')"
rm -rf "$T/p2_check"
bash tools/p2_render_fixtures.sh "$T/p2_check" >/dev/null
diff docs/superpowers/plans/2026-09-18-p2-baseline.sha256 "$T/p2_check/fixtures.sha256"   && echo PIXEL_IDENTICAL
```

（先 `mkdir -p /tmp/p2_check`。)
Expected: 打印 `PIXEL_IDENTICAL`。**不一致就停下来排查,不要继续下一个任务。**

- [ ] **Step 4: 跑现有测试**

Run: `python tests/test_render_menu.py && python tests/test_wowsbot_lib.py`
Expected: 两个都 `== ALL PASS ==`

- [ ] **Step 5: 提交**

```bash
git add report/bin/render_battle_report.py
git commit -m "refactor(report): render_battle_report 改用 wowsbot,不再兼职公共库

theme / text / i18n / results 已搬进 report/lib/wowsbot,这里改为 import。
绘图逻辑、font()、成就图标、PlayerStats/MatchReport/load/render 一行未动。
验收:渲染图 sha256 与重构前逐字节一致。"
```

---

## Task 6: 6 个 `from render_battle_report import` 脚本换源

**Files:** Modify `report/bin/render_chat.py` `render_criminals.py` `render_damage_chart.py` `render_menu.py` `render_query.py` `render_consumables_chart.py`

每个文件的改法相同:在原有 `sys.path.insert` 之后加一行 lib 路径,然后把 `from render_battle_report import (...)` 拆成按模块的 import。**符号名不变,所以函数体一行不用改。**

- [ ] **Step 1: 加 bootstrap(6 个文件都加)**

在每个文件现有的 `sys.path.insert(0, str(Path(__file__).resolve().parent))` 之后加:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
```

- [ ] **Step 2: 逐个替换 import**

`render_chat.py` —— 原:`from render_battle_report import t as _translate`
改为:

```python
from wowsbot.i18n import t as _translate   # noqa: E402
```

`render_criminals.py` —— 原一整块改为:

```python
from wowsbot.i18n import load_translations, t                          # noqa: E402
from wowsbot.results import load_result_indices, result_field          # noqa: E402
from wowsbot.text import clean_ship_name, fmt_time, strip_id, strip_known  # noqa: E402
from wowsbot.theme import (                                            # noqa: E402
    CJK_FONT, GAME_BG, GAME_BORDER, GAME_DIM, GAME_GOLD, GAME_GREEN,
    GAME_PANEL, GAME_PANEL_ALT, GAME_RED, GAME_TEXT, MONO_FONT,
)
```

`render_damage_chart.py` —— 改为:

```python
from wowsbot.i18n import t                                             # noqa: E402
from wowsbot.results import load_result_indices, result_field          # noqa: E402
from wowsbot.text import fmt_time, strip_known                         # noqa: E402
from wowsbot.theme import (                                            # noqa: E402
    CJK_FONT, GAME_BG, GAME_BORDER, GAME_DIM, GAME_GOLD, GAME_GREEN,
    GAME_PANEL, GAME_PURPLE, GAME_RED, GAME_TEXT, MONO_FONT,
)
```

`render_menu.py` —— 改为:

```python
from wowsbot.theme import CJK_FONT, GAME_GREEN, GAME_RED, MONO_FONT    # noqa: E402
```

`render_query.py` —— 改为:

```python
from wowsbot.theme import (                                            # noqa: E402
    CJK_FONT, GAME_GOLD, GAME_GREEN, GAME_RED, MONO_FONT,
)
```

`render_consumables_chart.py` —— 改为:

```python
from wowsbot.i18n import load_translations, t                          # noqa: E402
from wowsbot.text import clean_ship_name, strip_id, strip_known        # noqa: E402
from wowsbot.theme import (                                            # noqa: E402
    CJK_FONT, GAME_BG, GAME_BORDER, GAME_DIM, GAME_GREEN, GAME_PANEL,
    GAME_PANEL_ALT, GAME_RED, GAME_TEXT, MONO_FONT,
)
```

- [ ] **Step 3: 语法检查 + 零残留断言**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
python -m py_compile report/bin/render_chat.py report/bin/render_criminals.py \
  report/bin/render_damage_chart.py report/bin/render_menu.py \
  report/bin/render_query.py report/bin/render_consumables_chart.py && echo COMPILE_OK
grep -rn 'from render_battle_report import' report/ plugin/ ; echo "^ 必须为空"
```

Expected: `COMPILE_OK`,且 grep 无输出。

- [ ] **Step 4: 基线比对 + 现有测试**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
T="$(python -c 'import tempfile;print(tempfile.gettempdir())')"
rm -rf "$T/p2_check"
bash tools/p2_render_fixtures.sh "$T/p2_check" >/dev/null
diff docs/superpowers/plans/2026-09-18-p2-baseline.sha256 "$T/p2_check/fixtures.sha256"   && echo PIXEL_IDENTICAL
```

Expected: `PIXEL_IDENTICAL` + 菜单测试 `== ALL PASS ==`

- [ ] **Step 5: 提交**

```bash
git add report/bin/render_chat.py report/bin/render_criminals.py \
  report/bin/render_damage_chart.py report/bin/render_menu.py \
  report/bin/render_query.py report/bin/render_consumables_chart.py
git commit -m "refactor(report): 6 个渲染脚本改从 wowsbot 取 theme/text/i18n/results

不再 import render_battle_report(零残留 grep 已断言)。符号名保持不变,函数体
一行未改;渲染图 sha256 与重构前一致。"
```

---

## Task 7: 2 个 `import ... as rb` 脚本只换常量来源

`render_report_normalized.py` / `render_review_normalized.py` 保留对渲染器的依赖(`rb.render` `rb.load` `rb.MatchReport` `rb.PlayerStats` `rb.font` `rb.load_achievements` `rb._ACH_ID_TO_INDEX`),只把 theme 常量与标签表换成 `wowsbot`。

**Files:** Modify `report/bin/render_report_normalized.py` `report/bin/render_review_normalized.py`

已 grep 确认,两个文件的 `rb.` 引用**全集**如下(不需要再猜):

**`render_report_normalized.py`**

| 引用 | 处理 |
|---|---|
| `rb.DEATH_CAUSE_CN` `rb.MATCH_GROUP_CN` `rb.load_translations` | → `from wowsbot.i18n import ...` |
| `rb.MatchReport` `rb.PlayerStats` `rb.render` `rb.load_achievements` `rb._ACH_ID_TO_INDEX` | **保留不动** |

**`render_review_normalized.py`**

| 引用 | 处理 |
|---|---|
| `rb.CJK_FONT` `rb.MONO_FONT` `rb.GAME_BG` `rb.GAME_BORDER` `rb.GAME_DIM` `rb.GAME_GOLD` `rb.GAME_PANEL` `rb.GAME_TEXT` | → `from wowsbot.theme import ...` |
| `rb.load_translations` | → `from wowsbot.i18n import load_translations` |
| `rb.font` | **保留不动**(PIL 包装,仍在渲染器里) |

该文件还有 `dc.*`(`import render_damage_chart as dc`)—— **不属本任务,不动**。

- [ ] **Step 1: 复核引用全集与上表一致(防止期间有人改过文件)**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
for f in render_report_normalized render_review_normalized; do
  echo "--- $f"; grep -oE 'rb\.[A-Za-z_]+' report/bin/$f.py | sort -u | tr '
' ' '; echo
done
```

Expected: 与上面两张表完全吻合。若出现表里没有的符号,先补充分类再继续。

- [ ] **Step 2: 加 bootstrap 与 import**

两个文件都在现有 `sys.path.insert` 之后加:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
```

`render_report_normalized.py` 加:

```python
from wowsbot.i18n import DEATH_CAUSE_CN, MATCH_GROUP_CN, load_translations  # noqa: E402
```

并把 `rb.DEATH_CAUSE_CN` → `DEATH_CAUSE_CN`、`rb.MATCH_GROUP_CN` → `MATCH_GROUP_CN`、
`rb.load_translations` → `load_translations` 逐处替换。

`render_review_normalized.py` 加:

```python
from wowsbot.i18n import load_translations                                  # noqa: E402
from wowsbot.theme import (                                                 # noqa: E402
    CJK_FONT, GAME_BG, GAME_BORDER, GAME_DIM, GAME_GOLD, GAME_PANEL, GAME_TEXT, MONO_FONT,
)
```

并把 `rb.CJK_FONT` → `CJK_FONT`、`rb.MONO_FONT` → `MONO_FONT`、`rb.GAME_BG` → `GAME_BG`、
`rb.GAME_BORDER` → `GAME_BORDER`、`rb.GAME_DIM` → `GAME_DIM`、`rb.GAME_GOLD` → `GAME_GOLD`、
`rb.GAME_PANEL` → `GAME_PANEL`、`rb.GAME_TEXT` → `GAME_TEXT`、
`rb.load_translations` → `load_translations` 逐处替换。**`rb.font` 保持不动。**

- [ ] **Step 3: 语法检查 + 断言只剩合法的 `rb.` 引用**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
python -m py_compile report/bin/render_report_normalized.py report/bin/render_review_normalized.py && echo COMPILE_OK
grep -oE 'rb\.[A-Za-z_]+' report/bin/render_report_normalized.py report/bin/render_review_normalized.py | sort -u
```

Expected: `COMPILE_OK`;`rb.` 列表**只剩**这些渲染器符号 —— `render_report_normalized.py`:
`rb.MatchReport` `rb.PlayerStats` `rb.render` `rb.load_achievements` `rb._ACH_ID_TO_INDEX`;
`render_review_normalized.py`:`rb.font`。
**不含任何 `GAME_*` / `CJK_FONT` / `MONO_FONT` / `DEATH_CAUSE_CN` / `MATCH_GROUP_CN` / `rb.load_translations`。**

- [ ] **Step 4: 基线比对(这两个脚本正是基线的产出者,最关键的一次)**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
T="$(python -c 'import tempfile;print(tempfile.gettempdir())')"
rm -rf "$T/p2_check"
bash tools/p2_render_fixtures.sh "$T/p2_check" >/dev/null
diff docs/superpowers/plans/2026-09-18-p2-baseline.sha256 "$T/p2_check/fixtures.sha256"   && echo PIXEL_IDENTICAL
```

Expected: `PIXEL_IDENTICAL`

- [ ] **Step 5: 提交**

```bash
git add report/bin/render_report_normalized.py report/bin/render_review_normalized.py
git commit -m "refactor(report): normalized 两脚本的 theme/标签表改从 wowsbot 取

对渲染器的合法依赖(rb.render / rb.load / rb.MatchReport / rb.PlayerStats /
rb.font / rb.load_achievements / rb._ACH_ID_TO_INDEX)保留不动。
渲染图 sha256 与重构前一致。"
```

---

## Task 8: `report/bin` 入口脚本收路径 + build 解析去重

**Files:** Modify `report/bin/wows_report` `wows_full_report` `wows_full_report_normalized` `wows_damage_report` `wows_menu`

- [ ] **Step 1: `wows_report` —— 常量换 paths,build 解析换 replay**

在 import 区加:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from wowsbot import paths, replay          # noqa: E402
```

删掉这些声明,改用 `paths` 的同名值(赋值保留,免得改动函数体):

```python
BOT_HOME = paths.REPORT_ROOT              # 原 Path(__file__).resolve().parent.parent
REPLAYSHARK = paths.REPLAYSHARK
SPECS_DIR = paths.SPECS_DIR
CONSTANTS_JSON = paths.CONSTANTS_JSON
RENDER_PY = paths.RENDER_BATTLE_PY
DEFAULT_OUT_DIR = paths.OUT_DIR
EXTRACTED_ROOT = paths.EXTRACTED_ROOT
SPECS_PATCHED_ROOT = paths.SPECS_PATCHED_ROOT
```

删掉本文件的 `read_replay_meta()` 与 `parse_build()`,改用 `replay`:

```python
# 原:meta = read_replay_meta(replay_path); replay_build = parse_build(meta)
#     version_str = ".".join(meta.get("clientVersionFromExe","").split(",")[:3]) or "0.0.0"
replay_build = replay.build_of(str(replay_path))
version_str = replay.version_of(str(replay_path))
```

**注意**:原 `parse_build()` 若解析失败的返回值与 `replay.build_of` 的 `None` 不同,须保持调用点行为一致 —— 先跑 `grep -n 'parse_build\|read_replay_meta\|REPLAY_SIGNATURE' report/bin/wows_report` 看清所有用法再改;`REPLAY_SIGNATURE` 若仍被用于校验则保留。

- [ ] **Step 2: 另外 4 个入口脚本**

`wows_full_report`:

```python
BOT_HOME = paths.REPORT_ROOT
WOWS_REPORT = Path(paths.REPORT_BATTLE_CMD)
WOWS_DAMAGE_REPORT = Path(paths.REPORT_DAMAGE_CMD)
RENDER_CRIMINALS = Path(paths.RENDER_CRIMINALS_PY)
DEFAULT_OUT = paths.OUT_DIR
```

（`GAP` / `BG` 是拼图用的排版常量,留在原处不动。)

`wows_full_report_normalized`:

```python
BOT_HOME = paths.REPORT_ROOT
REPLAYSHARK = paths.REPLAYSHARK
BIN = paths.BIN_DIR
DEFAULT_OUT = paths.OUT_DIR
```

`wows_damage_report`:

```python
BOT_HOME = paths.REPORT_ROOT
WOWS_REPORT = Path(paths.REPORT_BATTLE_CMD)
RENDER_PY = Path(paths.RENDER_DAMAGE_PY)
DEFAULT_OUT = paths.OUT_DIR
```

`wows_menu`:

```python
BOT_HOME = paths.REPORT_ROOT
RENDER_PY = Path(paths.RENDER_MENU_PY)
```

每个文件都要在 import 区加 bootstrap 两行(同 Step 1)。

- [ ] **Step 3: 语法检查**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
python -m py_compile report/bin/wows_report report/bin/wows_full_report \
  report/bin/wows_full_report_normalized report/bin/wows_damage_report report/bin/wows_menu \
  && echo COMPILE_OK
```

Expected: `COMPILE_OK`

- [ ] **Step 4: 端到端跑一次全报告(证明入口脚本没被改坏)**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
export WOWS_CJK_FONT=C:/Windows/Fonts/msyh.ttc WOWS_MONO_FONT=C:/Windows/Fonts/consola.ttf
export WOWS_REPLAYSHARK=/c/Users/29801/Desktop/minimap/wows-toolkit/target/release/replayshark.exe
export WOWS_EXTRACTED_ROOT=/c/Users/29801/Desktop/minimap/wows-toolkit/extracted
python report/bin/wows_full_report_normalized "$(cat /tmp/p2_baseline/replay.txt)" /tmp/p2_e2e
ls -la /tmp/p2_e2e/*.png
```

Expected: 生成拼接图 PNG 且 > 5KB。（本机若缺 Lesta specs 等依赖导致失败,记录为环境限制,并在服务器部署后补做这条。)

- [ ] **Step 5: 提交**

```bash
git add report/bin/wows_report report/bin/wows_full_report \
  report/bin/wows_full_report_normalized report/bin/wows_damage_report report/bin/wows_menu
git commit -m "refactor(report): 5 个入口脚本常量收进 wowsbot.paths

wows_report 里自写的 read_replay_meta/parse_build 换成 wowsbot.replay
(与 plugin/minimap.py 那份合并为一份实现)。含义冲突的 BOT_HOME 保留为
paths.REPORT_ROOT 的别名,避免改动函数体。"
```

---

## Task 9: `plugin/minimap.py` 收路径 + build 去重 + sys.path helper

**Files:** Modify `plugin/minimap.py`

- [ ] **Step 1: 加 bootstrap**

`plugin/*` 会被 `cp` 到 EssexBot 目录,`Path(__file__)` 找不到仓库,所以用 env:

```python
import os as _os
import sys as _sys
_LIB = _os.path.join(_os.environ.get("WOWS_BOT_HOME", "/opt/wows-bot"), "report", "lib")
if _LIB not in _sys.path:
    _sys.path.insert(0, _LIB)
from wowsbot import paths as _paths, replay as _replay   # noqa: E402
```

- [ ] **Step 2: 常量改用 paths(名字全部保持不变)**

```python
RENDER_SH             = _paths.RENDER_SH
REPORT_FULL_CMD       = _paths.REPORT_FULL_CMD
REPORT_BATTLE_CMD     = _paths.REPORT_BATTLE_CMD
REPORT_DAMAGE_CMD     = _paths.REPORT_DAMAGE_CMD
RENDER_CRIMINALS_PY   = _paths.RENDER_CRIMINALS_PY
RENDER_CHAT_PY        = _paths.RENDER_CHAT_PY
REPORT_FULL_LESTA_CMD = _paths.REPORT_FULL_LESTA_CMD
REPLAYSHARK_LESTA     = _paths.REPLAYSHARK_LESTA
WOWS_DATA_DIR         = _paths.EXTRACTED_ROOT
REPORT_CMD            = _paths.REPORT_CMD
ANALYZE_CMD           = _paths.ANALYZE_CMD
BASE_DIR              = _paths.REPLAY_BASEDIR
SHIPS_JSON            = _paths.SHIPS_JSON
ARMOR_JSON            = _paths.ARMOR_JSON
MP4_TIMEOUT           = _paths.MP4_TIMEOUT
PNG_TIMEOUT           = _paths.PNG_TIMEOUT
ANALYZE_TIMEOUT       = _paths.ANALYZE_TIMEOUT
```

`SHIPS_JSON` / `ARMOR_JSON` 由此从「命令路径 `.parent.parent` 反推」变成「从 `REPORT_ROOT` 派生」—— 默认值相同,但不再受 `WOWS_REPORT_FULL_CMD` 被改动的牵连。

- [ ] **Step 3: build 解析换 replay**

删掉 `_replay_build()` 与 `_available_builds()`,把 `unsupported_build_notice()` 里的调用改为:

```python
    build = _replay.build_of(replay_path)
    ...
    avail = _replay.available_builds(WOWS_DATA_DIR)
```

其余逻辑(`friendly_error` / `_extract_build` / 文案)一行不动。

- [ ] **Step 4: 7 处 sys.path 样板收成 helper**

新增一个 helper,替换 7 处重复:

```python
def _import_report_bin(module: str):
    """import report/bin 下的渲染模块(它们不是包,靠 sys.path 找)。

    重构前这段 3 行样板在本文件里重复了 7 次。
    """
    bin_dir = str(_paths.BIN_DIR)
    if bin_dir not in _sys.path:
        _sys.path.insert(0, bin_dir)
    return __import__(module)
```

调用点例如:

```python
# 原:
#   if bin_path not in _sys.path:
#       _sys.path.insert(0, bin_path)
#   from render_query import render_query_png
render_query_png = _import_report_bin("render_query").render_query_png
```

**逐个改并保持函数体其余部分不变**;改完用 `grep -c 'sys.path.insert' plugin/minimap.py` 确认只剩 bootstrap 那一处。

- [ ] **Step 5: 语法检查 + 断言**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
python -m py_compile plugin/minimap.py && echo COMPILE_OK
grep -c 'sys.path.insert' plugin/minimap.py     # 期望 1(只剩 bootstrap)
grep -n 'os.environ.get' plugin/minimap.py      # 期望只剩 WOWS_BOT_HOME 那一处
```

Expected: `COMPILE_OK`;`sys.path.insert` 计数为 1;`os.environ.get` 只剩 bootstrap 里那一处。

- [ ] **Step 6: 冒烟(nonebot 不在本机也能验的部分)**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
WOWS_BOT_HOME=/opt/wows-bot python - <<'EOF'
import ast, pathlib
src = pathlib.Path("plugin/minimap.py").read_text(encoding="utf-8")
ast.parse(src)   # 语法与缩进
print("AST_OK")
EOF
python tests/test_permissions.py
```

Expected: `AST_OK` + `== ALL PASS ==`。（`import plugin.minimap` 需要 nonebot 运行环境,留到服务器部署后验。)

- [ ] **Step 7: 提交**

```bash
git add plugin/minimap.py
git commit -m "refactor(plugin): minimap.py 常量与 build 解析收进 wowsbot

20 处 os.environ.get 收成 paths 的赋值(名字与类型不变);自写的 _replay_build /
_available_builds 换 wowsbot.replay;7 处重复的 sys.path.insert 样板收成
_import_report_bin helper。SHIPS_JSON / ARMOR_JSON 不再从命令路径反推。"
```

---

## Task 10: `tools/*.py` 收路径并修掉默认路径错一层

**Files:** Modify `tools/build_builds_json.py` `tools/fetch_build_icons.py` `tools/build_ships_json.py` `tools/fetch_ship_icons.py`

- [ ] **Step 1: 先记录修复前的错误默认值(证据)**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
python tools/build_builds_json.py --help | grep -E 'default:'
```

Expected: 能看到 `--specs` / `--replayshark` 的默认值**缺少 `report/`** 这一层(例如 `/opt/wows-bot/specs`、`/opt/wows-bot/replayshark`)。把输出贴进执行记录作为修复前证据。

- [ ] **Step 2: 四个文件都加 bootstrap 并改默认值**

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "report" / "lib"))
from wowsbot import paths                # noqa: E402
```

`tools/build_builds_json.py`:

```python
DEFAULT_SPECS = Path(paths.SPECS_DIR)              # 原 BOT_HOME/"specs" —— 少了 report/
DEFAULT_MO = Path(paths.TRANSLATIONS_MO)
DEFAULT_OUT = Path(paths.BUILDS_JSON)
DEFAULT_REPLAYSHARK = Path(paths.REPLAYSHARK)      # 原 BOT_HOME/"replayshark" —— 少了 report/
```

`tools/fetch_build_icons.py`(已 grep 确认,前两个原本错一层):

```python
DEFAULT_SPECS = Path(paths.SPECS_DIR)              # 原 BOT_HOME/"specs" —— 少了 report/
DEFAULT_REPLAYSHARK = Path(paths.REPLAYSHARK)      # 原 BOT_HOME/"replayshark" —— 少了 report/
DEFAULT_UPGRADE_DIR = Path(paths.UPGRADE_ICON_DIR)
DEFAULT_SKILL_DIR = Path(paths.SKILL_ICON_DIR)
```

（`UPGRADE_URL` / `SKILL_URL` 是 wowsinfo 的下载地址,与路径无关,留在原处不动。)

`tools/build_ships_json.py`(第一个原本也错一层):

```python
DEFAULT_GAMEPARAMS = Path(paths.GAME_PARAMS_DATA)  # 原 BOT_HOME/"specs"/"content"/... —— 少了 report/
DEFAULT_MO = Path(paths.TRANSLATIONS_MO)
DEFAULT_OUT = Path(paths.SHIPS_JSON)
```

（`DEFAULT_HOST` / `DEFAULT_APP_ID` / `SPECIES_ZH` / `NATION_ZH` / `MODULE_PARAM` 与路径无关,不动。)

`tools/fetch_ship_icons.py`(这两个原本是对的,改用 paths 只为统一来源):

```python
DEFAULT_SHIPS_JSON = Path(paths.SHIPS_JSON)
DEFAULT_ICON_DIR = Path(paths.SHIP_ICON_DIR)
```

（`DEFAULT_HOST` / `DEFAULT_APP_ID` 不动。)

- [ ] **Step 3: 验证默认值已修正**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
python -m py_compile tools/build_builds_json.py tools/fetch_build_icons.py \
  tools/build_ships_json.py tools/fetch_ship_icons.py && echo COMPILE_OK
python tools/build_builds_json.py --help | grep -E 'default:'
```

Expected: `COMPILE_OK`,且默认值现在都带 `report/`。再核对另两个脚本:

```bash
python tools/fetch_build_icons.py --help | grep -E 'default:'
python tools/build_ships_json.py --help | grep -E 'default:'
```

Expected: `--specs` / `--replayshark` / GameParams 路径都带 `report/`(修复前缺这一层)。

- [ ] **Step 4: 提交**

```bash
git add tools/build_builds_json.py tools/fetch_build_icons.py \
  tools/build_ships_json.py tools/fetch_ship_icons.py
git commit -m "fix(tools): 默认路径少一层 report/ 的老坑,常量收进 wowsbot.paths

根因是 BOT_HOME 同名不同义:report/bin/* 里它指 report/,tools/* 里指仓库根,
所以 DEFAULT_SPECS / DEFAULT_REPLAYSHARK 少了一层(同文件 DEFAULT_MO/OUT 又是
对的)。改用 paths 后,刷 builds.json 不必再手动带 WOWS_REPLAYSHARK= 和 --specs。"
```

---

## Task 11: 收尾验证 + 文档

**Files:** Modify `docs/DEPLOY.md`(新增一节说明公共层)

- [ ] **Step 1: 依赖纯净性(硬约束)**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
grep -rnE 'nonebot|subprocess|ImageDraw' report/lib/wowsbot/ ; echo "^ 必须为空"
```

Expected: 无输出。

- [ ] **Step 2: 零残留(两种 import 形式)**

```bash
grep -rn 'from render_battle_report import' report/ plugin/ ; echo "^ 必须为空"
grep -oE 'rb\.[A-Za-z_]+' report/bin/render_report_normalized.py \
  report/bin/render_review_normalized.py | sort -u
```

Expected: 第一条无输出;第二条只剩渲染器符号(`rb.render` `rb.load` `rb.MatchReport` `rb.PlayerStats` `rb.font` `rb.load_achievements` `rb._ACH_ID_TO_INDEX`),无 theme/标签表。

- [ ] **Step 3: 全部测试**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
for t in tests/test_permissions.py tests/test_render_menu.py tests/test_render_armor.py \
         tests/test_wowsbot_paths.py tests/test_wowsbot_replay.py tests/test_wowsbot_lib.py; do
  echo "--- $t"; python "$t" || echo "FAILED: $t"
done
```

Expected: 6 个全部 `== ALL PASS ==`,无 `FAILED`。

- [ ] **Step 3b: 多环境 import 冒烟(spec 验证第 5 条,需在服务器上跑)**

公共层要同时被 nonebot 环境与 report 的 venv 环境 import。两个解释器各验一次:

```bash
# report 侧用的解释器(见 wows_report::find_python 的优先级)
PY_REPORT="$(python3 - <<'EOF'
import os, pathlib
v = os.environ.get("WOWS_PYTHON") or (
    (os.environ.get("WOWS_PY_VENV") or "/opt/wows-bot/venv") + "/bin/python")
print(v if pathlib.Path(v).exists() else "python3")
EOF
)"
echo "report python = $PY_REPORT"
"$PY_REPORT" -c "import sys; sys.path.insert(0,'/opt/wows-bot/report/lib'); from wowsbot import paths, replay, theme, text, i18n, results; print('REPORT_ENV_OK', paths.REPO_ROOT)"
```

```bash
# nonebot 侧解释器(改成实际的 EssexBot venv 路径)
NB_PY=~zifeng/桌面/bot/EssexBot/.venv/bin/python
test -x "$NB_PY" || NB_PY=python3
"$NB_PY" -c "import sys; sys.path.insert(0,'/opt/wows-bot/report/lib'); from wowsbot import paths, replay, theme, text, i18n, results; print('NONEBOT_ENV_OK', paths.REPO_ROOT)"
```

Expected: 两条都打印 `*_OK` 且 `REPO_ROOT` = `/opt/wows-bot`。
**若某个环境缺 `polib` 导致 `i18n` import 失败** —— 说明该环境本来就没装,记录下来:
`i18n.load_translations` 在缺 polib 时只打警告不抛,但 `import` 本身不该失败
(polib 是在函数体里 import 的),若真在 import 阶段炸就是搬迁写错了,必须修。

- [ ] **Step 4: 最终基线比对**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
T="$(python -c 'import tempfile;print(tempfile.gettempdir())')"
rm -rf "$T/p2_check"
bash tools/p2_render_fixtures.sh "$T/p2_check" >/dev/null
diff docs/superpowers/plans/2026-09-18-p2-baseline.sha256 "$T/p2_check/fixtures.sha256"   && echo PIXEL_IDENTICAL
```

Expected: `FINAL_PIXEL_IDENTICAL`

- [ ] **Step 4b: footer 覆盖检查(sha256 门槛跳过了 footer,单独验它没坏)**

主门槛用 `WOWS_SKIP_FOOTER=1`,所以 footer 那段绘图代码没被比对覆盖。footer 用的正是
搬走的 theme 常量(`GAME_GOLD` 等),所以要单独确认它仍能画出来、几何未变:

```bash
cd /c/Users/29801/Desktop/wows-bot-review
T="$(python -c 'import tempfile;print(tempfile.gettempdir())')"
python - <<'EOF'
import os, subprocess, sys, tempfile
from PIL import Image
T = tempfile.gettempdir()
json_in = os.path.join(T, "p2_baseline", "report.json")
env = dict(os.environ, WOWS_CJK_FONT="C:/Windows/Fonts/msyh.ttc",
           WOWS_MONO_FONT="C:/Windows/Fonts/consola.ttf",
           WOWS_BOT_VERSION="p2-fixture")
out = {}
for tag, skip in (("with", "0"), ("without", "1")):
    e = dict(env); e["WOWS_SKIP_FOOTER"] = skip
    png = os.path.join(T, f"p2_footer_{tag}.png")
    subprocess.run([sys.executable, "report/bin/render_report_normalized.py", json_in, png],
                   env=e, check=True, stdout=subprocess.DEVNULL)
    out[tag] = Image.open(png).size
print("with footer   :", out["with"])
print("without footer:", out["without"])
assert out["with"][0] == out["without"][0], "宽度不该变"
assert out["with"][1] - out["without"][1] == 48, f"footer 高度应为 48,实际 {out['with'][1]-out['without'][1]}"
print("FOOTER_GEOMETRY_OK")
EOF
```

Expected: 打印 `FOOTER_GEOMETRY_OK`(宽度不变、带 footer 高 48px)。
这证明 footer 绘制路径仍然正常执行、用的 theme 常量没缺失。

- [ ] **Step 4c: 删除重构期脚手架**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git rm tools/p2_render_fixtures.sh
git commit -m "chore(p2): 移除重构期的 fixture 渲染脚手架"
```

Expected: 脚本删除并提交。基线 sha256 文件保留在 `docs/superpowers/plans/` 里作为历史记录。

- [ ] **Step 5: 文档 —— 在 `docs/DEPLOY.md` 末尾加一节**

```markdown
## 公共层 `report/lib/wowsbot/`

bot 的 Python 公共层。路径/配置、回放元数据、主题、文本、翻译、结算字段各一个模块。

- **谁在用**:`plugin/*`(nonebot 环境)、`report/bin/*`(venv 环境)、`tools/*`。
- **怎么被找到**:纯 `sys.path`,不需要 pip install(运行时存在多个 Python 环境,
  见 `wows_report::find_python`)。`report/bin/*` 与 `tools/*` 用相对路径;
  `plugin/*` 因为会被 `cp` 到 EssexBot 目录,靠 `WOWS_BOT_HOME`(默认 `/opt/wows-bot`)。
- **硬约束**:`wowsbot/` 内不 import `nonebot`、不 `subprocess`、不做 PIL 绘图 ——
  否则三类环境无法共用。CI/收尾验证里有 grep 断言。
- **env 变量**:全部在 `wowsbot/paths.py` 里集中声明(名字与历史完全兼容)。
  加新路径请只改那里,不要在别处再写 `os.environ.get`。
- **注意 `BOT_HOME` 的历史含义冲突**:老代码里它在 `report/bin/*` 指 `report/`、
  在 `tools/*` 指仓库根。新代码用 `paths.REPO_ROOT` / `paths.REPORT_ROOT`,别再用这个名字。
```

- [ ] **Step 6: 提交**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add docs/DEPLOY.md
git commit -m "docs(deploy): 记录 report/lib/wowsbot 公共层的用法与硬约束"
```

- [ ] **Step 7: 部署(交给用户执行,不要自动重启服务)**

给用户这几条,并说明**`.env` 一行不用改**:

```bash
cd /opt/wows-bot && sudo git pull
```
```bash
sudo cp /opt/wows-bot/plugin/*.py ~zifeng/桌面/bot/EssexBot/src/plugins/
```
部署后由用户重启 nonebot,然后发一份回放做端到端验收(MP4 / 战报 / 复盘 / 聊天)。
若 `plugin/minimap.py` 报 `ModuleNotFoundError: wowsbot`,说明 `WOWS_BOT_HOME` 与
实际仓库位置不符 —— 在 `.env` 里加 `WOWS_BOT_HOME=/opt/wows-bot` 即可。

---

## 完成标准

1. `report/lib/wowsbot/` 下 6 个模块各自单一职责,grep 断言无禁止依赖。
2. `grep -rn 'from render_battle_report import' report/ plugin/` 为空;两个 `rb.` 脚本只剩渲染器符号。
3. 6 个测试文件全绿(3 个原有 + 3 个新增)。
4. 渲染图 sha256 与 Task 0 基线**逐字节一致**。
5. `plugin/minimap.py` 里 `sys.path.insert` 只剩 1 处、`os.environ.get` 只剩 1 处。
6. `tools/build_builds_json.py --help` 的默认路径带 `report/`。
7. `.env` 未做任何改动。
