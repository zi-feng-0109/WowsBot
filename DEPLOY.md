# DEPLOY.md — Linux one-time setup

Sets up the Linux bot host. Run once per host, never again unless the host
or major dependencies (Rust, Python) change.

Assumes Debian/Ubuntu (`apt`). Adjust package names for other distros.

## 1. System dependencies

```bash
sudo apt update
sudo apt install -y \
    git build-essential pkg-config curl \
    fonts-noto-cjk fonts-dejavu \
    python3 python3-venv python3-pip
```

## 2. Rust toolchain

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
source "$HOME/.cargo/env"
rustc --version  # should be ≥ 1.92
```

## 3. Build replayshark (with our battle-report subcommand)

```bash
cd /tmp
git clone --depth 1 https://github.com/landaire/wows-toolkit.git
cd wows-toolkit
git apply /path/to/wows_report_bot/tools/replayshark_battle_report.patch
cargo build --release -p replayshark
cp target/release/replayshark /path/to/wows_report_bot/replayshark
```

## 4. Python venv

```bash
cd /path/to/wows_report_bot
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install Pillow polib
```

## 5. Initial specs

You need at least one specs/ snapshot before the first run. Either:

- **scp from home machine** (run `tools/update_specs.py` there first), OR
- run `tools/update_specs.py` directly on the Linux host (works if it has internet).

The dir bundled with this repo already contains a specs/ for the build that
was current at packaging time — usable until the next game update.

## 6. Verify

```bash
./bin/wows_report /tmp/some_real.wowsreplay
# expect: stderr progress lines, stdout last line = /tmp/wows_report/<name>.png
```

If you see "No CJK font found", install `fonts-noto-cjk` or set
`WOWS_CJK_FONT=/path/to/some.ttf`.

## 7. Wire into the bot

```python
import asyncio
async def make_report(replay_path: str, out_dir: str = "/tmp/wows_report") -> str:
    proc = await asyncio.create_subprocess_exec(
        "/path/to/wows_report_bot/bin/wows_report", replay_path, out_dir,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode())
    return stdout.decode().strip().splitlines()[-1]  # png path
```
