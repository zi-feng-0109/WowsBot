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

RENDER_SH        = os.environ.get("WOWS_RENDER_SH",   "/opt/wows-bot/minimap/render.sh")
REPORT_CMD       = os.environ.get("WOWS_REPORT_CMD",  "/opt/wows-bot/report/bin/wows_full_report")
ANALYZE_CMD      = os.environ.get("WOWS_ANALYZE_CMD", "/opt/wows-bot/report/bin/wows_analyze")
BASE_DIR         = os.path.expanduser(os.environ.get("WOWS_REPLAY_BASEDIR", "~/wows-bot-replay"))
MP4_TIMEOUT      = int(os.environ.get("WOWS_MP4_TIMEOUT", "600"))
PNG_TIMEOUT      = int(os.environ.get("WOWS_PNG_TIMEOUT", "300"))
ANALYZE_TIMEOUT  = int(os.environ.get("WOWS_ANALYZE_TIMEOUT", "120"))

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


# ====== /分析 指令 =============================================================

analyze_cmd = on_command("分析", priority=5, block=True)


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


@replay_handler.handle()
async def handle_replay_file(bot: Bot, event: Event, state: T_State):
    """接收 .wowsreplay 文件,下载到本地后入队。"""
    global processing

    for seg in event.get_message():
        if seg.type != "file":
            continue

        file_name = seg.data.get("name") or seg.data.get("file") or ""
        if not file_name.endswith(".wowsreplay"):
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
    try:
        if isinstance(event, GroupMessageEvent):
            info = await bot.call_api("get_group_file_url", group_id=event.group_id, file_id=file_id)
        else:
            info = await bot.call_api("get_file", file_id=file_id)
        return info.get("url")
    except Exception as e:
        logger.error(f"获取文件 URL 失败: {e}")
        raise


async def download_file(url: str, save_path: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as resp:
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
    """串行处理队列(并行只在单任务内部:MP4 + PNG 同时跑)。"""
    global processing
    processing = True

    while not task_queue.empty():
        user_id, message_id, group_id, user_dir, replay_path = await task_queue.get()

        try:
            await send_message(
                bot, user_id, group_id, message_id,
                f"🎬 开始渲染... (剩余队列：{task_queue.qsize()})"
            )

            if not os.path.exists(replay_path):
                raise RuntimeError("replay 文件不存在")

            # 并行: MP4 + 战报 PNG
            mp4_result, png_result = await asyncio.gather(
                render_mp4(replay_path, user_dir),
                render_report(replay_path, user_dir),
                return_exceptions=True,
            )

            # MP4 失败致命;PNG 失败降级
            if isinstance(mp4_result, Exception):
                raise mp4_result

            png_path = None
            png_error = None
            if isinstance(png_result, Exception):
                png_error = str(png_result)
                logger.warning(f"战报 PNG 失败 (不影响 MP4): {png_error}")
            else:
                png_path = png_result

            mp4_files = [f for f in os.listdir(user_dir) if f.endswith(".mp4")]
            if not mp4_files:
                raise RuntimeError("渲染完成但未生成 MP4")
            mp4_path = os.path.join(user_dir, mp4_files[0])

            await upload_and_notify(bot, user_id, group_id, message_id,
                                    mp4_path, png_path, png_error)

            # 开了分析就追发一条 LLM 复盘文本
            # 用 permissions 替代旧的 analyze_enabled
            scope = "group" if group_id else "private"
            ident = str(group_id) if group_id else user_id
            if permissions.feature_enabled(scope, ident, "分析"):
                json_path = os.path.join(user_dir, f"{Path(replay_path).stem}.json")
                if os.path.isfile(json_path):
                    try:
                        analysis = await run_analyze(json_path)
                        await send_message(bot, user_id, group_id, message_id,
                                           f"🧠 战后复盘:\n{analysis}")
                    except Exception as e:
                        logger.warning(f"LLM 分析失败 (不影响 MP4/PNG): {e}")
                        await send_message(bot, user_id, group_id, message_id,
                                           f"⚠️ LLM 分析失败: {e}")
                else:
                    logger.warning(f"未找到战报 JSON,跳过分析: {json_path}")

            logger.info(f"用户 {user_id} 任务完成")

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


async def render_mp4(replay_path: str, work_dir: str):
    """调用 WOWS_RENDER_SH 渲染 MP4。"""
    output_path = os.path.join(work_dir, f"{Path(replay_path).stem}.mp4")
    try:
        proc = await asyncio.create_subprocess_exec(
            RENDER_SH, replay_path, output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=MP4_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"MP4 渲染超时({MP4_TIMEOUT}s)")
        if proc.returncode != 0:
            tail = stderr.decode('utf-8', errors='ignore')[-500:] if stderr else "未知错误"
            raise RuntimeError(f"MP4 渲染失败: {tail}")
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


async def render_report(replay_path: str, work_dir: str) -> str:
    """调用 WOWS_REPORT_CMD 生成战报+复盘合并 PNG,返回 PNG 路径。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            REPORT_CMD, replay_path, work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=PNG_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"战报渲染超时({PNG_TIMEOUT}s)")
        if proc.returncode != 0:
            tail = stderr.decode('utf-8', errors='ignore')[-500:] if stderr else "未知错误"
            raise RuntimeError(f"战报渲染失败: {tail}")
        lines = stdout.decode('utf-8', errors='ignore').strip().splitlines()
        if not lines:
            raise RuntimeError("战报脚本没有输出 PNG 路径")
        png_path = lines[-1].strip()
        if not os.path.exists(png_path):
            raise RuntimeError(f"战报 PNG 不存在: {png_path}")
        logger.info(f"战报 PNG 完成: {png_path}")
        return png_path
    except FileNotFoundError:
        raise RuntimeError(f"找不到战报命令: {REPORT_CMD}")


async def upload_and_notify(bot: Bot, user_id: str, group_id: Optional[int],
                            message_id: int, mp4_path: str,
                            png_path: Optional[str] = None,
                            png_error: Optional[str] = None):
    """上传 MP4 文件,并把 PNG (或失败说明) 一起回到原消息上。"""
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

    if png_path and os.path.exists(png_path):
        text = f"✅ 渲染完成！视频已上传：{file_name}\n战报如下："
        message = MessageSegment.reply(message_id) + text + MessageSegment.image(f"file://{png_path}")
    elif png_error:
        text = f"✅ 视频已上传：{file_name}\n⚠️ 战报生成失败：{png_error}"
        message = MessageSegment.reply(message_id) + text
    else:
        text = f"✅ 渲染完成！视频已上传：{file_name}"
        message = MessageSegment.reply(message_id) + text

    try:
        if group_id:
            await bot.call_api("send_group_msg", group_id=group_id, message=message)
        else:
            await bot.call_api("send_private_msg", user_id=int(user_id), message=message)
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
