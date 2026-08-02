# plugin/version.py
"""Bot 版本信息 — render_menu.py / 战报 footer / 未来的 /version 命令共用。

版本字符串来源(优先级从高到低):
  1. WOWS_BOT_VERSION 环境变量(由 NoneBot 启动时从 .env 注入 os.environ)
  2. _DEFAULT_VERSION 兜底常量(本文件里的最新发布号)

为什么走 env: 服务器上发版只改 .env 一行 + 重启 bot 即可,
不必每次都改代码 → cp → push。__version__ 还会暴露给以前依赖它的
代码(若有),取值跟 version_str() 一致。

战报/复盘 PNG 的 footer 不读这个文件,而是直接读 WOWS_BOT_VERSION env
(见 report/bin/render_battle_report.py / render_damage_chart.py),这样
subprocess 渲染器跟 NoneBot 进程共用同一个变量,不会发生菜单 v1.0.1 但
战报底栏 v1.0.0 的情况。
"""
import os
import subprocess
from pathlib import Path

_DEFAULT_VERSION = "1.4.0"

__version__ = os.environ.get("WOWS_BOT_VERSION") or _DEFAULT_VERSION

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
    """格式化版本字符串: 'v1.0.1+abc1234' 或 'v1.0.1'(无 git 时)。"""
    h = git_short_hash()
    return f"v{__version__}+{h}" if h else f"v{__version__}"
