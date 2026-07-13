# plugin/wg_online.py
"""wg_online.py — WG 三服 (NA/EU/ASIA) 在线人数查询。

WGN cross-product API,挂在 tanks 域下但 game=wows 就返船服数据:
    GET https://api.worldoftanks.{host}/wgn/servers/info/?application_id=X&game=wows
返回: {"data": {"wows": [{"players_online": N, "server": "ASIA"}]}}

一个 realm 一次请求。3 realm 并发拉,几百毫秒返完。

app_id 从 WOWS_WG_APP_ID env 读 (跟 build_ships_json 复用同一个);
Lesta RU / 360 CN 各自独立、不在本模块范围。
"""
import asyncio
import os
from typing import Optional
import aiohttp
from nonebot.log import logger

# WG 三服:realm code → (WGN 域名, 显示名)
# 注意用 api.worldoftanks.{host} 不是 worldofwarships — WGN 是跨产品接口。
_WGN_HOSTS = {
    "asia": ("api.worldoftanks.asia", "亚服 ASIA"),
    "eu":   ("api.worldoftanks.eu",   "欧服 EU"),
    "na":   ("api.worldoftanks.com",  "美服 NA"),
}


def _app_id() -> Optional[str]:
    """WG application_id。跟 build_ships_json 复用同一 env。"""
    return os.environ.get("WOWS_WG_APP_ID") or None


def is_configured() -> bool:
    return bool(_app_id())


async def _fetch_one(session: aiohttp.ClientSession,
                     realm: str, timeout: float) -> tuple[str, Optional[int]]:
    host, _ = _WGN_HOSTS[realm]
    url = f"https://{host}/wgn/servers/info/"
    app = _app_id()
    if not app:
        return realm, None
    try:
        async with session.get(url,
                                params={"application_id": app, "game": "wows"},
                                timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            data = await r.json(content_type=None)
        if data.get("status") != "ok":
            logger.warning(f"WGN {realm} 返回 error: {data.get('error')}")
            return realm, None
        arr = (data.get("data") or {}).get("wows") or []
        if not arr:
            return realm, None
        return realm, int(arr[0].get("players_online") or 0)
    except Exception as e:
        logger.warning(f"WGN {realm} 请求失败: {e}")
        return realm, None


async def fetch_all(timeout: float = 6.0) -> dict[str, Optional[int]]:
    """3 服并发查。返回 {realm: 在线数 | None},None = 该服失败。"""
    async with aiohttp.ClientSession() as sess:
        results = await asyncio.gather(
            *(_fetch_one(sess, r, timeout) for r in _WGN_HOSTS),
            return_exceptions=False,
        )
    return {realm: n for realm, n in results}


def display_name(realm: str) -> str:
    return _WGN_HOSTS.get(realm, (None, realm))[1]
