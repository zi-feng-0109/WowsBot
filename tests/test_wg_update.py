# tests/test_wg_update.py
"""wg_update 服务器侧逻辑自测。
用法: python tests/test_wg_update.py
退出码 0=全过。无 pytest 依赖,纯 assert + print。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plugin import wg_update  # noqa: E402


class FakeRunner:
    """记录被要求做了什么,按脚本返回结果。不碰真实文件系统。"""

    def __init__(self, results=None):
        self.calls = []
        self.results = results or {}
        self.moved = []

    def run(self, argv, cwd=None):
        key = argv[0] if isinstance(argv, list) else str(argv)
        self.calls.append((key, argv, cwd))
        return self.results.get(key, (0, "", ""))

    def move(self, src, dst):
        self.moved.append((str(src), str(dst)))
        return None


def _make_incoming(root: Path, name="15.9.0_13999999", marked=True):
    inc = root / "incoming"
    v = inc / name
    (v / "vfs" / "content").mkdir(parents=True)
    (v / "vfs" / "scripts").mkdir(parents=True)
    (v / "vfs" / "spaces").mkdir(parents=True)
    (v / "metadata.toml").write_text("x", encoding="utf-8")
    (v / "constants.json").write_text("{}", encoding="utf-8")
    (v / "vfs" / "content" / "GameParams.data").write_bytes(b"x" * 16)
    (v / "game_params.rkyv").write_bytes(b"y" * (31 * 1024 * 1024))
    if marked:
        (inc / f"{name}.done").write_text('{"build": 13999999}', encoding="utf-8")
    return inc


def test_find_pending_empty():
    with tempfile.TemporaryDirectory() as d:
        inc = Path(d) / "incoming"
        inc.mkdir()
        assert wg_update.find_pending(inc) == []
    print("  ok 空暂存区返回空列表")


def test_find_pending_ignores_unmarked():
    """模拟 scp 中断:目录传上来了但没有 .done 标记 —— 必须被忽略。"""
    with tempfile.TemporaryDirectory() as d:
        inc = _make_incoming(Path(d), marked=False)
        assert wg_update.find_pending(inc) == []
    print("  ok 没有 .done 标记的目录被忽略")


def test_find_pending_one():
    with tempfile.TemporaryDirectory() as d:
        inc = _make_incoming(Path(d))
        assert wg_update.find_pending(inc) == ["15.9.0_13999999"]
    print("  ok 找到一个待处理版本")


def test_find_pending_sorted():
    with tempfile.TemporaryDirectory() as d:
        inc = _make_incoming(Path(d), "15.9.0_13999999")
        _make_incoming(Path(d), "16.0.0_14000000")
        assert wg_update.find_pending(inc) == ["15.9.0_13999999", "16.0.0_14000000"]
    print("  ok 多个待处理版本按名字排序")


def test_missing_incoming_root():
    lines, ok = wg_update.run_update(
        incoming_root=Path("/definitely/not/here"), extracted_root=Path("/tmp"),
        repo_dir=Path("/tmp"), plugins_dir=Path("/tmp"), runner=FakeRunner())
    assert ok is False
    assert any("暂存区" in l for l in lines), lines
    print("  ok 暂存区不存在时给出可读提示而不是抛异常")


def test_refuses_when_target_exists():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        inc = _make_incoming(root)
        ext = root / "extracted"
        (ext / "15.9.0_13999999").mkdir(parents=True)
        r = FakeRunner()
        lines, ok = wg_update.run_update(
            incoming_root=inc, extracted_root=ext,
            repo_dir=root, plugins_dir=root, runner=r)
        assert ok is False
        assert r.moved == [], "目标已存在却还是搬了"
        assert any("已有这个版本" in l for l in lines), lines
        assert any("rm -rf" in l for l in lines), "没给出恢复办法"
    print("  ok extracted 已有同版本时拒绝搬运并给出恢复提示")


def test_bad_data_is_refused_before_move():
    """复校验的意义:标记只证明传完了,不证明传对了。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        inc = _make_incoming(root)
        (inc / "15.9.0_13999999" / "game_params.rkyv").unlink()
        r = FakeRunner()
        lines, ok = wg_update.run_update(
            incoming_root=inc, extracted_root=root / "extracted",
            repo_dir=root, plugins_dir=root, runner=r)
        assert ok is False
        assert r.moved == [], "数据坏了却还是搬进了生产目录"
        assert any("game_params.rkyv" in l for l in lines), lines
    print("  ok 复校验不通过时在搬运之前就停住")


def test_happy_path_order():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        inc = _make_incoming(root)
        ext = root / "extracted"
        ext.mkdir()
        r = FakeRunner(results={
            "git": (0, "Already up to date.", ""),
            "link_specs": (0, "linked", ""),
            "builds-dump": (0, "found 118 modernizations / 2345 exteriors / "
                               "662 crews / 82 skills", ""),
            "build_builds_json": (0, "wrote builds.json", ""),
            "fetch_build_icons": (0, "0 new icons", ""),
        })
        lines, ok = wg_update.run_update(
            incoming_root=inc, extracted_root=ext,
            repo_dir=root, plugins_dir=root, runner=r)
        assert ok is True, lines
        # 搬运必须发生,且方向正确
        assert len(r.moved) == 1, r.moved
        assert r.moved[0][0].endswith("15.9.0_13999999")
        assert r.moved[0][1].endswith("15.9.0_13999999")
        # 顺序:git pull 在搬运之前,link_specs 在搬运之后
        order = [c[0] for c in r.calls]
        assert order.index("git") < order.index("link_specs"), order
        # 标记处理完要删掉,否则下次扫描看到幽灵条目
        assert not (inc / "15.9.0_13999999.done").exists(), "标记没删"
        # 汇报里要有四类条目数
        joined = "\n".join(lines)
        for n in ("118", "2345", "662", "82"):
            assert n in joined, f"汇报里缺 {n}:\n{joined}"
    print("  ok 顺利路径:顺序正确、标记已删、汇报含四类条目数")


def test_link_specs_gets_explicit_version_dir():
    """裸跑 link_specs 会挑到 Lesta 26.x —— 必须显式传版本目录。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        inc = _make_incoming(root)
        ext = root / "extracted"
        ext.mkdir()
        r = FakeRunner(results={"builds-dump": (0, "found 1 modernizations / 2 exteriors / "
                                                  "3 crews / 4 skills", "")})
        wg_update.run_update(incoming_root=inc, extracted_root=ext,
                             repo_dir=root, plugins_dir=root, runner=r)
        call = [c for c in r.calls if c[0] == "link_specs"]
        assert call, "没调用 link_specs"
        argv = call[0][1]
        assert any("15.9.0_13999999" in str(a) for a in argv), argv
    print("  ok link_specs 拿到的是显式版本目录")


def test_plugin_change_sets_restart_flag():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        inc = _make_incoming(root)
        ext = root / "extracted"
        ext.mkdir()
        r = FakeRunner(results={
            "git": (0, "Fast-forward\n plugin/minimap.py | 3 +-\n", ""),
            "builds-dump": (0, "found 1 modernizations / 2 exteriors / 3 crews / 4 skills", ""),
        })
        lines, ok = wg_update.run_update(
            incoming_root=inc, extracted_root=ext,
            repo_dir=root, plugins_dir=root, runner=r)
        joined = "\n".join(lines)
        assert "需重启" in joined, joined
        # 必须是提示,不能自己重启
        assert not any("systemctl" in str(c[1]) for c in r.calls), r.calls
    print("  ok plugin 有变动时提示需重启,且没有自行重启")


def test_no_restart_flag_when_plugin_unchanged():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        inc = _make_incoming(root)
        ext = root / "extracted"
        ext.mkdir()
        r = FakeRunner(results={
            "git": (0, "Already up to date.", ""),
            "builds-dump": (0, "found 1 modernizations / 2 exteriors / 3 crews / 4 skills", ""),
        })
        lines, _ = wg_update.run_update(
            incoming_root=inc, extracted_root=ext,
            repo_dir=root, plugins_dir=root, runner=r)
        assert "需重启" not in "\n".join(lines)
    print("  ok plugin 无变动时不提示重启")


def test_multiple_pending_requires_explicit_version():
    """暂存区有多个待处理版本时,不带参数必须要求显式指定,不能自己挑一个。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        inc = _make_incoming(root, "15.9.0_13999999")
        _make_incoming(root, "16.0.0_14000000")
        r = FakeRunner()
        lines, ok = wg_update.run_update(
            incoming_root=inc, extracted_root=root / "extracted",
            repo_dir=root, plugins_dir=root, runner=r)
        assert ok is False
        assert r.moved == [], "有歧义却还是搬了一个"
        joined = "\n".join(lines)
        assert "15.9.0_13999999" in joined and "16.0.0_14000000" in joined, joined
        assert "指定" in joined, joined
    print("  ok 多个待处理版本时要求显式指定,不擅自挑")


def test_explicit_version_is_honored():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        inc = _make_incoming(root, "15.9.0_13999999")
        _make_incoming(root, "16.0.0_14000000")
        ext = root / "extracted"
        ext.mkdir()
        r = FakeRunner(results={"builds-dump": (0, "found 1 modernizations / 2 exteriors / "
                                                  "3 crews / 4 skills", "")})
        lines, ok = wg_update.run_update(
            incoming_root=inc, extracted_root=ext, repo_dir=root, plugins_dir=root,
            runner=r, version="16.0.0_14000000")
        assert ok is True, lines
        assert len(r.moved) == 1 and r.moved[0][0].endswith("16.0.0_14000000"), r.moved
    print("  ok 显式指定版本时处理的是指定那个")


def test_report_includes_disk_info():
    """spec 验收项:汇报里要有版本数与磁盘占用。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        inc = _make_incoming(root)
        ext = root / "extracted"
        (ext / "15.7.0_13015811").mkdir(parents=True)
        r = FakeRunner(results={"builds-dump": (0, "found 1 modernizations / 2 exteriors / "
                                                  "3 crews / 4 skills", "")})
        lines, _ = wg_update.run_update(
            incoming_root=inc, extracted_root=ext, repo_dir=root, plugins_dir=root, runner=r)
        joined = "\n".join(lines)
        assert "版本" in joined and ("磁盘" in joined or "占用" in joined), joined
    print("  ok 汇报里包含版本数与磁盘信息")


def test_allow_warn_from_marker_is_surfaced():
    """PC 侧用过 --AllowWarn 时,标记里会记一笔;服务器汇报必须把它带出来,
    否则就成了「悄悄放过一个告警」。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        inc = _make_incoming(root)
        (inc / "15.9.0_13999999.done").write_text(
            '{"build": 13999999, "allow_warn": true}', encoding="utf-8")
        ext = root / "extracted"
        ext.mkdir()
        r = FakeRunner(results={"builds-dump": (0, "found 1 modernizations / 2 exteriors / "
                                                  "3 crews / 4 skills", "")})
        lines, _ = wg_update.run_update(
            incoming_root=inc, extracted_root=ext, repo_dir=root, plugins_dir=root, runner=r)
        joined = "\n".join(lines)
        assert "allow_warn" in joined or "跳过了 WARN" in joined or "AllowWarn" in joined, joined
    print("  ok 标记里的 allow_warn 被汇报出来,不会悄悄放过")


def test_builds_json_failure_does_not_rollback():
    """搬运之后失败不回滚 —— 回放渲染已经可用了,只是配装面板数据没刷新。"""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        inc = _make_incoming(root)
        ext = root / "extracted"
        ext.mkdir()
        r = FakeRunner(results={
            "builds-dump": (0, "found 1 modernizations / 2 exteriors / 3 crews / 4 skills", ""),
            "build_builds_json": (1, "", "polib 没装"),
        })
        lines, ok = wg_update.run_update(
            incoming_root=inc, extracted_root=ext,
            repo_dir=root, plugins_dir=root, runner=r)
        assert ok is False
        assert len(r.moved) == 1, "搬运被回滚了 —— 不该回滚"
        joined = "\n".join(lines)
        assert "回放渲染已可用" in joined, joined
    print("  ok 搬运后失败不回滚,并说明回放渲染仍可用")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("== ALL PASS ==")
