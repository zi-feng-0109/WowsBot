"""wowsbot 依赖纯净性 —— 硬约束的唯一守卫。

为什么用 ast 而不是 grep 源码文本:模块的 docstring 本身会写"不 import nonebot"
这类说明,grep 字面量会把文档误判成违规(计划初版就踩了这个坑)。ast 只看真实的
import 语句,函数体内的延迟 import 也能覆盖。

为什么一个文件扫整个目录、而不是每个模块各写一份:新增模块自动被覆盖,不会漏。

约束理由:三类 consumer 要 import 同一份公共层 —— nonebot 环境的 plugin/*、
venv 环境的 report/bin/*(见 wows_report::find_python,解释器可能是三种之一)、
以及将来 P1 的网站。任何一个模块拉进 nonebot / PIL,就有环境装不了。
subprocess 则是职责边界:公共层只做常量与纯函数,不派生进程。

无 pytest 依赖,纯 assert + print。用法: python tests/test_wowsbot_purity.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "report" / "lib" / "wowsbot"

FORBIDDEN = ("nonebot", "subprocess", "PIL")


def _imported_top_level(src: str) -> set:
    """收集文件里所有被 import 的顶层模块名(含函数体内的延迟 import)。"""
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # from . import paths -> node.module is None,相对导入不算外部依赖
            if node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return names


def test_no_forbidden_imports():
    files = sorted(LIB.glob("*.py"))
    assert files, f"没找到任何模块: {LIB}"
    for f in files:
        imported = _imported_top_level(f.read_text(encoding="utf-8"))
        bad = sorted(set(FORBIDDEN) & imported)
        assert not bad, f"{f.name} 不该 import {bad}(实际 import: {sorted(imported)})"
        print(f"  {f.name}: OK (import {sorted(imported) or '无'})")
    print(f"  test_no_forbidden_imports PASS ({len(files)} 个模块)")


def test_detects_a_real_violation():
    """反向验证:这个检查真的能抓到违规,不是空跑。"""
    assert "nonebot" in _imported_top_level("import nonebot")
    assert "nonebot" in _imported_top_level("from nonebot import get_driver")
    assert "PIL" in _imported_top_level("from PIL import Image")
    assert "subprocess" in _imported_top_level("def f():\n    import subprocess\n")
    # docstring 里提到这些词不算违规
    assert not (set(FORBIDDEN) & _imported_top_level('"""不 import nonebot、不 subprocess、不碰 PIL。"""'))
    print("  test_detects_a_real_violation PASS")


if __name__ == "__main__":
    print("== test_wowsbot_purity ==")
    test_no_forbidden_imports()
    test_detects_a_real_violation()
    print("== ALL PASS ==")
