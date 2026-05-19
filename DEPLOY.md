# DEPLOY.md — Linux 一次性部署

每台 bot 主机跑一次。除非 Rust / Python 等大依赖换了，否则不用再跑。

下面命令按 Debian / Ubuntu (`apt`) 写。其他发行版改一下包名即可。

## 1. 系统依赖

```bash
sudo apt update
sudo apt install -y \
    git build-essential pkg-config curl \
    fonts-noto-cjk fonts-dejavu \
    python3 python3-pip python3-pil python3-polib
```

> 如果发行版没打包好的 `python3-pil` / `python3-polib`，用 pip 装：
> `sudo pip install --break-system-packages Pillow polib`。
>
> CJK 字体（中文显示）必须装。如果没用 noto，可以装 `fonts-wqy-zenhei`，
> 或自己设置 `WOWS_CJK_FONT=/path/to/some.ttf` 环境变量。

## 2. 部署 replayshark 二进制

任选一种方式：

### 方式 A（推荐）：直接用仓库自带的 Linux x86_64 预编译版

```bash
cd /path/to/wows_report_bot
cp prebuilt/replayshark-linux-x86_64 replayshark
chmod +x replayshark
./replayshark --help    # 验证一下
```

不需要装 Rust、不需要 clone wows-toolkit。**90% 用户走这条**就够了。

### 方式 B：自己 build（已有 wows-toolkit clone 时最快）

适用场景：你已经为别的事情（如 Rust 版小地图 MP4 渲染）clone 过 wows-toolkit；或者你想用其他 CPU 架构（aarch64 / arm 等）。

```bash
# 1. 装 Rust 工具链（如已有可跳）
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
source "$HOME/.cargo/env"

# 2. 在已有 / 新 clone 的 wows-toolkit 仓库根目录：
cd /path/to/wows-toolkit       # 你的 clone；没有的话先 git clone --depth 1 https://github.com/landaire/wows-toolkit.git
git apply /path/to/wows_report_bot/tools/replayshark_battle_report.patch
cargo build --release -p replayshark
cp target/release/replayshark /path/to/wows_report_bot/replayshark
```

## 3. Python 依赖

只需要 `Pillow` 和 `polib` 两个库。优先用系统包管理：

```bash
# Debian/Ubuntu 有打包好的版本
sudo apt install -y python3-pil python3-polib
```

如果系统包不可用，用 pip（PEP 668 系统需加 `--break-system-packages`）：

```bash
sudo pip install --break-system-packages Pillow polib
```

> 不需要虚拟环境。脚本会自动找 `python3`（在 PATH 上）。
> 如果你确实有虚拟环境想用，把它放到 `wows_report_bot/venv/`
> 或设 `WOWS_PY_VENV=/path/to/venv`（或 `WOWS_PYTHON=/path/to/python`）。

## 4. 初始化 specs

第一次运行前 `specs/` 必须有内容。两种方式任选：

- **家里 Win 跑 `tools/update_specs.py` 然后 scp**（推荐，见 `UPDATE.md`）
- 直接在 Linux 主机上 `python tools/update_specs.py`（如果机器能联网拉 GitHub）

## 5. 验证

两个命令各跑一次确认：

```bash
# 全队战报
./bin/wows_report /tmp/某个真实回放.wowsreplay
# 预期：stdout 最后一行 = /tmp/wows_report/<回放名>.png

# 主角伤害复盘
./bin/wows_damage_report /tmp/某个真实回放.wowsreplay
# 预期：stdout 最后一行 = /tmp/wows_report/<回放名>.damage.png
```

两个命令共用同一份 replayshark / venv / specs / data，第二个命令不需要额外装东西。

如果看到 `No CJK font found`，回到第 1 步把 noto-cjk 装上，或设
`WOWS_CJK_FONT=/path/to/some.ttf`。

## 6. QQ 机器人接入示例

两个命令 I/O 完全一致：参数 `<replay> [out_dir]`、stdout 最后一行是 PNG 路径、stderr 是进度日志、退出码非 0 表示失败。所以一个通用 helper 就够了。

异步版（推荐，避免阻塞 bot）：

```python
import asyncio

BOT_HOME = "/path/to/wows_report_bot"

async def make_report(kind: str, replay_path: str,
                      out_dir: str = "/tmp/wows_report") -> str:
    """
    生成战报 PNG，返回文件路径。
    kind: "team" → 全队战报；"damage" → 主角伤害复盘
    """
    cmd = {
        "team":   f"{BOT_HOME}/bin/wows_report",
        "damage": f"{BOT_HOME}/bin/wows_damage_report",
    }[kind]
    proc = await asyncio.create_subprocess_exec(
        cmd, replay_path, out_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode())
    return stdout.decode().strip().splitlines()[-1]   # PNG 路径
```

同步版（脚本里临时跑）：

```python
import subprocess

result = subprocess.run(
    [f"{BOT_HOME}/bin/wows_damage_report", replay_path, out_dir],
    capture_output=True, text=True, check=True,
)
png_path = result.stdout.strip().splitlines()[-1]
```

得到 PNG 路径后，按你 bot 框架的方式发图（nonebot/aiocqhttp 等都有 `MessageSegment.image(f"file://{path}")`）。

> 性能小贴士：调用 `wows_damage_report` 时它会自动跑一次 `wows_report` 以得到 JSON。如果你**同时**要两张图，先调 `wows_report` 再调 `wows_damage_report`（后者会复用 JSON），可以省一次 replayshark 解析。
