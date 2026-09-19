# plugin/wg_update_cmd.py
"""/更新wg版本 —— 超管指令:把 PC 侧上传到暂存区的新版本游戏数据搬进生产。

搭配 `tools/update_wg.bat`(PC 侧)使用。日常流程只有三步:
更新游戏 → 双击那个 bat → 在 QQ 里发本指令。

**逻辑不在这里**,全在 `plugin/wg_update.py`。分开的原因:`on_command(...)` 在模块顶层
执行,带 matcher 的文件没法被测试直接 import(现有 `tests/test_permissions.py` 能 import
`permissions.py`,正是因为那个模块没有 matcher)。所以逻辑模块不 import nonebot、
外部动作全经注入的 runner —— 21 个用例不需要真服务器、真 294MB 数据就能跑。

本文件只做三件事:鉴权、把参数传进去、把汇报发出来。**不执行任何重启** ——
`plugin/*.py` 有变动时逻辑模块会在汇报里提示「需重启」,由人决定什么时候重启。
"""
import asyncio
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Event, Message
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from . import permissions
from . import wg_update

__plugin_meta__ = PluginMetadata(
    name="WG 版本更新",
    description="超管把 PC 侧上传的新版本游戏数据搬进生产并刷新派生数据",
    usage=("/更新wg版本                自动处理暂存区里唯一的待处理版本\n"
           "/更新wg版本 <ver>_<build>   暂存区有多个待处理版本时显式指定"),
    type="application",
    supported_adapters={"~onebot.v11"},
)

update_cmd = on_command("更新wg版本", priority=5, block=True)


@update_cmd.handle()
async def _handle(event: Event, args: Message = CommandArg()):
    if not permissions.is_super_admin(event.get_user_id()):
        await update_cmd.finish("权限不足:本命令只允许超管使用")

    version = args.extract_plain_text().strip() or None
    await update_cmd.send("开始处理版本更新…")

    # 整条流程是阻塞的(搬目录、跑 cargo 外的几个子进程),丢到线程里免得卡住事件循环。
    # 服务器侧其实很快:incoming 与 extracted 同文件系统,搬运是 rename;
    # builds-dump 几秒;图标已存在的会跳过。通常一分钟内结束。
    lines, ok = await asyncio.to_thread(
        wg_update.run_update,
        incoming_root=Path(wg_update.paths.INCOMING_ROOT),
        extracted_root=Path(wg_update.paths.EXTRACTED_ROOT),
        repo_dir=Path(wg_update.BOT_REPO_DIR),
        # 本文件运行时就在 NoneBot 的 plugins 目录里,所以「同步 plugin/*.py」那步
        # 不需要任何配置项(announcement.py 用的同一个技巧)。
        plugins_dir=Path(__file__).parent,
        runner=wg_update.SubprocessRunner(),
        version=version,
    )

    head = "✅ 更新完成" if ok else "❌ 更新未完成"
    await update_cmd.finish(head + "\n" + "\n".join(lines))
