# Bot 功能菜单 + 群级开关系统 — 设计

日期: 2026-05-21
状态: 待审
作者: [NUIST]___Ciallo___

## 目标

为 EssexBot (NoneBot2 插件) 提供一张可视化功能菜单 PNG，同时把现有"丢 replay 自动出活"流水线拆成 4 个可独立开关的子功能 (`视频 / 战报 / 复盘 / 分析`)，配上两级权限模型 (超管全局黑名单 + 群主/管理员本群开关)。

非目标:
- 不做猜船 (`/猜船`) 功能本体 — 已确认本 spec 暂不预留接口
- 不做积分/排行 / 用户级别的开关 (粒度只到群)
- 不做菜单的交互式按钮 (QQ 协议不便，菜单全部是只读 PNG)
- 不重写现有 replay 渲染管线 — 只在外面套开关层

## 输入

无外部数据输入。所有信息来自 bot 本地状态:

- `report/data/toggle_state.json` — 群/私聊开关 + 全局黑名单
- `plugin/version.py:__version__` + git short hash (运行时取)
- 当前请求的 `group_id` (用于在菜单里高亮本群开关状态)
- NoneBot `get_driver().config.superusers` (.env 配的超管 QQ 列表)

## 输出

`menu.png`，宽度 **1100px** (比战报的 2200 窄，手机看不缩水)，复用 `render_battle_report` 的色板 (`GAME_BG/PANEL/TEXT/GREEN/RED/...`) 和字体常量 (`CJK_FONT/MONO_FONT`)。

渲染时每行末尾画 `●开 / ○关 / ✕禁`，状态取自当前作用域 (群聊取本群、私聊取该用户的 private bucket)。无作用域时 (如未配置过) 按 `DEFAULT_ON = True` 显示。

## 整体架构

```
[QQ event]
   │
   ├─ /菜单 /menu /help               ─→ render_menu → PNG → reply
   ├─ notice.group_increase(self)     ─→ render_menu → PNG → reply
   ├─ @bot only (plaintext 空)         ─→ render_menu → PNG → reply
   │
   └─ .wowsreplay 文件落地             ─→ permissions.feature_enabled(group, X)
                                            │
                                            ├─ 视频:   WOWS_RENDER_SH       (独立子进程)
                                            ├─ 战报:   wows_report           (产 PNG + JSON)
                                            ├─ 复盘:   render_damage_chart   (消费 JSON)
                                            └─ 分析:   wows_analyze          (消费 JSON)
```

**关键依赖**: `复盘 / 分析` 都需要 `wows_report` 产的 battle.json。如果 `战报=关` 但 `复盘=开` 或 `分析=开`，仍要内部跑 `wows_report`，只是不发战报 PNG。

## 开关默认值与依赖逻辑

- 默认值: 新群所有 4 项 = `true` (除非在 `global_blacklist` 里)
- 一个都没开 → 静默 (不报错、不回复，等同于 bot 没看到 replay)
- 战报 + 复盘 都开 → 复用现有 `wows_full_report` 把两张拼成 `.full.png` 一并发出
- 战报 关 + 复盘 开 → 内部跑 wows_report，只发 damage 单图

伪码:

```python
on = {f: feature_enabled(scope, ident, f) for f in FEATURES}
if not any(on.values()):
    return

if on["视频"]:
    await send_video(await render_mp4(replay))

need_json = on["战报"] or on["复盘"] or on["分析"]
if need_json:
    json_path, report_png = await run_wows_report(replay)
    if on["战报"] and on["复盘"]:
        await send_image(await stitch_full(report_png, json_path))
    elif on["战报"]:
        await send_image(report_png)
    elif on["复盘"]:
        await send_image(await render_damage(json_path))
    if on["分析"]:
        await send_text(await run_analyze(json_path))
```

## 权限模型

两级 veto:

| 角色 | 能做什么 |
|---|---|
| 超管 (`superusers` 配置) | 全局禁用某功能 (`/sa ban 复盘`); 任意群的开关都能改 |
| 群主 / 管理员 (`event.sender.role in {owner, admin}`) | 改本群开关; 看不到也改不了 `global_blacklist` |
| 普通用户 | 看菜单、丢 replay; 不能 toggle |
| 私聊 | 只能改自己作用域的开关 |

判定函数 (写命令处理时一律走这个，handler 不直接读 state):

```python
def can_toggle(event, scope_ident) -> bool:
    if is_super_admin(event.user_id):
        return True
    if isinstance(event, GroupMessageEvent):
        return event.sender.role in ("owner", "admin")
    return scope_ident == str(event.user_id)
```

超管全局禁用 = 硬 veto: 群管尝试 `/复盘 开` 时回复 "复盘 已被超管全局禁用，无法本群启用"。

## 状态文件

`report/data/toggle_state.json`:

```json
{
  "version": 1,
  "global_blacklist": [],
  "groups": {
    "123456789": { "视频": true, "战报": true, "复盘": false, "分析": true }
  },
  "private": {
    "10086": { "分析": true }
  }
}
```

读写在 `permissions.py` 里用单例 + 全局锁。每次 `set_feature` 后立即 `save()` (atomic write: 写 tmp + rename)。

### 从 `analyze_toggle.json` 迁移

bot 启动一次性触发，幂等:

```python
def migrate_legacy():
    legacy = BOT_DATA / "analyze_toggle.json"
    new = BOT_DATA / "toggle_state.json"
    if new.exists() or not legacy.exists():
        return
    old = json.loads(legacy.read_text("utf-8"))
    state = {"version": 1, "global_blacklist": [], "groups": {}, "private": {}}
    for key, val in old.items():
        bucket, ident = key.split(":", 1)   # "g:xxx" / "u:xxx"
        target = "groups" if bucket == "g" else "private"
        state[target][ident] = {"分析": bool(val)}
    new.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    legacy.rename(legacy.with_suffix(".bak"))
```

## 菜单 PNG 视觉

```
┌──────────────────────────────────────────────────┐
│  战舰世界助手 · EssexBot                          │  ← f_title 32 (CJK_FONT)
│  v0.4.0+a3f1d2c  ·  作者 [NUIST]___Ciallo___     │  ← f_meta 16 (CJK_FONT, GAME_DIM)
├──────────────────────────────────────────────────┤
│  【当前功能】                                     │  ← f_section 22
│  ┌─────┬─────────────┬──────────────┬───────┐  │
│  │视频  │ MP4 战斗回放 │ /视频 开|关   │ ● 开  │  │
│  │战报  │ 全队成绩单    │ /战报 开|关   │ ● 开  │  │
│  │复盘  │ 主角伤害分布  │ /复盘 开|关   │ ○ 关  │  │
│  │AI分析│ DeepSeek 复盘 │ /分析 开|关   │ ● 开  │  │
│  └─────┴─────────────┴──────────────┴───────┘  │
│                                                  │
│  【使用方法】                                     │
│   把 .wowsreplay 拖进群里 / 私聊我               │
│   开着的输出会自动产生并发回                    │
│                                                  │
│  【全部指令】                                     │
│   /菜单 /help /menu     打开本面板               │
│   /<功能> 开|关|状态    切换或查看本群开关       │
│   /sa ban|unban <功能>  超管: 全局禁/解禁        │
│                                                  │
│  【规划中】                                       │  ← GAME_DIM 半透明
│    (常量 PLANNED_FEATURES 起步为空)              │
│    后续追加: 名称 + 一句话简介                   │
│                                                  │
├──────────────────────────────────────────────────┤
│  本面板由 EssexBot 渲染 · 2026-05-21 13:42       │  ← f_dim 13
└──────────────────────────────────────────────────┘
```

**色块语义**:

| 标记 | 颜色 | 含义 |
|---|---|---|
| `●` 实心圆 | `GAME_GREEN` | 本群可用 (未被禁 + 群管开) |
| `○` 空心圆 | `GAME_RED` | 群管关 |
| `✕` X 标 | `GAME_DIM` | 全局禁用 (`global_blacklist`)，群管也开不了 |
| 整行半透明 | `GAME_DIM` | 规划中 |

"全部指令"区里 `/sa` 仅当渲染请求来自超管时显示，普通用户/群管渲染版本看不到此行。

### 版本与作者

```python
# plugin/version.py
__version__ = "0.4.0"

import subprocess
from pathlib import Path

def git_short_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent, text=True,
        ).strip()
    except Exception:
        return ""

def version_str() -> str:
    h = git_short_hash()
    return f"v{__version__}+{h}" if h else f"v{__version__}"
```

作者常量 `AUTHOR = "[NUIST]___Ciallo___"` 放在 `render_menu.py` 顶部。

## Handler

### 菜单触发

```python
# /菜单 /menu /help
menu = on_command(("菜单", "menu", "help"), priority=5, block=True)
@menu.handle()
async def _(bot: Bot, event: MessageEvent):
    await reply_menu(bot, event)

# bot 刚被拉进群
welcome = on_notice()
@welcome.handle()
async def _(bot: Bot, event: GroupIncreaseNoticeEvent):
    if event.user_id == int(bot.self_id):
        await reply_menu(bot, event)

# @bot 且 plaintext 为空
at_only = on_message(rule=to_me() & _is_pure_at, priority=10)
def _is_pure_at(event: MessageEvent) -> bool:
    return not event.get_plaintext().strip()
@at_only.handle()
async def _(bot: Bot, event: MessageEvent):
    await reply_menu(bot, event)
```

`@bot only` 用 `to_me() + plaintext 为空` — 因为现有 handler (replay drop, /分析) 都不依赖 to_me，不会冲突。优先级 10 比 `/菜单 (priority 5)` 低，确保斜杠指令命中时不会同时回菜单。

### 开关命令

4 个完全同构，工厂式注册:

```python
for feature in FEATURES:
    cmd = on_command(feature, priority=5, block=True)
    @cmd.handle()
    async def _(event: MessageEvent, args=CommandArg(), feature=feature):
        action = args.extract_plain_text().strip()
        scope, ident = scope_of(event)
        if action == "状态":
            on = feature_enabled(scope, ident, feature)
            await cmd.send(f"{feature}: {'开' if on else '关'}")
            return
        if action not in ("开", "关"):
            await cmd.send(f"用法: /{feature} 开|关|状态")
            return
        if not can_toggle(event, ident):
            await cmd.send("仅群主 / 管理员 / 超管可以改")
            return
        if action == "开" and feature in state["global_blacklist"]:
            await cmd.send(f"{feature} 已被超管全局禁用，无法本群启用")
            return
        set_feature(scope, ident, feature, action == "开")
        await cmd.send(f"{feature}: {action}")
```

### 超管命令

```
/sa list                       # 看 global_blacklist + 谁禁了
/sa ban <视频|战报|复盘|分析>   # 全局禁
/sa unban <feature>            # 解禁
/sa stats                      # 多少群启用了 bot、各功能开关分布
```

`/sa` 在非超管手里直接返回 "权限不足"。

## 文件清单

```
新增:
  plugin/permissions.py             权限模型 + 状态持久化 + can_toggle/feature_enabled
  plugin/version.py                 __version__ + git_short_hash()
  report/bin/render_menu.py         菜单 PNG 渲染主入口
  report/bin/wows_menu              bin 入口 (类比 wows_report)
  report/data/toggle_state.json     状态文件 (首次启动自动建)

改:
  plugin/minimap.py                 拆 4 个开关、菜单 handler、用 permissions 替代直读 JSON
  docs/DEPLOY.md                    superusers 配置说明、状态文件迁移说明
```

## 验收

- `/菜单` 在私聊/群聊都返回一张 PNG，含版本、作者、4 个功能行
- 群里 `/复盘 关` 后再丢 replay，不发复盘图，其他 3 项照常
- 超管 `/sa ban 分析` 后，任意群 `/分析 开` 都被拒
- 群管(非超管非群主) 尝试 `/分析 开` 在普通群里不被拒
- 普通用户 `/分析 开` 被拒
- bot 首次启动后 `analyze_toggle.json` 自动迁移成 `toggle_state.json`，旧文件改 `.bak`
- bot 入新群 → 自动发一次菜单
- @bot 不带其他内容 → 发菜单; @bot 加一句话 → 不发菜单 (走原有逻辑)

## 风险与回退

- **现有 `analyze_toggle.json` 迁移失败** → 不阻断启动，写 stderr，继续用旧文件路径 (老逻辑可保留兜底一两个版本)
- **菜单字体缺失** → render_menu 复用 `render_battle_report` 已验证的 CJK_FONT/MONO_FONT，不引入新依赖
- **`@bot only` 误判** → 改成需要明确 plaintext 是空白字符串而非 None；如果误触多了可以下掉这个触发，保留斜杠指令
- **全局 superusers 配置变更** → 通过 `get_driver().config.superusers` 动态读，不缓存
