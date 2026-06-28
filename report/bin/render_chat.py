# report/bin/render_chat.py
"""render_chat.py — 本局聊天记录 PNG。

库用法 (bot 直接 import 不实用,走 CLI):
CLI 用法:
    render_chat.py <replay.wowsreplay> <out.png>

依赖 replayshark binary(WOWS_REPLAYSHARK_BIN env,默认
/opt/wows-toolkit/target/release/replayshark)。replayshark chat 子命令
只解 chat / voiceline packet,不需要 GameParams。

返回码:
  0 = 成功(渲了 PNG)
  3 = 本局没任何聊天(replay 安静,故意不发图,minimap.py 静默跳过)
  其他 = 错误

样式:
  时间戳 (灰)   玩家名 (亮)   消息正文 (白)
  voiceline 行带 📣 前缀,自动用浅蓝区分(WoWs 里 F 键预设/警告)。
"""
import argparse
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

_HEADER_H = 72
_ROW_H    = 26
_VOICE_COLOR  = (110, 195, 255)   # 浅蓝
_CHAT_COLOR   = (250, 230, 170)   # 暖黄 玩家名

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


def render_chat_png(out_path: str, rows: list) -> str:
    fonts = {
        "title": _font(CJK_FONT, 22),
        "sub":   _font(CJK_FONT, 14),
        "time":  _font(MONO_FONT, 14),
        "user":  _font(CJK_FONT, 15),
        "msg":   _font(CJK_FONT, 15),
    }
    n = len(rows)
    body_h = max(_ROW_H, n * _ROW_H + 12)
    H = _HEADER_H + body_h + FOOTER_H

    img = Image.new("RGB", (W, H), GAME_BG)
    draw = ImageDraw.Draw(img)

    # Header
    draw.rectangle([0, 0, W, _HEADER_H], fill=GAME_PANEL)
    draw.line([0, _HEADER_H, W, _HEADER_H], fill=GAME_GOLD, width=2)
    draw.text((PAD, 14), "聊天记录", GAME_TEXT, fonts["title"])
    chat_n  = sum(1 for r in rows if r["kind"] == "chat")
    voice_n = sum(1 for r in rows if r["kind"] == "voice")
    draw.text((PAD, 46), f"玩家发言 {chat_n}  ·  预设语音 {voice_n}",
              GAME_DIM, fonts["sub"])

    # Body
    y = _HEADER_H + 6
    time_col_w = 60
    user_col_w = 200
    for i, r in enumerate(rows):
        if i % 2 == 1:
            draw.rectangle([0, y - 2, W, y + _ROW_H - 4], fill=GAME_PANEL_ALT)
        x = PAD
        draw.text((x, y), _fmt_time(r["time"]), GAME_DIM, fonts["time"])
        x += time_col_w
        user_color = _VOICE_COLOR if r["kind"] == "voice" else _CHAT_COLOR
        user = r["user"]
        if fonts["user"].getlength(user) > user_col_w - 8:
            while fonts["user"].getlength(user + "…") > user_col_w - 8 and len(user) > 1:
                user = user[:-1]
            user += "…"
        draw.text((x, y), user, user_color, fonts["user"])
        x += user_col_w
        # 不用 emoji — CJK_FONT (Noto Sans CJK) 不带 emoji 字形,会变 □ 豆腐
        prefix = "[F] " if r["kind"] == "voice" else ""
        msg = prefix + r["msg"]
        # 简单截断,不做 wrap(过长消息也几乎都在 100 字符内)
        if fonts["msg"].getlength(msg) > W - x - PAD:
            while fonts["msg"].getlength(msg + "…") > W - x - PAD and len(msg) > 1:
                msg = msg[:-1]
            msg += "…"
        draw.text((x, y), msg, GAME_TEXT, fonts["msg"])
        y += _ROW_H

    _draw_footer(draw, 0, H - FOOTER_H, W, FOOTER_H)
    img.save(out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("replay")
    ap.add_argument("out")
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
    render_chat_png(args.out, rows)
    print(args.out)


if __name__ == "__main__":
    main()
