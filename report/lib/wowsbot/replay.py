"""回放文件元数据 —— 重构前有 3 份各自手写的二进制头解析。

文件头布局(WG 与 Lesta 相同):
    u32 magic | u32 blockCount | u32 meta_len | UTF-8 JSON meta
meta 里的 clientVersionFromExe 形如 "15,8,0,13187581" —— 末段是 build,前三段是版本。

约束:只做只读解析。不 import nonebot、不 subprocess、不碰 PIL。
所有函数对损坏/缺失输入返回 None 或空值,不抛异常 —— 调用方据此决定放行还是拦下。
"""
import json
import os
import re
from typing import Optional

# extracted 根目录下的版本子目录名,如 15.8.0_13187581 / 26.8.0_8861049
_VERSION_DIR_RE = re.compile(r"^\d+(?:\.\d+)+_(\d+)$")

_MAX_META_LEN = 5 * 1024 * 1024   # 超过这个视为损坏,不尝试读


def read_meta(path: str) -> Optional[dict]:
    """读回放头部的 JSON meta。读不出返回 None(不抛异常)。"""
    try:
        with open(path, "rb") as f:
            head = f.read(12)
            if len(head) < 12:
                return None
            meta_len = int.from_bytes(head[8:12], "little")
            if not 0 < meta_len <= _MAX_META_LEN:
                return None
            raw = f.read(meta_len)
        return json.loads(raw.decode("utf-8", errors="ignore"))
    except (OSError, ValueError):
        return None


def build_of(path: str) -> Optional[int]:
    """回放的 build 号。读不出返回 None。"""
    meta = read_meta(path)
    if not meta:
        return None
    parts = str(meta.get("clientVersionFromExe", "")).split(",")
    if len(parts) < 4:
        return None
    try:
        return int(parts[3].strip())
    except ValueError:
        return None


def version_of(path: str) -> str:
    """回放的版本串,如 "15.8.0"。读不出返回 "0.0.0"(沿用重构前 wows_report 的约定)。"""
    meta = read_meta(path)
    if not meta:
        return "0.0.0"
    parts = [p.strip() for p in str(meta.get("clientVersionFromExe", "")).split(",")]
    return ".".join(parts[:3]) if len(parts) >= 3 else "0.0.0"


def is_lesta(path: str) -> bool:
    """是否 Lesta(«Мир кораблей»)回放 —— 按扩展名判,与重构前一致。

    不按版本号判:Lesta 是 26.x、WG 是 15.x,但扩展名更直接且不会随版本漂移。
    """
    return str(path).endswith(".korablireplay")


def available_builds(extracted_root: str) -> set:
    """扫 extracted 根目录,收集可用的 build 号。

    只认 `<版本>_<build>/` 形式的**目录**,忽略 common / vfs_common 等 CAS 存储池。
    目录读不到时返回空集合 —— 调用方应据此放行,不能因为一时读不到就把所有回放拦死。
    """
    builds = set()
    try:
        for name in os.listdir(extracted_root):
            m = _VERSION_DIR_RE.match(name)
            if m and os.path.isdir(os.path.join(extracted_root, name)):
                builds.add(int(m.group(1)))
    except OSError:
        return set()
    return builds
