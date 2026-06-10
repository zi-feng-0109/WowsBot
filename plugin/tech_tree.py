# plugin/tech_tree.py
"""科技树重建 —— 纯本地,从 ships.json 的 next_ships 字段建一棵 (国家,舰种) 树。

设计见 docs/superpowers/specs/2026-06-10-tech-tree-line-design.md。
本模块零 nonebot 依赖,可独立测试 / 给 render_line 直接调。

核心: build_tree(ships, nation_code, species_code) -> dict | None
"""
from typing import Optional


# 中文(及简写)→ ships.json 里的 nation code(GameParams 代号,实测见下)
NATION_ZH2CODE = {
    "日本": "Japan", "日": "Japan",
    "美国": "USA", "美": "USA",
    "苏联": "Russia", "苏": "Russia", "俄国": "Russia", "俄罗斯": "Russia",
    "德国": "Germany", "德": "Germany",
    "英国": "United_Kingdom", "英": "United_Kingdom",
    "法国": "France", "法": "France",
    "意大利": "Italy", "意": "Italy",
    "泛亚": "Pan_Asia",
    "欧洲": "Europe", "欧": "Europe",
    "荷兰": "Netherlands", "荷": "Netherlands",
    "泛美": "Pan_America",
    "英联邦": "Commonwealth",
    "西班牙": "Spain", "西": "Spain",
}

# 中文(及简写/英文缩写)→ ships.json 里的 species code
SPECIES_ZH2CODE = {
    "战列舰": "Battleship", "战列": "Battleship", "战舰": "Battleship", "bb": "Battleship",
    "巡洋舰": "Cruiser", "巡洋": "Cruiser", "ca": "Cruiser", "cl": "Cruiser",
    "驱逐舰": "Destroyer", "驱逐": "Destroyer", "dd": "Destroyer",
    "航母": "AirCarrier", "航空母舰": "AirCarrier", "cv": "AirCarrier",
    "潜艇": "Submarine", "潜水艇": "Submarine", "ss": "Submarine",
}

NATION_CODE2ZH = {
    "Japan": "日本", "USA": "美国", "Russia": "苏联", "Germany": "德国",
    "United_Kingdom": "英国", "France": "法国", "Italy": "意大利",
    "Pan_Asia": "泛亚", "Europe": "欧洲", "Netherlands": "荷兰",
    "Pan_America": "泛美", "Commonwealth": "英联邦", "Spain": "西班牙",
}
SPECIES_CODE2ZH = {
    "Battleship": "战列舰", "Cruiser": "巡洋舰", "Destroyer": "驱逐舰",
    "AirCarrier": "航空母舰", "Submarine": "潜艇",
}


def resolve_nation(s: str) -> Optional[str]:
    return NATION_ZH2CODE.get(s.strip())


def resolve_species(s: str) -> Optional[str]:
    return SPECIES_ZH2CODE.get(s.strip().lower()) or SPECIES_ZH2CODE.get(s.strip())


def build_tree(ships: dict, nation: str, species: str) -> Optional[dict]:
    """从 ships(ship_id->meta) 重建 (nation, species) 科技树。

    返回 dict:
      {
        'nation': code, 'species': code,
        'nation_zh':, 'species_zh':,
        'nodes': {sid: {'tier','name','icon','row','xp'}},  # xp=研发本舰经验(根为0)
        'edges': [(parent_sid, child_sid), ...],
        'roots': [sid, ...],         # 正常 1 个
        'n_rows':, 'min_tier':, 'max_tier':,
      }
    无该组合 / 无科技线时返回 None。
    """
    # 1. 候选:同国同舰种,排除金币/特种
    cand = {
        sid: s for sid, s in ships.items()
        if s.get("nation") == nation and s.get("species") == species
        and not s.get("is_premium") and not s.get("is_special")
    }
    if not cand:
        return None

    # 2. 建边(只保留指向候选内的后继);记录研发 xp(next_ships 的值)
    children = {sid: [] for sid in cand}
    indeg = {sid: 0 for sid in cand}
    xp_of = {sid: 0 for sid in cand}
    for sid, s in cand.items():
        for j, xp in (s.get("next_ships") or {}).items():
            j = str(j)
            if j in cand:
                children[sid].append(j)
                indeg[j] += 1
                xp_of[j] = int(xp) if xp else 0

    # 3. 丢孤立节点(入度 0 且无后继):金币/特种漏标、或不在研发树上的散船
    alive = {sid for sid in cand if indeg[sid] > 0 or children[sid]}
    if not alive:
        return None
    children = {sid: [c for c in children[sid] if c in alive] for sid in alive}
    indeg = {sid: 0 for sid in alive}
    for sid in alive:
        for c in children[sid]:
            indeg[c] += 1

    # 4. 找根:入度 0(且有后继,因为孤立已丢)
    roots = sorted((sid for sid in alive if indeg[sid] == 0),
                   key=lambda x: cand[x].get("tier", 0))
    if not roots:
        return None

    # 5. 子树深度(最长后继链),用于让最长线走主干(同一行)
    depth = {}

    def calc_depth(sid):
        if sid in depth:
            return depth[sid]
        kids = children[sid]
        depth[sid] = 1 + max((calc_depth(c) for c in kids), default=0)
        return depth[sid]

    for sid in alive:
        calc_depth(sid)

    # 6. 分行:最长子树续在父行,其余分叉另起新行(主干直,支线下沉)
    rows = {}
    next_row = [0]

    def assign(sid, row):
        rows[sid] = row
        kids = sorted(children[sid], key=lambda c: (-depth[c], cand[c].get("tier", 0)))
        parent_tier = cand[sid].get("tier", 0)
        placed = False  # 是否已有一个后继续在本行
        for c in kids:
            # 只有 tier 严格更大(=不同列)的后继才能续在父行,否则同 tier 会同列重叠
            if not placed and cand[c].get("tier", 0) > parent_tier:
                assign(c, row)
                placed = True
            else:
                next_row[0] += 1
                assign(c, next_row[0])

    for r in roots:
        if rows:  # 多根时(异常)每根另起行
            next_row[0] += 1
            assign(r, next_row[0])
        else:
            assign(r, 0)

    # 7. 组装输出
    nodes = {}
    tiers = []
    for sid in alive:
        s = cand[sid]
        t = s.get("tier", 0)
        tiers.append(t)
        nodes[sid] = {
            "tier": t,
            "name": s.get("name_zh") or s.get("name_en") or sid,
            "icon": s.get("icon") or s.get("index"),
            "row": rows[sid],
            "xp": xp_of[sid],
        }
    edges = [(sid, c) for sid in alive for c in children[sid]]

    return {
        "nation": nation,
        "species": species,
        "nation_zh": NATION_CODE2ZH.get(nation, nation),
        "species_zh": SPECIES_CODE2ZH.get(species, species),
        "nodes": nodes,
        "edges": edges,
        "roots": roots,
        "n_rows": next_row[0] + 1,
        "min_tier": min(tiers),
        "max_tier": max(tiers),
    }
