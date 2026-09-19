# P4-2 更新流程自动化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WoWs 出大版本后,管理员只需「更新游戏 → 双击一个脚本 → 发一条 QQ 指令」,其余全自动,且把三个历史踩过的坑变成硬性校验。

**Architecture:** 两段式,中间隔暂存区 `/var/lib/wows-data/incoming/`。PC 侧 `.bat` 提数据 → 校验 → `scp` → 写完成标记;服务器侧超管指令 `/更新wg版本` 扫标记 → `git pull` → 复校验 → `mv` 进 `extracted/` → `link_specs` → 刷 builds.json 与图标 → 汇报。**校验逻辑只写一份**,放共享层 `wowsbot/dumpcheck.py`,两侧都用。

**Tech Stack:** Python 3(纯 stdlib)、PowerShell(PC 侧)、bash、NoneBot 2.4 + OneBot v11。

**设计文档:** `docs/superpowers/specs/2026-09-19-wg-update-automation-design.md`

---

## 执行须知(先读)

1. **服务器操作边界**:允许传文件到 `/tmp`、只读检查(`ls`/`grep`/`cat`);**禁止**任何写生产状态的命令
   —— 那些一律给用户命令、由他自己跑。**永远不重启服务。**
2. 涉及服务器的任务(Task 7)**不能交给 subagent** —— subagent 没法跟用户对话。
3. **写文件用 Write/Edit 工具,不要用 bash heredoc** —— 这台机器上 heredoc 会破坏中文编码,
   本项目已因此反复失败。要批量改就用 Write 写一个 python 补丁脚本再执行。
4. **不要碰 `plugin/minimap.py`** —— 它已 1658 行,拆它是 P3 的事。验收标准里有这一条。
5. 测试风格照现有的:**纯 `assert` + `print`,无 pytest**,`python tests/test_x.py` 退出码 0 = 全过。
6. `report/lib/wowsbot/` 有纯净性守卫(`tests/test_wowsbot_purity.py`):**除 `paths.py` 外不许出现
   `os.environ`**。新模块要遵守 —— 配置从参数进来。

---

## 文件结构

| 文件 | 变更 | 责任 |
|---|---|---|
| `report/lib/wowsbot/dumpcheck.py` | 创建 | 校验一份 extracted 版本目录 + dump 日志。纯 stdlib、无 env 读取。PC 侧与服务器侧**共用同一份** |
| `report/lib/wowsbot/paths.py` | 修改 | 加 `INCOMING_ROOT`(env `WOWS_INCOMING_ROOT`) |
| `tools/update_wg.ps1` | 创建 | PC 侧全部逻辑:认 build → 校验区服 → 提数据 → 调 dumpcheck → scp → 写标记 |
| `tools/update_wg.bat` | 创建 | 三行启动器,双击即跑(`-ExecutionPolicy Bypass` + `pause`) |
| `plugin/wg_update.py` | 创建 | 服务器侧逻辑。**不 import nonebot**,所有外部动作经注入的 runner —— 这样可测 |
| `plugin/wg_update_cmd.py` | 创建 | NoneBot matcher,薄壳:鉴权 + 调 `wg_update` + 逐步汇报 |
| `tests/test_wowsbot_dumpcheck.py` | 创建 | dumpcheck 的用例(造临时目录,覆盖每条失败路径) |
| `tests/test_wg_update.py` | 创建 | 服务器侧逻辑的用例(假 runner,不碰真文件系统) |
| `docs/UPDATE.md` | 修改 | 增「自动化流程」一节,放在手工流程之前 |

**为什么 `.bat` 只是启动器**:spec 原写「`.bat` 外壳 + 内嵌 PowerShell」,改成独立 `.ps1` +
启动器 —— 内嵌的 PowerShell 没法单独调用测试,而 `-ExecutionPolicy Bypass` 已经解决了 spec
担心的那个问题,双击体验不变。

**为什么校验逻辑放 `wowsbot/`**:spec 要求服务器侧「复校验:重跑一遍 PC 侧那套结构校验」。
两份实现必然漂移。`plugin/*.py` 已有 bootstrap 把 `report/lib` 加进 `sys.path`
(见 `plugin/minimap.py` 顶部),`tools/*.py` 也是同样做法,所以共享层两边都能用。

---

## Task 1:`wowsbot/dumpcheck.py` —— 共用的校验逻辑

**Files:**
- Create: `C:\Users\29801\Desktop\wows-bot-review\report\lib\wowsbot\dumpcheck.py`
- Test: `C:\Users\29801\Desktop\wows-bot-review\tests\test_wowsbot_dumpcheck.py`

- [ ] **Step 1:先写测试**

用 Write 工具创建 `tests/test_wowsbot_dumpcheck.py`:

```python
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
                target.rmdir()
            else:
                target.unlink()
            probs = dumpcheck.check_version_dir(v)
            assert any(rel in p for p in probs), f"{rel} 没被报出: {probs}"
    print(f"  ok {len(required)} 个关键路径逐个验证")


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


def test_warn_is_reported_and_skippable():
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "dump.log"
        log.write_text("ok\nWARN skipped GameParams re-derivation\nok\n", encoding="utf-8")
        probs = dumpcheck.check_dump_log(log)
        assert len(probs) == 1 and "WARN" in probs[0], probs
        # 原文要带出来,人才能判断
        assert "skipped GameParams re-derivation" in probs[0], probs
        # allow_warn 只跳过 WARN
        assert dumpcheck.check_dump_log(log, allow_warn=True) == []
    print("  ok WARN 被报出且可用 allow_warn 跳过")


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
```

- [ ] **Step 2:跑测试确认它失败**

```bash
cd /c/Users/29801/Desktop/wows-bot-review && python tests/test_wowsbot_dumpcheck.py
```

期望:`ModuleNotFoundError: No module named 'wowsbot.dumpcheck'`

- [ ] **Step 3:实现 `dumpcheck.py`**

用 Write 工具创建 `report/lib/wowsbot/dumpcheck.py`:

```python
"""dumpcheck.py — 校验一份 wows-data-mgr 提出来的 extracted 版本目录。

为什么需要这个
--------------
`wows-data-mgr dump-renderer-data` 遇到未知实体类型时**不会失败**:它静默跳过 GameParams
重新派生、只打一行 WARN、仍然 exit 0。产出的目录缺 `game_params.rkyv`,于是船名/船只数据
全无 —— 15.7 那次就是这么中招的,不盯日志根本发现不了。

所以「提完数据」之后必须有一道硬性校验,而且 PC 侧(上传前)和服务器侧(搬进生产前)
要用**同一份实现** —— 两份必然漂移。

本模块只依赖标准库,不读任何环境变量(库内纯净性守卫要求),配置全部走参数。
"""
import re
from pathlib import Path

# rkyv 是 GameParams 派生产物。实测 15.8 是 49 MB、15.7 是 50.7 MB;
# 30 MB 这个下限只为抓「派生被跳过留下个残片」,不是精确期望值。
MIN_RKYV_BYTES = 30 * 1024 * 1024

# 一份可用的 extracted 版本目录至少要有这些
REQUIRED_PATHS = [
    ("metadata.toml", "file"),
    ("constants.json", "file"),
    ("vfs/content/GameParams.data", "file"),
    ("vfs/scripts", "dir"),
    ("vfs/spaces", "dir"),
]

# 日志里出现这些就说明这次 dump 不可信。allow_warn 只放过 WARN 这一档 ——
# panic 与未知类型意味着数据真的不完整,放过它们等于把 15.7 那个坑重新挖开。
_FATAL_PATTERNS = [
    (re.compile(r"Unrecognized type\s+(\S+)"), "Unrecognized type", False),
    (re.compile(r"panic(ked)?", re.I), "panic", False),
    (re.compile(r"\bWARN\b"), "WARN", True),
]

_VERSION_DIR_RE = re.compile(r"^(\d+(?:\.\d+)+)_(\d+)$")


def check_version_dir(version_dir) -> list:
    """检查目录结构。返回问题列表,空列表 = 没问题。"""
    v = Path(version_dir)
    if not v.is_dir():
        return [f"版本目录不存在: {v}"]

    problems = []
    for rel, kind in REQUIRED_PATHS:
        p = v / rel
        ok = p.is_dir() if kind == "dir" else p.is_file()
        if not ok:
            problems.append(f"缺 {rel}({'目录' if kind == 'dir' else '文件'})")

    rkyv = v / "game_params.rkyv"
    if not rkyv.is_file():
        problems.append(
            "缺 game_params.rkyv —— 这通常意味着 GameParams 重新派生被静默跳过了,"
            "船名与船只数据会全无")
    else:
        size = rkyv.stat().st_size
        if size < MIN_RKYV_BYTES:
            problems.append(
                f"game_params.rkyv 偏小({size} 字节 < {MIN_RKYV_BYTES}),"
                "派生可能只完成了一部分")
    return problems


def check_dump_log(log_path, allow_warn: bool = False) -> list:
    """检查 dump 日志。返回问题列表(**带触发的原文行**),空列表 = 没问题。

    allow_warn=True 只跳过 WARN;panic 与 Unrecognized type 永远不跳过。
    """
    p = Path(log_path)
    if not p.is_file():
        return [f"dump 日志不存在: {p}"]

    text = p.read_text(encoding="utf-8", errors="replace")
    problems = []
    for line in text.splitlines():
        for pattern, label, skippable in _FATAL_PATTERNS:
            if not pattern.search(line):
                continue
            if skippable and allow_warn:
                continue
            hint = ""
            if label == "Unrecognized type":
                hint = ("(WG 加了新实体类型。不要动数据 —— "
                        "按 docs/REPLAYSHARK_BUILD.md §8 给 parse_type 加分支后重编)")
            problems.append(f"日志里出现 {label}{hint}: {line.strip()}")
            break
    return problems


def summarize(version_dir) -> dict:
    """产出一份摘要,给完成标记文件与汇报用。"""
    v = Path(version_dir)
    m = _VERSION_DIR_RE.match(v.name)
    sizes = {}
    for rel in ["metadata.toml", "constants.json", "game_params.rkyv",
                "vfs/content/GameParams.data"]:
        p = v / rel
        if p.is_file():
            sizes[rel] = p.stat().st_size
    return {
        "version": v.name,
        "build": int(m.group(2)) if m else None,
        "version_str": m.group(1) if m else None,
        "sizes": sizes,
    }


def check_all(version_dir, log_path=None, allow_warn: bool = False) -> list:
    """结构 + 日志一起查。log_path 为 None 时只查结构(服务器侧复校验用 —— 日志不上传)。"""
    problems = check_version_dir(version_dir)
    if log_path is not None:
        problems += check_dump_log(log_path, allow_warn=allow_warn)
    return problems


def _main(argv) -> int:
    """CLI:`python dumpcheck.py <版本目录> [--log <日志>] [--allow-warn]`

    退出码 0 = 通过,1 = 有问题(逐条打到 stderr),2 = 用法错。
    """
    import sys
    if len(argv) < 2:
        print(_main.__doc__, file=sys.stderr)
        return 2
    version_dir = argv[1]
    log_path = None
    allow_warn = "--allow-warn" in argv
    if "--log" in argv:
        i = argv.index("--log")
        if i + 1 >= len(argv):
            print("--log 后面要跟路径", file=sys.stderr)
            return 2
        log_path = argv[i + 1]

    problems = check_all(version_dir, log_path, allow_warn=allow_warn)
    if problems:
        print(f"校验未通过({len(problems)} 项):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    s = summarize(version_dir)
    print(f"校验通过: {s['version']} (build {s['build']})")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv))
```

- [ ] **Step 4:跑测试确认全过**

```bash
cd /c/Users/29801/Desktop/wows-bot-review && python tests/test_wowsbot_dumpcheck.py
```

期望:10 行 `ok ...` 然后 `== ALL PASS ==`,退出码 0。

- [ ] **Step 5:纯净性守卫必须仍然通过**

```bash
cd /c/Users/29801/Desktop/wows-bot-review && python tests/test_wowsbot_purity.py
```

期望:`== ALL PASS ==`。`dumpcheck.py` 不读 `os.environ`,所以该过。若失败,说明实现里
偷偷读了环境变量 —— 改成走参数,不要改守卫。

- [ ] **Step 6:用真实数据验一次(本机有 15.8)**

```bash
cd /c/Users/29801/Desktop/wows-bot-review/report/lib && python wowsbot/dumpcheck.py /c/Users/29801/Desktop/minimap/wows-toolkit/extracted/15.8.0_13187581
```

期望:`校验通过: 15.8.0_13187581 (build 13187581)`,退出码 0。
**这一步比单测更有价值** —— 它证明校验项与真实产物的结构对得上,而不只是与我造的假目录对得上。

- [ ] **Step 7:提交**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add report/lib/wowsbot/dumpcheck.py tests/test_wowsbot_dumpcheck.py
git commit -F <消息文件>
```

消息先用 Write 写到 `C:\Users\29801\AppData\Local\Temp\p42_t1_msg.txt`,要点:为什么需要这道
校验(dump 静默降级只打 WARN 仍 exit 0,15.7 那次的实际后果)、为什么 PC 与服务器共用一份、
`allow_warn` 为什么只放过 WARN、真实 15.8 数据验证通过。末尾加
`Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`。

---

## Task 2:`paths.py` 加 `INCOMING_ROOT`

**Files:**
- Modify: `C:\Users\29801\Desktop\wows-bot-review\report\lib\wowsbot\paths.py`
- Modify: `C:\Users\29801\Desktop\wows-bot-review\tests\test_wowsbot_paths.py`

- [ ] **Step 1:在 `paths.py` 里 `SPECS_PATCHED_ROOT` 那一组旁边加**

用 Edit 工具,在 `SPECS_PATCHED_ROOT = os.environ.get(...)` 之后插入:

```python
# 上传暂存区:PC 侧脚本把新版本数据 scp 到这里,超管指令 /更新wg版本 校验后再搬进
# EXTRACTED_ROOT。之所以不直接传进 extracted:渲染器按 build 号扫 extracted/,
# 294MB 的 scp 传一半断了、而此时正好有玩家发新版本回放,就会挑中那个半截目录。
INCOMING_ROOT = os.environ.get("WOWS_INCOMING_ROOT", "/var/lib/wows-data/incoming")
```

- [ ] **Step 2:在 `tests/test_wowsbot_paths.py` 里加断言**

找到检查 `SPECS_PATCHED_ROOT` 默认值的那个测试函数,在它里面加一行同形状的断言:

```python
    assert p.INCOMING_ROOT == "/var/lib/wows-data/incoming", p.INCOMING_ROOT
```

同时找到那个把一批 env 设成 `None` 的字典(`WOWS_REPLAYSHARK=None, WOWS_SPECS_DIR=None, ...`),
补上 `WOWS_INCOMING_ROOT=None`,免得本机设了这个变量时测试假过。

- [ ] **Step 3:跑测试**

```bash
cd /c/Users/29801/Desktop/wows-bot-review && python tests/test_wowsbot_paths.py && python tests/test_wowsbot_purity.py
```

期望:两个都 `== ALL PASS ==`。

- [ ] **Step 4:提交**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add report/lib/wowsbot/paths.py tests/test_wowsbot_paths.py
git commit -m "feat(paths): 声明 INCOMING_ROOT 上传暂存区

P4-2 用它:PC 侧 scp 到这里,/更新wg版本 校验后再搬进 extracted。
不直传 extracted 是因为渲染器按 build 号扫那个目录,半截的 scp 会被挑中。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3:服务器侧逻辑 `plugin/wg_update.py`

**Files:**
- Create: `C:\Users\29801\Desktop\wows-bot-review\plugin\wg_update.py`
- Test: `C:\Users\29801\Desktop\wows-bot-review\tests\test_wg_update.py`

**设计要点**:本模块**不 import nonebot**,所有外部动作(跑命令、移动目录)经一个注入的
`runner` 对象。这样测试用假 runner 就能覆盖全部分支,不需要真的服务器、真的 294MB 数据。

- [ ] **Step 1:先写测试**

用 Write 工具创建 `tests/test_wg_update.py`:

```python
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
```

- [ ] **Step 2:跑测试确认失败**

```bash
cd /c/Users/29801/Desktop/wows-bot-review && python tests/test_wg_update.py
```

期望:`ModuleNotFoundError: No module named 'plugin.wg_update'`

- [ ] **Step 3:实现 `plugin/wg_update.py`**

用 Write 工具创建。**模块必须导出这些名字**(Task 4 的 matcher 会用到,少一个就 import 失败):

```python
# 顶部 bootstrap —— 照 plugin/minimap.py 的写法
import os as _os, sys as _sys
BOT_REPO_DIR = _os.environ.get("WOWS_BOT_HOME", "/opt/wows-bot")
_LIB = _os.path.join(BOT_REPO_DIR, "report", "lib")
if _LIB not in _sys.path:
    _sys.path.insert(0, _LIB)
from wowsbot import dumpcheck, paths          # noqa: E402

MARKER_SUFFIX = ".done"

class SubprocessRunner:
    """生产实现。测试用假的替换它,所以这里不做任何判断逻辑。"""
    def run(self, argv, cwd=None): ...        # -> (rc:int, stdout:str, stderr:str)
    def move(self, src, dst): ...            # shutil.move

def find_pending(incoming_root) -> list: ...  # 同级有 <name>.done 的版本目录名,排序

def run_update(*, incoming_root, extracted_root, repo_dir, plugins_dir,
               runner, version=None) -> tuple: ...   # -> (lines: list[str], ok: bool)
```

`BOT_REPO_DIR` 是唯一读 env 的地方(bootstrap 需要,与 `minimap.py` 一致);**注意
`report/lib/wowsbot/` 里的纯净性守卫不管 `plugin/`,但 `dumpcheck.py` 里不许读 env。**

实现要点:
- 顶部 bootstrap 把 `report/lib` 加进 `sys.path`(照 `plugin/minimap.py` 的写法,
  用 `WOWS_BOT_HOME` 环境变量、默认 `/opt/wows-bot`),然后 `from wowsbot import dumpcheck, paths`
- **不 import nonebot**
- `find_pending(incoming_root) -> list[str]`:列出同级有 `<name>.done` 的版本目录名,排序返回
- `class SubprocessRunner`:`run(argv, cwd=None) -> (rc, stdout, stderr)` 用 `subprocess.run`;
  `move(src, dst)` 用 `shutil.move`。这是生产实现,测试用假的替换
- `run_update(*, incoming_root, extracted_root, repo_dir, plugins_dir, runner, version=None,
  timeout=...) -> (lines: list[str], ok: bool)`,按 spec 的 8 步走;每步往 `lines` 追加一行
- 每个 runner 调用的第一个元素当 key,测试靠它识别:`"git"` / `"link_specs"` /
  `"builds-dump"` / `"build_builds_json"` / `"fetch_build_icons"`
- `git pull` 输出里出现 `plugin/` 就置 `need_restart=True`,并 `cp plugin/*.py` 到 `plugins_dir`
- builds-dump 的输出用正则抽四个数字放进汇报
- 搬运之后的失败:`ok=False` 但**不回滚**,汇报里写「回放渲染已可用,builds.json 未刷新,
  重跑指令即可」

- [ ] **Step 4:跑测试确认全过**

```bash
cd /c/Users/29801/Desktop/wows-bot-review && python tests/test_wg_update.py
```

期望:16 行 `ok ...` + `== ALL PASS ==`。

- [ ] **Step 5:确认没碰 minimap.py、也没引入 nonebot 依赖**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git status --short plugin/
grep -n "nonebot" plugin/wg_update.py || echo "  ok 没有 nonebot 依赖"
```

期望:`git status` 只列出新增的 `plugin/wg_update.py`(minimap.py 不在其中);grep 无输出。

- [ ] **Step 6:提交**

消息写到 `C:\Users\29801\AppData\Local\Temp\p42_t3_msg.txt`,要点:为什么逻辑与 matcher 分开
(顶层 `on_command` 让文件无法被测试 import)、runner 注入让 12 个分支全可测、
搬运后失败为什么不回滚。

---

## Task 4:NoneBot matcher `plugin/wg_update_cmd.py`

**Files:**
- Create: `C:\Users\29801\Desktop\wows-bot-review\plugin\wg_update_cmd.py`

- [ ] **Step 1:实现**

用 Write 工具创建。照 `plugin/announcement.py` 的形状(`__plugin_meta__` + `on_command`),
内容要点:

```python
# plugin/wg_update_cmd.py
"""/更新wg版本 —— 超管指令,把 PC 侧上传到暂存区的新版本数据搬进生产。

逻辑全在 plugin/wg_update.py(那个文件不 import nonebot,所以可被测试直接 import)。
这里只做三件事:鉴权、把参数传进去、把汇报逐条发出来。
"""
import asyncio
from pathlib import Path

from nonebot import on_command
from nonebot.adapters.onebot.v11 import Event, Message
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata

from . import permissions
from . import wg_update

__plugin_meta__ = PluginMetadata(
    name="WG 版本更新",
    description="超管把 PC 侧上传的新版本游戏数据搬进生产并刷新派生数据",
    usage=("/更新wg版本              自动处理暂存区里唯一的待处理版本\n"
           "/更新wg版本 <ver>_<build>  暂存区有多个时显式指定"),
    type="application",
    supported_adapters={"~onebot.v11"},
)

update_cmd = on_command("更新wg版本", priority=5, block=True)


@update_cmd.handle()
async def _handle(event: Event, args: Message = CommandArg()):
    if not permissions.is_super_admin(event.get_user_id()):
        await update_cmd.finish("权限不足:本命令只允许超管使用")
    version = args.extract_plain_text().strip() or None

    await update_cmd.send("开始处理版本更新…")
    lines, ok = await asyncio.to_thread(
        wg_update.run_update,
        incoming_root=Path(wg_update.paths.INCOMING_ROOT),
        extracted_root=Path(wg_update.paths.EXTRACTED_ROOT),
        repo_dir=Path(wg_update.BOT_REPO_DIR),
        plugins_dir=Path(__file__).parent,   # 插件自己所在的目录就是 NoneBot 的 plugins 目录
        runner=wg_update.SubprocessRunner(),
        version=version,
    )
    head = "✅ 更新完成" if ok else "❌ 更新未完成"
    await update_cmd.finish(head + "\n" + "\n".join(lines))
```

注意 `plugins_dir=Path(__file__).parent` —— 这个文件运行时就在 NoneBot 的 plugins 目录里,
所以不需要任何配置项(`plugin/announcement.py` 用的是同一个技巧)。

- [ ] **Step 2:语法与导入形状检查**

```bash
cd /c/Users/29801/Desktop/wows-bot-review && python -c "import ast; ast.parse(open('plugin/wg_update_cmd.py',encoding='utf-8').read()); print('语法 OK')"
grep -c "await asyncio.to_thread\|is_super_admin" plugin/wg_update_cmd.py
```

期望:`语法 OK`,grep 计数 ≥ 2(阻塞工作在线程里跑、有鉴权)。

- [ ] **Step 3:确认没有自动重启的痕迹**

```bash
cd /c/Users/29801/Desktop/wows-bot-review && grep -n "systemctl\|restart\|kill" plugin/wg_update_cmd.py plugin/wg_update.py || echo "  ok 没有任何重启服务的代码"
```

期望:只可能命中「需重启」这类**提示文本**,不能有执行重启的代码。

- [ ] **Step 4:跑全部测试**

```bash
cd /c/Users/29801/Desktop/wows-bot-review && for t in tests/test_*.py; do printf "%-34s " "$(basename $t)"; python "$t" >/dev/null 2>&1 && echo PASS || echo FAIL; done
```

期望:9 个套件(原 7 + 新 2)全 PASS。

- [ ] **Step 5:提交**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add plugin/wg_update_cmd.py
git commit -m "feat(bot): /更新wg版本 超管指令(薄壳)

鉴权 + 调 wg_update.run_update + 逐条发汇报。逻辑不在这里,所以这个文件不需要测试。
plugins_dir 用 Path(__file__).parent —— 这个文件运行时就在 NoneBot 的 plugins 目录里,
不需要配置项(announcement.py 用的同一个技巧)。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5:PC 侧 `tools/update_wg.ps1` + `tools/update_wg.bat`

**Files:**
- Create: `C:\Users\29801\Desktop\wows-bot-review\tools\update_wg.ps1`
- Create: `C:\Users\29801\Desktop\wows-bot-review\tools\update_wg.bat`

- [ ] **Step 1:写 `update_wg.bat`(三行启动器)**

用 Write 工具创建:

```bat
@echo off
REM update_wg.bat — 双击运行(建议右键「以管理员身份运行」)。
REM 真正的逻辑在同目录的 update_wg.ps1;这里只是个启动器,
REM 因为内嵌的 PowerShell 没法单独调用测试。
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_wg.ps1" %*
echo.
pause
```

- [ ] **Step 2:写 `update_wg.ps1`**

用 Write 工具创建。参数:`[switch]$DryRun`、`[switch]$AllowWarn`。配置用
`$env:XXX` 兜底默认值(见 spec 的表)。流程:

1. 认 build:`Get-ChildItem "$GameDir\bin" -Directory | Where-Object { $_.Name -match '^\d+$' } |
   Sort-Object { [long]$_.Name } | Select-Object -Last 1`
2. 校验区服:`Get-Content "$GameDir\currentrealm.txt"` 必须是 `asia`(trim 后比较);
   否则打印「当前客户端是 <realm> 服,不是 asia。从公开测试服/国服提数据会污染数据集」并退出 1
3. 判断要不要干活:本机 `$ExtractedOut\*_<build>` 已存在 **且**
   `ssh $SshTarget "ls -d $IncomingRoot/../extracted/*_<build>"` 成功 → 打印「游戏还没更新」退出 0
4. 提数据:`& $DataMgr dump-renderer-data --game-dir $GameDir --build $build -o $ExtractedOut`,
   输出自己收行后用 `[IO.File]::WriteAllLines($LogPath, $lines, (New-Object System.Text.UTF8Encoding($false)))`
   落盘。

   > ⚠️ **不要用 `Tee-Object -FilePath`(本计划初稿就是这么写的,那是个陷阱)。**
   > Windows PowerShell 5.1 的 `Tee-Object` 写出来是 **UTF-16**,而 `dumpcheck.py` 按 UTF-8
   > 读日志 —— 于是 `WARN` / `panic` / `Unrecognized type` **一条都匹配不上,校验会假过**,
   > 正好把这个项目最核心的那层保护静默抹掉,而表面上一切正常。
   > 2026-09-19 实测发现。另外 `.ps1` 本身**必须带 UTF-8 BOM**,否则 WinPS 5.1 按 ANSI
   > 解码,所有中文提示变乱码。
5. 校验:`& python "<repo>\report\lib\wowsbot\dumpcheck.py" $verDir --log $LogPath`
   (`$AllowWarn` 时追加 `--allow-warn`)。退出码非 0 → **停,不上传**,把 dumpcheck 打的问题
   原样显示
6. `$DryRun` 到此结束,打印「dry-run:校验通过,未上传」
7. 上传:`ssh $SshTarget "mkdir -p $IncomingRoot"` 然后 `scp -r $verDir "${SshTarget}:$IncomingRoot/"`
8. 写标记:把 dumpcheck 的 `summarize` 输出(用 `python -c` 取 JSON)加上
   `allow_warn` 与时间戳,`ssh ... "cat > $IncomingRoot/<ver>.done"`
9. 打印「下一步:去 QQ 发 /更新wg版本」

每一步失败都 `Write-Host` 说明原因并 `exit 1`。脚本开头打印一次解析出来的配置,
方便排查默认值不对的情况。

- [ ] **Step 3:语法检查(不执行)**

```bash
cd /c/Users/29801/Desktop/wows-bot-review && powershell -NoProfile -Command "\$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw tools/update_wg.ps1), [ref]\$null); Write-Host 'ps1 语法 OK'"
```

期望:`ps1 语法 OK`

- [ ] **Step 4:`-DryRun` 实跑(本机游戏是 15.8,已提取过)**

```bash
cd /c/Users/29801/Desktop/wows-bot-review && powershell -NoProfile -ExecutionPolicy Bypass -File tools/update_wg.ps1 -DryRun
```

期望:识别出 build `13187581`、区服 `asia` 通过、然后因为「本机已提取且服务器已有」在第 3 步
就退出并打印「游戏还没更新」。**这正是日常最常见的情况**,必须不做无用功。

- [ ] **Step 5:三条失败路径逐个验证**

用临时的假游戏目录逐条试,每条都必须停下并指出原因:

```bash
# 准备假游戏目录
mkdir -p /c/Users/29801/AppData/Local/Temp/fakegame/bin/13999999
echo "eu" > /c/Users/29801/AppData/Local/Temp/fakegame/currentrealm.txt
```

- **区服不对**:`WOWS_GAME_DIR=<假目录>` 跑,期望停在第 2 步、提示当前是 `eu` 服
- **日志有 WARN**:造一个含 `WARN` 的日志 + 一份结构完整的假版本目录,直接调
  `python report/lib/wowsbot/dumpcheck.py <目录> --log <日志>`,期望退出码 1 且打出原文行;
  加 `--allow-warn` 后退出码 0
- **缺 rkyv**:同上,删掉 `game_params.rkyv`,期望退出码 1;**加 `--allow-warn` 仍然是 1**

把每条的实际输出记下来,Task 7 的执行记录要用。

- [ ] **Step 6:提交**

消息写到 `C:\Users\29801\AppData\Local\Temp\p42_t5_msg.txt`,要点:为什么 `.bat` 只是启动器、
区服校验为什么是硬拒绝(build 体系独立,污染数据集)、三条失败路径的实测结果。

---

## Task 6:`docs/UPDATE.md` 增「自动化流程」一节

**Files:**
- Modify: `C:\Users\29801\Desktop\wows-bot-review\docs\UPDATE.md`

- [ ] **Step 1:在「## 完整流程」之前插入新一节**

用 Edit 工具。内容要点:

- 三步:更新游戏 → 双击 `tools\update_wg.bat`(建议以管理员身份运行)→ QQ 发 `/更新wg版本`
- PC 侧脚本会拦住什么:区服不是 asia、dump 日志有 `panic`/`WARN`/`Unrecognized type`、
  缺 `game_params.rkyv` 或体积异常、五个关键路径缺失
- `--DryRun` 跑到校验为止不上传;`--AllowWarn` 只跳过 WARN 这一档,
  `panic`/`Unrecognized type`/缺文件**不可跳过**
- `/更新wg版本` 会做什么、汇报里有什么、什么时候提示「需重启」
- **失败怎么办**:搬运前失败 → `incoming/` 原样留着,修完重发指令;搬运后失败 →
  回放渲染已可用,只是 builds.json 没刷新,重跑指令即可
- 手工流程(下面那节)**保留作为退路**,并说明什么时候需要它
  (自动化本身出问题、或 WG 加了新实体类型需要先重编 replayshark)

- [ ] **Step 2:校验文档里的链接与路径都存在**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
for f in tools/update_wg.bat tools/update_wg.ps1 plugin/wg_update.py plugin/wg_update_cmd.py report/lib/wowsbot/dumpcheck.py; do
  [ -f "$f" ] && echo "  ok $f" || echo "  缺! $f"
done
grep -c "update_wg" docs/UPDATE.md
```

期望:五个文件都 `ok`;`grep -c` ≥ 2(文档确实提到了新脚本)。

- [ ] **Step 3:提交**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add docs/UPDATE.md
git commit -m "docs(update): 增自动化流程一节,手工流程保留作为退路

三步:更新游戏 → 双击 tools\\update_wg.bat → QQ 发 /更新wg版本。
写明 PC 侧脚本会拦住哪些情况、--AllowWarn 只跳过 WARN 一档、
以及搬运前/后失败各自怎么恢复。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7:假版本演练(需要主会话与用户交互)

**不需要等 WG 出新版本就能端到端验证指令。** 用现有 15.8 数据造一个不可能的版本号走一遍。

> **这个任务不能交给 subagent** —— 全部步骤都要用户在服务器上跑。
> 用不可能的 build 号(`99999999`)是为了确保即使演练中途出问题,渲染器也绝不会真的挑中它。

- [ ] **Step 1:推代码,服务器拉取**

```bash
cd /c/Users/29801/Desktop/wows-bot-review && git log --oneline origin/main..HEAD && git push
```

推之前把 `git log` 给用户看。然后给用户:

```
cd /opt/wows-bot && sudo git pull
sudo cp /opt/wows-bot/plugin/*.py ~zifeng/桌面/bot/EssexBot/src/plugins/
```

第二条是必须的 —— 新增了两个插件文件,不 cp 过去 NoneBot 看不到 `/更新wg版本`。
**然后需要重启一次 bot 才能加载新指令**(这是唯一必须重启的一次;提示用户,由他自己重启)。

- [ ] **Step 2:造假版本进暂存区**

给用户(`cp -rL` 解开软链,让假版本自成一份实体数据,免得与真 15.8 共享 CAS 文件):

```
sudo mkdir -p /var/lib/wows-data/incoming
sudo cp -rL /var/lib/wows-data/extracted/15.8.0_13187581 /var/lib/wows-data/incoming/15.8.0_99999999
sudo bash -c 'echo "{\"build\": 99999999, \"drill\": true}" > /var/lib/wows-data/incoming/15.8.0_99999999.done'
du -sh /var/lib/wows-data/incoming/15.8.0_99999999
```

期望:约 294MB。这一步会占几百 MB 并花点时间(`cp -rL` 是真复制)。

- [ ] **Step 3:发指令,逐条核对汇报**

用户在 QQ 里发 `/更新wg版本`。逐条核对:

- 有没有先回一条「开始处理版本更新…」
- 每一步是否各一行
- `git pull` 那步:刚 pull 过所以应该是 `Already up to date.`,不提示需重启
- 搬运:`incoming/15.8.0_99999999` → `extracted/15.8.0_99999999`
- `link_specs` 拿到的是显式版本目录(不是裸跑)
- builds.json 四类条目数应为 `118 / 2345 / 662 / 82`(数据就是 15.8 的副本)
- 汇报里有版本数与磁盘占用
- 末尾是 `✅ 更新完成`

- [ ] **Step 4:核对副作用**

给用户:

```
ls -la /opt/wows-bot/report/specs/
ls -d /var/lib/wows-data/incoming/* 2>/dev/null; echo "(暂存区应该空了)"
ls /var/lib/wows-data/extracted/
```

期望:`specs` 的三条软链现在指向 `15.8.0_99999999`;暂存区里没有目录也没有 `.done` 标记
(标记处理完要删);`extracted/` 里多了 `15.8.0_99999999`。

- [ ] **Step 5:验证幂等与「已存在则拒绝」**

给用户:再造一次标记然后重发指令 ——

```
sudo bash -c 'echo "{}" > /var/lib/wows-data/incoming/15.8.0_99999999.done'
sudo mkdir -p /var/lib/wows-data/incoming/15.8.0_99999999
```

再发 `/更新wg版本`。期望:**拒绝**,并提示 `extracted/` 里已有这个版本、要覆盖请先手工
`rm -rf`。这验证了 spec 里那条保护。

- [ ] **Step 6:验证「没有标记就忽略」**

给用户:

```
sudo rm -f /var/lib/wows-data/incoming/15.8.0_99999999.done
```

再发 `/更新wg版本`。期望:「`incoming/` 里没有待处理的数据。PC 侧的 `update_wg.bat` 跑了吗?」
—— 目录还在但没标记,必须被忽略(这正是模拟 scp 中断)。

- [ ] **Step 7:验证非超管被拒**

让一个非超管账号(或在群里让别人)发 `/更新wg版本`。期望:「权限不足:本命令只允许超管使用」。
若不方便找人,把这一条如实记为「未验证」,不要假装验过。

- [ ] **Step 8:清理演练痕迹 —— 这一步绝不能漏**

给用户,**顺序重要**:先把 specs 指回真 15.8,再删假版本。

```
sudo bash /opt/wows-bot/tools/link_specs.sh /var/lib/wows-data/extracted/15.8.0_13187581
ls -la /opt/wows-bot/report/specs/
```

确认三条软链都指回 `15.8.0_13187581` 之后:

```
sudo rm -rf /var/lib/wows-data/extracted/15.8.0_99999999
sudo rm -rf /var/lib/wows-data/incoming/15.8.0_99999999
ls /var/lib/wows-data/extracted/
```

期望:`extracted/` 回到演练前的 8 个版本 + `vfs_common`;暂存区空。

- [ ] **Step 9:重刷一次 builds.json,确保它对应真 15.8**

演练时 builds.json 是从假版本生成的(内容与真 15.8 相同,因为就是副本),但为了不留下
「生产数据来自一个已删除目录」的状态,重跑一次:

```
cd /opt/wows-bot && sudo python3 tools/build_builds_json.py
```

期望:四类条目数仍是 `118 / 2345 / 662 / 82`。

- [ ] **Step 10:把演练记录写进本计划**

在本文件末尾追加「## 执行记录」一节,写:每步的实际汇报内容、Step 5/6/7 三条保护的验证结果、
以及任何与预期不符的地方。**Step 7 若没验就如实写「未验证」。**

- [ ] **Step 11:更新记忆**

改 `C:\Users\29801\.claude\projects\C--Users-29801-Desktop-minimap-wows-toolkit\memory\wg_1570_update_notes.md`
的「标准更新流程」一节:开头加一句「**日常走自动化**:更新游戏 → 双击 `tools\\update_wg.bat`
→ QQ 发 `/更新wg版本`;下面的手工流程是退路」,并指向 `docs/UPDATE.md` 的自动化一节。
`MEMORY.md` 的那条指针描述同步更新。

---

## 完成标准

对照设计文档的 17 条验收标准逐条核。可在本机验的:

- [ ] `dumpcheck` 对真实 15.8 数据校验通过(Task 1 Step 6)
- [ ] `dumpcheck` 的每条失败路径都被报出且带原文(Task 1 Step 4:10 个用例)
- [ ] `--allow-warn` 只跳过 WARN;`panic` / `Unrecognized type` / 缺文件仍然拒绝(Task 1)
- [ ] `update_wg.ps1 -DryRun` 在游戏未更新时正确退出、不做无用功(Task 5 Step 4)
- [ ] 区服不是 `asia` 时拒绝并说明原因(Task 5 Step 5)
- [ ] 服务器侧逻辑 16 个用例全过,含「没标记则忽略」「目标已存在则拒绝」「坏数据在搬运前
      就停住」「搬运后失败不回滚」「多个待处理时要求显式指定」「标记里的 allow_warn 被
      汇报出来」(Task 3 Step 4)
- [ ] `plugin/wg_update.py` 不 import nonebot(Task 3 Step 5)
- [ ] 两个新插件文件里没有任何执行重启的代码(Task 4 Step 3)
- [ ] `minimap.py` 未被修改(Task 3 Step 5 的 `git status`)
- [ ] 9 个测试套件全绿(Task 4 Step 4)
- [ ] 库内纯净性守卫仍通过(Task 1 Step 5)

要在服务器上验的(Task 7):

- [ ] 假版本演练走通,四类条目数 `118 / 2345 / 662 / 82`
- [ ] 汇报里包含版本数与磁盘占用
- [ ] 重发指令时因「目标已存在」被拒,并给出恢复提示
- [ ] 删掉标记后指令忽略该目录
- [ ] 非超管被拒(验不了就如实记为未验证)
- [ ] 演练痕迹清理干净,`specs` 软链指回真 15.8,`extracted/` 回到 8 个版本

---

## 执行记录(2026-09-19)

### 各任务结果

| Task | 结果 |
|---|---|
| 1 `wowsbot/dumpcheck.py` | 13 个用例 + **真实 15.8 数据校验通过**(`校验通过: 15.8.0_13187581`)。纯净性守卫仍绿 |
| 2 `paths.INCOMING_ROOT` | 完成 |
| 3 服务器侧逻辑 | 21 个用例全过。不 import nonebot,外部动作全经注入的 runner |
| 4 NoneBot matcher | 完成,`minimap.py` 未被修改 |
| 5 PC 侧 `.ps1` + `.bat` | `-DryRun` 实跑正确识别「游戏还没更新」并退出;三条失败路径逐条验过 |
| 6 `docs/UPDATE.md` | 自动化一节已加,手工流程保留作退路 |
| 7 假版本演练 | 见下 |

### 演练(15.8.0_99999999,294MB 真实数据副本)

指令实际汇报:

```
✅ 更新完成
待处理版本:15.8.0_99999999
⚠️ 标记里 allow_warn=true:PC 侧提取时用过 --AllowWarn,那一次跳过了 WARN 检查
   (panic 与未知类型没跳)。若渲染出怪结果先查这个。
✓ 复校验通过(build 99999999,game_params.rkyv 48.4 MiB)
✓ git pull:已经是最新的。
✓ plugin/*.py 无变动,bot 不用重启
✓ 已搬进生产目录:/var/lib/wows-data/extracted/15.8.0_99999999
✓ link_specs 已指向 15.8.0_99999999
✓ builds-dump:升级品 118 / 涂装 2345 / 舰长 662 / 技能 82
✓ builds.json 已刷新
✓ 升级/技能图标已刷新
extracted 现有 9 个版本:…
extracted 占用:2.2G    磁盘:已用 38.1 GiB / 共 456.3 GiB,剩余 395.0 GiB
✓ 15.8.0_99999999 更新完成
```

三条保护逐条验过:

| 场景 | 实际 |
|---|---|
| 暂存区不存在 | `✗ 暂存区不存在…PC 侧脚本会把数据 scp 到这里,先确认目录已建好、权限对。` |
| `extracted/` 已有同版本 | `✗ …已有这个版本…没有覆盖动作 —— 覆盖等于在渲染器正在读的目录上动手。确认要重来:先 rm -rf …` |
| 目录在但没 `.done` 标记(= scp 中断) | `✗ 暂存区里没有待处理版本…只认同级带 <版本>.done 完成标记的目录…这种半截目录会被忽略。` |

「目标已存在」确实排在复校验**之前** —— 演练时那个重造的暂存目录是空的,若顺序反了会先报数据不完整。

副作用核对:处理后 `specs` 三条软链指向新版本、暂存区**完全空**(目录搬走 + 标记已删)。
清理后 `specs` 指回真 15.8、`extracted/` 回到 8 个版本 + `vfs_common`、暂存区空、
builds.json 从真 15.8 重新生成(`118 / 2345 / 662 / 82`,137.0 KB)。

**未验证**:非超管调用被拒(手头没有第二个账号,只有单测覆盖)。如实记着。

### 顺带独立复验了 P4-1

演练时 `specs/scripts` 指向的是 `extracted/<ver>/vfs/scripts` —— **未做 FLOAT64 手术的原始
scripts**,而 `builds-dump` 走这条路产出了正确的 118/2345/662/82。这是在生产环境里又一次
证明新 replayshark 原生认 FLOAT64,手术真的不需要了。

### 执行中改掉的三个问题

1. **计划里 `Tee-Object -FilePath` 那条指令会让整层校验静默失效。** Windows PowerShell 5.1 的
   `Tee-Object` 写出来是 UTF-16,而 `dumpcheck.py` 按 UTF-8 读日志 —— `WARN` / `panic` /
   `Unrecognized type` 一条都匹配不上,校验会假过,表面上一切正常。改成
   `[IO.File]::WriteAllLines` + 无 BOM UTF-8,并把陷阱写进计划。
   同类的一条:`.ps1` 本身**必须带 UTF-8 BOM**,否则 WinPS 5.1 按 ANSI 解码,中文提示全乱。
2. **`dumpcheck` 的判据有两个洞**(我查 `wows-data-mgr` 二进制里的真实告警文本发现的):
   `GameParams re-derivation failed` / `VFS is empty` / idx 解析失败 原本只被宽口径的 `WARN`
   命中,**可以被 `--allow-warn` 跳过**,而它们和 panic 一样致命 —— 已单列为不可跳过;
   目录原本只查 `is_dir()`,而 dump 报 `VFS is empty` 时目录会在、内容是空的 —— 已改为查非空。
3. **计划里的测试有两处形同虚设**:没有任何用例断言 `build_builds_json` / `fetch_build_icons`
   被调用过(`FakeRunner` 对未列出的 key 默认返回成功,所以一个压根不刷 builds.json 的实现
   照样全绿),以及 `test_report_includes_disk_info` 只断言 `"版本" in joined` 而第一行
   「待处理版本:」天然含这两个字。都已补实,并顺带补了四条未覆盖分支。
   其中新增的 plugin 同步用例抓到实现里一个真问题:同步是通过 runner 跑 `cp` 做的,
   假 runner 下压根不复制 —— 改成直接 `shutil.copy2`。

### 未做 / 已知限制

- 真正的 294MB `dump-renderer-data` 与 `scp` 上传**没有实跑过**(本机游戏就是 15.8,
  没有新版本可提)。第一次真更新时会走到,那时要盯一下第 4/6/7 步
- 「本机已提取但服务器没有」的恢复场景仍会重提一遍 294MB。用户已知情,暂不加开关 ——
  复用旧产物时旧日志可能已经没了,那就只能做结构校验、少一层保护
- `ships.json` / 战舰预览图 / `armor.json` 不在自动化范围内
