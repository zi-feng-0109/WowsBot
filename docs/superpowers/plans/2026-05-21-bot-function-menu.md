# Bot 功能菜单 + 群级开关系统 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 EssexBot 加一张 PNG 功能菜单 + 4 个独立可开关的子功能 (`视频/战报/复盘/分析`) + 两级权限 (超管全局黑名单 + 群管本群开关)，并把旧的 `analyze_toggle.json` 平滑迁移成统一的 `toggle_state.json`。

**Architecture:** 新增 `plugin/permissions.py` 作为权限+状态唯一来源；新增 `plugin/version.py` 提供版本字符串；新增 `report/bin/render_menu.py` 渲染 PNG (复用 `render_battle_report` 色板)；`plugin/minimap.py` 改成所有开关读写都过 `permissions`，replay 流水线按 4 个 feature toggle 决定跑哪几步。

**Tech Stack:** Python 3.11+, NoneBot2 (onebot.v11), PIL (Pillow)。无现有测试框架，新增的纯逻辑模块用 `python tests/test_*.py` 风格自测脚本 (assert + print)，不引入 pytest 依赖。Bot handler 用手动 smoke test。

**Spec:** `docs/superpowers/specs/2026-05-21-bot-function-menu-design.md`

---

## 关键路径变量 (适用全计划)

```bash
# 本地开发机
WOWS_BOT=/c/Users/29801/Desktop/wows-bot-review

# 服务器侧 (部署时参考)
SERVER_BOT=/opt/wows-bot                              # 渲染工具仓库
SERVER_APP=/home/zifeng/桌面/bot/EssexBot              # NoneBot 应用 (subprocess 调用 SERVER_BOT 里的脚本)

# 字体 (render_menu 复用 render_battle_report 已用的)
export WOWS_CJK_FONT="C:/Windows/Fonts/msyh.ttc"      # 本地 smoke test 用
```

---

## File Structure

**新增 (Python):**
- `plugin/version.py` — `__version__` 常量 + `git_short_hash()` + `version_str()`，~25 行
- `plugin/permissions.py` — 全局单例状态 + 读写 + `feature_enabled / set_feature / is_super_admin / can_toggle / super_admin_ban / super_admin_unban` + 旧文件迁移，~150 行
- `report/bin/render_menu.py` — 菜单 PNG 渲染库 + main 入口，~250 行
- `report/bin/wows_menu` — shell wrapper，类比 `wows_report`，bot subprocess 调用入口，~50 行

**新增 (测试):**
- `tests/test_permissions.py` — 用 tmp 目录跑 read/write/migrate/can_toggle 边界，~120 行
- `tests/test_render_menu.py` — 用合成 state 渲染一张 PNG，验证文件存在且 size > 1KB，~50 行

**修改:**
- `plugin/minimap.py` — 删除 `_toggle_state` / `analyze_enabled` / `analyze_set` (line 52-95)；替换为 `from . import permissions`；新增 4 个 toggle 命令的工厂式注册；新增菜单 handler；新增 /sa 命令；`process_queue` 改用 `permissions.feature_enabled` 按 feature 过滤
- `docs/DEPLOY.md` — 新增 §"超管 & 群级开关" 段，说明 `superusers` 配置、`toggle_state.json` 位置、自动迁移逻辑

**新增数据文件 (运行时创建,不入 git):**
- `<WOWS_REPLAY_BASEDIR>/toggle_state.json` — 状态持久化文件 (旧 `analyze_toggle.json` 会被自动迁移并改名 `.bak`)

---

## 顺序与依赖

```
Task 1 (version.py)         独立
Task 2 (permissions.py)     独立
Task 3 (test_permissions)   依赖 Task 2
Task 4 (migrate + 测试)     依赖 Task 2, 3
Task 5 (render_menu.py)     依赖 Task 1, 2
Task 6 (wows_menu wrapper)  依赖 Task 5
Task 7 (test_render_menu)   依赖 Task 5
Task 8 (delegate /分析 到 permissions)   依赖 Task 2, 4
Task 9 (4-feature toggle commands)        依赖 Task 8
Task 10 (menu handler 三入口)             依赖 Task 6
Task 11 (/sa 超管命令)                    依赖 Task 2
Task 12 (process_queue 按 feature 过滤)   依赖 Task 8, 9
Task 13 (DEPLOY.md)                       依赖 Task 1-12 全部完成
```

按 1→13 顺序执行,每个 task 完成立即 commit。

---

## Task 1: 版本号模块

**Files:**
- Create: `plugin/version.py`

- [ ] **Step 1: 写 version.py**

```python
# plugin/version.py
"""Bot 版本信息 — render_menu.py 和未来的 /version 命令都从这里取。"""
import subprocess
from pathlib import Path

__version__ = "0.4.0"

_REPO_ROOT = Path(__file__).resolve().parent.parent  # plugin/.. = repo root


def git_short_hash() -> str:
    """运行时取 git short hash;不在 git 仓库或 git 不可用时返回空串。"""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""


def version_str() -> str:
    """格式化版本字符串: 'v0.4.0+abc1234' 或 'v0.4.0'(无 git 时)。"""
    h = git_short_hash()
    return f"v{__version__}+{h}" if h else f"v{__version__}"
```

- [ ] **Step 2: 命令行 smoke test**

Run:
```bash
cd /c/Users/29801/Desktop/wows-bot-review
python -c "from plugin.version import version_str, __version__, git_short_hash; \
print('version:', version_str()); print('hash:', git_short_hash() or '<empty>'); \
assert __version__.count('.') == 2; assert version_str().startswith('v')"
```

Expected stdout:
```
version: v0.4.0+<7位hex>
hash: <7位hex>
```

- [ ] **Step 3: Commit**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add plugin/version.py
git commit -m "feat(plugin): version.py — __version__ + git short hash"
```

---

## Task 2: 权限状态模块骨架

**Files:**
- Create: `plugin/permissions.py`

- [ ] **Step 1: 写 permissions.py (不含 migration,先做核心)**

```python
# plugin/permissions.py
"""权限模型 + 群级开关状态持久化。

状态结构 (toggle_state.json):
    {
      "version": 1,
      "global_blacklist": [],
      "groups": {"<group_id>": {"视频": true, "战报": true, ...}},
      "private": {"<user_id>": {"分析": true, ...}}
    }

唯一来源原则:bot 任何地方查/改开关都过本模块的函数,不要直接读 state 字典。
"""
import json
import os
import threading
from pathlib import Path
from typing import Tuple

from nonebot import get_driver
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

FEATURES = ["视频", "战报", "复盘", "分析"]
DEFAULT_ON = True
_STATE_VERSION = 1
_LEGACY_FILE_NAME = "analyze_toggle.json"
_STATE_FILE_NAME = "toggle_state.json"

_lock = threading.RLock()
_state: dict = {}
_loaded = False
_state_path: Path | None = None


def _empty_state() -> dict:
    return {
        "version": _STATE_VERSION,
        "global_blacklist": [],
        "groups": {},
        "private": {},
    }


def init(state_dir: str) -> None:
    """显式初始化:bot 启动时调一次。state_dir 通常 = WOWS_REPLAY_BASEDIR。
    幂等;重复调只会重新读盘。"""
    global _state_path, _state, _loaded
    with _lock:
        _state_path = Path(state_dir) / _STATE_FILE_NAME
        _state_path.parent.mkdir(parents=True, exist_ok=True)
        _load()
        _loaded = True


def _load() -> None:
    """从盘上读 state;不存在或损坏时用空 state。需在 _lock 内调用。"""
    global _state
    assert _state_path is not None, "permissions.init() not called"
    if _state_path.is_file():
        try:
            with open(_state_path, "r", encoding="utf-8") as f:
                _state = json.load(f)
        except (json.JSONDecodeError, OSError):
            _state = _empty_state()
    else:
        _state = _empty_state()
    # 兜底:旧文件可能字段缺失
    for k in ("global_blacklist", "groups", "private"):
        _state.setdefault(k, [] if k == "global_blacklist" else {})
    _state.setdefault("version", _STATE_VERSION)


def _save() -> None:
    """原子写:tmp + rename。需在 _lock 内调用。"""
    assert _state_path is not None
    tmp = _state_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _state_path)


def scope_of(event: MessageEvent) -> Tuple[str, str]:
    """根据 event 返回 (scope, ident) — 群消息 -> ('group', group_id);否则 ('private', user_id)。"""
    if isinstance(event, GroupMessageEvent):
        return ("group", str(event.group_id))
    return ("private", str(event.user_id))


def _bucket_name(scope: str) -> str:
    if scope == "group":
        return "groups"
    if scope == "private":
        return "private"
    raise ValueError(f"unknown scope: {scope}")


def feature_enabled(scope: str, ident: str, feature: str) -> bool:
    """权威开关查询:超管黑名单优先,然后查作用域开关,缺失走 DEFAULT_ON。"""
    assert feature in FEATURES, f"unknown feature: {feature}"
    with _lock:
        if feature in _state["global_blacklist"]:
            return False
        bucket = _state[_bucket_name(scope)]
        return bucket.get(str(ident), {}).get(feature, DEFAULT_ON)


def set_feature(scope: str, ident: str, feature: str, value: bool) -> None:
    """改作用域开关并落盘。不检查权限 — 调用方先用 can_toggle 鉴权。"""
    assert feature in FEATURES, f"unknown feature: {feature}"
    with _lock:
        bucket = _state[_bucket_name(scope)]
        bucket.setdefault(str(ident), {})[feature] = bool(value)
        _save()


def is_super_admin(user_id: str | int) -> bool:
    """对照 NoneBot superusers 配置;每次现读,不缓存(便于热改 .env)。"""
    return str(user_id) in get_driver().config.superusers


def can_toggle(event: MessageEvent, scope_ident: str) -> bool:
    """谁能改某作用域开关:超管全能;群管/群主能改本群;私聊只能改自己。"""
    if is_super_admin(event.user_id):
        return True
    if isinstance(event, GroupMessageEvent):
        return event.sender.role in ("owner", "admin")
    return scope_ident == str(event.user_id)


def super_admin_ban(feature: str) -> None:
    """超管全局禁用 — 任何作用域都开不了。"""
    assert feature in FEATURES
    with _lock:
        bl = set(_state["global_blacklist"])
        bl.add(feature)
        _state["global_blacklist"] = sorted(bl)
        _save()


def super_admin_unban(feature: str) -> None:
    assert feature in FEATURES
    with _lock:
        bl = set(_state["global_blacklist"])
        bl.discard(feature)
        _state["global_blacklist"] = sorted(bl)
        _save()


def global_blacklist() -> list[str]:
    """只读快照,UI/菜单用。"""
    with _lock:
        return list(_state["global_blacklist"])


def snapshot() -> dict:
    """整份状态的只读深拷贝 — 给 render_menu / /sa stats 用。"""
    with _lock:
        return json.loads(json.dumps(_state))
```

- [ ] **Step 2: 命令行 syntax check**

Run:
```bash
cd /c/Users/29801/Desktop/wows-bot-review
python -c "import ast; ast.parse(open('plugin/permissions.py', encoding='utf-8').read()); print('syntax OK')"
```

Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add plugin/permissions.py
git commit -m "feat(plugin): permissions.py — 群级开关 + 超管黑名单状态模型"
```

---

## Task 3: permissions 单元测试

**Files:**
- Create: `tests/test_permissions.py`

- [ ] **Step 1: 写测试**

```python
# tests/test_permissions.py
"""permissions 模块自测脚本。
用法: python tests/test_permissions.py
退出码 0=全过,非 0=失败。
无 pytest 依赖,纯 assert + print。"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# 让脚本能 import plugin/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _reset_module():
    """每个 case 起一次新 tempdir + 重导模块,避免单例污染。"""
    import importlib
    if "plugin.permissions" in sys.modules:
        del sys.modules["plugin.permissions"]
    if "plugin" in sys.modules:
        del sys.modules["plugin"]
    # mock nonebot.get_driver 提供假 superusers 配置
    fake_driver = MagicMock()
    fake_driver.config.superusers = {"11111"}
    import nonebot  # noqa
    nonebot.get_driver = lambda: fake_driver
    from plugin import permissions
    return permissions


def test_default_state():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        perms.init(d)
        # 没设过的 group + feature 应该按 DEFAULT_ON
        assert perms.feature_enabled("group", "999", "战报") is True
        assert perms.feature_enabled("private", "888", "分析") is True
    print("  default_state PASS")


def test_set_and_persist():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        perms.init(d)
        perms.set_feature("group", "999", "复盘", False)
        assert perms.feature_enabled("group", "999", "复盘") is False
        # 文件落地了
        state_file = Path(d) / "toggle_state.json"
        assert state_file.is_file()
        data = json.loads(state_file.read_text("utf-8"))
        assert data["groups"]["999"]["复盘"] is False
        # 重新 init 后状态保留
        perms2 = _reset_module()
        perms2.init(d)
        assert perms2.feature_enabled("group", "999", "复盘") is False
    print("  set_and_persist PASS")


def test_global_blacklist_vetoes_group():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        perms.init(d)
        perms.set_feature("group", "999", "分析", True)
        assert perms.feature_enabled("group", "999", "分析") is True
        perms.super_admin_ban("分析")
        # 超管 ban 后,即便 group 自己开着也算关
        assert perms.feature_enabled("group", "999", "分析") is False
        perms.super_admin_unban("分析")
        assert perms.feature_enabled("group", "999", "分析") is True
    print("  global_blacklist_vetoes_group PASS")


def test_is_super_admin():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        perms.init(d)
        assert perms.is_super_admin("11111") is True
        assert perms.is_super_admin(11111) is True  # int 也行
        assert perms.is_super_admin("99999") is False
    print("  is_super_admin PASS")


def test_can_toggle_group_admin():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        perms.init(d)
        # 模拟一个群管 (非超管) 发送群消息
        ev = MagicMock()
        ev.user_id = "22222"
        ev.sender.role = "admin"
        ev.group_id = 999
        # 让 isinstance 检查通过
        from nonebot.adapters.onebot.v11 import GroupMessageEvent
        ev.__class__ = GroupMessageEvent
        assert perms.can_toggle(ev, "999") is True
        # 普通 member 不行
        ev.sender.role = "member"
        assert perms.can_toggle(ev, "999") is False
        # 但超管不论角色都行
        ev.user_id = "11111"
        ev.sender.role = "member"
        assert perms.can_toggle(ev, "999") is True
    print("  can_toggle_group_admin PASS")


def test_unknown_feature_assertion():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        perms.init(d)
        try:
            perms.feature_enabled("group", "999", "猜船")
        except AssertionError:
            pass
        else:
            raise AssertionError("应该 raise AssertionError")
    print("  unknown_feature_assertion PASS")


if __name__ == "__main__":
    print("== test_permissions ==")
    test_default_state()
    test_set_and_persist()
    test_global_blacklist_vetoes_group()
    test_is_super_admin()
    test_can_toggle_group_admin()
    test_unknown_feature_assertion()
    print("== ALL PASS ==")
```

- [ ] **Step 2: 跑测试,确认全过**

Run:
```bash
cd /c/Users/29801/Desktop/wows-bot-review
python tests/test_permissions.py
```

Expected stdout 最后一行: `== ALL PASS ==`

如果某个 case 报 AssertionError,回 Task 2 修。

- [ ] **Step 3: Commit**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add tests/test_permissions.py
git commit -m "test(permissions): 默认值/落盘/黑名单/can_toggle 边界"
```

---

## Task 4: 旧 analyze_toggle.json 迁移

**Files:**
- Modify: `plugin/permissions.py` (新增 migrate_legacy 函数 + init 里挂钩)
- Modify: `tests/test_permissions.py` (新增 test_migrate_legacy)

- [ ] **Step 1: 在 permissions.py 加 migrate_legacy**

在 `_save()` 函数之后、`scope_of` 之前插入:

```python
def migrate_legacy(state_dir: str | Path) -> bool:
    """从 analyze_toggle.json 迁移到 toggle_state.json。
    幂等:目标文件已存在或源文件不存在时返回 False,不动手。
    成功迁移返回 True,旧文件改名 .bak 留底。"""
    legacy = Path(state_dir) / _LEGACY_FILE_NAME
    new = Path(state_dir) / _STATE_FILE_NAME
    if new.exists() or not legacy.is_file():
        return False
    try:
        old = json.loads(legacy.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    state = _empty_state()
    for key, val in old.items():
        if ":" not in key:
            continue
        bucket_marker, ident = key.split(":", 1)
        if bucket_marker == "g":
            target = "groups"
        elif bucket_marker == "u":
            target = "private"
        else:
            continue
        state[target].setdefault(ident, {})["分析"] = bool(val)
    new.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    legacy.rename(legacy.with_suffix(".bak"))
    return True
```

- [ ] **Step 2: 改 init() 在 _load 前先尝试迁移**

把原 `init()` 函数体改成:

```python
def init(state_dir: str) -> None:
    """显式初始化:bot 启动时调一次。state_dir 通常 = WOWS_REPLAY_BASEDIR。
    幂等;重复调只会重新读盘。会自动迁移旧的 analyze_toggle.json。"""
    global _state_path, _state, _loaded
    with _lock:
        _state_path = Path(state_dir) / _STATE_FILE_NAME
        _state_path.parent.mkdir(parents=True, exist_ok=True)
        migrate_legacy(state_dir)   # 幂等;已迁移过会跳过
        _load()
        _loaded = True
```

- [ ] **Step 3: 在 tests/test_permissions.py 末尾(if __name__ 之前)加测试 case**

```python
def test_migrate_legacy():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        legacy = Path(d) / "analyze_toggle.json"
        legacy.write_text(json.dumps({
            "g:111": True,
            "g:222": False,
            "u:333": True,
            "garbage_key": True,  # 应该被跳过
        }), "utf-8")
        ok = perms.migrate_legacy(d)
        assert ok is True
        # 新文件出现
        new = Path(d) / "toggle_state.json"
        assert new.is_file()
        data = json.loads(new.read_text("utf-8"))
        assert data["groups"]["111"]["分析"] is True
        assert data["groups"]["222"]["分析"] is False
        assert data["private"]["333"]["分析"] is True
        assert "garbage_key" not in data["groups"]
        # 旧文件被改名
        assert not legacy.exists()
        assert (Path(d) / "analyze_toggle.json.bak").exists()
        # 再迁一次是 no-op
        assert perms.migrate_legacy(d) is False
    print("  migrate_legacy PASS")


def test_init_auto_migrates():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "analyze_toggle.json").write_text(
            json.dumps({"g:777": True}), "utf-8"
        )
        perms.init(d)
        assert perms.feature_enabled("group", "777", "分析") is True
        # 其他 feature 走 DEFAULT_ON
        assert perms.feature_enabled("group", "777", "视频") is True
    print("  init_auto_migrates PASS")
```

并在 `__main__` 末尾追加调用:

```python
    test_migrate_legacy()
    test_init_auto_migrates()
```

(顺序放在 `test_unknown_feature_assertion()` 之后、`print("== ALL PASS ==")` 之前)

- [ ] **Step 4: 跑测试**

Run:
```bash
cd /c/Users/29801/Desktop/wows-bot-review
python tests/test_permissions.py
```

Expected: 最后一行 `== ALL PASS ==`,中间能看到 `migrate_legacy PASS` 和 `init_auto_migrates PASS`。

- [ ] **Step 5: Commit**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add plugin/permissions.py tests/test_permissions.py
git commit -m "feat(permissions): analyze_toggle.json → toggle_state.json 自动迁移"
```

---

## Task 5: 菜单 PNG 渲染库

**Files:**
- Create: `report/bin/render_menu.py`

- [ ] **Step 1: 写 render_menu.py**

```python
# report/bin/render_menu.py
"""render_menu.py — bot 功能菜单 PNG。

库用法 (bot 直接 import):
    from render_menu import render_menu_png
    png_bytes = render_menu_png(scope="group", ident="123456",
                                state_snapshot=..., is_super=False)

CLI 用法 (调试):
    render_menu.py <out.png> [--scope group --ident 123456 --super]
    (无 --scope 时按 private + 假 ident '0' 渲染)

复用 render_battle_report 的色板/字体常量,与战报视觉一致。
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_battle_report import (  # noqa: E402
    CJK_FONT, MONO_FONT,
    GAME_BG, GAME_PANEL, GAME_PANEL_ALT,
    GAME_TEXT, GAME_DIM, GAME_GREEN, GAME_RED, GAME_BORDER,
)
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

# bot 元信息 (跟 plugin/version.py 的内容保持口径一致 — CLI 模式下读不到 plugin,所以 hardcode)
AUTHOR = "[NUIST]___Ciallo___"

# 4 个 feature 必须跟 plugin/permissions.FEATURES 顺序一致
FEATURES = ["视频", "战报", "复盘", "分析"]
FEATURE_DESC = {
    "视频":  "MP4 战斗回放",
    "战报":  "全队成绩单",
    "复盘":  "主角伤害分布",
    "分析":  "DeepSeek 复盘文本",
}

# 起步空;未来要展示规划中功能在这里追加: ("名字", "一句话简介")
PLANNED_FEATURES: list[tuple[str, str]] = []

W = 1100
PAD = 24
HEADER_H = 90
ROW_H = 42
SECTION_GAP = 18
FOOTER_H = 36


def _font(path, size):
    return ImageFont.truetype(path, size)


def _draw_status_dot(draw: ImageDraw.ImageDraw, x: int, y: int,
                     status: str) -> None:
    """status ∈ {'on', 'off', 'banned'} — 画 ●开 / ○关 / ✕禁。"""
    r = 9
    box = [x - r, y - r, x + r, y + r]
    if status == "on":
        draw.ellipse(box, fill=GAME_GREEN, outline=GAME_GREEN)
        label, color = "开", GAME_GREEN
    elif status == "off":
        draw.ellipse(box, outline=GAME_RED, width=2)
        label, color = "关", GAME_RED
    else:  # banned
        draw.text((x - r - 2, y - r - 3), "✕", fill=GAME_DIM,
                  font=_font(CJK_FONT, 18))
        label, color = "禁", GAME_DIM
    draw.text((x + r + 6, y - 10), label, fill=color, font=_font(CJK_FONT, 16))


def _feature_status(state: dict, scope: str, ident: str, feature: str) -> str:
    if feature in state.get("global_blacklist", []):
        return "banned"
    bucket = state["groups" if scope == "group" else "private"]
    val = bucket.get(str(ident), {}).get(feature, True)  # DEFAULT_ON
    return "on" if val else "off"


def render_menu_png(out_path: str, *, scope: str, ident: str,
                    state_snapshot: dict, is_super: bool,
                    version: str = "v0.4.0") -> str:
    """渲染一张菜单 PNG 到 out_path,返回 out_path。
    state_snapshot 是 permissions.snapshot() 的输出。"""
    f_title   = _font(CJK_FONT, 30)
    f_meta    = _font(CJK_FONT, 15)
    f_section = _font(CJK_FONT, 20)
    f_row     = _font(CJK_FONT, 17)
    f_desc    = _font(CJK_FONT, 14)
    f_mono    = _font(MONO_FONT, 14)
    f_dim     = _font(CJK_FONT, 12)

    # 先估高度
    n_features = len(FEATURES)
    n_planned = len(PLANNED_FEATURES)
    sa_visible = is_super

    height = (
        HEADER_H + PAD
        + 30 + n_features * ROW_H + SECTION_GAP                  # 当前功能
        + 30 + 2 * ROW_H + SECTION_GAP                           # 使用方法
        + 30 + (4 if sa_visible else 3) * 28 + SECTION_GAP       # 全部指令
        + 30 + max(1, n_planned) * 24 + SECTION_GAP              # 规划中
        + FOOTER_H + PAD
    )

    img = Image.new("RGB", (W, height), GAME_BG)
    draw = ImageDraw.Draw(img)

    # ----- Header -----
    draw.rectangle([0, 0, W, HEADER_H], fill=GAME_PANEL)
    draw.text((PAD, 18), "战舰世界助手 · EssexBot", GAME_TEXT, f_title)
    draw.text((PAD, 58), f"{version}  ·  作者 {AUTHOR}", GAME_DIM, f_meta)

    y = HEADER_H + PAD

    # ----- 当前功能 -----
    draw.text((PAD, y), "【当前功能】", GAME_TEXT, f_section); y += 30
    name_x, desc_x, cmd_x, dot_x = PAD + 12, PAD + 110, PAD + 360, W - PAD - 80
    for feat in FEATURES:
        draw.rectangle([PAD, y, W - PAD, y + ROW_H - 2], fill=GAME_PANEL_ALT)
        draw.text((name_x, y + 10), feat, GAME_TEXT, f_row)
        draw.text((desc_x, y + 12), FEATURE_DESC[feat], GAME_DIM, f_desc)
        draw.text((cmd_x,  y + 10), f"/{feat} 开|关|状态", GAME_TEXT, f_mono)
        status = _feature_status(state_snapshot, scope, ident, feat)
        _draw_status_dot(draw, dot_x, y + ROW_H // 2, status)
        y += ROW_H
    y += SECTION_GAP

    # ----- 使用方法 -----
    draw.text((PAD, y), "【使用方法】", GAME_TEXT, f_section); y += 30
    draw.text((PAD + 12, y), "把 .wowsreplay 拖进群里 / 私聊我", GAME_TEXT, f_row); y += ROW_H
    draw.text((PAD + 12, y), "开着的输出会自动产生并发回", GAME_DIM, f_row); y += ROW_H
    y += SECTION_GAP

    # ----- 全部指令 -----
    draw.text((PAD, y), "【全部指令】", GAME_TEXT, f_section); y += 30
    cmds = [
        ("/菜单  /menu  /help", "打开本面板"),
        ("/<功能> 开|关|状态",   "切换或查看本群开关"),
        ("/<功能> 状态",         "看自己当前生效状态"),
    ]
    if sa_visible:
        cmds.append(("/sa ban|unban <功能>", "超管:全局禁/解禁"))
    for cmd, desc in cmds:
        draw.text((PAD + 12, y), cmd, GAME_TEXT, f_mono)
        draw.text((PAD + 320, y), desc, GAME_DIM, f_row)
        y += 28
    y += SECTION_GAP

    # ----- 规划中 -----
    draw.text((PAD, y), "【规划中】", GAME_DIM, f_section); y += 30
    if not PLANNED_FEATURES:
        draw.text((PAD + 12, y), "敬请期待…", GAME_DIM, f_row); y += 24
    else:
        for name, desc in PLANNED_FEATURES:
            draw.text((PAD + 12, y), f"· {name} — {desc}", GAME_DIM, f_row)
            y += 24
    y += SECTION_GAP

    # ----- Footer -----
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    draw.rectangle([0, height - FOOTER_H, W, height], fill=GAME_PANEL)
    draw.text((PAD, height - FOOTER_H + 10),
              f"本面板由 EssexBot 渲染 · {ts}", GAME_DIM, f_dim)

    img.save(out_path)
    return out_path


def _cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", help="output PNG path")
    ap.add_argument("--scope", choices=["group", "private"], default="private")
    ap.add_argument("--ident", default="0")
    ap.add_argument("--super", action="store_true", dest="is_super",
                    help="渲染超管视角(显示 /sa 行)")
    ap.add_argument("--state-json",
                    help="可选:从该 JSON 读 state_snapshot;不给就用空 state")
    ap.add_argument("--version", default="v0.4.0",
                    help="版本字符串显示用")
    args = ap.parse_args()

    if args.state_json:
        with open(args.state_json, "r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {"version": 1, "global_blacklist": [], "groups": {}, "private": {}}

    render_menu_png(
        args.out, scope=args.scope, ident=args.ident,
        state_snapshot=state, is_super=args.is_super, version=args.version,
    )
    print(args.out)


if __name__ == "__main__":
    _cli()
```

- [ ] **Step 2: syntax check**

Run:
```bash
cd /c/Users/29801/Desktop/wows-bot-review
python -c "import ast; ast.parse(open('report/bin/render_menu.py', encoding='utf-8').read()); print('syntax OK')"
```

Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add report/bin/render_menu.py
git commit -m "feat(report): render_menu.py — 菜单 PNG 渲染库 + CLI"
```

---

## Task 6: wows_menu shell wrapper

**Files:**
- Create: `report/bin/wows_menu`

- [ ] **Step 1: 写 wrapper(类比 wows_damage_report)**

```python
#!/usr/bin/env python3
"""wows_menu — bot 调用入口,生成菜单 PNG。

用法:
    wows_menu <out.png> [--scope group --ident 123456] [--super] [--state-json path]

直接 forward 到 render_menu.py。存在的目的是统一 bin/ 入口风格 (类比 wows_report)。
"""
import os
import subprocess
import sys
from pathlib import Path

BOT_HOME = Path(__file__).resolve().parent.parent
RENDER_PY = BOT_HOME / "bin" / "render_menu.py"


def find_python() -> str:
    override = os.environ.get("WOWS_PYTHON")
    if override:
        return override
    venv = os.environ.get("WOWS_PY_VENV") or str(BOT_HOME / "venv")
    candidate = Path(venv) / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return "python3"


def main():
    if len(sys.argv) < 2:
        print("usage: wows_menu <out.png> [--scope group --ident <id>] [--super] [--state-json <path>]",
              file=sys.stderr)
        sys.exit(2)
    py = find_python()
    res = subprocess.run([py, str(RENDER_PY)] + sys.argv[1:])
    sys.exit(res.returncode)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 加可执行权限 (Linux/macOS;Windows 跳过)**

Run (Linux/macOS):
```bash
cd /c/Users/29801/Desktop/wows-bot-review
chmod +x report/bin/wows_menu
```

Windows 上 chmod 是 no-op,跳过即可,bot 在服务器上才需要执行权限。

- [ ] **Step 3: Commit**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add report/bin/wows_menu
git update-index --chmod=+x report/bin/wows_menu  2>/dev/null || true
git commit -m "feat(report): wows_menu — bin 入口 wrapper"
```

---

## Task 7: render_menu smoke test

**Files:**
- Create: `tests/test_render_menu.py`

- [ ] **Step 1: 写 smoke test**

```python
# tests/test_render_menu.py
"""render_menu 烟囱测试 — 渲三种 state,确认 PNG 文件被写出来且 > 5KB。
用法: python tests/test_render_menu.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

# 让脚本能 import report/bin
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "report" / "bin"))

# 字体环境变量必须在 import render_menu 之前设
os.environ.setdefault("WOWS_CJK_FONT", "C:/Windows/Fonts/msyh.ttc")

from render_menu import render_menu_png  # noqa: E402


def _render_check(label: str, out: Path, **kw):
    render_menu_png(str(out), **kw)
    assert out.is_file(), f"{label}: PNG 没写出来"
    size = out.stat().st_size
    assert size > 5_000, f"{label}: PNG 才 {size} 字节,太小,可能渲染异常"
    print(f"  {label} PASS ({size} bytes)")


def test_private_default():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "menu_private.png"
        state = {"version": 1, "global_blacklist": [],
                 "groups": {}, "private": {}}
        _render_check("private_default", out,
                      scope="private", ident="0",
                      state_snapshot=state, is_super=False)


def test_group_with_mixed_toggles():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "menu_group.png"
        state = {
            "version": 1, "global_blacklist": [],
            "groups": {"999": {"视频": True, "战报": True,
                               "复盘": False, "分析": True}},
            "private": {},
        }
        _render_check("group_mixed", out,
                      scope="group", ident="999",
                      state_snapshot=state, is_super=False)


def test_super_view_with_blacklist():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "menu_super.png"
        state = {"version": 1, "global_blacklist": ["复盘"],
                 "groups": {}, "private": {}}
        _render_check("super_blacklist", out,
                      scope="group", ident="123",
                      state_snapshot=state, is_super=True)


if __name__ == "__main__":
    print("== test_render_menu ==")
    test_private_default()
    test_group_with_mixed_toggles()
    test_super_view_with_blacklist()
    print("== ALL PASS ==")
```

- [ ] **Step 2: 跑测试**

Run:
```bash
cd /c/Users/29801/Desktop/wows-bot-review
python tests/test_render_menu.py
```

Expected: 最后 `== ALL PASS ==`,中间能看到 3 个 PASS。如果报字体找不到,确认 `WOWS_CJK_FONT` 指向真实存在的 ttf/ttc。

- [ ] **Step 3: 人工抽检一张图**

Run:
```bash
cd /c/Users/29801/Desktop/wows-bot-review
python report/bin/render_menu.py _test_out/menu_demo.png --scope group --ident 999 --super
```

打开 `_test_out/menu_demo.png` 看,确认:
- header 显示 `战舰世界助手 · EssexBot`、版本号、作者 `[NUIST]___Ciallo___`
- 4 行 feature 表格,每行右侧 `●开` 或 `○关`
- `/sa ban|unban <功能>` 那行出现 (因为 `--super`)
- footer 时间戳是当前时间

如果颜色/布局不对劲,回 Task 5 调常量。

- [ ] **Step 4: Commit**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add tests/test_render_menu.py
git commit -m "test(render_menu): 3 种 state 烟囱测试,文件存在 & 尺寸合理"
```

---

## Task 8: minimap.py 把 /分析 委托到 permissions(行为不变)

这一步是无风险 refactor:删除老 `_toggle_state/_toggle_load/_toggle_save/analyze_enabled/analyze_set`,改为透传到 `permissions` 模块。`/分析 开|关|状态` 的对外行为完全一致,但底层走新状态文件 (init 时自动迁移旧的)。

**Files:**
- Modify: `plugin/minimap.py:52-95` (替换 toggle 段) 和 `plugin/minimap.py:104-122` (handle_analyze_cmd 内部) 和文件顶部 import

- [ ] **Step 1: 在 minimap.py 顶部 import 段加 permissions 引用**

把 `plugin/minimap.py:17-30` 这一段:

```python
import os
import json
import shutil
import asyncio
import aiohttp
from typing import Optional, Tuple
from pathlib import Path

from nonebot import on_message, on_command, get_driver
from nonebot.adapters.onebot.v11 import Bot, Event, Message, MessageSegment
from nonebot.adapters.onebot.v11.event import GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.typing import T_State
from nonebot.log import logger
```

替换为(加 `from . import permissions`):

```python
import os
import json
import shutil
import asyncio
import aiohttp
from typing import Optional, Tuple
from pathlib import Path

from nonebot import on_message, on_command, get_driver
from nonebot.adapters.onebot.v11 import Bot, Event, Message, MessageSegment
from nonebot.adapters.onebot.v11.event import GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.typing import T_State
from nonebot.log import logger

from . import permissions
```

- [ ] **Step 2: 删除整段老 toggle 实现 (52-95 行)**

删除从 `# ====== 分析开关: 按聊天上下文持久化 ===` 注释到 `def analyze_set(...)` 结尾,即 plugin/minimap.py 的第 52-95 行整段。

把它替换为以下"启动钩子",负责调用 `permissions.init(...)`:

```python
# ====== 启动初始化 =============================================================
# permissions 模块需要知道状态文件目录;复用 BASE_DIR (跟 replay 临时目录同位置)

@driver.on_startup
async def _init_permissions():
    try:
        permissions.init(BASE_DIR)
        logger.info(f"permissions inited at {BASE_DIR}")
    except Exception as e:
        logger.error(f"permissions 初始化失败: {e}")
        raise
```

- [ ] **Step 3: 改 handle_analyze_cmd 走 permissions**

把 `handle_analyze_cmd` 整个函数 (现在大约在 100-122 行) 替换为:

```python
@analyze_cmd.handle()
async def handle_analyze_cmd(bot: Bot, event: Event, args: Message = CommandArg()):
    arg = args.extract_plain_text().strip()
    scope, ident = permissions.scope_of(event)

    if arg in ("开", "on", "enable", "开启"):
        if not permissions.can_toggle(event, ident):
            await analyze_cmd.finish("仅群主 / 管理员 / 超管可以改本群开关")
        if "分析" in permissions.global_blacklist():
            await analyze_cmd.finish("分析 已被超管全局禁用,无法本群启用")
        permissions.set_feature(scope, ident, "分析", True)
        await analyze_cmd.finish("✅ 战报分析已开启,后续每份 replay 都会附带 LLM 复盘文本。")
    elif arg in ("关", "off", "disable", "关闭"):
        if not permissions.can_toggle(event, ident):
            await analyze_cmd.finish("仅群主 / 管理员 / 超管可以改本群开关")
        permissions.set_feature(scope, ident, "分析", False)
        await analyze_cmd.finish("已关闭战报分析。MP4 + 战报图正常发,不再调 LLM。")
    elif arg in ("", "状态", "status"):
        on = permissions.feature_enabled(scope, ident, "分析")
        await analyze_cmd.finish(
            f"当前分析: {'开启' if on else '关闭'}\n"
            f"用法: /分析 开 | /分析 关 | /分析 状态"
        )
    else:
        await analyze_cmd.finish("用法: /分析 开 | /分析 关 | /分析 状态")
```

- [ ] **Step 4: 改 process_queue 里查 toggle 的那一行 (现在大约 252 行)**

把 `if analyze_enabled(group_id, user_id):` 替换为:

```python
            # 用 permissions 替代旧的 analyze_enabled
            scope = "group" if group_id else "private"
            ident = str(group_id) if group_id else user_id
            if permissions.feature_enabled(scope, ident, "分析"):
```

- [ ] **Step 5: 删掉 TOGGLE_FILE 环境变量 (现在用 permissions 管,不再需要)**

删 `plugin/minimap.py:39` 这一行:

```python
TOGGLE_FILE      = os.environ.get("WOWS_TOGGLE_FILE", os.path.join(BASE_DIR, "analyze_toggle.json"))
```

(注意 docstring 也提到了 WOWS_TOGGLE_FILE,把那行 docstring 也删了 — 在文件顶部 6-15 行那段注释里)

- [ ] **Step 6: syntax check**

Run:
```bash
cd /c/Users/29801/Desktop/wows-bot-review
python -c "import ast; ast.parse(open('plugin/minimap.py', encoding='utf-8').read()); print('syntax OK')"
```

Expected: `syntax OK`

- [ ] **Step 7: 跑一次 permissions 测试,确认重构没破坏权限语义**

Run:
```bash
cd /c/Users/29801/Desktop/wows-bot-review
python tests/test_permissions.py
```

Expected: `== ALL PASS ==`

- [ ] **Step 8: Commit**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add plugin/minimap.py
git commit -m "refactor(minimap): /分析 委托到 permissions 模块, 行为不变"
```

---

## Task 9: 4-feature toggle commands 工厂式注册

把 `/视频 /战报 /复盘 /分析` 4 个开关用同一段工厂注册。`/分析` 上一步已经独立写过了,这一步把它**也**纳入工厂,删掉重复实现。

**Files:**
- Modify: `plugin/minimap.py` (删 analyze_cmd 段;在 process_queue 上面加 register_feature_cmds 段)

- [ ] **Step 1: 删除 /分析 单独的 on_command + handle_analyze_cmd**

删 plugin/minimap.py 里:
- `analyze_cmd = on_command("分析", priority=5, block=True)` 那一行
- `@analyze_cmd.handle()` 装饰器 + 整个 `async def handle_analyze_cmd(...)` 函数

- [ ] **Step 2: 在 process_queue 函数上方插入工厂注册段**

```python
# ====== 4-feature toggle 命令 (视频/战报/复盘/分析) =====================
# 全部走 permissions 模块;命令处理器同构,一次注册。

def _make_toggle_handler(feature: str):
    """工厂:为某个 feature 生成一个处理器闭包。
    捕获 feature 进闭包,避免 for-loop late binding。"""
    cmd = on_command(feature, priority=5, block=True)

    @cmd.handle()
    async def handler(event: Event, args: Message = CommandArg()):
        action = args.extract_plain_text().strip()
        scope, ident = permissions.scope_of(event)

        if action in ("", "状态", "status"):
            on = permissions.feature_enabled(scope, ident, feature)
            await cmd.finish(f"{feature}: {'开' if on else '关'}\n"
                             f"用法: /{feature} 开|关|状态")
        if action not in ("开", "关", "on", "off", "开启", "关闭"):
            await cmd.finish(f"用法: /{feature} 开|关|状态")
        if not permissions.can_toggle(event, ident):
            await cmd.finish("仅群主 / 管理员 / 超管可以改本群开关")
        want_on = action in ("开", "on", "开启")
        if want_on and feature in permissions.global_blacklist():
            await cmd.finish(f"{feature} 已被超管全局禁用,无法本群启用")
        permissions.set_feature(scope, ident, feature, want_on)
        await cmd.finish(f"{feature}: {'开' if want_on else '关'}")

    return cmd


for _feat in permissions.FEATURES:
    _make_toggle_handler(_feat)
```

- [ ] **Step 3: syntax check**

Run:
```bash
cd /c/Users/29801/Desktop/wows-bot-review
python -c "import ast; ast.parse(open('plugin/minimap.py', encoding='utf-8').read()); print('syntax OK')"
```

Expected: `syntax OK`

- [ ] **Step 4: Commit**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add plugin/minimap.py
git commit -m "feat(minimap): /视频 /战报 /复盘 /分析 工厂注册 toggle 命令"
```

---

## Task 10: 菜单 handler 三入口 (/菜单 + group_increase + @bot only)

**Files:**
- Modify: `plugin/minimap.py` (新增 import + 新增 reply_menu 异步函数 + 3 个 on_xxx handler)

- [ ] **Step 1: 加 import**

在文件顶部 import 段追加(`from . import permissions` 那行下面):

```python
from nonebot import on_notice
from nonebot.rule import to_me
from nonebot.adapters.onebot.v11.event import GroupIncreaseNoticeEvent, MessageEvent
from .version import version_str
```

- [ ] **Step 2: 在工厂注册段下面加 menu handler 段**

```python
# ====== 菜单触发 ===============================================================

# /菜单 /menu /help  —— 三个 alias 共用一个处理器
menu_cmd = on_command(("菜单", "menu", "help"), priority=5, block=True)

@menu_cmd.handle()
async def _menu_cmd(bot: Bot, event: MessageEvent):
    await _reply_menu(bot, event)


# bot 自己刚被拉进群 —— 主动发一次菜单
group_join = on_notice(priority=5)

@group_join.handle()
async def _group_join(bot: Bot, event: GroupIncreaseNoticeEvent):
    if event.user_id == int(bot.self_id):
        # 给群里一个稍稍延迟,让"欢迎新成员"消息先飘过去
        await asyncio.sleep(1)
        await _reply_menu(bot, event)


# @bot 且没附别的内容 —— plaintext 为空就发菜单
def _is_pure_at(event: MessageEvent) -> bool:
    return not event.get_plaintext().strip()

at_only = on_message(rule=to_me() & _is_pure_at, priority=20, block=False)

@at_only.handle()
async def _at_only(bot: Bot, event: MessageEvent):
    await _reply_menu(bot, event)


async def _reply_menu(bot: Bot, event):
    """渲染当前作用域的菜单 PNG,回复到群/私聊。"""
    scope, ident = permissions.scope_of(event)
    is_super = permissions.is_super_admin(getattr(event, "user_id", 0))
    state = permissions.snapshot()
    version = version_str()

    # 写到一个临时文件再读;避免 PIL → bytes 转换的复杂性
    out_dir = Path(BASE_DIR) / "_menu_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"menu_{scope}_{ident}.png"

    try:
        await asyncio.to_thread(
            _render_menu_sync,
            str(out_path), scope, ident, state, is_super, version,
        )
    except Exception as e:
        logger.error(f"渲染菜单失败: {e}")
        await bot.send(event, f"菜单渲染失败: {e}")
        return

    # group_increase 不能 reply;message event 可以
    msg_id = getattr(event, "message_id", None)
    msg = MessageSegment.image(f"file://{out_path}")
    if msg_id:
        msg = MessageSegment.reply(msg_id) + msg
    await bot.send(event, msg)


def _render_menu_sync(out_path, scope, ident, state, is_super, version):
    """sync wrapper 给 to_thread 用 — render_menu 没有 async 接口。"""
    # 在 thread 里 import,避免插件加载阶段就拉 render_menu 的依赖链
    import sys as _sys
    bin_path = Path(REPORT_CMD).parent  # /opt/wows-bot/report/bin
    if str(bin_path) not in _sys.path:
        _sys.path.insert(0, str(bin_path))
    from render_menu import render_menu_png
    render_menu_png(
        out_path, scope=scope, ident=ident,
        state_snapshot=state, is_super=is_super, version=version,
    )
```

- [ ] **Step 3: syntax check**

Run:
```bash
cd /c/Users/29801/Desktop/wows-bot-review
python -c "import ast; ast.parse(open('plugin/minimap.py', encoding='utf-8').read()); print('syntax OK')"
```

Expected: `syntax OK`

- [ ] **Step 4: Commit**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add plugin/minimap.py
git commit -m "feat(minimap): /菜单 /menu /help + group_increase + @bot only 三入口"
```

---

## Task 11: /sa 超管命令

**Files:**
- Modify: `plugin/minimap.py` (在 menu handler 段下方追加 /sa 段)

- [ ] **Step 1: 加 /sa 命令实现**

```python
# ====== /sa 超管命令 ============================================================

sa_cmd = on_command("sa", priority=5, block=True)

_SA_HELP = (
    "用法: /sa <子命令>\n"
    "  /sa list                   看全局黑名单\n"
    "  /sa ban <视频|战报|复盘|分析>   全局禁用某功能\n"
    "  /sa unban <feature>         解禁\n"
    "  /sa stats                   各功能开关统计"
)


@sa_cmd.handle()
async def _sa(event: Event, args: Message = CommandArg()):
    if not permissions.is_super_admin(event.get_user_id()):
        await sa_cmd.finish("权限不足:本命令只允许超管使用")
    parts = args.extract_plain_text().strip().split()
    if not parts:
        await sa_cmd.finish(_SA_HELP)
    sub = parts[0]

    if sub == "list":
        bl = permissions.global_blacklist()
        if bl:
            await sa_cmd.finish("全局黑名单: " + ", ".join(bl))
        await sa_cmd.finish("全局黑名单为空 — 4 个功能默认全部可用")

    if sub in ("ban", "unban"):
        if len(parts) != 2:
            await sa_cmd.finish(f"用法: /sa {sub} <{'|'.join(permissions.FEATURES)}>")
        feat = parts[1]
        if feat not in permissions.FEATURES:
            await sa_cmd.finish(f"未知功能 '{feat}',合法: {permissions.FEATURES}")
        if sub == "ban":
            permissions.super_admin_ban(feat)
            await sa_cmd.finish(f"已全局禁用: {feat}")
        else:
            permissions.super_admin_unban(feat)
            await sa_cmd.finish(f"已解禁: {feat}")

    if sub == "stats":
        snap = permissions.snapshot()
        lines = [f"全局黑名单: {snap['global_blacklist'] or '空'}"]
        lines.append(f"已配群: {len(snap['groups'])} 个")
        lines.append(f"已配私聊用户: {len(snap['private'])} 个")
        for feat in permissions.FEATURES:
            on_count = sum(
                1 for g in snap["groups"].values()
                if g.get(feat, True)
            )
            off_count = sum(
                1 for g in snap["groups"].values()
                if g.get(feat, True) is False
            )
            lines.append(f"  {feat}: 群里开 {on_count} / 关 {off_count}")
        await sa_cmd.finish("\n".join(lines))

    await sa_cmd.finish(f"未知子命令 '{sub}'\n\n{_SA_HELP}")
```

- [ ] **Step 2: syntax check**

Run:
```bash
cd /c/Users/29801/Desktop/wows-bot-review
python -c "import ast; ast.parse(open('plugin/minimap.py', encoding='utf-8').read()); print('syntax OK')"
```

Expected: `syntax OK`

- [ ] **Step 3: Commit**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add plugin/minimap.py
git commit -m "feat(minimap): /sa list|ban|unban|stats 超管命令"
```

---

## Task 12: process_queue 按 feature_enabled 分发 4 路输出

这一步把 `process_queue` 里"无脑跑 MP4 + 战报 + 复盘 拼图,可选跑 分析"的硬编码,改成按 4 个 feature 开关精确控制。

**Files:**
- Modify: `plugin/minimap.py` (整个 process_queue 函数 + 新增 run_battle_report / run_damage_report 辅助函数)

- [ ] **Step 1: 在文件顶部 import 段加 wows_damage_report 配置**

把 `plugin/minimap.py:33` 这一行:

```python
REPORT_CMD       = os.environ.get("WOWS_REPORT_CMD",  "/opt/wows-bot/report/bin/wows_full_report")
```

替换为(分开三个命令,wows_full_report 仍然在用,新增 wows_report 和 wows_damage_report 单独入口):

```python
REPORT_FULL_CMD  = os.environ.get("WOWS_REPORT_FULL_CMD",  "/opt/wows-bot/report/bin/wows_full_report")
REPORT_BATTLE_CMD = os.environ.get("WOWS_REPORT_BATTLE_CMD", "/opt/wows-bot/report/bin/wows_report")
REPORT_DAMAGE_CMD = os.environ.get("WOWS_REPORT_DAMAGE_CMD", "/opt/wows-bot/report/bin/wows_damage_report")
# 旧 alias 暂留兼容(.env 里可能还有);后续清理
REPORT_CMD       = os.environ.get("WOWS_REPORT_CMD", REPORT_FULL_CMD)
```

同时把 menu handler 里 `Path(REPORT_CMD).parent` 改成 `Path(REPORT_FULL_CMD).parent`(因为 REPORT_CMD 改语义了)。

- [ ] **Step 2: 把 render_report 函数复制成两个新函数 (battle / damage)**

`render_report` 函数现在大概在 335 行。保留它(后面 Step 4 才删),新增以下两个:

```python
async def run_battle_report(replay_path: str, work_dir: str) -> str:
    """跑 wows_report,返回战报 PNG 路径。同时会在 work_dir 留下同名 .json。"""
    return await _run_report_like(REPORT_BATTLE_CMD, replay_path, work_dir, "战报")


async def run_damage_report(replay_path: str, work_dir: str) -> str:
    """跑 wows_damage_report,返回复盘 PNG 路径。会复用缓存的 .json。"""
    return await _run_report_like(REPORT_DAMAGE_CMD, replay_path, work_dir, "复盘")


async def run_full_report(replay_path: str, work_dir: str) -> str:
    """跑 wows_full_report,返回拼接 PNG 路径 (战报+复盘 竖向拼一张)。"""
    return await _run_report_like(REPORT_FULL_CMD, replay_path, work_dir, "全报告")


async def _run_report_like(cmd: str, replay_path: str, work_dir: str, label: str) -> str:
    """三个 wows_*_report 子进程同构,抽 helper。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            cmd, replay_path, work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=PNG_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"{label}渲染超时({PNG_TIMEOUT}s)")
        if proc.returncode != 0:
            tail = stderr.decode('utf-8', errors='ignore')[-500:] if stderr else "未知错误"
            raise RuntimeError(f"{label}渲染失败: {tail}")
        lines = stdout.decode('utf-8', errors='ignore').strip().splitlines()
        if not lines:
            raise RuntimeError(f"{label}脚本无 PNG 输出")
        png_path = lines[-1].strip()
        if not os.path.exists(png_path):
            raise RuntimeError(f"{label} PNG 不存在: {png_path}")
        logger.info(f"{label} PNG 完成: {png_path}")
        return png_path
    except FileNotFoundError:
        raise RuntimeError(f"找不到{label}命令: {cmd}")
```

- [ ] **Step 3: 重写 process_queue 的核心循环**

把 `async def process_queue(bot: Bot):` 整段函数 (大约 207-284 行) 替换为:

```python
async def process_queue(bot: Bot):
    """串行处理队列;每个 replay 按本群 4 个 feature 开关决定跑哪几个输出。"""
    global processing
    processing = True

    while not task_queue.empty():
        user_id, message_id, group_id, user_dir, replay_path = await task_queue.get()
        scope = "group" if group_id else "private"
        ident = str(group_id) if group_id else user_id

        try:
            on = {f: permissions.feature_enabled(scope, ident, f)
                  for f in permissions.FEATURES}

            if not any(on.values()):
                await send_message(bot, user_id, group_id, message_id,
                                   "本聊天 4 个开关全关,跳过本份 replay。"
                                   "管理员可 /菜单 查看,/<功能> 开 启用。")
                task_queue.task_done()
                continue

            await send_message(
                bot, user_id, group_id, message_id,
                f"🎬 开始渲染 ({', '.join(f for f, v in on.items() if v)})... "
                f"(剩余队列:{task_queue.qsize()})"
            )

            if not os.path.exists(replay_path):
                raise RuntimeError("replay 文件不存在")

            # 决定走哪条报告路径(产 JSON 的子进程只跑一次)
            if on["战报"] and on["复盘"]:
                report_kind = "full"
            elif on["战报"]:
                report_kind = "battle"
            elif on["复盘"]:
                report_kind = "damage"
            elif on["分析"]:
                report_kind = "battle"   # 只为产 JSON;PNG 不发
            else:
                report_kind = None

            # 并行: MP4 (可选) + 报告 (可选)
            tasks: dict[str, asyncio.Future] = {}
            if on["视频"]:
                tasks["mp4"] = asyncio.create_task(render_mp4(replay_path, user_dir))
            if report_kind == "full":
                tasks["report"] = asyncio.create_task(run_full_report(replay_path, user_dir))
            elif report_kind == "battle":
                tasks["report"] = asyncio.create_task(run_battle_report(replay_path, user_dir))
            elif report_kind == "damage":
                tasks["report"] = asyncio.create_task(run_damage_report(replay_path, user_dir))

            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            result_map = dict(zip(tasks.keys(), results))

            # MP4 处理 —— 视频开了就发,失败致命
            mp4_path = None
            if on["视频"]:
                r = result_map.get("mp4")
                if isinstance(r, Exception):
                    raise r
                # render_mp4 不返回路径,而是把文件放到 user_dir
                mp4_files = [f for f in os.listdir(user_dir) if f.endswith(".mp4")]
                if not mp4_files:
                    raise RuntimeError("视频渲染完成但未生成 MP4")
                mp4_path = os.path.join(user_dir, mp4_files[0])

            # 报告 PNG 处理 —— 战报/复盘开了才发对应那张
            report_png = None
            report_error = None
            r = result_map.get("report")
            if isinstance(r, Exception):
                report_error = str(r)
                logger.warning(f"报告渲染失败 (kind={report_kind}): {r}")
            elif isinstance(r, str):
                # 只在用户真要看 PNG 时才送图(report_kind == "battle" 且只为分析时不送)
                if (on["战报"] or on["复盘"]) and report_kind != "battle" or (on["战报"] and report_kind in ("full", "battle")):
                    report_png = r

            # 发 MP4 + 报告(沿用原 upload_and_notify 接口)
            if mp4_path or report_png or report_error:
                await upload_and_notify(bot, user_id, group_id, message_id,
                                        mp4_path, report_png, report_error)

            # 分析:从 user_dir 里找 .json
            if on["分析"]:
                json_path = os.path.join(user_dir, f"{Path(replay_path).stem}.json")
                if os.path.isfile(json_path):
                    try:
                        analysis = await run_analyze(json_path)
                        await send_message(bot, user_id, group_id, message_id,
                                           f"🧠 战后复盘:\n{analysis}")
                    except Exception as e:
                        logger.warning(f"LLM 分析失败: {e}")
                        await send_message(bot, user_id, group_id, message_id,
                                           f"⚠️ LLM 分析失败: {e}")
                else:
                    logger.warning(f"未找到战报 JSON,跳过分析: {json_path}")

            logger.info(f"用户 {user_id} 任务完成 (开: {[k for k,v in on.items() if v]})")

        except Exception as e:
            logger.error(f"处理任务出错: {e}")
            await send_message(
                bot, user_id, group_id, message_id,
                f"❌ 渲染失败: {str(e)}"
            )

        finally:
            try:
                if os.path.exists(user_dir):
                    shutil.rmtree(user_dir, ignore_errors=True)
            except Exception as e:
                logger.error(f"清理目录失败: {e}")

        task_queue.task_done()

    processing = False
```

- [ ] **Step 4: 改 upload_and_notify 兼容 mp4_path 可能为 None**

定位到 `async def upload_and_notify(...)` 函数(原来在 364 行附近),把开头改成:

```python
async def upload_and_notify(bot: Bot, user_id: str, group_id: Optional[int],
                            message_id: int, mp4_path: Optional[str],
                            png_path: Optional[str] = None,
                            png_error: Optional[str] = None):
    """上传 MP4(如果有),并把 PNG (或失败说明) 一起回到原消息上。
    mp4_path / png_path / png_error 三者均可为 None — 全 None 时本函数静默 no-op。"""
    if not (mp4_path or png_path or png_error):
        return

    file_name = None
    if mp4_path:
        file_name = os.path.basename(mp4_path)
        try:
            if group_id:
                await bot.call_api("upload_group_file", group_id=group_id, file=mp4_path, name=file_name)
            else:
                await bot.call_api("upload_private_file", user_id=int(user_id), file=mp4_path, name=file_name)
            logger.info(f"MP4 已上传 ({user_id}): {file_name}")
        except Exception as e:
            logger.error(f"MP4 上传失败: {e}")
            raise RuntimeError(f"视频上传失败: {str(e)}")

    # 拼回复消息
    parts = []
    if file_name:
        parts.append(f"✅ 视频已上传:{file_name}")
    if png_path and os.path.exists(png_path):
        parts.append("战报如下:")
    elif png_error:
        parts.append(f"⚠️ 战报生成失败:{png_error}")

    text = "\n".join(parts) if parts else ""
    message = MessageSegment.reply(message_id) + text
    if png_path and os.path.exists(png_path):
        message = message + MessageSegment.image(f"file://{png_path}")

    try:
        if group_id:
            await bot.call_api("send_group_msg", group_id=group_id, message=message)
        else:
            await bot.call_api("send_private_msg", user_id=int(user_id), message=message)
    except Exception as e:
        logger.error(f"发送合并消息失败: {e}")
        raise RuntimeError(f"消息发送失败: {str(e)}")
```

- [ ] **Step 5: 删掉老的 render_report 函数(不再有人调,被 _run_report_like 取代)**

定位 `async def render_report(...)` 整段(以前 335 行附近),整段删除。

- [ ] **Step 6: syntax check + 跑 permissions 测试,确认没意外破坏**

Run:
```bash
cd /c/Users/29801/Desktop/wows-bot-review
python -c "import ast; ast.parse(open('plugin/minimap.py', encoding='utf-8').read()); print('syntax OK')"
python tests/test_permissions.py
python tests/test_render_menu.py
```

Expected: 三条命令都成功、最后两条结尾 `== ALL PASS ==`。

- [ ] **Step 7: Commit**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add plugin/minimap.py
git commit -m "refactor(minimap): process_queue 按 4 个 feature 开关分发输出"
```

---

## Task 13: 更新 DEPLOY.md

**Files:**
- Modify: `docs/DEPLOY.md` (新增 §"超管 & 群级开关",改 §5.3 LLM 分析的环境变量说明)

- [ ] **Step 1: 在 DEPLOY.md 末尾追加新 section**

在 `docs/DEPLOY.md` 末尾追加:

```markdown
## 8. 超管 & 群级开关 (v0.4+)

### 8.1 配置超管

在 NoneBot 应用 (`EssexBot/.env` 之类) 里:

```
SUPERUSERS=["你的QQ号"]
```

支持多个超管: `SUPERUSERS=["111", "222"]`。超管能在任意群 toggle 任意 feature,也能用 `/sa` 命令操作全局黑名单。

### 8.2 4 个 feature 开关

每个聊天 (群 / 私聊) 默认 4 个 feature 都开:
- `视频` —— MP4 战斗回放
- `战报` —— 全队成绩单 PNG
- `复盘` —— 主角伤害分布 PNG
- `分析` —— DeepSeek 文字复盘

群管/群主可用 `/视频 开|关|状态` 等命令切换本群。

### 8.3 超管命令 `/sa`

```
/sa list                          # 看全局黑名单
/sa ban <视频|战报|复盘|分析>      # 全局禁用某 feature (所有群都开不了)
/sa unban <feature>                # 解禁
/sa stats                          # 各 feature 在所有群里的开关分布
```

### 8.4 状态文件

位置: `<WOWS_REPLAY_BASEDIR>/toggle_state.json` (默认 `~/wows-bot-replay/toggle_state.json`)。

格式见 `plugin/permissions.py` 顶部 docstring。Bot 启动时如果发现同目录有老的 `analyze_toggle.json`,会自动迁移:
- 读出来,把每条 `g:xxx → true|false` 翻译成 `groups["xxx"].分析 = true|false`
- 写新的 `toggle_state.json`
- 把旧文件改名 `analyze_toggle.json.bak`

迁移是幂等的(目标文件存在就跳过),多次重启不会反复折腾。

### 8.5 菜单触发

- 用户发 `/菜单`、`/menu` 或 `/help` —— 任意群/私聊都会回一张菜单 PNG
- Bot 被拉进新群 —— 自动延迟 1 秒后发一次菜单当自我介绍
- 用户在群里 @bot 且没附别的内容 —— 同样回菜单
```

- [ ] **Step 2: 改 DEPLOY.md 里 LLM 分析那段 (§5.3 或附近)**

定位 `analyze_prompt.txt` 字样,如果还在,把那一段改成:

```markdown
### LLM Persona

`wows_analyze` 不再用单一 prompt,改成从 `report/data/personas/*.txt` 随机抽。
仓库自带 3 个: `aichan / michelle / shion`。

固定某个人格:`export WOWS_PERSONA=aichan`。
不设环境变量 = 每次随机。

加新人格:在 `report/data/personas/` 下放 `<名字>.txt`,文件内容就是 system prompt 全文。
```

- [ ] **Step 3: Commit**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add docs/DEPLOY.md
git commit -m "docs(deploy): 超管 & 群级开关章节 + personas 替换 analyze_prompt"
```

---

## 实施后手动验收 (本地)

无法离开实际 bot 运行验证的项,完成所有 task 后在服务器上手动跑一遍:

```bash
# 0. 部署到服务器
cd /opt/wows-bot && git pull

# 1. bot 启动后看日志确认初始化
#    应该看到 "permissions inited at /xxx"
#    如果服务器之前用过 /分析,还应看到迁移日志或 analyze_toggle.json.bak 文件

# 2. 测试 5 类指令(在测试群里):
/菜单                  # 应回一张 PNG
@bot                  # 仅 @,应回 PNG
/分析 状态             # 应回当前开/关
/视频 关               # 群管发,关闭视频
/视频 状态             # 确认关上了

# 3. 测试 replay 分发:
丢一份 .wowsreplay 进群,看 bot 是不是只发开着的输出

# 4. 测试超管命令(从超管 QQ 私聊 bot):
/sa list
/sa ban 复盘
# 群里再 /复盘 开 — 应回"被超管全局禁用"
/sa unban 复盘

# 5. 测试新群欢迎:
把 bot 拉到一个新群,1-2 秒内应自动发一张菜单
```

---

## 风险与回滚

| 风险 | 缓解 |
|---|---|
| `analyze_toggle.json` 迁移失败 → bot 启动崩 | `migrate_legacy` 内部 try/except,失败返回 False,init 继续走;最坏 case 是状态丢失但 bot 能起来 |
| 新 toggle 命令跟其他插件命令冲突 | priority=5,跟现有 `/分析` 同优先级。如果跟未知第三方插件冲突,改成更高数字 (优先级越低) |
| `@bot only` 误判把别的消息当菜单触发 | rule = `to_me() & 空 plaintext`,只在精确空消息时触发。如果还有误触发,删 `at_only` handler 即可 |
| render_menu 字体在 server 找不到 | 复用 `render_battle_report` 已经在 server 跑过的 `CJK_FONT/MONO_FONT`,如果它能跑战报,菜单就能跑 |
| process_queue 重构破坏现有 /分析 用户 | Task 8 先做"行为不变"的 refactor,Task 12 才改语义。两步 commit 拆开,出问题可单独 revert Task 12 |

回滚指令:`git revert <task-commit-hash>`。每个 task 都是独立 commit,可以精准回退某一步。
