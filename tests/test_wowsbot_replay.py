"""wowsbot.replay 测试 —— 用真实回放验 build/version/服务器判定 + 边界。
无 pytest 依赖。用法: python tests/test_wowsbot_replay.py

真实回放是可选的:环境里找不到就跳过那几项(打印 SKIP),其余边界用例照跑。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "report" / "lib"))
from wowsbot import replay  # noqa: E402

WG_REPLAY_DIR = Path("C:/Program Files (x86)/Steam/steamapps/common/World of Warships/replays")
LESTA_REPLAY_DIR = Path("C:/Games/Korabli/replays")


def _any(d: Path, pattern: str):
    return next(iter(sorted(d.glob(pattern))), None) if d.is_dir() else None


def test_wg_replay_build_and_version():
    f = _any(WG_REPLAY_DIR, "*.wowsreplay")
    if f is None:
        print("  test_wg_replay_build_and_version SKIP (无 WG 回放)")
        return
    b = replay.build_of(str(f))
    v = replay.version_of(str(f))
    assert isinstance(b, int) and b > 1_000_000, (f.name, b)
    # version_of 形如 "15.8.0"
    parts = v.split(".")
    assert len(parts) == 3 and all(x.isdigit() for x in parts), (f.name, v)
    assert replay.is_lesta(str(f)) is False
    print(f"  test_wg_replay_build_and_version PASS (build={b} ver={v})")


def test_lesta_replay_detected():
    f = _any(LESTA_REPLAY_DIR, "*.korablireplay")
    if f is None:
        print("  test_lesta_replay_detected SKIP (无 Lesta 回放)")
        return
    assert replay.is_lesta(str(f)) is True
    assert isinstance(replay.build_of(str(f)), int)
    print("  test_lesta_replay_detected PASS")


def test_corrupt_and_missing_return_none():
    d = Path(tempfile.mkdtemp())
    broken = d / "broken.wowsreplay"
    broken.write_bytes(b"garbage")
    assert replay.build_of(str(broken)) is None
    assert replay.version_of(str(broken)) == "0.0.0"
    empty = d / "empty.wowsreplay"
    empty.write_bytes(b"")
    assert replay.build_of(str(empty)) is None
    assert replay.build_of(str(d / "nope.wowsreplay")) is None
    print("  test_corrupt_and_missing_return_none PASS")


def test_absurd_meta_len_rejected():
    # meta_len 超过 5MB 上限视为损坏,不尝试读
    d = Path(tempfile.mkdtemp())
    f = d / "huge.wowsreplay"
    f.write_bytes(b"\x12\x32\x34\x11" + b"\x01\x00\x00\x00" + (99_000_000).to_bytes(4, "little"))
    assert replay.build_of(str(f)) is None
    print("  test_absurd_meta_len_rejected PASS")


def test_available_builds_only_version_dirs():
    root = Path(tempfile.mkdtemp())
    for name in ("15.8.0_13187581", "26.8.0_8861049", "15.3.0_12267945"):
        (root / name).mkdir()
    for noise in ("common", "vfs_common", "not_a_version", "15.8.0"):
        (root / noise).mkdir()
    (root / "15.9.0_99999999").write_text("file not dir")
    got = replay.available_builds(str(root))
    assert got == {13187581, 8861049, 12267945}, got
    print("  test_available_builds_only_version_dirs PASS")


def test_available_builds_unreadable_root_is_empty():
    # 目录读不到时返回空集合,由调用方决定放行(不能因此把所有回放拦死)
    assert replay.available_builds("/definitely/not/here") == set()
    print("  test_available_builds_unreadable_root_is_empty PASS")


if __name__ == "__main__":
    print("== test_wowsbot_replay ==")
    test_wg_replay_build_and_version()
    test_lesta_replay_detected()
    test_corrupt_and_missing_return_none()
    test_absurd_meta_len_rejected()
    test_available_builds_only_version_dirs()
    test_available_builds_unreadable_root_is_empty()
    print("== ALL PASS ==")
