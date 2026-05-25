# plugin/render_mode.py
"""render_mode.py — 渲染并发模式 (并行/串行) 运行时切换。

为什么要这个:
  MP4 (minimap_renderer --cpu) 单跑就 2-4 GB + 1 核满,战报 (replayshark
  + PIL) 再叠 700 MB-1.5 GB。两者 asyncio.gather 并行时峰值能到 ~8 GB,
  在 4 核 8G VM 上能把 bot 主线程憋死。串行起来峰值腰斩,只多 5-15s。

  默认并行 (保留历史行为),小机器上超管随时 /sa 并行 关 切串行。

状态文件: $WOWS_REPLAY_BASEDIR/render_mode.json,跟 query_index / toggle_state 同位置。
"""
import json
import os
import threading
from pathlib import Path
from typing import Optional

_STATE_FILE_NAME = "render_mode.json"

_lock = threading.RLock()
_parallel: bool = True            # 默认并行
_state_path: Optional[Path] = None


def init(state_dir: str) -> None:
    """bot 启动调一次。state_dir = WOWS_REPLAY_BASEDIR。"""
    global _state_path, _parallel
    with _lock:
        _state_path = Path(state_dir) / _STATE_FILE_NAME
        _state_path.parent.mkdir(parents=True, exist_ok=True)
        if _state_path.is_file():
            try:
                data = json.loads(_state_path.read_text("utf-8"))
                _parallel = bool(data.get("parallel", True))
            except (json.JSONDecodeError, OSError):
                _parallel = True


def is_parallel() -> bool:
    with _lock:
        return _parallel


def set_parallel(value: bool) -> None:
    global _parallel
    with _lock:
        _parallel = bool(value)
        _save_locked()


def _save_locked() -> None:
    if _state_path is None:
        return
    tmp = _state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"parallel": _parallel}, ensure_ascii=False, indent=2),
                   "utf-8")
    os.replace(tmp, _state_path)
