"""wowsbot.paths 测试 —— env 覆盖 / 默认值 / 派生规则。
依赖纯净性由 tests/test_wowsbot_purity.py 统一守卫,这里不重复。
无 pytest 依赖,纯 assert + print。用法: python tests/test_wowsbot_paths.py"""
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "report" / "lib"))


def _fresh(**env):
    """在指定 env 下重新导入 paths(模块级常量只在 import 时求值)。

    传 None 表示删除该 env。调用结束恢复原值,避免测试互相污染。
    """
    saved = {k: os.environ.get(k) for k in env}
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        import wowsbot.paths as p
        return importlib.reload(p)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


_ALL = dict(WOWS_BOT_HOME=None, WOWS_DATA_DIR=None, WOWS_EXTRACTED_ROOT=None,
            WOWS_REPLAYSHARK=None, WOWS_SPECS_DIR=None, WOWS_SHIPS_JSON=None,
            WOWS_MP4_TIMEOUT=None, WOWS_PNG_TIMEOUT=None,
            WOWS_INCOMING_ROOT=None)


def test_defaults_derive_from_repo_root():
    """断言派生规则,而不是硬编码字符串 —— Windows 上 Path 产出反斜杠,
    硬编码 "/opt/..." 的断言在开发机上必然失败。"""
    p = _fresh(**_ALL)
    root = p.REPO_ROOT
    # 未设 WOWS_BOT_HOME 时,根从库自身位置推导,应指向本仓库
    assert (root / "report" / "lib" / "wowsbot" / "paths.py").is_file(), root
    assert p.REPORT_ROOT == root / "report", p.REPORT_ROOT
    # 数据路径从 REPORT_ROOT 派生,不从命令路径反推
    assert p.SHIPS_JSON == str(root / "report" / "data" / "ships.json"), p.SHIPS_JSON
    assert p.ARMOR_JSON == str(root / "report" / "data" / "armor.json"), p.ARMOR_JSON
    # 二进制/specs 在 report/ 下 —— 修掉 tools/ 里错一层的老坑
    assert p.REPLAYSHARK == str(root / "report" / "replayshark"), p.REPLAYSHARK
    assert p.SPECS_DIR == str(root / "report" / "specs"), p.SPECS_DIR
    assert p.REPORT_FULL_CMD == str(root / "report" / "bin" / "wows_full_report"), p.REPORT_FULL_CMD
    # extracted 是绝对路径常量,与仓库位置无关
    assert p.EXTRACTED_ROOT == "/var/lib/wows-data/extracted", p.EXTRACTED_ROOT
    assert p.INCOMING_ROOT == "/var/lib/wows-data/incoming", p.INCOMING_ROOT
    print("  test_defaults_derive_from_repo_root PASS")


def test_bot_home_override_moves_everything():
    p = _fresh(**{**_ALL, "WOWS_BOT_HOME": "/srv/bot"})
    root = Path("/srv/bot")
    assert p.REPO_ROOT == root, p.REPO_ROOT
    assert p.REPLAYSHARK == str(root / "report" / "replayshark"), p.REPLAYSHARK
    assert p.SHIPS_JSON == str(root / "report" / "data" / "ships.json"), p.SHIPS_JSON
    print("  test_bot_home_override_moves_everything PASS")


def test_explicit_env_beats_derived():
    p = _fresh(**{**_ALL, "WOWS_REPLAYSHARK": "/custom/rs",
                 "WOWS_SHIPS_JSON": "/custom/ships.json"})
    assert p.REPLAYSHARK == "/custom/rs"
    assert p.SHIPS_JSON == "/custom/ships.json"
    print("  test_explicit_env_beats_derived PASS")


def test_extracted_root_reads_both_names():
    # 老名字 WOWS_DATA_DIR 仍生效(minimap.py / render_chat.py 一直用它)
    p = _fresh(**{**_ALL, "WOWS_DATA_DIR": "/data/a"})
    assert p.EXTRACTED_ROOT == "/data/a", p.EXTRACTED_ROOT
    # 两者同时存在时新名字优先
    p = _fresh(**{**_ALL, "WOWS_DATA_DIR": "/data/a", "WOWS_EXTRACTED_ROOT": "/data/b"})
    assert p.EXTRACTED_ROOT == "/data/b", p.EXTRACTED_ROOT
    print("  test_extracted_root_reads_both_names PASS")


def test_empty_string_env_is_kept():
    # os.environ.get(name, default) 语义:设成空串就是空串,不回落默认值
    p = _fresh(**{**_ALL, "WOWS_REPLAYSHARK": ""})
    assert p.REPLAYSHARK == "", repr(p.REPLAYSHARK)
    print("  test_empty_string_env_is_kept PASS")


def test_timeouts_are_ints():
    p = _fresh(**{**_ALL, "WOWS_PNG_TIMEOUT": "123"})
    assert p.MP4_TIMEOUT == 600 and isinstance(p.MP4_TIMEOUT, int)
    assert p.PNG_TIMEOUT == 123 and isinstance(p.PNG_TIMEOUT, int)
    print("  test_timeouts_are_ints PASS")


if __name__ == "__main__":
    print("== test_wowsbot_paths ==")
    test_defaults_derive_from_repo_root()
    test_bot_home_override_moves_everything()
    test_explicit_env_beats_derived()
    test_extracted_root_reads_both_names()
    test_empty_string_env_is_kept()
    test_timeouts_are_ints()
    print("== ALL PASS ==")
