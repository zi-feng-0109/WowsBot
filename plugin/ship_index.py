# plugin/ship_index.py
"""ship_index.py — 战舰名 → ship 数据 的查找/消歧 (只读)。

`/船 <中文名>` 命令用。bot 启动 init(ships_json_path) 一次 json.load 进缓存
(同 query_index 模式),运行时不重建、不打外部 API。

ships.json 由 tools/build_ships_json.py 预构建 (打版本时),结构:
  {"version", "ships": {ship_id: {...}}, "search_index": {by_zh, by_en, aliases}}

find() 分级短路匹配:精确 (标准中文名 / 英文名 / WG 梗名别名) → 去空格归一
→ substring 部分匹配 → difflib 模糊兜底。
"""
import difflib
import json
from pathlib import Path
from typing import Optional

_data: dict = {}
_ships: dict = {}            # ship_id_str → ship dict
_by_zh: dict = {}           # 标准中文名 → ship_id_str
_by_en: dict = {}           # 英文名 lower → ship_id_str
_aliases: dict = {}         # WG 梗名 → ship_id_str
_norm_zh: dict = {}         # 去空格归一中文名 → ship_id_str
_loaded = False

# 部分匹配 / 模糊 返回的候选上限
MAX_CANDIDATES = 8


def _norm(s: str) -> str:
    """归一:去空格、转小写。中文不受 lower 影响,英文大小写无关。"""
    return "".join((s or "").split()).lower()


def init(ships_json_path: str) -> None:
    """bot 启动调一次。ships.json 缺失/损坏时退化成空索引 (find 永远 none)。"""
    global _data, _ships, _by_zh, _by_en, _aliases, _norm_zh, _loaded
    _loaded = False
    try:
        _data = json.loads(Path(ships_json_path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        _data = {}
        return
    _ships = _data.get("ships") or {}
    si = _data.get("search_index") or {}
    _by_zh = si.get("by_zh") or {}
    _by_en = {k.lower(): v for k, v in (si.get("by_en") or {}).items()}
    _aliases = si.get("aliases") or {}
    # 归一表:标准中文名 + 别名 + 英文名 都塞进去,key 冲突时标准名优先
    _norm_zh = {}
    for src in (_by_en, _aliases, _by_zh):  # 后写的覆盖,_by_zh 最后 → 优先
        for name, sid in src.items():
            _norm_zh[_norm(name)] = sid
    _loaded = True


def is_ready() -> bool:
    return _loaded and bool(_ships)


def get(ship_id: str) -> Optional[dict]:
    return _ships.get(str(ship_id))


def version() -> str:
    return _data.get("version", "?")


def find(query: str) -> tuple[str, list]:
    """查船。返回 (kind, payload):
      ('exact', [ship_dict])         唯一命中 → 直接渲染
      ('multi', [ship_dict, ...])    多个候选 (≤MAX_CANDIDATES) → 让用户挑
      ('none',  [name_suggestion..]) 没命中 → 给 difflib 建议名 (可能空)
    """
    if not is_ready():
        return ("none", [])
    q = (query or "").strip()
    if not q:
        return ("none", [])
    qn = _norm(q)

    # 1) 精确:标准中文名 → 英文名 → 别名
    for table in (_by_zh, _aliases):
        if q in table:
            return ("exact", [_ships[table[q]]])
    if qn in _by_en:
        return ("exact", [_ships[_by_en[qn]]])
    # 2) 归一精确 (去空格/大小写)
    if qn in _norm_zh:
        return ("exact", [_ships[_norm_zh[qn]]])

    # 3) substring 部分匹配 (中文名 / 别名 / 英文名 包含 query)
    hit_ids = []
    seen = set()
    for name, sid in {**_by_en, **_aliases, **_by_zh}.items():
        if sid in seen:
            continue
        if qn and qn in _norm(name):
            hit_ids.append(sid)
            seen.add(sid)
    # 去重到 ship_id 维度 (同船多名只算一次)
    uniq = []
    seen = set()
    for sid in hit_ids:
        if sid not in seen:
            uniq.append(sid)
            seen.add(sid)
    if len(uniq) == 1:
        return ("exact", [_ships[uniq[0]]])
    if 2 <= len(uniq) <= MAX_CANDIDATES:
        return ("multi", [_ships[s] for s in uniq])
    if len(uniq) > MAX_CANDIDATES:
        # 太多 → 当作没精确命中,给前几个名字当建议
        return ("none", [_ships[s]["name_zh"] for s in uniq[:MAX_CANDIDATES]])

    # 4) difflib 模糊兜底 (按标准中文名 + 别名)
    pool = list(_by_zh.keys()) + list(_aliases.keys())
    close = difflib.get_close_matches(q, pool, n=MAX_CANDIDATES, cutoff=0.6)
    return ("none", close)
