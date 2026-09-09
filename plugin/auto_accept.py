# plugin/auto_accept.py
"""自动同意好友请求 + 自动同意入群邀请。

两类事件(OneBot v11):
  - FriendRequestEvent            别人加 bot 好友
  - GroupRequestEvent
      sub_type == "invite"        别人邀请 bot 进群       <- 自动同意
      sub_type == "add"           别人申请加入 bot 所在群 <- **不处理**

为什么 "add" 不自动同意:那是在替群主审人(bot 得是管理员才有权限),放开等于
让任何人无审核进别人的群。这个插件只管"bot 自己的社交关系",不代群主做决定。

开关(NoneBot .env,注意 nonebot 2.4 只把声明过的键塞进 Config,所以统一走
get_driver().config 读,不用 os.environ):
    WOWS_AUTO_ACCEPT_FRIEND=true      默认 true
    WOWS_AUTO_ACCEPT_INVITE=true      默认 true
    WOWS_AUTO_ACCEPT_NOTIFY=true      默认 true —— 同意后发通知
    WOWS_AUTO_ACCEPT_NOTIFY_GROUP=892054735   通知发到哪个群(默认见常量)

通知统一发到 NOTIFY_GROUP 这个群里并 @ 全部超管(不私聊)。超管名单复用
announcement.py 那份 data/admins.json(同一份名单,单一来源)。
"""
import json
from pathlib import Path
from typing import List

from nonebot import get_driver, on_request
from nonebot.adapters.onebot.v11 import (
    Bot,
    FriendRequestEvent,
    GroupRequestEvent,
    Message,
    MessageSegment,
)
from nonebot.log import logger
from nonebot.plugin import PluginMetadata

__plugin_meta__ = PluginMetadata(
    name="自动同意好友/入群邀请",
    description="自动通过好友请求和拉群邀请,并在通知群里 @ 超管",
    usage="无指令,后台自动生效。开关/通知群见 .env 的 WOWS_AUTO_ACCEPT_*",
    type="application",
    supported_adapters={"~onebot.v11"},
)

PLUGIN_DIR = Path(__file__).parent
BOT_DIR = PLUGIN_DIR.parent.parent          # EssexBot 根目录
ADMIN_DATA_PATH = BOT_DIR / "data" / "admins.json"
# 通知落地的群(可用 .env 的 WOWS_AUTO_ACCEPT_NOTIFY_GROUP 覆盖)
DEFAULT_NOTIFY_GROUP = 892054735


def _cfg_bool(name: str, default: bool = True) -> bool:
    """从 nonebot Config 读布尔开关。未配置时用 default。

    .env 里的值是字符串("true"/"1"/"yes" 都算真),也兼容已经是 bool 的情况。
    """
    raw = getattr(get_driver().config, name.lower(), None)
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _load_admins() -> List[str]:
    """读超管名单;文件缺失/损坏时返回空表(只影响通知,不影响自动同意)。"""
    if not ADMIN_DATA_PATH.is_file():
        return []
    try:
        with open(ADMIN_DATA_PATH, "r", encoding="utf-8") as f:
            return [str(x) for x in json.load(f)]
    except Exception as e:
        logger.error(f"[自动同意] 读管理员名单失败: {e}")
        return []


def _notify_group_id() -> int:
    """通知群号:.env 覆盖优先,否则用 DEFAULT_NOTIFY_GROUP。"""
    raw = getattr(get_driver().config, "wows_auto_accept_notify_group", None)
    if raw is None:
        return DEFAULT_NOTIFY_GROUP
    try:
        return int(str(raw).strip())
    except ValueError:
        logger.warning(f"[自动同意] 通知群号配置无效({raw!r}),回退 {DEFAULT_NOTIFY_GROUP}")
        return DEFAULT_NOTIFY_GROUP


async def _notify(bot: Bot, text: str) -> None:
    """发通知到指定群,开头 @ 全部超管。

    发送失败只记 error —— 通知丢了不影响已经完成的同意动作(好友/入群已生效)。
    超管名单为空时仍然发,只是没有 @(至少群里能看到发生了什么)。
    """
    if not _cfg_bool("WOWS_AUTO_ACCEPT_NOTIFY"):
        return
    group_id = _notify_group_id()
    msg = Message()
    for admin in _load_admins():
        try:
            msg += MessageSegment.at(int(admin)) + " "
        except ValueError:
            logger.warning(f"[自动同意] 跳过无效超管 QQ: {admin!r}")
    msg += text
    try:
        await bot.send_group_msg(group_id=group_id, message=msg)
    except Exception as e:
        logger.error(f"[自动同意] 发通知到群 {group_id} 失败: {e}")


# ==================== 好友请求 ====================
friend_req = on_request(priority=5, block=False)


@friend_req.handle()
async def handle_friend(bot: Bot, event: FriendRequestEvent):
    if not _cfg_bool("WOWS_AUTO_ACCEPT_FRIEND"):
        logger.info(f"[自动同意] 好友自动同意已关,忽略 {event.user_id}")
        return
    try:
        await event.approve(bot)
        logger.info(f"[自动同意] 已同意好友请求: {event.user_id} (验证消息: {event.comment})")
    except Exception as e:
        logger.error(f"[自动同意] 同意好友 {event.user_id} 失败: {e}")
        return
    await _notify(bot, f"已自动同意好友请求\nQQ: {event.user_id}\n验证消息: {event.comment or '(无)'}")


# ==================== 入群邀请 ====================
group_req = on_request(priority=5, block=False)


@group_req.handle()
async def handle_group(bot: Bot, event: GroupRequestEvent):
    # 只处理"邀请 bot 进群";"申请加群"是群主的事,不代为审批(见模块 docstring)
    if event.sub_type != "invite":
        return
    if not _cfg_bool("WOWS_AUTO_ACCEPT_INVITE"):
        logger.info(f"[自动同意] 入群邀请自动同意已关,忽略群 {event.group_id}")
        return
    try:
        await event.approve(bot)
        logger.info(f"[自动同意] 已接受入群邀请: 群 {event.group_id} (邀请人 {event.user_id})")
    except Exception as e:
        logger.error(f"[自动同意] 接受入群邀请 {event.group_id} 失败: {e}")
        return
    await _notify(bot, f"已自动接受入群邀请\n群号: {event.group_id}\n邀请人: {event.user_id}")
