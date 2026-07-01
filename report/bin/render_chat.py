# report/bin/render_chat.py
"""render_chat.py — 本局聊天记录 PNG。

CLI 用法:
    render_chat.py <replay.wowsreplay> <out.png> [--report-json <path>]

依赖 replayshark binary(WOWS_REPLAYSHARK_BIN env,默认
/opt/wows-toolkit/target/release/replayshark)。可选 --report-json 是
wows_full_report 写盘的战报 JSON,拿到 → 每行带船中文名 + 敌友着色。
拿不到就退化到纯用户名 + 中性色。

返回码:
  0 = 成功(渲了 PNG)
  3 = 本局没任何聊天(replay 安静,minimap.py 静默跳过)
  其他 = 错误
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_query import (  # noqa: E402
    GAME_BG, GAME_PANEL, GAME_PANEL_ALT, GAME_TEXT, GAME_DIM, GAME_GOLD,
    CJK_FONT, MONO_FONT, W, PAD, FOOTER_H, _font, _draw_footer,
)
from render_battle_report import t as _translate  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

REPLAYSHARK = os.environ.get(
    "WOWS_REPLAYSHARK_BIN", "/opt/wows-toolkit/target/release/replayshark"
)
WOWS_DATA_DIR = os.environ.get("WOWS_DATA_DIR", "/var/lib/wows-data/extracted")


def find_latest_extracted() -> str | None:
    """从 WOWS_DATA_DIR 下挑版本号最大的 <ver>_<build>/ 子目录,给
    replayshark -e 用。新版 replayshark chat 也要 GameParams 解 entity。"""
    base = Path(WOWS_DATA_DIR)
    if not base.is_dir():
        return None
    pat = re.compile(r"^(\d+)\.(\d+)\.(\d+)_(\d+)$")
    cands = []
    for p in base.iterdir():
        if not p.is_dir():
            continue
        m = pat.match(p.name)
        if m:
            cands.append((tuple(int(x) for x in m.groups()), p))
    if not cands:
        return None
    cands.sort()
    return str(cands[-1][1])

_HEADER_H = 112  # 给副标题留三行 (玩家/语音统计 + upstream bug 提示 + 系统消息提示)
_ROW_H    = 26
# relation → 用户名+船名着色。self/friendly/enemy 三档,查不到走 _UNKNOWN_*。
_COLOR_SELF     = (255, 220, 90)    # 亮金
_COLOR_FRIENDLY = (120, 220, 140)   # 淡绿 (WoWs 队友色)
_COLOR_ENEMY    = (255, 130, 110)   # 橙红 (WoWs 敌方色)
_UNKNOWN_CHAT   = (250, 230, 170)   # 暖黄 — 战报 JSON 缺失时的 chat fallback
_UNKNOWN_VOICE  = (110, 195, 255)   # 浅蓝 — 同上, voiceline fallback


def load_player_meta(json_path: str | None) -> dict:
    """从战报 JSON 建 name → {ship_zh, relation}。
    JSON 缺失/损坏/无 players 段 → 返空 dict,render 时退化到中性色 + 纯用户名。
    key 用玩家 username 字符串(replayshark 输出的也是 name 字段,亚服数字 ID
    玩家两边都是 "348616720" 这种字符串,天然匹配)。"""
    if not json_path or not Path(json_path).is_file():
        return {}
    try:
        raw = json.load(open(json_path, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    self_name = (raw.get("match") or {}).get("self_player_name") or ""
    self_team = None
    for p in raw.get("players", []) or []:
        if p.get("name") == self_name:
            self_team = p.get("team_id")
            break
    out = {}
    for p in raw.get("players", []) or []:
        name = p.get("name")
        if not name:
            continue
        ship = p.get("ship") or {}
        ship_idx = ship.get("index") or ""
        ship_raw = ship.get("name") or ""
        # 复用战报的 IDS_<index> → zh_sg.mo 翻译;查不到 fallback 原名。
        ship_zh = _translate(f"IDS_{ship_idx}", ship_raw) if ship_idx else ship_raw
        team = p.get("team_id")
        if name == self_name:
            relation = "self"
        elif team is not None and self_team is not None and team == self_team:
            relation = "friendly"
        elif team is not None and self_team is not None:
            relation = "enemy"
        else:
            relation = "unknown"
        out[name] = {"ship": ship_zh, "relation": relation}
    return out


def _relation_color(relation: str, kind: str) -> tuple:
    if relation == "self":     return _COLOR_SELF
    if relation == "friendly": return _COLOR_FRIENDLY
    if relation == "enemy":    return _COLOR_ENEMY
    return _UNKNOWN_VOICE if kind == "voice" else _UNKNOWN_CHAT

# replayshark chat 输出格式(见 wows-replays/src/analyzer/chat.rs):
#   "{clock}: {username}: {audience} {message}"           # 玩家 chat
#   "{clock}: {username}: voiceline {voiceline_msg:#?}"   # F 键预设
# {clock} 现在是 "127.8s" 或 "02:13.456";voiceline 用 Rust pretty-debug
# `{:#?}`,enum 含 field 时会换行(例如 `Unknown(\n    0,\n)` 跨 3 行),所以
# 不能 line-by-line 直接 regex,要先折叠续行。
_TS_RE  = re.compile(r"^[\d.:]+s?$")
_REC_RE = re.compile(r"^(\S+?): (.+?): (\S+) ?(.*)$")
_WS_RE  = re.compile(r"\s+")


def _collapse_records(text: str) -> list[str]:
    """把 stdout 折成一条一行 — "行首像时间戳" 起新记录,其它视为续行 strip
    后追加,中间用空格分隔。"""
    records: list[str] = []
    cur: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        head = line.split(":", 1)[0].strip()
        if _TS_RE.match(head):
            if cur is not None:
                records.append(cur)
            cur = line
        elif cur is not None:
            cur += " " + line.strip()
    if cur is not None:
        records.append(cur)
    return records


def _clean_voiceline(payload: str) -> str:
    """`Unknown( 0, )` 类多行 debug 折叠后形如 'Unknown( 0, )',压回 'Unknown(0)'。"""
    payload = _WS_RE.sub(" ", payload).strip()
    payload = re.sub(r"\(\s+", "(", payload)
    payload = re.sub(r",?\s+\)", ")", payload)
    return payload


def parse_chat_log(text: str) -> list:
    """返回 [{kind, time, user, audience, msg}]。kind ∈ 'chat' | 'voice'."""
    rows = []
    for rec in _collapse_records(text):
        m = _REC_RE.match(rec)
        if not m:
            continue
        ts, user, third, rest = m.group(1), m.group(2).strip(), m.group(3), m.group(4)
        if third == "voiceline":
            payload = _clean_voiceline(rest)
            if not payload:
                continue
            rows.append({"kind": "voice", "time": ts, "user": user,
                         "audience": "", "msg": payload})
        else:
            rows.append({"kind": "chat", "time": ts, "user": user,
                         "audience": third, "msg": rest})
    return rows


def _fmt_time(clock: str) -> str:
    """replayshark 输出 clock 形如 '02:13.456' 或 '127.8s' / '123.456';截到 MM:SS。"""
    clock = clock.rstrip("s")
    if ":" in clock:
        head = clock.split(".")[0]
        return head
    try:
        secs = int(float(clock))
        return f"{secs // 60:02d}:{secs % 60:02d}"
    except ValueError:
        return clock[:5]


def render_chat_png(out_path: str, rows: list, player_meta: dict | None = None) -> str:
    player_meta = player_meta or {}
    fonts = {
        "title": _font(CJK_FONT, 22),
        "sub":   _font(CJK_FONT, 14),
        "time":  _font(MONO_FONT, 14),
        "user":  _font(CJK_FONT, 15),
        "msg":   _font(CJK_FONT, 15),
    }
    # 两类 row 信息量为零,从 body 隐藏只在副标题给计数:
    #   1) voiceline + msg "Unknown(0)" — WoWs 12.7.0+ upstream 没解的协议
    #   2) chat + msg 空 — 一般是系统消息 / sender_id=0 的特殊包,replay 解不出正文
    def _is_unknown_voice(r): return r["kind"] == "voice" and r["msg"].startswith("Unknown(")
    def _is_empty_chat(r):   return r["kind"] == "chat" and not r["msg"].strip()
    visible = [r for r in rows if not _is_unknown_voice(r) and not _is_empty_chat(r)]
    chat_n          = sum(1 for r in rows if r["kind"] == "chat" and r["msg"].strip())
    chat_n_empty    = sum(1 for r in rows if _is_empty_chat(r))
    voice_n_known   = sum(1 for r in rows if r["kind"] == "voice" and not r["msg"].startswith("Unknown("))
    voice_n_unknown = sum(1 for r in rows if _is_unknown_voice(r))

    n = len(visible)
    body_h = max(_ROW_H, n * _ROW_H + 12)
    H = _HEADER_H + body_h + FOOTER_H

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)

    # Header
    draw.rectangle([0, 0, W, _HEADER_H], fill=GAME_PANEL)
    draw.line([0, _HEADER_H, W, _HEADER_H], fill=GAME_GOLD, width=2)
    draw.text((PAD, 10), "聊天记录", GAME_TEXT, fonts["title"])
    draw.text((PAD, 40), f"玩家发言 {chat_n}  ·  预设语音 {voice_n_known}",
              GAME_DIM, fonts["sub"])
    sub_y = 60
    if voice_n_unknown:
        draw.text((PAD, sub_y),
                  f"另有 {voice_n_unknown} 条预设语音 (按 F 键的提示) — 上游解码器暂未支持新版 voiceline,内容未知",
                  GAME_DIM, fonts["sub"])
        sub_y += 18
    if chat_n_empty:
        draw.text((PAD, sub_y),
                  f"另有 {chat_n_empty} 条系统消息 — 正文未在 replay 中携带,内容未知",
                  GAME_DIM, fonts["sub"])

    # Body
    y = _HEADER_H + 6
    time_col_w = 60
    user_col_w = 300   # 加宽 — 装得下 "英文长 ID · 中文长船名"
    for i, r in enumerate(visible):
        if i % 2 == 1:
            draw.rectangle([0, y - 2, W, y + _ROW_H - 4], fill=GAME_PANEL_ALT)
        x = PAD
        draw.text((x, y), _fmt_time(r["time"]), GAME_DIM, fonts["time"])
        x += time_col_w
        info = player_meta.get(r["user"], {})
        relation = info.get("relation", "unknown")
        ship = info.get("ship") or ""
        user_color = _relation_color(relation, r["kind"])
        user_text = f"{r['user']}[{ship}]" if ship else r["user"]
        if fonts["user"].getlength(user_text) > user_col_w - 8:
            while fonts["user"].getlength(user_text + "…") > user_col_w - 8 and len(user_text) > 1:
                user_text = user_text[:-1]
            user_text += "…"
        draw.text((x, y), user_text, user_color, fonts["user"])
        x += user_col_w
        # 不用 emoji — CJK_FONT (Noto Sans CJK) 不带 emoji 字形,会变 □ 豆腐
        prefix = "[F] " if r["kind"] == "voice" else ""
        msg = prefix + r["msg"]
        # 简单截断,不做 wrap(过长消息也几乎都在 100 字符内)
        if fonts["msg"].getlength(msg) > W - x - PAD:
            while fonts["msg"].getlength(msg + "…") > W - x - PAD and len(msg) > 1:
                msg = msg[:-1]
            msg += "…"
        draw.text((x, y), msg, user_color, fonts["msg"])
        y += _ROW_H

    _draw_footer(draw, 0, H - FOOTER_H, W, FOOTER_H)
    img.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("replay")
    ap.add_argument("out")
    ap.add_argument("--report-json", default=None,
                    help="可选:战报 JSON 路径,用来给每条聊天带船中文名 + 敌友着色")
    args = ap.parse_args()
    if not Path(args.replay).is_file():
        print(f"replay 不存在: {args.replay}", file=sys.stderr); sys.exit(2)
    if not Path(REPLAYSHARK).is_file():
        print(f"replayshark binary 不存在: {REPLAYSHARK} "
              "(设 WOWS_REPLAYSHARK_BIN 覆盖)", file=sys.stderr); sys.exit(2)
    cmd = [REPLAYSHARK]
    extracted = find_latest_extracted()
    if extracted:
        cmd += ["-e", extracted]
    cmd += ["chat", args.replay]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        print("replayshark chat 超时", file=sys.stderr); sys.exit(1)
    if proc.returncode != 0:
        tail = (proc.stderr or "")[-500:] or "?"
        print(f"replayshark chat 失败 (rc={proc.returncode}): {tail}",
              file=sys.stderr); sys.exit(1)
    rows = parse_chat_log(proc.stdout)
    if not rows:
        # 区分两种 "无聊天":真的没输出 vs 有输出但 regex 没吃。后者把样本回写
        # 给上游 log,定位 replayshark 输出格式漂移(比如 voiceline 用了 {:#?})
        stdout_stripped = (proc.stdout or "").strip()
        if stdout_stripped:
            sample = "\n".join(stdout_stripped.splitlines()[:10])
            print(f"replayshark chat 输出 {len(stdout_stripped.splitlines())} 行但 0 行能解析,样本:\n{sample}",
                  file=sys.stderr)
        else:
            print("本局无聊天 / 预设语音 (replayshark 无输出)", file=sys.stderr)
        sys.exit(3)
    player_meta = load_player_meta(args.report_json)
    render_chat_png(args.out, rows, player_meta)
    print(args.out)


if __name__ == "__main__":
    main()
