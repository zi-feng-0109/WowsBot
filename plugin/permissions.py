# plugin/permissions.py
"""权限模型 + 群级开关状态持久化。

状态结构 (toggle_state.json):
    {
      "version": 1,
      "global_blacklist": [],
      "groups": {"<group_id>": {"视频": true, "战报": true, ...}},
      "private": {"<user_id>": {"分析": true, ...}}
    }

唯一来源原则:bot 任何地方查/改开关都过本模块的函数,不要直接读 state 字典。
"""
import json
import os
import threading
from pathlib import Path
from typing import Tuple

from nonebot import get_driver
from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

FEATURES = ["视频", "战报", "复盘", "分析", "战犯", "聊天"]
# 每个 feature 的默认开启状态(用户没主动设过的话采用这里的值)。
# 分析 默认关:DeepSeek 调用要 API key + 算钱,群主自己评估再开。
# 战犯 默认关:噪声大、对录制者非 CV 时数据受限,需要群主手动开启。
# 聊天 默认开(v2 起):功能已稳定,默认给所有群。想关的群 `/聊天 关` 即可。
DEFAULT_ENABLED = {
    "视频": True,
    "战报": True,
    "复盘": True,
    "分析": False,
    "战犯": False,
    "聊天": True,
}
# v1 -> v2:聊天默认从关改为开。升级时清掉各作用域已存的「聊天」覆盖值,让
# 已有的群/私聊也回落到新默认(开),而不是停留在当初的默认关状态。
_STATE_VERSION = 2
_CHAT_DEFAULT_ON_VERSION = 2
_LEGACY_FILE_NAME = "analyze_toggle.json"
_STATE_FILE_NAME = "toggle_state.json"

_lock = threading.RLock()
_state: dict = {}
_loaded = False
_state_path: Path | None = None


def _empty_state() -> dict:
    return {
        "version": _STATE_VERSION,
        "global_blacklist": [],
        "groups": {},
        "private": {},
    }


def init(state_dir: str) -> None:
    """显式初始化:bot 启动时调一次。state_dir 通常 = WOWS_REPLAY_BASEDIR。
    幂等;重复调只会重新读盘。会自动迁移旧的 analyze_toggle.json。"""
    global _state_path, _state, _loaded
    with _lock:
        _state_path = Path(state_dir) / _STATE_FILE_NAME
        _state_path.parent.mkdir(parents=True, exist_ok=True)
        migrate_legacy(state_dir)   # 幂等;已迁移过会跳过
        _load()
        _loaded = True


def _load() -> None:
    """从盘上读 state;不存在或损坏时用空 state。需在 _lock 内调用。"""
    global _state
    assert _state_path is not None, "permissions.init() not called"
    if _state_path.is_file():
        try:
            with open(_state_path, "r", encoding="utf-8") as f:
                _state = json.load(f)
        except (json.JSONDecodeError, OSError):
            _state = _empty_state()
    else:
        _state = _empty_state()
    # 兜底:旧文件可能字段缺失
    for k in ("global_blacklist", "groups", "private"):
        _state.setdefault(k, [] if k == "global_blacklist" else {})
    _state.setdefault("version", _STATE_VERSION)
    _upgrade_chat_default()


def _upgrade_chat_default() -> None:
    """v1 -> v2 一次性迁移:聊天默认从关改为开。需在 _lock 内调用。

    只改「聊天」这一个 key:把各群/私聊已存的覆盖值删掉,让它们回落到新的
    DEFAULT_ENABLED(开)。删而不是置 True,是为了让这些作用域继续跟随默认值 ——
    以后若再调默认,它们同样自动跟上;群主之后 `/聊天 关` 会重新写入覆盖值。
    其他 feature 的覆盖值一律不动。落盘由本函数完成,升级只发生一次(靠 version)。
    """
    if int(_state.get("version", 1)) >= _CHAT_DEFAULT_ON_VERSION:
        return
    for bucket in ("groups", "private"):
        for overrides in _state.get(bucket, {}).values():
            if isinstance(overrides, dict):
                overrides.pop("聊天", None)
    _state["version"] = _STATE_VERSION
    _save()


def _save() -> None:
    """原子写:tmp + rename。需在 _lock 内调用。"""
    assert _state_path is not None
    tmp = _state_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _state_path)


def migrate_legacy(state_dir: str | Path) -> bool:
    """从 analyze_toggle.json 迁移到 toggle_state.json。
    幂等:目标文件已存在或源文件不存在时返回 False,不动手。
    成功迁移返回 True,旧文件改名 .bak 留底。"""
    legacy = Path(state_dir) / _LEGACY_FILE_NAME
    new = Path(state_dir) / _STATE_FILE_NAME
    if new.exists() or not legacy.is_file():
        return False
    try:
        old = json.loads(legacy.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    state = _empty_state()
    for key, val in old.items():
        if ":" not in key:
            continue
        bucket_marker, ident = key.split(":", 1)
        if bucket_marker == "g":
            target = "groups"
        elif bucket_marker == "u":
            target = "private"
        else:
            continue
        state[target].setdefault(ident, {})["分析"] = bool(val)
    new.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    legacy.rename(legacy.parent / (legacy.name + ".bak"))
    return True


def scope_of(event: MessageEvent) -> Tuple[str, str]:
    """根据 event 返回 (scope, ident) — 群消息 -> ('group', group_id);否则 ('private', user_id)。"""
    if isinstance(event, GroupMessageEvent):
        return ("group", str(event.group_id))
    return ("private", str(event.user_id))


def _bucket_name(scope: str) -> str:
    if scope == "group":
        return "groups"
    if scope == "private":
        return "private"
    raise ValueError(f"unknown scope: {scope}")


def feature_enabled(scope: str, ident: str, feature: str) -> bool:
    """权威开关查询:超管黑名单优先,然后查作用域开关,缺失走 DEFAULT_ENABLED。"""
    assert feature in FEATURES, f"unknown feature: {feature}"
    with _lock:
        if feature in _state["global_blacklist"]:
            return False
        bucket = _state[_bucket_name(scope)]
        default = DEFAULT_ENABLED.get(feature, True)
        return bucket.get(str(ident), {}).get(feature, default)


def set_feature(scope: str, ident: str, feature: str, value: bool) -> None:
    """改作用域开关并落盘。不检查权限 — 调用方先用 can_toggle 鉴权。"""
    assert feature in FEATURES, f"unknown feature: {feature}"
    with _lock:
        bucket = _state[_bucket_name(scope)]
        bucket.setdefault(str(ident), {})[feature] = bool(value)
        _save()


def is_super_admin(user_id: str | int) -> bool:
    """对照 NoneBot superusers 配置;每次现读,不缓存(便于热改 .env)。"""
    return str(user_id) in get_driver().config.superusers


def can_toggle(event: MessageEvent, scope_ident: str) -> bool:
    """谁能改某作用域开关:超管全能;群管/群主能改本群;私聊只能改自己。"""
    if is_super_admin(event.user_id):
        return True
    if isinstance(event, GroupMessageEvent):
        return event.sender.role in ("owner", "admin")
    return scope_ident == str(event.user_id)


def super_admin_ban(feature: str) -> None:
    """超管全局禁用 — 任何作用域都开不了。"""
    assert feature in FEATURES
    with _lock:
        bl = set(_state["global_blacklist"])
        bl.add(feature)
        _state["global_blacklist"] = sorted(bl)
        _save()


def super_admin_unban(feature: str) -> None:
    assert feature in FEATURES
    with _lock:
        bl = set(_state["global_blacklist"])
        bl.discard(feature)
        _state["global_blacklist"] = sorted(bl)
        _save()


def global_blacklist() -> list[str]:
    """只读快照,UI/菜单用。"""
    with _lock:
        return list(_state["global_blacklist"])


def snapshot() -> dict:
    """整份状态的只读深拷贝 — 给 render_menu / /sa stats 用。"""
    with _lock:
        return json.loads(json.dumps(_state))
