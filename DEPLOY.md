# DEPLOY.md — Linux 一次性部署

每台 bot 主机跑一次。除非 Rust / Python 等大依赖换了，否则不用再跑。

下面命令按 Debian / Ubuntu (`apt`) 写。其他发行版改一下包名即可。

## 1. 系统依赖

```bash
sudo apt update
sudo apt install -y \
    git build-essential pkg-config curl \
    fonts-noto-cjk fonts-dejavu \
    python3 python3-venv python3-pip
```

> CJK 字体（中文显示）必须装。如果没用 noto，可以装 `fonts-wqy-zenhei`，
> 或自己设置 `WOWS_CJK_FONT=/path/to/some.ttf` 环境变量。

## 2. Rust 工具链

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
source "$HOME/.cargo/env"
rustc --version   # 需 ≥ 1.92
```

## 3. 编译 replayshark（加我们的 battle-report 子命令）

```bash
cd /tmp
git clone --depth 1 https://github.com/landaire/wows-toolkit.git
cd wows-toolkit
git apply /path/to/wows_report_bot/tools/replayshark_battle_report.patch
cargo build --release -p replayshark
cp target/release/replayshark /path/to/wows_report_bot/replayshark
```

## 4. 创建 Python 虚拟环境

```bash
cd /path/to/wows_report_bot
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install Pillow polib
```

## 5. 初始化 specs

第一次运行前 `specs/` 必须有内容。两种方式任选：

- **家里 Win 跑 `tools/update_specs.py` 然后 scp**（推荐，见 `UPDATE.md`）
- 直接在 Linux 主机上 `python tools/update_specs.py`（如果机器能联网拉 GitHub）

## 6. 验证

```bash
./bin/wows_report /tmp/某个真实回放.wowsreplay
# 预期：stderr 输出进度，stdout 最后一行 = /tmp/wows_report/<回放名>.png
```

如果看到 `No CJK font found`，回到第 1 步把 noto-cjk 装上，或设
`WOWS_CJK_FONT=/path/to/some.ttf`。

## 7. QQ 机器人接入示例

异步调用（推荐，避免阻塞 bot）：

```python
import asyncio

async def make_report(replay_path: str,
                      out_dir: str = "/tmp/wows_report") -> str:
    """生成战报 PNG，返回文件路径。"""
    proc = await asyncio.create_subprocess_exec(
        "/path/to/wows_report_bot/bin/wows_report", replay_path, out_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode())
    return stdout.decode().strip().splitlines()[-1]  # PNG 路径
```

同步版（脚本里临时跑）：

```python
import subprocess
result = subprocess.run(
    ["/path/to/wows_report_bot/bin/wows_report", replay_path, out_dir],
    capture_output=True, text=True, check=True
)
png_path = result.stdout.strip().splitlines()[-1]
```

得到 PNG 路径后，按你 bot 框架的方式发图（nonebot/aiocqhttp 等都有 `MessageSegment.image(f"file://{path}")`）。
