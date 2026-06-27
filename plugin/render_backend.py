# plugin/render_backend.py
"""render_backend.py — MP4 渲染 backend (cpu / gpu) 运行时切换。

为什么需要:
  - CPU(--cpu + 默认 AV1 软编):稳定、画质好(~7 MB / 20 分钟)、不依赖 NVIDIA
    driver,但慢(2-3 分钟一份 replay)。
  - GPU(NVENC H.264 + --max-size-mib 10):快(20 秒一份)、画质 OK,但依赖
    NVIDIA driver + VK_DRIVER_FILES 指向 nvidia_icd.json。

  默认 CPU(稳)。超管随时 /渲染模式 gpu|cpu 切。切换只影响下一次新 spawn 的
  渲染 subprocess,正在跑的不受影响(已 spawn 出去的进程带着当时的 env)。

状态文件: $WOWS_REPLAY_BASEDIR/render_backend.json,跟 render_mode /
query_index / toggle_state 同位置。
"""
import json
import os
import threading
from pathlib import Path
from typing import Optional

_STATE_FILE_NAME = "render_backend.json"
_VALID = ("cpu", "gpu")

_lock = threading.RLock()
_backend: str = "cpu"          # 默认 CPU
_state_path: Optional[Path] = None


def init(state_dir: str) -> None:
    """bot 启动调一次。state_dir = WOWS_REPLAY_BASEDIR。"""
    global _state_path, _backend
    with _lock:
        _state_path = Path(state_dir) / _STATE_FILE_NAME
        _state_path.parent.mkdir(parents=True, exist_ok=True)
        if _state_path.is_file():
            try:
                data = json.loads(_state_path.read_text("utf-8"))
                v = str(data.get("backend", "cpu")).lower()
                if v in _VALID:
                    _backend = v
            except (json.JSONDecodeError, OSError):
                _backend = "cpu"


def get_backend() -> str:
    """返回 'cpu' 或 'gpu'。"""
    with _lock:
        return _backend


def set_backend(value: str) -> str:
    """设新 backend,返回最终值(校验后)。无效值抛 ValueError。"""
    global _backend
    v = str(value).lower()
    if v not in _VALID:
        raise ValueError(f"backend 只能是 'cpu' 或 'gpu',收到 {value!r}")
    with _lock:
        _backend = v
        _save_locked()
        return _backend


def _save_locked() -> None:
    if _state_path is None:
        return
    tmp = _state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"backend": _backend}, ensure_ascii=False, indent=2),
                   "utf-8")
    os.replace(tmp, _state_path)
