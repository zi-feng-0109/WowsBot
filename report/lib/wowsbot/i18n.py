"""翻译:WoWs gettext 目录(.mo)加载 + 硬编码中文标签表。

原本长在 render_battle_report.py 里。三张标签表(SPECIES_SHORT / DEATH_CAUSE_CN /
MATCH_GROUP_CN)也被别的脚本跨文件引用,原注释就写着 "Hardcoded fallback for
things not keyed as IDS_*",所以跟翻译放一起。

有 I/O 和模块级缓存,所以跟纯函数的 text.py 分开。
"""
from typing import Optional

from . import paths

_TRANSLATIONS: dict = {}


def load_translations(mo_path: str = None):
    """Load WoWs gettext catalog into a dict, on demand.

    默认路径来自 paths.TRANSLATIONS_MO(env WOWS_TRANSLATIONS_MO 可覆盖)。
    加载失败只打警告不抛 —— 缺翻译时退化成显示原始 IDS_* 键,不该让渲染整体失败。
    """
    global _TRANSLATIONS
    if _TRANSLATIONS:
        return
    path = mo_path or paths.TRANSLATIONS_MO
    try:
        import polib
        mo = polib.mofile(path)
        _TRANSLATIONS = {e.msgid: e.msgstr for e in mo if e.msgstr}
    except Exception as e:
        import sys
        print(f"warn: failed to load translations from {path}: {e}", file=sys.stderr)


def t(key: str, default: Optional[str] = None) -> str:
    """Translate an IDS_* key. Returns default (or key itself) if not found."""
    load_translations()
    return _TRANSLATIONS.get(key, default if default is not None else key)


SPECIES_SHORT = {
    "Battleship": "BB",
    "Cruiser": "CL",
    "Destroyer": "DD",
    "AirCarrier": "CV",
    "Submarine": "SS",
    "Auxiliary": "AUX",
}

DEATH_CAUSE_CN = {
    "ApShell": "AP",
    "HeShell": "HE",
    "CsShell": "CS",
    "Torpedo": "鱼雷",
    "AerialTorpedo": "机雷",
    "AerialRocket": "火箭",
    "AerialBomb": "炸弹",
    "DiveBomber": "俯冲",
    "SkipBomber": "跳炸",
    "AerialDepthCharge": "深弹",
    "DepthCharge": "深弹",
    "Fire": "燃烧",
    "Flooding": "进水",
    "Ram": "撞击",
    "Terrain": "撞礁",
    "Detonate": "弹药库",
    "SecondaryCaliber": "副炮",
    "AntiAir": "副炮",
    "SeaMine": "水雷",
    "Health": "血量",
}

# Hardcoded fallback for things not keyed as IDS_*
MATCH_GROUP_CN = {
    "pvp": "随机战",
    "ranked": "排位赛",
    "cooperative": "合作战斗",
    "training": "训练房",
    "clan": "战队战",
    "brawl": "乱斗",
    "scenario": "战役",
}
