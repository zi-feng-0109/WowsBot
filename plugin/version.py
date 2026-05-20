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
