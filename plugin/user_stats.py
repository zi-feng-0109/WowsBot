# plugin/user_stats.py
"""user_stats.py — bot 用户使用统计 持久化模块。

定义"用户" = **触发过 bot 非菜单功能** 的 QQ 号。/菜单 / /help / @bot 空消息
不计;查询/船舶卡片/装甲/科技线/replay 渲染/猜船开局/猜船猜中 都计。
猜船仅按"完整回合"计:开局算发起者一次,猜中者(若 != 发起者)算一次,
中间互动不计。

状态文件: $WOWS_REPLAY_BASEDIR/user_stats.json(跟 query_index.json 同目录)。
schema:
  {
    "version": 1,
    "users": {
      "<user_id>": {
        "first_seen_ts": 1718000000.0,
        "last_seen_ts":  1718999999.0,
        "total": 42,
        "by_feature": {"ship": 10, "query": 5, "replay": 27, ...}
      }, ...
    }
  }

线程/进程安全:仅在 asyncio 事件循环线程操作(NoneBot 单线程),无锁。
写盘是 write-then-rename,跟 query_index 一致。
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Optional

_STATE_FILE_NAME = "user_stats.json"

_state_path: Optional[Path] = None
_state: dict = {"version": 1, "users": {}}


def init(base_dir: str) -> None:
    """启动时调一次。base_dir 跟 query_index / permissions 同一目录。
    顺手把历史误记的超管条目清掉(规则改前漏记的)。"""
    global _state_path, _state
    _state_path = Path(base_dir) / _STATE_FILE_NAME
    _state_path.parent.mkdir(parents=True, exist_ok=True)
    if _state_path.is_file():
        try:
            _state = json.loads(_state_path.read_text("utf-8"))
            if not isinstance(_state, dict) or "users" not in _state:
                _state = {"version": 1, "users": {}}
        except Exception:
            _state = {"version": 1, "users": {}}
    else:
        _state = {"version": 1, "users": {}}
    _prune_superusers()


def _prune_superusers() -> None:
    """清掉当前 SUPERUSERS 名单里的用户条目(历史误记的)。"""
    try:
        from . import permissions
    except Exception:
        return
    users = _state.get("users") or {}
    removed = [uid for uid in list(users) if permissions.is_super_admin(uid)]
    if not removed:
        return
    for uid in removed:
        users.pop(uid, None)
    _save()


def _save() -> None:
    """原子写盘:先写 .tmp 再 rename。"""
    if _state_path is None:
        return
    tmp = _state_path.with_suffix(_state_path.suffix + ".tmp")
    tmp.write_text(json.dumps(_state, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(_state_path)


def record(user_id, feature: str) -> None:
    """记一次。user_id 强转 str(QQ 号),feature 任意 tag(ship/query/line/replay/guess_start/guess_win)。
    超管 (SUPERUSERS) 被排除 — 调试/巡检 会污染"真实用户"指标。"""
    if _state_path is None:        # init 没跑过(测试 / 早期启动)直接吞掉,不抛
        return
    uid = str(user_id)
    if not uid or not feature:
        return
    # 排除超管 (晚 import 避循环依赖)
    try:
        from . import permissions
        if permissions.is_super_admin(uid):
            return
    except Exception:
        pass
    now = time.time()
    u = _state["users"].setdefault(uid, {
        "first_seen_ts": now,
        "last_seen_ts": now,
        "total": 0,
        "by_feature": {},
    })
    u["last_seen_ts"] = now
    u["total"] = int(u.get("total", 0)) + 1
    bf = u.setdefault("by_feature", {})
    bf[feature] = int(bf.get(feature, 0)) + 1
    _save()


def snapshot(top_n: int = 5) -> dict:
    """返回当前快照:总用户数 / 总调用次数 / Top-N 用户列表 (按 total 降序)。

    返回:
      {
        "total_users": int,
        "total_calls": int,
        "top": [
          {"user_id": "12345", "total": 42, "by_feature": {...},
           "first_seen_ts": ..., "last_seen_ts": ...},
          ...
        ],
      }
    """
    users = _state.get("users") or {}
    total_users = len(users)
    total_calls = sum(int(u.get("total", 0)) for u in users.values())
    ranked = sorted(users.items(), key=lambda kv: -int(kv[1].get("total", 0)))
    top = [{"user_id": uid, **{k: v for k, v in u.items()}} for uid, u in ranked[:top_n]]
    return {
        "total_users": total_users,
        "total_calls": total_calls,
        "top": top,
    }


def state_path() -> Optional[Path]:
    """暴露状态文件路径(给运维 / 诊断用)。"""
    return _state_path
