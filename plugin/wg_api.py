# plugin/wg_api.py
"""wg_api.py — WoWs 玩家生涯 stats 查询,/查询 命令用。

走游戏自家 vortex 后端 (各 realm 都是),无需 application_id,
4 服全覆盖 (CN/Asia/EU/NA;RU/Lesta 不支持)。

设计思路:
- 不要 application_id (vortex 是游戏客户端自己用的,无 auth)
- 多 realm 并发探,首个返回有效 stats 的胜出
- realm 缓存到 query_index 的玩家条目里 (下次同玩家直接命中)
- 字段名按 vortex 而非 WG public API (battles_count / survived 等)

env (可选,无则按下面默认):
  WOWS_REALMS  逗号分隔,按此顺序优先尝试。默认 "asia,cn,eu,na"。
"""
import asyncio
import os
import aiohttp
from typing import Optional
from nonebot.log import logger

# realm → vortex host
_VORTEX_HOSTS = {
    "cn":   "vortex.wowsgame.cn",
    "asia": "vortex.worldofwarships.asia",
    "eu":   "vortex.worldofwarships.eu",
    "na":   "vortex.worldofwarships.com",
}

# CN 服 account_id 通常 ≥ 5B (民间经验);WG 国际服在 1-4B 之间。
# 仅用作首选 realm 排序,猜错也只是多打几个请求,不致命。
_CN_ID_THRESHOLD = 5_000_000_000


def is_configured() -> bool:
    """vortex 无需 application_id,永远 True;保留接口给 handler 用。"""
    return True


def _realm_priority(account_id: int) -> list[str]:
    """给定 account_id 返回最优 realm 探测顺序。"""
    env_order = os.environ.get("WOWS_REALMS", "").strip()
    if env_order:
        order = [r.strip().lower() for r in env_order.split(",") if r.strip()]
    elif account_id >= _CN_ID_THRESHOLD:
        order = ["cn", "asia", "eu", "na"]
    else:
        order = ["asia", "cn", "eu", "na"]
    # 过滤掉未知 realm,保持顺序去重
    seen = set()
    out = []
    for r in order:
        if r in _VORTEX_HOSTS and r not in seen:
            out.append(r)
            seen.add(r)
    return out


async def _fetch_one(session: aiohttp.ClientSession, realm: str,
                      account_id: int, ship_id: int) -> tuple[str, Optional[dict]]:
    """打一个 realm。返回 (realm, pvp_dict | None)。无数据 / 网络错误都返 None。"""
    host = _VORTEX_HOSTS[realm]
    url = (f"https://{host}/api/accounts/{account_id}/ships/{ship_id}/pvp/")
    try:
        async with session.get(url) as r:
            data = await r.json()
    except Exception as e:
        logger.debug(f"vortex {realm} {account_id} failed: {e}")
        return realm, None

    if data.get("status") != "ok":
        return realm, None
    per_acc = (data.get("data") or {}).get(str(account_id))
    if not per_acc:
        return realm, None
    stats = (per_acc.get("statistics") or {}).get(str(ship_id))
    if not stats:
        return realm, None
    pvp = stats.get("pvp")
    if not pvp or int(pvp.get("battles_count") or 0) == 0:
        return realm, None
    return realm, pvp


async def fetch_ship_stats(account_id: int, ship_id: int,
                           preferred_realm: Optional[str] = None,
                           timeout: float = 6.0) -> tuple[Optional[dict], Optional[str]]:
    """查该账号该船 pvp 生涯 stats。

    preferred_realm: 上次成功的 realm,直接命中省探测;不传则按 id 范围猜。
    返回 (pvp_dict | None, hit_realm | None)。
    """
    # 优先级: preferred_realm 顶着 → id-range 推荐 → 其余兜底
    primary = preferred_realm.lower() if preferred_realm else None
    rest = [r for r in _realm_priority(account_id) if r != primary]
    order = ([primary] if primary in _VORTEX_HOSTS else []) + rest

    # 串行先打首选 (大概率命中);失败再并发探剩下的 (省时)
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout),
        headers={"User-Agent": "EssexBot/0.5 (WoWs stats)"},
    ) as s:
        if order:
            r, pvp = await _fetch_one(s, order[0], account_id, ship_id)
            if pvp:
                return pvp, r
        tail = order[1:]
        if not tail:
            return None, None
        # 并发探剩下的,首个非 None 胜出
        tasks = [asyncio.create_task(_fetch_one(s, r, account_id, ship_id))
                 for r in tail]
        try:
            for coro in asyncio.as_completed(tasks):
                r, pvp = await coro
                if pvp:
                    # 取消其它仍在跑的 task
                    for t in tasks:
                        if not t.done():
                            t.cancel()
                    return pvp, r
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
        return None, None


def format_stats_summary(player: dict, pvp: Optional[dict],
                          realm: Optional[str] = None) -> str:
    """纯文字 fallback,PNG 渲染走 render_query.py。"""
    name = player.get("name", "?")
    idx = player.get("idx", "?")
    ship_zh = player.get("ship_zh") or player.get("ship_name", "?")
    lvl = player.get("ship_level", "?")
    species = player.get("species_zh", "")
    tg = player.get("this_game", {}) or {}
    this_dmg = int(tg.get("dmg", 0) or 0)
    this_frags = tg.get("frags", 0) or 0
    alive_str = "存活" if tg.get("alive") else "阵亡"
    tl = tg.get("time_lived_secs")
    lived_str = ""
    if isinstance(tl, (int, float)):
        s = int(tl)
        lived_str = f" · {s // 60:02d}:{s % 60:02d}"

    head = (f"#{idx} {name}\n"
            f"  {ship_zh}  L{lvl} {species}\n"
            f"本局: 击伤 {this_dmg:,} · 击杀 {this_frags} · {alive_str}{lived_str}"
            .replace(",", " "))

    if not pvp:
        return head + ("\n生涯: CN/Asia/EU/NA 均无该船 pvp 数据"
                       " (可能:玩家隐藏隐私 / 未玩过 / vortex 暂不可用)")

    n = int(pvp.get("battles_count") or 0)
    if n == 0:
        return head + "\n生涯: 该船 0 场"

    wins  = int(pvp.get("wins") or 0)
    surv  = int(pvp.get("survived") or 0)
    dmg   = int(pvp.get("damage_dealt") or 0)
    frags = int(pvp.get("frags") or 0)
    win_rate  = wins / n * 100
    surv_rate = surv / n * 100
    avg_dmg   = dmg / n
    avg_frags = frags / n
    kdr = (frags / (n - surv)) if n > surv else float("inf")
    kdr_str = f"{kdr:.2f}" if kdr != float("inf") else "∞"

    cmp_line = ""
    if avg_dmg > 0:
        pct = (this_dmg / avg_dmg - 1) * 100
        sign = "+" if pct >= 0 else ""
        cmp_line = f"\n对比: 本局击伤是生涯均值的 {sign}{pct:.0f}%"

    realm_tag = f" [{realm}服]" if realm else ""
    career = (
        f"\n生涯{realm_tag}: {n} 场 · 胜率 {win_rate:.1f}% · 生存率 {surv_rate:.1f}%\n"
        f"      均伤 {avg_dmg:,.0f} · 均击杀 {avg_frags:.2f} · KDR {kdr_str}"
        .replace(",", " ")
    )
    return head + career + cmp_line
