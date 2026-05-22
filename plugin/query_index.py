# plugin/query_index.py
"""query_index.py — bot 发战报的 msg_id → 索引玩家列表 持久化。

/查询 命令引用回复战报时,根据 reply.message_id 反查得到本局玩家清单
(编号 + account_id + ship_id 等),再去打 WG API。

只保留 3 小时窗口 (用户看完战报基本立刻查或不查);每次 remember() 顺手 prune。
状态文件: $WOWS_REPLAY_BASEDIR/query_index.json (跟 toggle_state.json 同目录)。
"""
import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

_STATE_FILE_NAME = "query_index.json"
_TTL_SECS = 3 * 60 * 60   # 3 小时

_lock = threading.RLock()
_state: dict = {}             # {msg_id_str: entry_dict}
_state_path: Optional[Path] = None


def init(state_dir: str) -> None:
    """显式初始化;bot 启动调一次。state_dir = WOWS_REPLAY_BASEDIR。"""
    global _state_path, _state
    with _lock:
        _state_path = Path(state_dir) / _STATE_FILE_NAME
        _state_path.parent.mkdir(parents=True, exist_ok=True)
        if _state_path.is_file():
            try:
                _state = json.loads(_state_path.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                _state = {}
        else:
            _state = {}
        _prune_locked()
        _save_locked()


def remember(msg_id: int, match_meta: dict, indexed_players: list) -> None:
    """记一条战报消息对应的索引清单。
    match_meta: {"map": str, "mode": str, "date": str}
    indexed_players: [{idx, name, account_id, ship_id, ship_zh, ...}]"""
    with _lock:
        _state[str(msg_id)] = {
            "ts": time.time(),
            "match": match_meta,
            "players": indexed_players,
        }
        _prune_locked()
        _save_locked()


def lookup(msg_id: int) -> Optional[dict]:
    """按 msg_id 找出该战报的索引清单。不查 TTL,过期 entry 也会原样返回 —
    需要 is_expired() 单独判,这样 handler 可以给出"不存在 vs 过期"两条不同文案。"""
    with _lock:
        return _state.get(str(msg_id))


def is_expired(entry: dict) -> bool:
    """entry 是否已超 TTL。entry 必须是 lookup() 的返回值。"""
    return time.time() - entry.get("ts", 0) >= _TTL_SECS


def cache_realm(msg_id: int, account_id: int, realm: str) -> None:
    """把成功查到的 realm 写回这条战报 entry,下次同 account 直接命中。
    存到 entry._realms = {"<account_id>": "asia"}。"""
    with _lock:
        entry = _state.get(str(msg_id))
        if entry is None:
            return
        realms = entry.setdefault("_realms", {})
        realms[str(account_id)] = realm
        _save_locked()


def _prune_locked() -> None:
    cutoff = time.time() - _TTL_SECS
    old = [k for k, v in _state.items() if v.get("ts", 0) < cutoff]
    for k in old:
        del _state[k]


def _save_locked() -> None:
    if _state_path is None:
        return
    tmp = _state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(_state, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, _state_path)
