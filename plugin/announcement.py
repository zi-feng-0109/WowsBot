# plugin/announcement.py
"""全群公告 / 定向公告 — 超管对所有/指定群发消息。

支持文本 + 图片 + QQ 表情。`@` 和回复段会被丢掉(避免把 `@机器人 /公告 ...`
里的 @ 也当公告内容广播出去)。

命令:
  /全群公告 <内容>       别名: /广播 /公告
  /定向公告 <群号1> [群号2] ... <内容>   别名: /指定公告

管理员名单独立维护在 `EssexBot/data/admins.json` (一个 JSON 数组,元素是
QQ 号字符串或数字),启动时一次性加载。不复用 NoneBot SUPERUSERS,因为
超管语义比"能用 bot 调试命令"更敏感,需要单独白名单。
"""
import json
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Tuple

from nonebot import on_command, get_driver
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata
from nonebot.adapters.onebot.v11 import Bot, MessageSegment, Message, MessageEvent
from nonebot.log import logger

__plugin_meta__ = PluginMetadata(
    name="全群公告",
    description="超管向所有/指定群组发送公告(支持文字+图片+表情)",
    usage=(
        "/全群公告 <内容>   全部已加群广播\n"
        "/定向公告 <群号1> [群号2] ... <内容>   只发指定群\n"
        "  内容可以混排文字 / 图片 / 表情,@ 和引用回复会被自动剔除"
    ),
    type="application",
    homepage="",
    supported_adapters={"~onebot.v11"},
)

# ==================== 配置 ====================
PLUGIN_DIR = Path(__file__).parent
BOT_DIR = PLUGIN_DIR.parent.parent  # EssexBot 根目录
ADMIN_DATA_PATH = BOT_DIR / "data" / "admins.json"

admin_list: List[str] = []


# ==================== 管理员 ====================
def load_admin_list() -> None:
    global admin_list
    if not ADMIN_DATA_PATH.exists():
        admin_list = []
        logger.warning(f"[公告] 未找到管理员配置文件: {ADMIN_DATA_PATH}")
        return
    try:
        with open(ADMIN_DATA_PATH, "r", encoding="utf-8") as f:
            raw_list = json.load(f)
        admin_list = [str(admin) for admin in raw_list]
        logger.info(f"[公告] 已加载 {len(admin_list)} 个管理员")
    except Exception as e:
        logger.error(f"[公告] 加载管理员列表失败: {e}")
        admin_list = []


def is_admin(user_id: str) -> bool:
    return user_id in admin_list or (user_id.isdigit() and int(user_id) in admin_list)


def build_reply_message(text: str, message_id: int = None, user_id: str = None) -> Message:
    msg = Message()
    if message_id:
        msg += MessageSegment.reply(message_id)
    elif user_id:
        msg += MessageSegment.at(user_id) + " "
    msg += text
    return msg


driver = get_driver()


@driver.on_startup
async def _():
    load_admin_list()


# ==================== 段过滤 ====================
def _filter_broadcast_body(args: Message) -> Tuple[Message, str, int]:
    """从用户输入抽广播 body。保留 text/image/face,丢 at/reply。
    返回 (清洗后的 Message, 纯文字预览, 图片数)。"""
    cleaned = Message()
    text_buf: List[str] = []
    img_count = 0
    for seg in args:
        if seg.type == "text":
            t = seg.data.get("text", "")
            if t:
                cleaned += MessageSegment.text(t)
                text_buf.append(t)
        elif seg.type == "image":
            src = seg.data.get("url") or seg.data.get("file")
            if src:
                cleaned += MessageSegment.image(src)
                img_count += 1
        elif seg.type == "face":
            cleaned += seg
    return cleaned, "".join(text_buf).strip(), img_count


def _split_target_groups(args: Message) -> Tuple[List[int], Message, str, int]:
    """从 args 头部抽连续的数字群号,剩下的当 body (同样过 text/image/face 过滤)。
    返回 (群号列表, body Message, 纯文字预览, 图片数)。"""
    group_ids: List[int] = []
    body = Message()
    text_buf: List[str] = []
    img_count = 0
    body_mode = False

    for seg in args:
        if not body_mode and seg.type == "text":
            tokens = seg.data.get("text", "").split()
            i = 0
            while i < len(tokens) and tokens[i].isdigit():
                group_ids.append(int(tokens[i]))
                i += 1
            if i < len(tokens):
                remainder = " ".join(tokens[i:])
                body += MessageSegment.text(remainder)
                text_buf.append(remainder)
                body_mode = True
        else:
            body_mode = True
            if seg.type == "text":
                t = seg.data.get("text", "")
                if t:
                    body += MessageSegment.text(t)
                    text_buf.append(t)
            elif seg.type == "image":
                src = seg.data.get("url") or seg.data.get("file")
                if src:
                    body += MessageSegment.image(src)
                    img_count += 1
            elif seg.type == "face":
                body += seg

    return group_ids, body, "".join(text_buf).strip(), img_count


def _preview_label(text_preview: str, img_count: int) -> str:
    """给确认/统计消息用的简短预览。"""
    text_part = text_preview[:50] + ("..." if len(text_preview) > 50 else "")
    if img_count:
        suffix = f" [+{img_count}图]"
        return (text_part or "(无文字)") + suffix
    return text_part


# ==================== /全群公告 ====================
broadcast_cmd = on_command("全群公告", aliases={"广播", "公告"}, priority=5, block=True)


@broadcast_cmd.handle()
async def handle_broadcast(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    user_id = event.get_user_id()
    message_id = getattr(event, "message_id", None)

    if not is_admin(user_id):
        await broadcast_cmd.finish(build_reply_message(
            "❌ 你没有管理员权限,无法发送全群公告", message_id, user_id
        ))

    body, text_preview, img_count = _filter_broadcast_body(args)
    if not text_preview and img_count == 0:
        await broadcast_cmd.finish(build_reply_message(
            "❌ 请输入公告内容\n"
            "用法:/全群公告 <文字>  或  /全群公告 <文字> [图片]\n"
            "例如:/全群公告 服务器今晚维护",
            message_id, user_id,
        ))

    try:
        group_list = await bot.call_api("get_group_list")
        if not group_list:
            await broadcast_cmd.finish(build_reply_message("❌ 未找到任何群组", message_id, user_id))
        total_groups = len(group_list)
        await bot.send(event, build_reply_message(
            f"📢 开始向 {total_groups} 个群组发送公告...\n公告内容:{_preview_label(text_preview, img_count)}",
            message_id, user_id,
        ))
    except Exception as e:
        logger.error(f"[公告] 获取群组列表失败: {e}")
        await broadcast_cmd.finish(build_reply_message(f"❌ 获取群组列表失败: {e}", message_id, user_id))

    announcement_msg = Message()
    announcement_msg += MessageSegment.text(f"📢【全群公告】\n{'-' * 20}\n")
    announcement_msg += body
    announcement_msg += MessageSegment.text(f"\n{'-' * 20}")

    success_count = 0
    failed_count = 0
    failed_groups: List[Dict[str, Any]] = []

    for group_info in group_list:
        group_id = group_info.get("group_id")
        group_name = group_info.get("group_name", "未知群组")
        try:
            await bot.call_api("send_group_msg", group_id=group_id, message=announcement_msg)
            success_count += 1
            logger.info(f"[公告] 成功发送到群组 {group_name}({group_id})")
            await asyncio.sleep(0.5)
        except Exception as e:
            failed_count += 1
            failed_groups.append({"group_id": group_id, "group_name": group_name, "error": str(e)})
            logger.error(f"[公告] 发送到群组 {group_name}({group_id}) 失败: {e}")

    result_text = (
        f"✅ 公告发送完成!\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 统计:\n"
        f"  • 总群组数:{total_groups}\n"
        f"  • 成功发送:{success_count}\n"
        f"  • 发送失败:{failed_count}"
    )
    if failed_groups and len(failed_groups) <= 5:
        result_text += "\n\n❌ 失败群组:"
        for fg in failed_groups:
            result_text += f"\n  • {fg['group_name']}({fg['group_id']})"
    elif failed_groups:
        result_text += f"\n\n❌ 失败群组:{failed_count}个(过多不显示详情)"

    await bot.send(event, build_reply_message(result_text, message_id, user_id))


# ==================== /定向公告 ====================
target_broadcast_cmd = on_command("定向公告", aliases={"指定公告"}, priority=5, block=True)


@target_broadcast_cmd.handle()
async def handle_target_broadcast(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
    user_id = event.get_user_id()
    message_id = getattr(event, "message_id", None)

    if not is_admin(user_id):
        await target_broadcast_cmd.finish(build_reply_message(
            "❌ 你没有管理员权限", message_id, user_id
        ))

    group_ids, body, text_preview, img_count = _split_target_groups(args)

    if not group_ids:
        await target_broadcast_cmd.finish(build_reply_message(
            "❌ 未找到有效的群号\n"
            "用法:/定向公告 <群号1> [群号2] ... <内容>\n"
            "例如:/定向公告 123456789 987654321 测试公告",
            message_id, user_id,
        ))
    if not text_preview and img_count == 0:
        await target_broadcast_cmd.finish(build_reply_message(
            "❌ 未找到公告内容", message_id, user_id
        ))

    await bot.send(event, build_reply_message(
        f"📢 开始向 {len(group_ids)} 个指定群组发送公告...\n"
        f"目标群组:{', '.join(str(gid) for gid in group_ids)}\n"
        f"公告内容:{_preview_label(text_preview, img_count)}",
        message_id, user_id,
    ))

    announcement_msg = Message()
    announcement_msg += MessageSegment.text(f"📢【定向公告】\n{'-' * 20}\n")
    announcement_msg += body
    announcement_msg += MessageSegment.text(f"\n{'-' * 20}")

    success_count = 0
    failed_count = 0
    failed_groups: List[Dict[str, Any]] = []

    for group_id in group_ids:
        try:
            await bot.call_api("send_group_msg", group_id=group_id, message=announcement_msg)
            success_count += 1
            logger.info(f"[定向公告] 成功发送到群组 {group_id}")
            await asyncio.sleep(0.3)
        except Exception as e:
            failed_count += 1
            failed_groups.append({"group_id": group_id, "error": str(e)})
            logger.error(f"[定向公告] 发送到群组 {group_id} 失败: {e}")

    result_text = (
        f"✅ 定向公告发送完成!\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 统计:\n"
        f"  • 目标群组:{len(group_ids)}\n"
        f"  • 成功发送:{success_count}\n"
        f"  • 发送失败:{failed_count}"
    )
    if failed_groups:
        result_text += "\n\n❌ 失败群组:"
        for fg in failed_groups:
            result_text += f"\n  • {fg['group_id']}: {fg['error']}"

    await bot.send(event, build_reply_message(result_text, message_id, user_id))
