"""纯字符串处理 —— replayshark JSON 里的包装值拆解、船名清理、时长格式化。

原本长在 render_battle_report.py 里,被 render_criminals / render_damage_chart /
render_consumables_chart import。纯函数、无 I/O、无状态,所以单独一个模块,
跟要读 .mo 的 i18n、要读 constants.json 的 results 分开(测试互不牵连)。
"""
import re

ID_RE = re.compile(r"(?:AccountId|EntityId|GameParamId)\((\d+)\)")
KNOWN_RE = re.compile(r"Known\(([A-Za-z]+)\)")
RELATION_RE = re.compile(r"Relation\((\d+)\)")


def strip_id(s: str) -> int:
    m = ID_RE.match(s or "")
    return int(m.group(1)) if m else 0


def strip_known(s: str) -> str:
    if not s:
        return ""
    m = KNOWN_RE.match(s)
    return m.group(1) if m else s


def relation_name(s: str) -> str:
    # 0 = Self, 1 = Friendly, 2 = Enemy (BigWorld convention)
    m = RELATION_RE.match(s or "")
    n = int(m.group(1)) if m else -1
    return {0: "self", 1: "friendly", 2: "enemy"}.get(n, "?")


def clean_ship_name(raw: str) -> str:
    """PASS208_Salmon -> Salmon, PASC108_Baltimore_1944 -> Baltimore."""
    if not raw:
        return "?"
    # Drop prefix segment (e.g. PASS208, PASC108)
    parts = raw.split("_")
    if len(parts) >= 2:
        parts = parts[1:]
    # Drop trailing year-like segments (4-digit numbers)
    while parts and parts[-1].isdigit() and len(parts[-1]) == 4:
        parts.pop()
    return "_".join(parts) or raw


def fmt_time(secs: int) -> str:
    secs = int(secs)
    return f"{secs//60:02d}:{secs%60:02d}"
