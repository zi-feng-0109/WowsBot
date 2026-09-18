"""视觉常量:字体路径 + 调色板。原本长在 render_battle_report.py 里,被 6 个渲染
脚本 import —— 那个 887 行渲染器实际兼职了公共库。搬出来后它只管渲染。

**这里的值必须与重构前逐一相同**,否则渲染结果会变(验收靠渲染图 sha256 比对)。

不 import PIL:font(path, size)(ImageFont.truetype 的两行包装)留在渲染器里,
以保住"三类 Python 环境都能 import 这个包"的硬约束。

env 覆盖(WOWS_CJK_FONT / WOWS_MONO_FONT)从 paths 取,不在这里直接读 os.environ ——
paths 是全部 env 的唯一声明处。查找链本身留在这里,因为它要逐个探测文件是否存在。
"""
import os

from . import paths

# Fonts: per-OS lookup with env-var override (CJK + monospace required).
# On Linux, install fonts-noto-cjk + fonts-dejavu (or set WOWS_CJK_FONT).
_CJK_CANDIDATES = [
    paths.CJK_FONT_OVERRIDE,
    "/System/Library/Fonts/Hiragino Sans GB.ttc",                  # macOS
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",      # Debian/Ubuntu (Noto)
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",    # Fedora
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",                # WenQuanYi fallback
]
_MONO_CANDIDATES = [
    paths.MONO_FONT_OVERRIDE,
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
