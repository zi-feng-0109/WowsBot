# tests/test_wowsbot_dumpcheck.py
"""dumpcheck 自测脚本。
用法: python tests/test_wowsbot_dumpcheck.py
退出码 0=全过。无 pytest 依赖,纯 assert + print。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "report" / "lib"))
from wowsbot import dumpcheck  # noqa: E402

MIN_RKYV = 30 * 1024 * 1024


def _make_good(root: Path, rkyv_size: int = MIN_RKYV + 1) -> Path:
    """造一份结构完整的假 extracted 版本目录。"""
    v = root / "15.9.0_13999999"
    (v / "vfs" / "content").mkdir(parents=True)
    (v / "vfs" / "scripts").mkdir(parents=True)
    (v / "vfs" / "spaces").mkdir(parents=True)
    # 目录必须非空 —— dump 报 "VFS is empty" 时目录会在、内容是空的
    (v / "vfs" / "scripts" / "entity_defs").mkdir()
    (v / "vfs" / "spaces" / "01_solomon_islands").mkdir()
    (v / "metadata.toml").write_text('version = "15.9.0"\nbuild = 13999999\n', encoding="utf-8")
    (v / "constants.json").write_text("{}", encoding="utf-8")
    (v / "vfs" / "content" / "GameParams.data").write_bytes(b"x" * 1024)
    (v / "game_params.rkyv").write_bytes(b"y" * rkyv_size)
    return v


def test_good_dir_has_no_problems():
    with tempfile.TemporaryDirectory() as d:
        v = _make_good(Path(d))
        assert dumpcheck.check_version_dir(v) == [], dumpcheck.check_version_dir(v)
    print("  ok 完整目录零问题")


def test_missing_rkyv_is_reported():
    with tempfile.TemporaryDirectory() as d:
        v = _make_good(Path(d))
        (v / "game_params.rkyv").unlink()
        probs = dumpcheck.check_version_dir(v)
        assert len(probs) == 1, probs
        assert "game_params.rkyv" in probs[0], probs
    print("  ok 缺 rkyv 被报出")


def test_small_rkyv_is_reported():
    with tempfile.TemporaryDirectory() as d:
        v = _make_good(Path(d), rkyv_size=1024)
        probs = dumpcheck.check_version_dir(v)
        assert any("game_params.rkyv" in p and "偏小" in p for p in probs), probs
    print("  ok rkyv 过小被报出")


def test_each_required_path_is_checked():
    """五个关键路径逐个删掉,都必须被报出来。"""
    required = ["metadata.toml", "constants.json",
                "vfs/content/GameParams.data", "vfs/scripts", "vfs/spaces"]
    for rel in required:
        with tempfile.TemporaryDirectory() as d:
            v = _make_good(Path(d))
            target = v / rel
            if target.is_dir():
                import shutil
                shutil.rmtree(target)
            else:
                target.unlink()
            probs = dumpcheck.check_version_dir(v)
            assert any(rel in p for p in probs), f"{rel} 没被报出: {probs}"
    print(f"  ok {len(required)} 个关键路径逐个验证")


def test_empty_vfs_dir_is_reported():
    """dump 报 "VFS is empty" 时,目录会在但内容是空的 —— 只查 is_dir() 会放过这种。"""
    for rel in ["vfs/scripts", "vfs/spaces"]:
        with tempfile.TemporaryDirectory() as d:
            v = _make_good(Path(d))
            for child in (v / rel).iterdir():
                child.rmdir()
            probs = dumpcheck.check_version_dir(v)
            assert any(rel in p and "空目录" in p for p in probs), f"{rel}: {probs}"
    print("  ok 空的 vfs 子目录被报出")


def test_fatal_warns_are_not_skippable():
    """这几行是从 wows-data-mgr 二进制里 grep 出来的真实告警文本。它们以 WARN 打头,
    但语义是致命的 —— 必须连 allow_warn 都跳不过去,否则逃生口就成了漏洞。"""
    fatal = [
        "WARN: GameParams re-derivation failed for build 13999999",
        "WARN: GameParams re-derivation panicked for build 13999999 (incompatible)",
        "WARN: VFS is empty despite 42 idx files parsing successfully",
        "WARN: 3 / 42 idx files failed to parse for build 13999999:",
        "WARN: Failed to parse idx file foo.idx (header: bad)",
    ]
    for line in fatal:
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "dump.log"
            log.write_text(f"ok\n{line}\nok\n", encoding="utf-8")
            assert dumpcheck.check_dump_log(log), f"没被报出: {line}"
            assert dumpcheck.check_dump_log(log, allow_warn=True), \
                f"竟然被 allow_warn 跳过了,这是漏洞: {line}"
    print(f"  ok {len(fatal)} 条致命 WARN 都不可被 allow_warn 跳过")


def test_benign_warn_is_still_skippable():
    """逃生口要真的还能用 —— 无害告警加了 allow_warn 之后必须放过。"""
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "dump.log"
        log.write_text("ok\nWARN: Could not initialize constants fetcher: timeout\nok\n",
                       encoding="utf-8")
        assert dumpcheck.check_dump_log(log), "无害告警也该先报出来让人看"
        assert dumpcheck.check_dump_log(log, allow_warn=True) == [], \
            "加了 allow_warn 却还是拦着,逃生口失效了"
    print("  ok 无害告警仍可用 allow_warn 跳过")


def test_nonexistent_dir():
    probs = dumpcheck.check_version_dir(Path("/definitely/not/here"))
    assert probs and "不存在" in probs[0], probs
    print("  ok 目录不存在被报出")


def test_clean_log_passes():
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "dump.log"
        log.write_text("loading GameParams\nwrote 20 languages\ndone\n", encoding="utf-8")
        assert dumpcheck.check_dump_log(log) == []
    print("  ok 干净日志零问题")


def test_warn_carries_the_original_line():
    """报问题时必须带上触发的原文 —— 否则人没法判断这条告警到底要不要紧,
    而 allow_warn 存在的前提就是「人看过原文之后决定放过」。

    注意这里用的是真·无害告警。最初我拿 "WARN skipped GameParams re-derivation" 当例子,
    但那行语义是致命的(没有 rkyv 就等于船只数据全无),现在已被单列为不可跳过 ——
    所以它不能再充当「可跳过的 WARN」的样本。
    """
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "dump.log"
        log.write_text("ok\nWARN: Could not initialize constants fetcher: timeout\nok\n",
                       encoding="utf-8")
        probs = dumpcheck.check_dump_log(log)
        assert len(probs) == 1 and "WARN" in probs[0], probs
        assert "Could not initialize constants fetcher" in probs[0], probs
    print("  ok 报问题时带上了触发的原文")


def test_panic_and_unrecognized_are_not_skippable():
    cases = [
        ("panicked at 'boom'", "panic"),
        ("Unrecognized type FLOAT128", "Unrecognized type"),
    ]
    for line, kind in cases:
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "dump.log"
            log.write_text(f"ok\n{line}\nok\n", encoding="utf-8")
            assert dumpcheck.check_dump_log(log), f"{kind} 没被报出"
            assert dumpcheck.check_dump_log(log, allow_warn=True), \
                f"{kind} 竟然被 allow_warn 跳过了 —— 这是绝对不能发生的"
    print("  ok panic / Unrecognized type 不可被 allow_warn 跳过")


def test_missing_log_is_reported():
    probs = dumpcheck.check_dump_log(Path("/definitely/not/here.log"))
    assert probs and "不存在" in probs[0], probs
    print("  ok 日志不存在被报出")


def test_summarize_shape():
    with tempfile.TemporaryDirectory() as d:
        v = _make_good(Path(d))
        s = dumpcheck.summarize(v)
        assert s["version"] == "15.9.0_13999999", s
        assert s["build"] == 13999999, s
        assert s["sizes"]["game_params.rkyv"] == MIN_RKYV + 1, s
        assert "metadata.toml" in s["sizes"], s
    print("  ok summarize 结构正确")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("== ALL PASS ==")
