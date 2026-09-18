"""结算数组按字段名取值。

replayshark 的 results_info 是一个扁平数组,字段名到下标的映射在 constants.json 的
CLIENT_PUBLIC_RESULTS_INDICES 里。原本长在 render_battle_report.py 里。

有 I/O 和模块级缓存,所以跟纯函数的 text.py 分开。索引表加载失败时 result_field
一律返回 default —— 缺 constants.json 应退化成"少几列",不该让渲染整体失败。
"""
import json
import sys

from . import paths

_RESULT_INDICES: dict = {}


def load_result_indices(path: str = None):
    """按需加载 字段名 -> 下标 映射。默认路径来自 paths.CONSTANTS_JSON。"""
    global _RESULT_INDICES
    if _RESULT_INDICES:
        return
    try:
        c = json.load(open(path or paths.CONSTANTS_JSON))
        _RESULT_INDICES = {k: int(v) for k, v in c.get("CLIENT_PUBLIC_RESULTS_INDICES", {}).items()}
    except Exception as e:
        print(f"warn: failed to load constants: {e}", file=sys.stderr)


def result_field(arr, name: str, default=None):
    """Look up a named field from a raw results_info array."""
    load_result_indices()
    idx = _RESULT_INDICES.get(name)
    if idx is None or arr is None or not isinstance(arr, list) or idx >= len(arr):
        return default
    return arr[idx]
