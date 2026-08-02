"""
NoneBot 插件: 接收 .wowsreplay 文件,并行渲染 MP4 (小地图) + PNG (战报),合并发送回 QQ。
开启分析后,会在 MP4+PNG 之后追发一条 DeepSeek 出的中文战后复盘。

可调环境变量 (默认值对应 docs/DEPLOY.md 的统一布局):
  WOWS_RENDER_SH       MP4 渲染脚本路径    默认 /opt/wows-bot/minimap/render.sh
  WOWS_REPORT_CMD      战报 PNG 入口        默认 /opt/wows-bot/report/bin/wows_full_report
  WOWS_ANALYZE_CMD     LLM 分析入口         默认 /opt/wows-bot/report/bin/wows_analyze
  WOWS_REPLAY_BASEDIR  回放/产物临时目录    默认 ~/wows-bot-replay
  WOWS_MP4_TIMEOUT     MP4 渲染超时 (秒)    默认 600
  WOWS_PNG_TIMEOUT     PNG 渲染超时 (秒)    默认 300
  WOWS_ANALYZE_TIMEOUT LLM 分析超时 (秒)    默认 120

DeepSeek API key 在 wows_analyze 那边读 WOWS_DEEPSEEK_KEY,不在本插件。
"""
import os
import re
import sys
import json
import shutil
import asyncio
import aiohttp
from typing import Dict, Optional, Tuple
from pathlib import Path

from nonebot import on_message, on_command, get_driver
from nonebot.adapters.onebot.v11 import Bot, Event, Message, MessageSegment
from nonebot.adapters.onebot.v11.event import GroupMessageEvent
from nonebot.params import CommandArg
from nonebot.typing import T_State
from nonebot.log import logger

from . import permissions
from . import query_index
from . import render_backend
from . import render_mode
from . import wg_api
from . import wg_online
from . import ship_index
from . import tech_tree
from . import user_stats
from nonebot import on_notice
from nonebot.rule import to_me
from nonebot.adapters.onebot.v11.event import GroupIncreaseNoticeEvent, MessageEvent
from .version import version_str

RENDER_SH        = os.environ.get("WOWS_RENDER_SH",   "/opt/wows-bot/minimap/render.sh")
REPORT_FULL_CMD  = os.environ.get("WOWS_REPORT_FULL_CMD",  "/opt/wows-bot/report/bin/wows_full_report")
REPORT_BATTLE_CMD = os.environ.get("WOWS_REPORT_BATTLE_CMD", "/opt/wows-bot/report/bin/wows_report")
REPORT_DAMAGE_CMD = os.environ.get("WOWS_REPORT_DAMAGE_CMD", "/opt/wows-bot/report/bin/wows_damage_report")
RENDER_CRIMINALS_PY = os.environ.get("WOWS_RENDER_CRIMINALS",
                                      "/opt/wows-bot/report/bin/render_criminals.py")
RENDER_CHAT_PY = os.environ.get("WOWS_RENDER_CHAT",
                                 "/opt/wows-bot/report/bin/render_chat.py")
# Lesta(«Мир кораблей», .korablireplay)分流:normalized 战报管线(战报+复盘拼一张)
# + 专用 Lesta replayshark(旧 replayshark 无 battle-results/聊天 Lesta 修复)。
# extracted root 由 replayshark 按回放 build 自动选版本(WG 15.x / Lesta 26.x 共存)。
REPORT_FULL_LESTA_CMD = os.environ.get("WOWS_REPORT_FULL_LESTA_CMD",
                                        "/opt/wows-bot/report/bin/wows_full_report_normalized")
REPLAYSHARK_LESTA = os.environ.get("WOWS_REPLAYSHARK_LESTA",
                                    "/opt/wows-bot/report/replayshark-lesta")
WOWS_DATA_DIR = os.environ.get("WOWS_DATA_DIR", "/var/lib/wows-data/extracted")
# 旧 alias 暂留兼容(.env 里可能还有);后续清理
REPORT_CMD       = os.environ.get("WOWS_REPORT_CMD", REPORT_FULL_CMD)
ANALYZE_CMD      = os.environ.get("WOWS_ANALYZE_CMD", "/opt/wows-bot/report/bin/wows_analyze")
BASE_DIR         = os.path.expanduser(os.environ.get("WOWS_REPLAY_BASEDIR", "~/wows-bot-replay"))
# /船 战舰数值卡:ships.json 跟 render_ship.py 都在 report 包里 (subprocess/import 现拉)
SHIPS_JSON       = os.environ.get("WOWS_SHIPS_JSON",
                                  str(Path(REPORT_FULL_CMD).parent.parent / "data" / "ships.json"))
ARMOR_JSON       = os.environ.get("WOWS_ARMOR_JSON",
                                  str(Path(SHIPS_JSON).parent / "armor.json"))
_armor_data = None  # 懒加载缓存:index -> {hull, turrets}


def _armor_for(index: str):
    """读 armor.json 取一条;文件缺失/无该船返回 None。"""
    global _armor_data
    if _armor_data is None:
        try:
            _armor_data = json.loads(Path(ARMOR_JSON).read_text("utf-8"))
        except Exception as e:
            logger.warning(f"armor.json 读取失败 ({ARMOR_JSON}): {e}")
            _armor_data = {}
    return _armor_data.get(index)


MP4_TIMEOUT      = int(os.environ.get("WOWS_MP4_TIMEOUT", "600"))
PNG_TIMEOUT      = int(os.environ.get("WOWS_PNG_TIMEOUT", "300"))
ANALYZE_TIMEOUT  = int(os.environ.get("WOWS_ANALYZE_TIMEOUT", "120"))

# 战报 / 战犯 数据免责声明 —— 回放只含玩家个人视野内的数据,视野外不下发
_DATA_DISCLAIMER = "由于 WG 不下发个人视野之外的数据,本数据仅供参考。"

replay_handler = on_message(priority=5, block=False)

task_queue: asyncio.Queue = asyncio.Queue()
processing = False

# (user_id, message_id, group_id, user_dir, replay_path)
TaskInfo = Tuple[str, int, Optional[int], str, str]

driver = get_driver()


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
    try:
        query_index.init(BASE_DIR)
        logger.info(f"query_index inited at {BASE_DIR}")
    except Exception as e:
        logger.error(f"query_index 初始化失败: {e}")
    try:
        render_mode.init(BASE_DIR)
        logger.info(f"render_mode inited at {BASE_DIR} "
                    f"(parallel={render_mode.is_parallel()})")
    except Exception as e:
        logger.error(f"render_mode 初始化失败: {e}")
    try:
        render_backend.init(BASE_DIR)
        logger.info(f"render_backend inited at {BASE_DIR} "
                    f"(backend={render_backend.get_backend()})")
    except Exception as e:
        logger.error(f"render_backend 初始化失败: {e}")
    try:
        ship_index.init(SHIPS_JSON)
        if ship_index.is_ready():
            logger.info(f"ship_index inited from {SHIPS_JSON} "
                        f"(v{ship_index.version()})")
        else:
            logger.warning(f"ship_index 未就绪 (ships.json 缺失?): {SHIPS_JSON} — "
                           f"/船 命令会提示数据未生成")
    except Exception as e:
        logger.error(f"ship_index 初始化失败: {e}")
    try:
        user_stats.init(BASE_DIR)
        snap = user_stats.snapshot(top_n=1)
        logger.info(f"user_stats inited at {BASE_DIR} "
                    f"({snap['total_users']} 用户 / {snap['total_calls']} 次调用)")
    except Exception as e:
        logger.error(f"user_stats 初始化失败: {e}")


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


# ====== 菜单触发 ===============================================================

# /菜单 /menu /help  —— 三个 alias 共用一个处理器
menu_cmd = on_command("菜单", aliases={"menu", "help"}, priority=5, block=True)

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


# 群里 @bot 且没附别的内容 —— plaintext 为空就发菜单。
# 注:私聊里 to_me() 恒 True,空明文消息(QQ 表情/卡片/系统"已接收文件"提示等)
# 会无差别触发,所以这条规则**只在群聊生效**;私聊用户想看菜单显式发 /菜单 即可。
def _is_pure_at(event: MessageEvent) -> bool:
    return (isinstance(event, GroupMessageEvent)
            and not event.get_plaintext().strip())

at_only = on_message(rule=to_me() & _is_pure_at, priority=20, block=False)

@at_only.handle()
async def _at_only(bot: Bot, event: MessageEvent):
    await _reply_menu(bot, event)


# 猜船开关状态由 EssexBot 维护(独立进程),菜单只读它的状态文件做显示。
GUESS_TOGGLE_FILE = os.environ.get(
    "ESSEXBOT_GUESS_TOGGLE",
    "/home/zifeng/桌面/bot/EssexBot/data/guess_toggle.json",
)


def _read_guess_enabled(group_id: str) -> bool:
    """读 EssexBot 的群级猜船开关;默认关闭,读失败也按关闭。"""
    try:
        with open(GUESS_TOGGLE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("groups", {}).get(str(group_id), False))
    except Exception:
        return False


async def _reply_menu(bot: Bot, event):
    """渲染当前作用域的菜单 PNG,回复到群/私聊。"""
    scope, ident = permissions.scope_of(event)
    is_super = permissions.is_super_admin(getattr(event, "user_id", 0))
    state = permissions.snapshot()
    version = version_str()
    # 猜船是群级开关:只在群作用域显示 ON/OFF;私聊不显示该行
    guess_enabled = _read_guess_enabled(ident) if scope == "group" else None

    # 写到一个临时文件再读;避免 PIL → bytes 转换的复杂性
    out_dir = Path(BASE_DIR) / "_menu_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"menu_{scope}_{ident}.png"

    try:
        await asyncio.to_thread(
            _render_menu_sync,
            str(out_path), scope, ident, state, is_super, version, guess_enabled,
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


def _render_menu_sync(out_path, scope, ident, state, is_super, version, guess_enabled=None):
    """sync wrapper 给 to_thread 用 — render_menu 没有 async 接口。"""
    # 在 thread 里 import,避免插件加载阶段就拉 render_menu 的依赖链
    import sys as _sys
    bin_path = Path(REPORT_FULL_CMD).parent  # /opt/wows-bot/report/bin
    if str(bin_path) not in _sys.path:
        _sys.path.insert(0, str(bin_path))
    from render_menu import render_menu_png
    render_menu_png(
        out_path, scope=scope, ident=ident,
        state_snapshot=state, is_super=is_super, version=version,
        guess_enabled=guess_enabled,
    )


# ====== /sa 超管命令 ============================================================

sa_cmd = on_command("sa", priority=5, block=True)

_SA_HELP = (
    "用法: /sa <子命令>\n"
    "  /sa list                   看全局黑名单\n"
    "  /sa ban <视频|战报|复盘|分析>   全局禁用某功能\n"
    "  /sa unban <feature>         解禁\n"
    "  /sa stats                   各功能开关统计\n"
    "  /sa 并行 开|关|status        切渲染模式 (并行省时间, 串行省内存)"
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
        lines.append(f"渲染模式: {'并行' if render_mode.is_parallel() else '串行'}")
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

    if sub == "并行":
        if len(parts) != 2:
            await sa_cmd.finish("用法: /sa 并行 开|关|status")
        op = parts[1]
        if op == "status":
            mode = "并行" if render_mode.is_parallel() else "串行"
            await sa_cmd.finish(f"当前渲染模式: {mode}")
        if op in ("开", "on"):
            render_mode.set_parallel(True)
            await sa_cmd.finish(
                "已切到 并行 (MP4 + 战报 同时跑, 快但峰值内存 ~8 GB)")
        if op in ("关", "off"):
            render_mode.set_parallel(False)
            await sa_cmd.finish(
                "已切到 串行 (MP4 + 战报 顺序跑, 慢 5-15s 但峰值内存腰斩)")
        await sa_cmd.finish(f"未知操作 '{op}',合法: 开|关|status")

    await sa_cmd.finish(f"未知子命令 '{sub}'\n\n{_SA_HELP}")


# ====== /渲染模式 cpu|gpu|状态 (仅超管) =========================================
# 切换 MP4 渲染 backend。切换不影响正在跑的渲染(subprocess 已 spawn 带旧 env),
# 只影响下一份 replay。状态持久化到 render_backend.json,重启 bot 也保留。

render_backend_cmd = on_command("渲染模式", priority=5, block=True)


@render_backend_cmd.handle()
async def _render_backend_cmd(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    if not permissions.is_super_admin(event.get_user_id()):
        await render_backend_cmd.finish("权限不足:本命令只允许超管使用")
    sub = (args.extract_plain_text().strip().lower() if args else "")
    cur = render_backend.get_backend()
    if sub in ("", "状态", "status"):
        await render_backend_cmd.finish(
            f"当前渲染 backend: {cur.upper()}\n"
            f"  - CPU: 默认 AV1 软编,~7 MB / 20min,慢(2-3 分钟)、稳定\n"
            f"  - GPU: NVENC H.264 硬编,~10 MB / 20min,快(~20 秒)、依赖 NVIDIA driver\n"
            f"切换:/渲染模式 cpu  或  /渲染模式 gpu"
        )
    if sub not in ("cpu", "gpu"):
        await render_backend_cmd.finish("用法: /渲染模式 cpu | gpu | 状态")
    try:
        new = render_backend.set_backend(sub)
    except ValueError as e:
        await render_backend_cmd.finish(f"❌ {e}")
    if new == cur:
        await render_backend_cmd.finish(f"渲染 backend 本来就是 {new.upper()},无变化")
    await render_backend_cmd.finish(
        f"渲染 backend: {cur.upper()} → {new.upper()} ✓\n"
        f"(正在渲染的 replay 不受影响,下一份起按新 backend 跑)"
    )


# ====== /用户统计 (仅超管) =====================================================
# 用户 = 触发过非菜单功能的 QQ 号(/船 /查询 /线 拖 replay 猜船开局/猜中)。
# 输出 PNG:总用户数 + 总调用次数 + Top 5(头像 / 昵称 / 总次数 / 各功能拆分)。

user_stats_cmd = on_command("用户统计", priority=5, block=True)


@user_stats_cmd.handle()
async def _user_stats(bot: Bot, event: MessageEvent):
    if not permissions.is_super_admin(event.get_user_id()):
        await user_stats_cmd.finish("权限不足:本命令只允许超管使用")
    snap = user_stats.snapshot(top_n=5)
    if snap["total_users"] == 0:
        await user_stats_cmd.finish(
            "暂无任何用户使用记录(本版本上线后从零开始计)")
    # 为 top 5 补头像 + 昵称(QQ 头像走 https,昵称走 OneBot get_stranger_info)
    enriched = []
    for u in snap["top"]:
        uid = u["user_id"]
        nick = uid
        try:
            info = await bot.call_api("get_stranger_info", user_id=int(uid))
            nick = info.get("nickname") or info.get("nick") or uid
        except Exception as e:
            logger.debug(f"get_stranger_info({uid}) 失败: {e}")
        enriched.append({**u, "nickname": nick})
    out_dir = Path(BASE_DIR) / "_stats_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "user_stats.png"
    try:
        await asyncio.to_thread(_render_user_stats_sync, str(out_png),
                                 snap["total_users"], snap["total_calls"], enriched)
    except Exception as e:
        logger.error(f"渲染 /用户统计 失败: {e}")
        # PNG 失败兜底为纯文本
        lines = [f"总用户数: {snap['total_users']}   总调用: {snap['total_calls']}", "Top 5:"]
        for i, u in enumerate(enriched, 1):
            lines.append(f"  {i}. {u['nickname']} ({u['user_id']}) — {u['total']} 次")
        await user_stats_cmd.finish("\n".join(lines))
    await user_stats_cmd.finish(MessageSegment.image(f"file://{out_png}"))


def _render_user_stats_sync(out_path: str, total_users: int,
                             total_calls: int, top: list):
    """thread wrapper — render_user_stats 没 async 接口。"""
    import sys as _sys
    bin_path = str(Path(REPORT_FULL_CMD).parent)
    if bin_path not in _sys.path:
        _sys.path.insert(0, bin_path)
    from render_user_stats import render_user_stats_png
    render_user_stats_png(out_path, total_users=total_users,
                          total_calls=total_calls, top=top)


# ====== /查询 <编号> ===========================================================
# 要求用户引用回复战报消息;按 # 列编号查该玩家这条船的 WG 生涯数据。

query_cmd = on_command("查询", priority=5, block=True)


@query_cmd.handle()
async def _query(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    text = args.extract_plain_text().strip()
    if not text or not text.split()[0].isdigit():
        await query_cmd.finish(
            "用法: 引用战报消息回复 + /查询 <编号>\n"
            "示例 (引用战报): /查询 5"
        )
    idx = int(text.split()[0])

    reply = getattr(event, "reply", None)
    if reply is None or not getattr(reply, "message_id", None):
        await query_cmd.finish("请引用 (回复) 战报图消息,再发 /查询 <编号>")

    entry = query_index.lookup(int(reply.message_id))
    if entry is None:
        await query_cmd.finish(
            "未找到对应战报。请确认你引用 (回复) 的是 bot 发出的战报图消息 (含 # 列那张),"
            "而不是 MP4 / 复盘图 / 别人发的消息"
        )
    if query_index.is_expired(entry):
        await query_cmd.finish(
            "该战报已超过 3 小时查询窗口,请重新发回放让 bot 生成新战报后再查"
        )

    players = entry.get("players") or []
    player = next((p for p in players if p.get("idx") == idx), None)
    if player is None:
        await query_cmd.finish(f"编号 {idx} 在本局不存在 (本局共 {len(players)} 人)")

    user_stats.record(event.get_user_id(), "query")
    await query_cmd.send(f"查询中… (#{idx} {player.get('name','?')})")
    cached_realm = entry.get("_realms", {}).get(str(player["account_id"]))
    try:
        pvp, hit_realm = await wg_api.fetch_ship_stats(
            account_id=player["account_id"],
            ship_id=player["ship_id"],
            preferred_realm=cached_realm,
        )
    except Exception as e:
        logger.error(f"vortex 调用异常: {e}")
        await query_cmd.finish(f"⚠️ 查询失败: {e}")

    # 命中后把 realm 缓存进 query_index 那条 entry,下次同 account 直接命中
    if hit_realm:
        try:
            query_index.cache_realm(int(reply.message_id),
                                     player["account_id"], hit_realm)
        except Exception as e:
            logger.debug(f"realm 缓存失败 (无害): {e}")

    # 渲 PNG 卡片
    out_dir = Path(BASE_DIR) / "_query_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / f"query_{reply.message_id}_{idx}.png"
    try:
        await asyncio.to_thread(_render_query_sync, str(out_png),
                                 player, pvp, hit_realm)
    except Exception as e:
        logger.error(f"渲染 /查询 卡失败: {e}")
        await query_cmd.finish(wg_api.format_stats_summary(player, pvp, hit_realm))

    msg = MessageSegment.image(f"file://{out_png}")
    await query_cmd.finish(msg)


def _render_query_sync(out_path: str, player: dict, pvp, realm):
    """thread wrapper — render_query 没 async 接口。"""
    import sys as _sys
    bin_path = str(Path(REPORT_FULL_CMD).parent)
    if bin_path not in _sys.path:
        _sys.path.insert(0, bin_path)
    from render_query import render_query_png
    render_query_png(out_path, player=player, pvp=pvp, realm=realm)


# ====== /船 <中文名> 战舰数值卡 ==============================================
# 查询类命令,任何人可用,不接 permissions 开关。数据全在本地 ships.json,
# 运行时不打外部 API (跟 /查询 走 vortex 不同)。

ship_cmd = on_command("船", aliases={"战舰", "ship"}, priority=5, block=True)


@ship_cmd.handle()
async def _ship(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    name = args.extract_plain_text().strip()
    if not name:
        await ship_cmd.finish("用法: /船 <中文舰名>\n示例: /船 大和  ·  /船 yamato  ·  /船 岛风")

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
    user_stats.record(event.get_user_id(), "ship")
    out_dir = Path(BASE_DIR) / "_ship_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    idx = ship.get("index", ship.get("name_en", "x"))

    # 数值卡(必出)
    ship_png = out_dir / f"ship_{idx}.png"
    try:
        await asyncio.to_thread(_render_ship_sync, str(ship_png), ship)
    except Exception as e:
        logger.error(f"渲染 /船 卡失败: {e}")
        await ship_cmd.finish(f"⚠️ 渲染失败: {e}")
    msg = MessageSegment.image(f"file://{ship_png}")

    # 装甲卡(有装甲数据才追加;装甲渲染失败不影响数值卡)
    armor = _armor_for(ship.get("index", ""))
    if armor:
        armor_png = out_dir / f"armor_{idx}.png"
        try:
            await asyncio.to_thread(_render_armor_sync, str(armor_png), ship, armor)
            msg = msg + MessageSegment.image(f"file://{armor_png}")
        except Exception as e:
            logger.error(f"渲染 /船 装甲图失败: {e}")

    await ship_cmd.finish(msg)


def _render_ship_sync(out_path: str, ship: dict):
    """thread wrapper — render_ship 没 async 接口。"""
    import sys as _sys
    bin_path = str(Path(REPORT_FULL_CMD).parent)
    if bin_path not in _sys.path:
        _sys.path.insert(0, bin_path)
    from render_ship import render_ship_png
    render_ship_png(out_path, ship=ship)


def _render_armor_sync(out_path: str, ship: dict, armor: dict):
    """thread wrapper — render_armor 没 async 接口。"""
    import sys as _sys
    bin_path = str(Path(REPORT_FULL_CMD).parent)
    if bin_path not in _sys.path:
        _sys.path.insert(0, bin_path)
    from render_armor import render_armor_png
    render_armor_png(out_path, ship=ship, armor=armor)


# /装甲分析 <船名> —— 防御视角穿深矩阵
# (5 块代表板 × 距离×角度 矩阵, 每格写"主流战列弹达到 X mm 口径可击穿"的临界值)
pen_cmd = on_command("装甲分析", aliases={"穿深", "穿透", "防御分析"},
                     priority=5, block=True)


@pen_cmd.handle()
async def _pen(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    name = args.extract_plain_text().strip()
    if not name:
        await pen_cmd.finish("用法: /装甲分析 <中文舰名>\n"
                             "示例: /装甲分析 蒙大拿  ·  /装甲分析 大和  ·  /装甲分析 yamato")
    if not ship_index.is_ready():
        await pen_cmd.finish("战舰数据未生成 (ships.json 缺失)。请管理员跑 tools/build_ships_json.py")
    kind, payload = ship_index.find(name)
    if kind == "none":
        if payload:
            sug = "  ".join(payload[:8])
            await pen_cmd.finish(f"没找到「{name}」。你是不是想查:{sug}")
        await pen_cmd.finish(f"没找到「{name}」,换个名字试试 (支持中文名 / 英文名)")
    if kind == "multi":
        lines = "\n".join(
            f"  · {s['name_zh']} ({s['name_en']} T{s['tier']} {s.get('species_zh','')})"
            for s in payload
        )
        await pen_cmd.finish(f"「{name}」匹配到多艘,请发完整舰名:\n{lines}")

    target = payload[0]
    armor = _armor_for(target.get("index", ""))
    if not armor:
        await pen_cmd.finish(f"{target['name_zh']} 暂无装甲数据 (armor.json 缺该船)")

    out_dir = Path(BASE_DIR) / "_ship_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / f"pen_{target['index']}.png"
    try:
        await asyncio.to_thread(_render_pen_sync, str(out_png), target, armor)
    except Exception as e:
        logger.error(f"渲染 /装甲分析 失败: {e}")
        await pen_cmd.finish(f"⚠️ 渲染失败: {e}")
    await pen_cmd.finish(MessageSegment.image(f"file://{out_png}"))


def _render_pen_sync(out_path: str, target: dict, armor: dict):
    """thread wrapper。需要把 ships.json 里所有 ap_ballistic 一起传(典型弹拟合用)。"""
    import sys as _sys
    bin_path = str(Path(REPORT_FULL_CMD).parent)
    if bin_path not in _sys.path:
        _sys.path.insert(0, bin_path)
    import json
    ships_data = json.loads(Path(SHIPS_JSON).read_text("utf-8")).get("ships") or {}
    all_ap = [s.get("ap_ballistic") for s in ships_data.values()
              if s.get("ap_ballistic")]
    from render_pen import render_armor_analysis_png
    render_armor_analysis_png(out_path, target=target, armor=armor,
                              all_ap_shells=all_ap)


# /线 <国家> <舰种> —— 整条科技树
line_cmd = on_command("线", aliases={"线路", "科技树", "tree"}, priority=5, block=True)

_LINE_USAGE = (
    "用法: /线 <国家> <舰种>\n"
    "示例: /线 美国 巡洋舰  ·  /线 日 战列舰  ·  /线 德国 驱逐舰\n"
    "国家: 美/日/苏/德/英/法/意/泛亚/欧洲/荷兰/泛美/英联邦/西班牙\n"
    "舰种: 战列舰/巡洋舰/驱逐舰/航母/潜艇"
)


@line_cmd.handle()
async def _line(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    parts = args.extract_plain_text().split()
    if len(parts) < 2:
        await line_cmd.finish(_LINE_USAGE)

    if not ship_index.is_ready():
        await line_cmd.finish("战舰数据未生成 (ships.json 缺失)。请管理员跑 tools/build_ships_json.py")

    nation = tech_tree.resolve_nation(parts[0])
    species = tech_tree.resolve_species(parts[1])
    if not nation:
        await line_cmd.finish(f"认不出国家「{parts[0]}」\n" + _LINE_USAGE)
    if not species:
        await line_cmd.finish(f"认不出舰种「{parts[1]}」\n" + _LINE_USAGE)

    tree = tech_tree.build_tree(ship_index.all_ships(), nation, species)
    if not tree:
        await line_cmd.finish(f"{parts[0]} {parts[1]} 没有科技树线路")

    user_stats.record(event.get_user_id(), "line")
    out_dir = Path(BASE_DIR) / "_line_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / f"line_{nation}_{species}.png"
    try:
        await asyncio.to_thread(_render_line_sync, str(out_png), tree)
    except Exception as e:
        logger.error(f"渲染 /线 失败: {e}")
        await line_cmd.finish(f"⚠️ 渲染失败: {e}")

    await line_cmd.finish(MessageSegment.image(f"file://{out_png}"))


def _render_line_sync(out_path: str, tree: dict):
    """thread wrapper — render_line 没 async 接口。"""
    import sys as _sys
    bin_path = str(Path(REPORT_FULL_CMD).parent)
    if bin_path not in _sys.path:
        _sys.path.insert(0, bin_path)
    from render_line import render_line_png
    render_line_png(out_path, tree)


# ====== /在线 —— WG 三服在线人数 ==============================================
# WGN cross-product /wgn/servers/info/;RU (Lesta) 和 CN (360) 都独立不覆盖。

online_cmd = on_command("在线", aliases={"online", "人数"},
                        priority=5, block=True)


@online_cmd.handle()
async def _online(bot: Bot, event: MessageEvent):
    if not wg_online.is_configured():
        await online_cmd.finish("未配置 WG application_id (WOWS_WG_APP_ID)")

    try:
        data = await wg_online.fetch_all(timeout=6.0)
    except Exception as e:
        logger.error(f"/在线 查询失败: {e}")
        await online_cmd.finish(f"⚠️ 查询失败: {e}")

    # 按值降序 (人多的在前),失败的在后
    ordered = sorted(data.items(), key=lambda kv: (kv[1] is None, -(kv[1] or 0)))
    rows = [{"code": realm, "name": wg_online.display_name(realm), "online": n}
            for realm, n in ordered]
    note = "CN 360 服 / RU Lesta 独立运营,不含在内"

    user_stats.record(event.get_user_id(), "online")

    out_dir = Path(BASE_DIR) / "_online_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_png = out_dir / "online.png"
    try:
        await asyncio.to_thread(_render_online_sync, str(out_png), rows, note)
    except Exception as e:
        logger.error(f"渲染 /在线 失败,兜底纯文本: {e}")
        lines = ["WoWs 在线人数"]
        total = sum(r["online"] for r in rows if r["online"] is not None)
        ok = 0
        for r in rows:
            if r["online"] is None:
                lines.append(f"  {r['name']}  查询失败")
            else:
                lines.append(f"  {r['name']}  {r['online']:,}")
                ok += 1
        if ok > 1:
            lines.append(f"  合计  {total:,}")
        lines.append("")
        lines.append(f"({note})")
        await online_cmd.finish("\n".join(lines))
    await online_cmd.finish(MessageSegment.image(f"file://{out_png}"))


def _render_online_sync(out_path: str, rows: list, note: str):
    """thread wrapper — render_online 没 async 接口。"""
    import sys as _sys
    bin_path = str(Path(REPORT_FULL_CMD).parent)  # /opt/wows-bot/report/bin
    if bin_path not in _sys.path:
        _sys.path.insert(0, bin_path)
    from render_online import render_online_png
    render_online_png(out_path, rows=rows, note=note)


@replay_handler.handle()
async def handle_replay_file(bot: Bot, event: Event, state: T_State):
    """接收 .wowsreplay 文件,下载到本地后入队。"""
    global processing

    for seg in event.get_message():
        if seg.type != "file":
            continue

        file_name = seg.data.get("name") or seg.data.get("file") or ""
        # WG = .wowsreplay;Lesta(«Мир кораблей»)= .korablireplay。下游按扩展名分流。
        if not file_name.endswith((".wowsreplay", ".korablireplay")):
            continue

        user_id = str(event.get_user_id())
        timestamp = asyncio.get_event_loop().time()
        unique_dir = f"{user_id}_{int(timestamp * 1000)}"
        user_dir = os.path.join(BASE_DIR, unique_dir)
        group_id = event.group_id if isinstance(event, GroupMessageEvent) else None

        try:
            os.makedirs(user_dir, exist_ok=True)

            file_id = seg.data.get("file_id") or seg.data.get("id")
            if not file_id:
                raise RuntimeError("无法获取 file_id")

            file_url = await get_file_url(bot, event, file_id)
            if not file_url:
                raise RuntimeError("文件下载链接为空")

            file_path = os.path.join(user_dir, file_name)
            await download_file(file_url, file_path)

            await task_queue.put((user_id, event.message_id, group_id, user_dir, file_path))
            user_stats.record(user_id, "replay")

            await send_message(
                bot, user_id, group_id, event.message_id,
                f"✅ 已接收 replay 文件，当前队列位置：{task_queue.qsize()}"
            )
            logger.info(f"用户 {user_id} 入队 (队列长度 {task_queue.qsize()})")

            if not processing:
                asyncio.create_task(process_queue(bot))

        except Exception as e:
            logger.error(f"接收 replay 出错: {e}")
            if os.path.exists(user_dir):
                shutil.rmtree(user_dir, ignore_errors=True)
            await send_message(
                bot, user_id, group_id, event.message_id,
                f"❌ 文件接收失败: {e}"
            )


async def get_file_url(bot: Bot, event: Event, file_id: str) -> Optional[str]:
    """返回**下载源**:群聊给 HTTP URL,私聊 napcat 通常给本地 file:// 或绝对路径。
    download_file 两种都吃。"""
    try:
        if isinstance(event, GroupMessageEvent):
            info = await bot.call_api("get_group_file_url", group_id=event.group_id, file_id=file_id)
        else:
            info = await bot.call_api("get_file", file_id=file_id)
        # napcat get_file 偶有把路径放在 'file' 而非 'url' 字段(版本差异),双重兜底。
        return info.get("url") or info.get("file")
    except Exception as e:
        logger.error(f"获取文件 URL 失败: {e}")
        raise


async def download_file(source: str, save_path: str):
    """把文件搬到 save_path。source 可以是 http(s) URL(走 aiohttp 下载)
    或者 napcat 本地路径(file:// 或 /root/... 这种 — 直接 copy)。

    napcat 私聊的 get_file 返回的就是 bot 进程能 stat 的本地路径,因为
    napcat 跟 bot 同机部署。"""
    # 1) 本地路径:file:// 前缀剥掉;或直接看是不是已存在的文件
    local_path = source
    if source.startswith("file://"):
        local_path = source[len("file://"):]
        # Windows 形如 file:///C:/... → /C:/...,去掉前导斜杠
        if len(local_path) >= 3 and local_path[0] == "/" and local_path[2] == ":":
            local_path = local_path[1:]
    if not source.lower().startswith(("http://", "https://")) and os.path.exists(local_path):
        try:
            shutil.copyfile(local_path, save_path)
            logger.info(f"本地文件拷贝完成: {local_path} -> {save_path}")
            return
        except Exception as e:
            raise RuntimeError(f"本地文件拷贝失败: {e}")
    # 2) HTTP(S) 下载
    if not source.lower().startswith(("http://", "https://")):
        raise RuntimeError(f"不是有效的下载源(非 http 也不是本地文件): {source}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(source, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"下载失败,HTTP 状态码 {resp.status}")
                with open(save_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        f.write(chunk)
        logger.info(f"下载完成: {save_path}")
    except asyncio.TimeoutError:
        raise RuntimeError("下载超时")
    except Exception as e:
        raise RuntimeError(f"下载失败: {e}")


async def process_queue(bot: Bot):
    """串行处理队列;每个 replay 按本群 4 个 feature 开关决定跑哪几个输出。"""
    global processing
    processing = True

    while not task_queue.empty():
        user_id, message_id, group_id, user_dir, replay_path = await task_queue.get()
        scope = "group" if group_id else "private"
        ident = str(group_id) if group_id else user_id
        # Lesta 回放走 normalized 管线;分析/战犯/查询索引(吃旧 schema JSON)对 Lesta 暂跳过。
        is_lesta = replay_path.endswith(".korablireplay")

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
            # Lesta 不上 分析/战犯,故不为它们强产 JSON。
            needs_json = (on["分析"] or on["战犯"]) and not is_lesta
            if on["战报"] and on["复盘"]:
                report_kind = "full"
            elif on["战报"]:
                report_kind = "battle"
            elif on["复盘"]:
                report_kind = "damage"
            elif needs_json:
                report_kind = "battle"   # 只为产 JSON;PNG 不发
            else:
                report_kind = None

            # MP4 (可选) + 报告 (可选);并行 vs 串行 看 render_mode (超管 /sa 并行 切)
            # 并行: MP4 + 报告 同时跑,快但峰值 ~8 GB
            # 串行: 先跑报告 (5-15s) 再跑 MP4,峰值腰斩,4 核 8G VM 友好
            def _mk_report_coro():
                if is_lesta:
                    # Lesta 只有 normalized 全报告(战报+复盘拼一张);战报/复盘任一开启都出这张。
                    return run_full_report_lesta(replay_path, user_dir) if report_kind else None
                if report_kind == "full":
                    return run_full_report(replay_path, user_dir)
                if report_kind == "battle":
                    return run_battle_report(replay_path, user_dir)
                if report_kind == "damage":
                    return run_damage_report(replay_path, user_dir)
                return None

            result_map: dict = {}
            if render_mode.is_parallel():
                tasks: dict[str, asyncio.Future] = {}
                if on["视频"]:
                    tasks["mp4"] = asyncio.create_task(render_mp4(replay_path, user_dir, is_lesta))
                report_coro = _mk_report_coro()
                if report_coro is not None:
                    tasks["report"] = asyncio.create_task(report_coro)
                results = await asyncio.gather(*tasks.values(), return_exceptions=True)
                result_map = dict(zip(tasks.keys(), results))
            else:
                # 报告先跑 (短) — 给用户先发文字进度感更好;再跑 MP4 (长)
                report_coro = _mk_report_coro()
                if report_coro is not None:
                    try:
                        result_map["report"] = await report_coro
                    except Exception as e:
                        result_map["report"] = e
                if on["视频"]:
                    try:
                        result_map["mp4"] = await render_mp4(replay_path, user_dir, is_lesta)
                    except Exception as e:
                        result_map["mp4"] = e

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
                # report_kind=="battle" 且只为分析时不送图
                if report_kind in ("full", "damage") or (report_kind == "battle" and on["战报"]):
                    report_png = r

            # 发 MP4 + 报告(沿用原 upload_and_notify 接口)
            sent_report_msg_id = None
            if mp4_path or report_png or report_error:
                sent_report_msg_id = await upload_and_notify(
                    bot, user_id, group_id, message_id,
                    mp4_path, report_png, report_error,
                )

            # 若发出去了战报 PNG (有 # 列那张),把索引清单 remember 进 query_index
            # 供 /查询 反查。报告失败 / kind=damage(无 # 列) / kind=None 不记。
            if (sent_report_msg_id is not None
                    and report_png
                    and report_kind in ("full", "battle")
                    and not is_lesta):   # Lesta normalized 图无 # 列 + JSON 是新 schema,不入索引
                json_path_for_idx = os.path.join(user_dir, f"{Path(replay_path).stem}.json")
                if os.path.isfile(json_path_for_idx):
                    try:
                        meta, indexed = _build_indexed_players(json_path_for_idx)
                        query_index.remember(sent_report_msg_id, meta, indexed)
                        logger.info(f"query_index 记 msg_id={sent_report_msg_id} ({len(indexed)} 玩家)")
                    except Exception as e:
                        logger.warning(f"query_index 入库失败 (不影响主流程): {e}")

            # 分析:从 user_dir 里找 .json（Lesta 暂不支持:normalized JSON 结构不同）
            json_path = os.path.join(user_dir, f"{Path(replay_path).stem}.json")
            if on["分析"] and not is_lesta:
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

            # 战犯卡 (独立 PNG,跟战报/复盘合并版互不重复;Lesta 暂不支持)
            if on["战犯"] and not is_lesta:
                if os.path.isfile(json_path):
                    try:
                        crim_png = await run_criminals(json_path, user_dir)
                        if crim_png:  # 空串 = 没战犯
                            msg = (MessageSegment.reply(message_id)
                                   + MessageSegment.image(f"file://{crim_png}")
                                   + f"\n{_DATA_DISCLAIMER}")
                            if group_id:
                                await bot.call_api("send_group_msg",
                                                    group_id=group_id, message=msg)
                            else:
                                await bot.call_api("send_private_msg",
                                                    user_id=int(user_id), message=msg)
                    except Exception as e:
                        logger.warning(f"战犯渲染失败: {e}")
                        await send_message(bot, user_id, group_id, message_id,
                                           f"⚠️ 战犯渲染失败: {e}")
                else:
                    logger.warning(f"未找到 JSON,跳过战犯: {json_path}")

            # 聊天 PNG (本局玩家发言 + F 键预设语音,独立成图;有战报 JSON 就
            # 顺带带船中文名 + 敌友着色,没有则退化到纯用户名 + 中性色)
            if on["聊天"]:
                try:
                    chat_png = await run_chat(replay_path, user_dir,
                                              json_path if os.path.isfile(json_path) else None)
                    if chat_png:  # 空串 = 本局无聊天 + 无 F 键预设
                        msg = (MessageSegment.reply(message_id)
                               + MessageSegment.image(f"file://{chat_png}"))
                        if group_id:
                            await bot.call_api("send_group_msg",
                                                group_id=group_id, message=msg)
                        else:
                            await bot.call_api("send_private_msg",
                                                user_id=int(user_id), message=msg)
                    else:
                        # 显式告知 "本局没聊天",免得用户以为 toggle 没生效
                        await send_message(bot, user_id, group_id, message_id,
                                           "💬 本局无聊天 / 预设语音,跳过聊天 PNG")
                except Exception as e:
                    logger.warning(f"聊天渲染失败: {e}")
                    await send_message(bot, user_id, group_id, message_id,
                                       f"⚠️ 聊天渲染失败: {e}")

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


_MP4_ANSI_RE     = re.compile(r"\x1b\[[0-9;]*m")  # 剥 tracing 输出的 ANSI 颜色码
_MP4_PROGRESS_RE = re.compile(r"INFO Progress stage=(\w+) frame=(\d+) total=(\d+)")
_MP4_BAR_WIDTH   = 24
_MP4_PCT_STEP    = 0.05   # 进度变化 ≥5% 才 emit
_MP4_TIME_STEP   = 5.0    # 或 时间 ≥5s 才 emit


def _mp4_progress_bar(stage: str, frame: int, total: int) -> str:
    """`Encoding ████████░░░░░░░░ 53.4% ( 824/1545)` 字符画风格。"""
    pct = (frame / total) if total > 0 else 0.0
    fill = int(round(_MP4_BAR_WIDTH * pct))
    bar = "█" * fill + "░" * (_MP4_BAR_WIDTH - fill)
    width = len(str(total))
    return f"{stage:8s} {bar} {pct*100:5.1f}% ({frame:>{width}}/{total})"


async def render_mp4(replay_path: str, work_dir: str, is_lesta: bool = False):
    """调用 WOWS_RENDER_SH 渲染 MP4。

    流式读 subprocess stdout/stderr 喂给 logger:
    - `Progress stage=X frame=Y total=Z` 行 → 解析 + 节流(≥5% 或 ≥5s 一条)+
      字符画进度条,代替逐 100 帧刷屏。
    - 其他 INFO / WARN / 错误行原样 INFO,带 `[mp4:<name>] <line>` 前缀。
    - 累积 tail_buf 给失败时报错截尾,不到结束才一次性 communicate()
      (那样进度全憋在 pipe 里,bot 看着像"卡住了")。"""
    output_path = os.path.join(work_dir, f"{Path(replay_path).stem}.mp4")
    name = Path(replay_path).stem
    # spawn 时按当前 backend 选 cpu/gpu 注入 env。subprocess 一旦 fork 出去就
    # 带着这份 env,后续 /渲染模式 切换不影响正在跑的渲染,只影响下一次新 spawn。
    backend = render_backend.get_backend()
    env = {**os.environ, "WOWS_RENDER_BACKEND": backend}
    # Lesta 客户端只有 ru 本地化槽,泽刻汉化把中文写进 ru;提取数据后中文也在
    # translations/ru。故 Lesta MP4 用 --lang ru(WG 用默认 zh_sg)才能出中文船名。
    if is_lesta:
        env["WOWS_RENDER_LANG"] = "ru"
    logger.info(f"[mp4:{name}] 启动渲染 backend={backend}{' lesta' if is_lesta else ''}")
    try:
        proc = await asyncio.create_subprocess_exec(
            RENDER_SH, replay_path, output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        tail_buf: list[str] = []
        TAIL_MAX = 200
        # stage → (last_pct, last_ts) 节流用
        last_progress: Dict[str, Tuple[float, float]] = {}
        loop = asyncio.get_event_loop()

        async def _stream(reader, label: str):
            assert reader is not None
            async for raw in reader:
                line = raw.decode('utf-8', errors='ignore').rstrip()
                if not line:
                    continue
                # 剥 ANSI 颜色码 —— tracing 默认带颜色,regex 匹配不到,而且
                # 写到 nonebot 文件 log 是 \x1b 乱码字节,清掉对终端显示无害。
                line = _MP4_ANSI_RE.sub("", line)
                # 进度条节流(始终累计到 tail_buf,以便失败时报错有完整上下文)
                tail_buf.append(line)
                if len(tail_buf) > TAIL_MAX:
                    tail_buf.pop(0)
                m = _MP4_PROGRESS_RE.search(line)
                if m:
                    stage, frame, total = m.group(1), int(m.group(2)), int(m.group(3))
                    pct = (frame / total) if total > 0 else 0.0
                    now = loop.time()
                    last_pct, last_ts = last_progress.get(stage, (-1.0, 0.0))
                    if (pct - last_pct >= _MP4_PCT_STEP
                            or now - last_ts >= _MP4_TIME_STEP
                            or pct >= 1.0):
                        last_progress[stage] = (pct, now)
                        logger.info(f"[mp4:{name}] {_mp4_progress_bar(stage, frame, total)}")
                    continue
                logger.info(f"[mp4:{name} {label}] {line}")

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _stream(proc.stdout, "out"),
                    _stream(proc.stderr, "err"),
                    proc.wait(),
                ),
                timeout=MP4_TIMEOUT,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"MP4 渲染超时({MP4_TIMEOUT}s)")

        if proc.returncode != 0:
            tail = "\n".join(tail_buf[-20:]) or "未知错误"
            raise RuntimeError(f"MP4 渲染失败:\n{tail}")
        logger.info(f"MP4 完成: {output_path}")
    except FileNotFoundError:
        raise RuntimeError(f"找不到 MP4 渲染脚本: {RENDER_SH}")


async def run_analyze(json_path: str) -> str:
    """调用 wows_analyze,返回 LLM 输出的分析文本。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            ANALYZE_CMD, json_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=ANALYZE_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"分析超时({ANALYZE_TIMEOUT}s)")
        if proc.returncode != 0:
            tail = stderr.decode('utf-8', errors='ignore')[-500:] if stderr else "未知错误"
            raise RuntimeError(f"分析失败: {tail}")
        text = stdout.decode('utf-8', errors='ignore').strip()
        if not text:
            raise RuntimeError("分析输出为空")
        return text
    except FileNotFoundError:
        raise RuntimeError(f"找不到分析命令: {ANALYZE_CMD}")


async def run_battle_report(replay_path: str, work_dir: str) -> str:
    """跑 wows_report,返回战报 PNG 路径。同时会在 work_dir 留下同名 .json。"""
    return await _run_report_like(REPORT_BATTLE_CMD, replay_path, work_dir, "战报")


async def run_damage_report(replay_path: str, work_dir: str) -> str:
    """跑 wows_damage_report,返回复盘 PNG 路径。会复用缓存的 .json。"""
    return await _run_report_like(REPORT_DAMAGE_CMD, replay_path, work_dir, "复盘")


def _strip_wrapped_id(s: str) -> int:
    """'AccountId(123)' / 'GameParamId(456)' / 'EntityId(789)' → int。"""
    if not s:
        return 0
    s = str(s)
    if "(" in s and s.endswith(")"):
        s = s[s.index("(") + 1:-1]
    try:
        return int(s)
    except ValueError:
        return 0


_SPECIES_ZH = {
    "Battleship": "战列", "Cruiser": "巡洋", "Destroyer": "驱逐",
    "Submarine": "潜艇", "AirCarrier": "航母",
}


def _build_indexed_players(json_path: str) -> tuple[dict, list]:
    """读 replay JSON,按战报 # 列同样的顺序 (己方 1..N,敌方 N+1..) 构建轻量索引清单。
    返回 (match_meta, indexed_players)。"""
    with open(json_path, "r", encoding="utf-8") as f:
        d = json.load(f)
    m = d.get("match", {}) or {}
    self_name = m.get("self_player_name", "")
    players = d.get("players", []) or []
    self_p = next((p for p in players if p.get("name") == self_name), None)
    self_team = self_p.get("team_id", 0) if self_p else 0

    # 尝试翻译船名 + 拿 server-authoritative damage 排序 (跟战报 # 列对齐)
    try:
        import sys as _sys
        rb_path = str(Path(REPORT_FULL_CMD).parent)
        if rb_path not in _sys.path:
            _sys.path.insert(0, rb_path)
        from render_battle_report import (
            t as _t, load_translations as _load_translations,
            clean_ship_name as _clean, result_field as _rf,
        )
        _load_translations()
        def _ship_zh(sp): return _t(f"IDS_{sp.get('index','')}", _clean(sp.get('name', '')))
        def _sort_dmg(p):
            # 跟 render_battle_report 一致: results_info.damage 优先 (含玩家迷雾外的伤害),
            # 否则 stats.damage_dealt。否则 /查询 N 会拿到 #N 之外的玩家 (issue: CV/侦察错位)
            d = _rf(p.get("results_info"), "damage")
            if d is None:
                d = (p.get("stats") or {}).get("damage_dealt") or 0
            return float(d)
    except Exception:
        def _ship_zh(sp): return sp.get("name", "")
        def _sort_dmg(p): return float((p.get("stats") or {}).get("damage_dealt") or 0)

    def _team_indexed(team_id: int, start_idx: int) -> list:
        members = [p for p in players if p.get("team_id") == team_id]
        members.sort(key=lambda p: -_sort_dmg(p))
        out = []
        for i, p in enumerate(members):
            sp = p.get("ship", {}) or {}
            st = p.get("stats", {}) or {}
            species_raw = sp.get("species", "")
            if species_raw.startswith("Known(") and species_raw.endswith(")"):
                species_raw = species_raw[6:-1]
            out.append({
                "idx": start_idx + i,
                "name": p.get("name", "?"),
                "account_id": _strip_wrapped_id(p.get("account_id")),
                "ship_id":    _strip_wrapped_id(sp.get("id")),
                "ship_name":  sp.get("name", ""),
                "ship_index": sp.get("index", ""),
                "ship_zh":    _ship_zh(sp),
                "ship_level": sp.get("level", 0),
                "species_raw": species_raw,
                "species_zh": _SPECIES_ZH.get(species_raw, species_raw or "?"),
                "team_id":    team_id,
                "this_game": {
                    # 跟 _sort_dmg + 战报 PNG # 列同源:results_info.damage 优先
                    # (server 权威值,含玩家迷雾外伤害),否则 stats.damage_dealt 兜底。
                    # 否则会出现 /查询 显示值跟战报对不上(stats.damage_dealt 是玩家视角,
                    # 在 CV / 侦察机相关情形偶尔偏小)。
                    "dmg":   int(_sort_dmg(p)),
                    "frags": int(st.get("frags") or 0),
                    "alive": bool(st.get("is_alive")),
                    "time_lived_secs": st.get("time_lived_secs"),
                },
                # 本局配装(舰长/技能/升级/旗帜),老 replay 或异常 entity 时为 None,render_query 会跳过 panel
                "build": sp.get("build"),
            })
        return out

    self_indexed  = _team_indexed(self_team, 1)
    other_indexed = _team_indexed(1 - self_team, len(self_indexed) + 1)
    indexed = self_indexed + other_indexed

    match_meta = {
        "map":  (m.get("map_name") or "").split("/")[-1],
        "mode": f"{m.get('match_group','?')}·{m.get('game_mode','?')}",
        "date": m.get("date_time", ""),
        "self_team": self_team,
    }
    return match_meta, indexed


async def run_full_report(replay_path: str, work_dir: str) -> str:
    """跑 wows_full_report,返回拼接 PNG 路径 (战报+复盘 竖向拼一张)。
    bot 调用恒带 WOWS_SKIP_CRIMINALS=1 — 战犯走独立 PNG 路径,避免重复。"""
    return await _run_report_like(REPORT_FULL_CMD, replay_path, work_dir, "全报告",
                                   extra_env={"WOWS_SKIP_CRIMINALS": "1"})


async def run_full_report_lesta(replay_path: str, work_dir: str) -> str:
    """Lesta:跑 wows_full_report_normalized(normalized 管线,战报+复盘拼一张)。
    用 Lesta 专用 replayshark + extracted root(replayshark 按回放 build 自动选版本);
    显式清空 WOWS_GAME_DIR 强制走 -e。同样在 work_dir 留 {stem}.json。"""
    return await _run_report_like(
        REPORT_FULL_LESTA_CMD, replay_path, work_dir, "全报告(Lesta)",
        extra_env={
            "WOWS_REPLAYSHARK": REPLAYSHARK_LESTA,
            "WOWS_EXTRACTED": WOWS_DATA_DIR,
            "WOWS_GAME_DIR": "",
        },
    )


async def run_criminals(json_path: str, work_dir: str) -> str:
    """对已有 JSON 跑 render_criminals.py,返回 PNG 路径。
    返回码 3 = 没战犯(平局/全员合格),用 FileNotFoundError 风格 raise 给上层降级。"""
    out_png = os.path.join(work_dir, f"{Path(json_path).stem}.criminals.png")
    py = os.environ.get("WOWS_PYTHON") or sys.executable
    try:
        proc = await asyncio.create_subprocess_exec(
            py, RENDER_CRIMINALS_PY, json_path, out_png,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=PNG_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"战犯渲染超时({PNG_TIMEOUT}s)")
        if proc.returncode == 3:
            return ""   # 没战犯, 静默
        if proc.returncode != 0:
            tail = stderr.decode('utf-8', errors='ignore')[-500:] if stderr else "?"
            raise RuntimeError(f"战犯渲染失败: {tail}")
        if not os.path.exists(out_png):
            raise RuntimeError(f"战犯 PNG 未生成: {out_png}")
        return out_png
    except FileNotFoundError:
        raise RuntimeError(f"找不到战犯渲染脚本: {RENDER_CRIMINALS_PY}")


async def run_chat(replay_path: str, work_dir: str, json_path: str | None = None) -> str:
    """跑 render_chat.py 出本局聊天 PNG。
    json_path 给了 → 每行聊天带船中文名 + 敌友着色;None / 文件不存在 → 退化到
    纯用户名 + 中性色。 rc=3 = 本局无任何聊天,返空串让上层降级静默。"""
    out_png = os.path.join(work_dir, f"{Path(replay_path).stem}.chat.png")
    py = os.environ.get("WOWS_PYTHON") or sys.executable
    extra_args = ["--report-json", json_path] if json_path and os.path.isfile(json_path) else []
    try:
        proc = await asyncio.create_subprocess_exec(
            py, RENDER_CHAT_PY, replay_path, out_png, *extra_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=PNG_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"聊天渲染超时({PNG_TIMEOUT}s)")
        if proc.returncode == 3:
            # 把 render_chat 的 stderr 打到 bot log,owner 能定位 "真无聊天" vs
            # "regex 没吃" 两种情况;用户那边仍然走静默"本局无聊天"提示
            tail = stderr.decode('utf-8', errors='ignore').strip() if stderr else ""
            if tail:
                logger.warning(f"[chat] render_chat rc=3 stderr:\n{tail[-1500:]}")
            return ""   # 本局无聊天, 静默
        if proc.returncode != 0:
            tail = stderr.decode('utf-8', errors='ignore')[-500:] if stderr else "?"
            raise RuntimeError(f"聊天渲染失败: {tail}")
        if not os.path.exists(out_png):
            raise RuntimeError(f"聊天 PNG 未生成: {out_png}")
        return out_png
    except FileNotFoundError:
        raise RuntimeError(f"找不到聊天渲染脚本: {RENDER_CHAT_PY}")


async def _run_report_like(cmd: str, replay_path: str, work_dir: str, label: str,
                            extra_env: dict | None = None) -> str:
    """三个 wows_*_report 子进程同构,抽 helper。extra_env 合并到当前环境。"""
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    try:
        proc = await asyncio.create_subprocess_exec(
            cmd, replay_path, work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
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


async def upload_and_notify(bot: Bot, user_id: str, group_id: Optional[int],
                            message_id: int, mp4_path: Optional[str],
                            png_path: Optional[str] = None,
                            png_error: Optional[str] = None) -> Optional[int]:
    """上传 MP4(如果有),并把 PNG (或失败说明) 一起回到原消息上。
    mp4_path / png_path / png_error 三者均可为 None — 全 None 时本函数静默 no-op。
    返回:发出去的 chat 消息 msg_id (供 /查询 反查),静默 no-op 时返 None。"""
    if not (mp4_path or png_path or png_error):
        return None

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
        message = message + f"\n{_DATA_DISCLAIMER}"

    try:
        if group_id:
            resp = await bot.call_api("send_group_msg", group_id=group_id, message=message)
        else:
            resp = await bot.call_api("send_private_msg", user_id=int(user_id), message=message)
        return int(resp.get("message_id")) if isinstance(resp, dict) and "message_id" in resp else None
    except Exception as e:
        logger.error(f"发送合并消息失败: {e}")
        raise RuntimeError(f"消息发送失败: {str(e)}")


async def send_message(bot: Bot, user_id: str, group_id: Optional[int],
                       message_id: int, content: str):
    try:
        message = MessageSegment.reply(message_id) + content
        if group_id:
            await bot.call_api("send_group_msg", group_id=group_id, message=message)
        else:
            await bot.call_api("send_private_msg", user_id=int(user_id), message=message)
    except Exception as e:
        logger.error(f"发送消息失败: {e}")


@driver.on_shutdown
async def cleanup():
    if processing:
        logger.warning("关闭中,队列还有任务未完成")
