# plugin/wg_api.py
"""wg_api.py — Wargaming public API 轻量 client,只为 /查询 取生涯 ship stats。

env:
  WOWS_WG_APP_ID   申请的 application_id (32 hex)
  WOWS_WG_REALM    asia | eu | na | ru  (默认 asia;ru 走 wargaming.ru 端点
                   即原 WG RU 而非 Lesta «Мир кораблей»,Lesta 我们不支持)
"""
import os
import aiohttp
from typing import Optional
from nonebot.log import logger

_REALM_HOSTS = {
    "asia": "api.worldofwarships.asia",
    "eu":   "api.worldofwarships.eu",
    "na":   "api.worldofwarships.com",
    "ru":   "api.worldofwarships.ru",
}


def _config() -> tuple[Optional[str], Optional[str]]:
    app_id = os.environ.get("WOWS_WG_APP_ID", "").strip()
    realm = os.environ.get("WOWS_WG_REALM", "asia").strip().lower()
    if not app_id:
        return None, None
    return app_id, _REALM_HOSTS.get(realm, _REALM_HOSTS["asia"])


def is_configured() -> bool:
    return bool(os.environ.get("WOWS_WG_APP_ID", "").strip())


async def fetch_ship_stats(account_id: int, ship_id: int,
                           timeout: float = 8.0) -> Optional[dict]:
    """该账号该船 pvp (随机战) 生涯 stats dict, 或 None。

    返回字段示例:
      {"battles": 87, "wins": 47, "damage_dealt": 13794123,
       "frags": 104, "survived_battles": 31, ...}
    """
    app_id, host = _config()
    if not app_id:
        logger.warning("WOWS_WG_APP_ID 未设, /查询 无 API key")
        return None
    url = f"https://{host}/wows/ships/stats/"
    params = {
        "application_id": app_id,
        "account_id": str(account_id),
        "ship_id":    str(ship_id),
    }
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as s:
            async with s.get(url, params=params) as r:
                data = await r.json()
    except Exception as e:
        logger.warning(f"WG API HTTP 失败: {e}")
        return None

    if data.get("status") != "ok":
        err = data.get("error", {}).get("message")
        logger.warning(f"WG API 业务失败: {err}")
        return None

    per_acc = data.get("data", {}).get(str(account_id))
    if not per_acc:
        return None    # 玩家隐藏 / 没玩过这条船
    entry = per_acc[0] if isinstance(per_acc, list) and per_acc else None
    return (entry or {}).get("pvp")


def format_stats_summary(player: dict, pvp: Optional[dict]) -> str:
    """文字汇总: 本局 + 生涯 + 对比。

    player: query_index 里 indexed_players 的一条
    pvp:    fetch_ship_stats() 返回 (可 None)
    """
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
        return head + "\n生涯: 无数据 (玩家隐藏 / 没玩过该船 / API 不可用)"

    n = int(pvp.get("battles") or 0)
    if n == 0:
        return head + "\n生涯: 该船 0 场"

    wins = int(pvp.get("wins") or 0)
    surv = int(pvp.get("survived_battles") or 0)
    dmg  = int(pvp.get("damage_dealt") or 0)
    frags = int(pvp.get("frags") or 0)
    win_rate = wins / n * 100
    surv_rate = surv / n * 100
    avg_dmg = dmg / n
    avg_frags = frags / n
    kdr = (frags / (n - surv)) if n > surv else float("inf")
    kdr_str = f"{kdr:.2f}" if kdr != float("inf") else "∞"

    cmp_line = ""
    if avg_dmg > 0:
        pct = (this_dmg / avg_dmg - 1) * 100
        sign = "+" if pct >= 0 else ""
        cmp_line = f"\n对比: 本局击伤是生涯均值的 {sign}{pct:.0f}%"

    career = (
        f"\n生涯: {n} 场 · 胜率 {win_rate:.1f}% · 生存率 {surv_rate:.1f}%\n"
        f"      均伤 {avg_dmg:,.0f} · 均击杀 {avg_frags:.2f} · KDR {kdr_str}"
        .replace(",", " ")
    )
    return head + career + cmp_line
