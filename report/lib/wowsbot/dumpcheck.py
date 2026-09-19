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
