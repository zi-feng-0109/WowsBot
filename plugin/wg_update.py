# plugin/wg_update.py
"""wg_update.py —— 超管指令 `/更新wg版本` 背后的服务器侧逻辑。

为什么单独一个文件(不含 matcher)
--------------------------------
NoneBot 的 `on_command(...)` 在模块顶层就执行,带 matcher 的文件一旦被测试 import
就会去要 driver / adapter,根本 import 不进来。所以这里只放纯逻辑、**一行 NoneBot
都不 import**;matcher 在 `plugin/wg_update_cmd.py`,它只负责鉴权、取参数、把
`run_update()` 返回的 lines 拼成一条消息发出去。

为什么要暂存区
--------------
渲染器按 build 号扫 `extracted/`。294MB 的 scp 传一半断了、而此时正好有玩家发新版本
回放,就会挑中那个半截目录然后诡异报错。所以 PC 侧先把数据传到 `incoming/`,传完再写
一个 `<ver>_<build>.done` 完成标记,本模块只认**带标记**的目录 —— 没标记的一律忽略,
半截目录因此不可能被看见。

为什么所有外部动作都走注入的 runner
----------------------------------
`git pull` / `link_specs.sh` / `replayshark builds-dump` / 刷 builds.json 与图标,
还有那次 `mv`,全部经 `runner` 出去。于是这套流程的每个分支(数据坏了、目标已存在、
暂存区有歧义、搬运后某一步失败……)都能在没有服务器、没有 294MB 数据的情况下测到。
生产实现 `SubprocessRunner` 也在本文件里,测试用假的替换它。

runner 协议
-----------
- `run(argv, cwd=None) -> (rc, stdout, stderr)`,其中 **`argv[0]` 是步骤标签,
  `argv[1:]` 才是真正要执行的命令行**。多这一层标签是因为「这一步是什么」稳定,
  而「用什么命令实现它」随时会变(bash 脚本 / python 脚本 / 二进制子命令),
  调用方与测试都只想认前者。
- `move(src, dst)`:搬目录。

**本模块不执行任何重启。** `plugin/*.py` 有变动时只在汇报里提示「需重启」,
重启与否由人决定。
"""
import json
import os as _os
import re
import shutil
import subprocess
import sys as _sys
import tempfile
from pathlib import Path

# plugin/* 会被 cp 到 EssexBot 目录部署,Path(__file__) 在那边找不到仓库,
# 所以走 WOWS_BOT_HOME env 定位 report/lib(默认 /opt/wows-bot,跟部署文档一致)。
# 开发机上的 checkout 没有这个 env,所以再补一条「相对本文件」的候选 —— 否则
# 本模块在开发机上连 import 都做不到,16 个分支也就无从测起。
BOT_REPO_DIR = _os.environ.get("WOWS_BOT_HOME", "/opt/wows-bot")
for _cand in (str(Path(__file__).resolve().parent.parent / "report" / "lib"),
              _os.path.join(BOT_REPO_DIR, "report", "lib")):
    if _cand not in _sys.path:
        _sys.path.insert(0, _cand)          # 后插的在前:部署路径优先
from wowsbot import dumpcheck, paths          # noqa: E402

# PC 侧传完数据后写的完成标记后缀。没有它的目录一律当作「还没传完」。
MARKER_SUFFIX = ".done"

# extracted/ 下的版本目录名,如 15.9.0_13999999
_VERSION_RE = re.compile(r"^\d+(?:\.\d+)+_\d+$")

# replayshark builds-dump 的收尾行:
#   found 118 modernizations / 2345 exteriors / 662 crews / 82 skills
_COUNTS_RE = re.compile(
    r"found\s+(\d+)\s+modernizations\s*/\s*(\d+)\s+exteriors\s*/\s*"
    r"(\d+)\s+crews\s*/\s*(\d+)\s+skills")


class SubprocessRunner:
    """生产实现。测试用假的替换它,所以这里不做任何判断逻辑。

    `argv[0]` 是步骤标签,不参与执行;真正跑的是 `argv[1:]`。
    """

    def __init__(self, timeout: int = 1800):
        self.timeout = timeout

    def run(self, argv, cwd=None):
        cmd = [str(a) for a in list(argv)[1:]]
        if not cmd:
            return (2, "", f"步骤 {argv[0]} 没给出要执行的命令")
        try:
            p = subprocess.run(cmd, cwd=(str(cwd) if cwd else None),
                               capture_output=True, text=True,
                               errors="replace", timeout=self.timeout)
        except FileNotFoundError as e:
            return (127, "", f"命令不存在: {e}")
        except subprocess.TimeoutExpired:
            return (124, "", f"超时({self.timeout}s): {' '.join(cmd)}")
        return (p.returncode, p.stdout or "", p.stderr or "")

    def move(self, src, dst):
        shutil.move(str(src), str(dst))


def find_pending(incoming_root) -> list:
    """列出暂存区里**同级有 `<name>.done` 标记**的版本目录名,按名字排序。

    没有标记就意味着 scp 还没传完(或中断了),必须忽略 —— 这是硬要求,不是优化。
    """
    root = Path(incoming_root)
    if not root.is_dir():
        return []
    names = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if (root / (child.name + MARKER_SUFFIX)).is_file():
            names.append(child.name)
    return sorted(names)


def _read_marker(marker_path) -> dict:
    """读完成标记里的摘要。标记坏了不该让整条流程挂掉,所以读不出就当空。"""
    try:
        data = json.loads(Path(marker_path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _human(nbytes) -> str:
    n = float(nbytes or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TiB"


def _tail(text, n: int = 3) -> str:
    """命令输出可能几百行,汇报要发到 QQ 里,只留最后几行有效行。"""
    rows = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not rows:
        return "(无输出)"
    return " | ".join(rows[-n:])


def _note(text, n: int = 1) -> str:
    """成功行的补充说明:命令没吭声就别在汇报里留一句「(无输出)」。"""
    rows = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return ":" + " | ".join(rows[-n:]) if rows else ""


def run_update(*, incoming_root, extracted_root, repo_dir, plugins_dir,
               runner, version=None) -> tuple:
    """扫暂存区 → git pull → 复校验 → 搬进 extracted → link_specs → 刷 builds.json 与图标。

    返回 `(lines, ok)`:`lines` 是逐步汇报(matcher 直接 join 成消息),
    `ok=False` 表示有步骤没成功。超时设置在 `SubprocessRunner` 里,不在本函数。

    **搬运之后的失败不回滚。** 复校验已经证明这份数据完整,`extracted/` 里多它一个是
    好事 —— 回放渲染立刻就能用了,失败的只是 `/查询` 配装面板那类附属数据。
    """
    incoming_root = Path(incoming_root)
    extracted_root = Path(extracted_root)
    repo_dir = Path(repo_dir)
    plugins_dir = Path(plugins_dir)
    lines = []
    failures = []          # 搬运之后失败的步骤名;非空 => ok=False,但绝不回滚

    # ---------- 1. 选出要处理的版本 ----------
    if not incoming_root.is_dir():
        lines.append(f"✗ 暂存区不存在:{incoming_root}")
        lines.append("  PC 侧脚本会把数据 scp 到这里,先确认目录已建好、权限对。")
        return lines, False

    pending = find_pending(incoming_root)
    if not pending:
        lines.append(f"✗ 暂存区里没有待处理版本:{incoming_root}")
        lines.append(f"  只认同级带 <版本>{MARKER_SUFFIX} 完成标记的目录 —— 没标记说明"
                     "还没传完(或 scp 中断了),这种半截目录会被忽略。")
        return lines, False

    if version:
        if version not in pending:
            lines.append(f"✗ 指定的 {version} 不在待处理列表里")
            lines.append("  当前待处理:" + "、".join(pending))
            return lines, False
        name = version
    elif len(pending) > 1:
        # 自己挑一个等于替人做决定,而挑错的代价是把 specs 指到错版本上。
        lines.append(f"✗ 暂存区有 {len(pending)} 个待处理版本,需要显式指定处理哪个:")
        for p in pending:
            lines.append(f"  - {p}")
        lines.append("  用法:/更新wg版本 <版本目录名>")
        return lines, False
    else:
        name = pending[0]

    src_dir = incoming_root / name
    marker = incoming_root / (name + MARKER_SUFFIX)
    target_dir = extracted_root / name
    lines.append(f"待处理版本:{name}")

    info = _read_marker(marker)
    if info.get("allow_warn"):
        # 悄悄放过一个告警是最坏的结果,所以必须带进汇报里。
        lines.append("⚠️ 标记里 allow_warn=true:PC 侧提取时用过 --AllowWarn,那一次"
                     "跳过了 WARN 检查(panic 与未知类型没跳)。若渲染出怪结果先查这个。")

    # ---------- 2. 目标已存在就停 ----------
    if target_dir.exists():
        lines.append(f"✗ extracted 里已有这个版本:{target_dir}")
        lines.append("  没有覆盖动作 —— 覆盖等于在渲染器正在读的目录上动手。")
        lines.append(f"  确认要重来:先 rm -rf {target_dir},再重跑本指令。")
        return lines, False

    # ---------- 3. 复校验(标记只证明传完了,不证明传对了) ----------
    # dump 日志不上传,所以这里只查结构;用的是 PC 侧同一份 dumpcheck,不另写一份。
    problems = dumpcheck.check_all(src_dir)
    if problems:
        lines.append(f"✗ 复校验未通过({len(problems)} 项),没有搬运:")
        for p in problems:
            lines.append(f"  - {p}")
        lines.append("  删掉暂存区里这份,重新提取上传;生产目录保持原样。")
        return lines, False
    summary = dumpcheck.summarize(src_dir)
    lines.append(f"✓ 复校验通过(build {summary['build']},game_params.rkyv "
                 f"{_human(summary['sizes'].get('game_params.rkyv', 0))})")

    # ---------- 4. git pull(必须在搬运之前:先让代码适配到位,再让新数据可见) ----------
    rc, out, err = runner.run(["git", "git", "pull", "--ff-only"], cwd=str(repo_dir))
    if rc != 0:
        lines.append(f"✗ git pull 失败(rc={rc}),没有搬运:{_tail(err or out)}")
        lines.append("  新版本期间 bot 仓库常有适配 commit,代码没到位就先别放数据进去。")
        return lines, False
    lines.append("✓ git pull" + _note(out))

    if "plugin/" in (out or ""):
        # plugin/*.py 是 cp 到 NoneBot 项目里跑的(DEPLOY.md §5.2:不能用软链),
        # 所以 git pull 拉到新版还得同步一遍副本。
        srcs = sorted((repo_dir / "plugin").glob("*.py"))
        if not srcs:
            lines.append(f"⚠️ 没找到 {repo_dir / 'plugin'}/*.py,同步这步跳过了,请人工确认")
        else:
            # 直接用 shutil.copy2,不经 runner 跑 `cp`:复制文件是本模块自己的文件系统操作,
            # 不是「外部命令」(删标记那步同理)。好处有二 —— 不依赖系统里有 cp 这个二进制,
            # 以及测试能真的断言「副本确实同步过去了」而不只是「请求过一次 cp」。
            try:
                for p in srcs:
                    shutil.copy2(p, plugins_dir / p.name)
            except OSError as e2:
                lines.append(f"✗ plugin/*.py 同步到 {plugins_dir} 失败:{e2}")
                failures.append("plugin 同步")
            else:
                lines.append(f"✓ plugin/*.py 已同步到 {plugins_dir}({len(srcs)} 个)")
        lines.append("⚠️ 这次 git pull 带来了 plugin/*.py 变动,需重启 bot 才生效。"
                     "本指令不会自动重启,由你确认后手动重启。")
    else:
        lines.append("✓ plugin/*.py 无变动,bot 不用重启")

    # ---------- 5. 搬进生产目录(此后失败一律不回滚) ----------
    try:
        extracted_root.mkdir(parents=True, exist_ok=True)
        runner.move(str(src_dir), str(target_dir))
    except Exception as e:                       # noqa: BLE001 —— 搬运失败的原因五花八门
        lines.append(f"✗ 搬运失败:{e}")
        lines.append(f"  数据还在暂存区 {src_dir},标记也没删,修掉原因后重跑即可。")
        return lines, False
    lines.append(f"✓ 已搬进生产目录:{target_dir}")

    # 标记要在搬运成功后立刻删,否则下次扫描会看到一个没有目录的幽灵条目。
    # 这一步不经 runner:find_pending 读的是真实文件系统,假 runner 的记账代替不了它。
    try:
        marker.unlink()
    except OSError as e:
        lines.append(f"⚠️ 完成标记没删掉({e}),下次扫描会看到幽灵条目,手动删 {marker}")

    # ---------- 6. specs 软链指向新版本 ----------
    # 必须传显式的版本目录!裸跑 link_specs.sh 会 `sort -V | tail -1` 挑版本号最大的
    # 子目录,而 Lesta 的 26.x 比 WG 的 15.x 大 —— 会把 WG 战报的 specs 指到 Lesta 数据上。
    rc, out, err = runner.run(["link_specs", "bash",
                               str(repo_dir / "tools" / "link_specs.sh"),
                               str(target_dir)], cwd=str(repo_dir))
    if rc == 0:
        lines.append(f"✓ link_specs 已指向 {name}")
    else:
        lines.append(f"✗ link_specs 失败(rc={rc}):{_tail(err or out)}")
        failures.append("link_specs")

    # ---------- 7. builds-dump 条目数体检 ----------
    dump_json = Path(tempfile.gettempdir()) / f"builds_dump_{name}.json"
    rc, out, err = runner.run(["builds-dump", paths.REPLAYSHARK, "-e", str(target_dir),
                               "builds-dump", "-o", str(dump_json)], cwd=str(repo_dir))
    counts = _COUNTS_RE.search(f"{out or ''}\n{err or ''}")
    if rc != 0:
        lines.append(f"✗ builds-dump 失败(rc={rc}):{_tail(err or out)}")
        lines.append("  若是 Unrecognized type,说明 WG 加了新实体类型,按 "
                     "docs/REPLAYSHARK_BUILD.md §8 给 parse_type 加分支后重编,别动数据。")
        failures.append("builds-dump")
    elif counts:
        mod, ext, crew, skill = counts.groups()
        lines.append(f"✓ builds-dump:升级品 {mod} / 涂装 {ext} / 舰长 {crew} / 技能 {skill}")
        if "0" in (mod, ext, crew, skill):
            lines.append("⚠️ 上面有一类是 0 条,builds.json 大概率不可用,值得人工看一眼")
    else:
        lines.append(f"⚠️ builds-dump 跑通了但没解析出条目数(输出格式变了?):{_tail(out or err)}")

    # ---------- 8. 刷 builds.json 与升级/技能图标 ----------
    py = _sys.executable or "python3"
    rc, out, err = runner.run(["build_builds_json", py,
                               str(repo_dir / "tools" / "build_builds_json.py")],
                              cwd=str(repo_dir))
    if rc == 0:
        lines.append("✓ builds.json 已刷新" + _note(out))
    else:
        lines.append(f"✗ builds.json 刷新失败(rc={rc}):{_tail(err or out)}")
        failures.append("builds.json")

    rc, out, err = runner.run(["fetch_build_icons", py,
                               str(repo_dir / "tools" / "fetch_build_icons.py")],
                              cwd=str(repo_dir))
    if rc == 0:
        lines.append("✓ 升级/技能图标已刷新" + _note(out))
    else:
        lines.append(f"✗ 升级/技能图标刷新失败(rc={rc}):{_tail(err or out)}")
        failures.append("升级/技能图标")

    # ---------- 收尾:版本清单 + 磁盘 ----------
    versions = []
    if extracted_root.is_dir():
        versions = sorted(p.name for p in extracted_root.iterdir()
                          if p.is_dir() and _VERSION_RE.match(p.name))
    lines.append(f"extracted 现有 {len(versions)} 个版本:" + ("、".join(versions) or "(空)"))
    rc, out, _e = runner.run(["du", "du", "-sh", str(extracted_root)])
    if rc == 0 and (out or "").strip():
        lines.append(f"extracted 占用:{_tail(out, 1)}")
    try:
        usage = shutil.disk_usage(str(extracted_root))
        lines.append(f"磁盘:已用 {_human(usage.used)} / 共 {_human(usage.total)},"
                     f"剩余 {_human(usage.free)}")
    except OSError as e:
        lines.append(f"磁盘:占用查不到({e})")

    ok = not failures
    if ok:
        lines.append(f"✓ {name} 更新完成")
    else:
        lines.append(f"✗ 有 {len(failures)} 步没成功:" + "、".join(failures))
        lines.append("  数据已搬进 extracted 且复校验通过,所以回放渲染已可用;没成功的是"
                     "上面标 ✗ 的附属步骤(builds.json 未刷新时 /查询 的配装面板走兜底)。"
                     "不回滚 —— extracted 里多这个版本是好事,修掉原因后重跑本指令即可。")
    return lines, ok
