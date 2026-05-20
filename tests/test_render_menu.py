"""render_menu 烟囱测试 — 渲三种 state,确认 PNG 文件被写出来且 > 5KB。
用法: python tests/test_render_menu.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

# 让脚本能 import report/bin
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "report" / "bin"))

# 字体环境变量必须在 import render_menu 之前设
os.environ.setdefault("WOWS_CJK_FONT", "C:/Windows/Fonts/msyh.ttc")

from render_menu import render_menu_png  # noqa: E402


def _render_check(label: str, out: Path, **kw):
    render_menu_png(str(out), **kw)
    assert out.is_file(), f"{label}: PNG 没写出来"
    size = out.stat().st_size
    assert size > 5_000, f"{label}: PNG 才 {size} 字节,太小,可能渲染异常"
    print(f"  {label} PASS ({size} bytes)")


def test_private_default():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "menu_private.png"
        state = {"version": 1, "global_blacklist": [],
                 "groups": {}, "private": {}}
        _render_check("private_default", out,
                      scope="private", ident="0",
                      state_snapshot=state, is_super=False)


def test_group_with_mixed_toggles():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "menu_group.png"
        state = {
            "version": 1, "global_blacklist": [],
            "groups": {"999": {"视频": True, "战报": True,
                               "复盘": False, "分析": True}},
            "private": {},
        }
        _render_check("group_mixed", out,
                      scope="group", ident="999",
                      state_snapshot=state, is_super=False)


def test_super_view_with_blacklist():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "menu_super.png"
        state = {"version": 1, "global_blacklist": ["复盘"],
                 "groups": {}, "private": {}}
        _render_check("super_blacklist", out,
                      scope="group", ident="123",
                      state_snapshot=state, is_super=True)


if __name__ == "__main__":
    print("== test_render_menu ==")
    test_private_default()
    test_group_with_mixed_toggles()
    test_super_view_with_blacklist()
    print("== ALL PASS ==")
