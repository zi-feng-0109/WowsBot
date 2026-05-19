# DEPLOY.md — Linux 一站式部署

把 wows-bot 完整跑起来需要四块:

1. **游戏数据 (extracted)** — wows-data-mgr 从你本地 WoWs 安装解出,scp 到 Linux
2. **MP4 渲染器** — wows-toolkit 的 `minimap_renderer` (Rust),独立项目,本仓库不内置
3. **战报 PNG 渲染器** — 本仓库 `report/`,Python + 自带 replayshark
4. **NoneBot 框架 + 插件** — 你自己的 NoneBot 2 项目 + 本仓库 `plugin/minimap.py`

每台 bot 主机部署一次。Ubuntu/Debian 写法,其他发行版改包名。

> ⚠️ napcat (或别的 OneBot v11 客户端) 安装/登录不在本文档范围,自行准备。
>
> 💡 第 2 节 Linux 编译 (`setup.sh` 跑 cargo build) 和第 1 节 Windows 提取数据
> 可以并行做,前者要等 5-10 分钟,正好可以同时 dump + scp。

## 0. 系统依赖

```bash
sudo apt update
sudo apt install -y \
    git build-essential pkg-config curl \
    fonts-noto-cjk fonts-dejavu \
    python3 python3-pip
```

> CJK 字体必须装。也可以用 `fonts-wqy-zenhei`,或自己设 `WOWS_CJK_FONT=/path/to/some.ttf`。

## 1. 克隆本仓库

```bash
sudo git clone https://gitee.com/zi-feng-0109/wows-bot.git /opt/wows-bot
sudo chown -R $USER:$USER /opt/wows-bot
cd /opt/wows-bot
```

后续示例都假设安装在 `/opt/wows-bot`。换位置就改下面对应路径。

## 2. 准备游戏数据 (一份给两个渲染器共用)

`wows-toolkit` 里的 `wows-data-mgr` CLI 工具从你本地 WoWs 安装解出 `extracted/<ver>_<build>/` 目录,**MP4 渲染器和战报 PNG 渲染器都吃同一份**,只 dump 一次。

### 2.1 Windows: 编译 wows-data-mgr 并 dump

```powershell
# 在 Windows 上 clone wows-toolkit (三种方式任选)
git clone https://github.com/landaire/wows-toolkit C:\wows-toolkit
# git clone https://gitclone.com/github.com/landaire/wows-toolkit C:\wows-toolkit
# git clone https://ghfast.top/https://github.com/landaire/wows-toolkit C:\wows-toolkit

cd C:\wows-toolkit

# 编译 wows-data-mgr (需要 Rust + MSVC build tools;仓库自带 _build_datamgr.bat)
.\_build_datamgr.bat
# 产物: C:\wows-toolkit\target\release\wows-data-mgr.exe

# 注册你本地 WoWs 安装路径 (改成你的实际路径)
.\target\release\wows-data-mgr.exe register --latest `
    --path "C:\Program Files (x86)\Steam\steamapps\common\World of Warships"

# dump 渲染数据,产物在 .\extracted\<version>_<build>\
.\target\release\wows-data-mgr.exe dump-renderer-data --latest -o .\extracted
```

### 2.2 scp 到 Linux

```bash
# Linux 先建好目录 + 归属
sudo mkdir -p /var/lib/wows-data/extracted
sudo chown -R $USER:$USER /var/lib/wows-data
```

```powershell
# Windows 上 scp 整个版本目录 (改成你实际的版本号)
scp -r .\extracted\15.3.0_12267945 <user>@<bot-host>:/var/lib/wows-data/extracted/
```

完成后 Linux 应该有:

```
/var/lib/wows-data/extracted/15.3.0_12267945/
├── metadata.toml
├── game_params.rkyv
├── translations/
└── vfs/
    ├── content/GameParams.data
    ├── scripts/entity_defs/
    └── ...
```

## 3. 部署 MP4 渲染器 (外部 wows-toolkit)

`minimap/render.sh` 只是个 wrapper,真正的渲染靠 [landaire/wows-toolkit](https://github.com/landaire/wows-toolkit) 的 `minimap_renderer` 二进制。Linux 上编译一份。

### 3.1 clone wows-toolkit 源码

```bash
# 三种方式任选
sudo git clone https://github.com/landaire/wows-toolkit /opt/wows-toolkit
# sudo git clone https://gitclone.com/github.com/landaire/wows-toolkit /opt/wows-toolkit
# sudo git clone https://ghfast.top/https://github.com/landaire/wows-toolkit /opt/wows-toolkit

sudo chown -R $USER:$USER /opt/wows-toolkit
```

### 3.2 编译 (推荐用自带 setup.sh)

wows-toolkit 自带 `setup.sh` 一键搞定 apt 装 vulkan/mesa/gtk + 配 USTC 镜像 + 装 rustup + cargo build:

```bash
cd /opt/wows-toolkit
./setup.sh
# 完成后会有: /opt/wows-toolkit/target/release/minimap_renderer
```

> setup.sh 默认开 `USE_CN_MIRROR=1` (USTC 镜像)。海外网络置 `0` 走默认源。
> 没装 NVIDIA 驱动会提示先装再重启;**纯 CPU 渲染也可以**,wrapper 已经 `--cpu`。

不想跑 setup.sh 的手动版:

```bash
sudo apt install -y build-essential pkg-config libssl-dev \
    libxcb-render0-dev libxcb-shape0-dev libxcb-xfixes0-dev \
    libxkbcommon-dev libgtk-3-dev \
    vulkan-tools libvulkan-dev mesa-vulkan-drivers

# rustup (国内加 RUSTUP_DIST_SERVER=https://mirrors.ustc.edu.cn/rust-static)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
source "$HOME/.cargo/env"

cd /opt/wows-toolkit
cargo build --release -p wows_minimap_renderer --features "bin,vulkan,cpu,arc"
```

> Cargo 国内编译卡 crates.io 的话,`~/.cargo/config.toml` 加:
> ```toml
> [source.crates-io]
> replace-with = "ustc"
> [source.ustc]
> registry = "sparse+https://mirrors.ustc.edu.cn/crates.io-index/"
> ```

### 3.3 验证 render.sh

```bash
chmod +x /opt/wows-bot/minimap/render.sh
/opt/wows-bot/minimap/render.sh /path/to/some.wowsreplay /tmp/test.mp4
ls -la /tmp/test.mp4
```

路径不一样的话用环境变量覆盖:

```bash
export WOWS_TOOLKIT_BIN=/your/path/to/minimap_renderer
export WOWS_DATA_DIR=/your/path/to/extracted
```

## 4. 部署战报 PNG 渲染器

### 4.1 replayshark 二进制

```bash
cd /opt/wows-bot
cp report/prebuilt/replayshark-linux-x86_64 report/replayshark
chmod +x report/replayshark
./report/replayshark --help | head -3   # 验证
```

aarch64 / 其他架构自己 build (在第 3 节装好 Rust + clone wows-toolkit 后):
`git apply /opt/wows-bot/tools/replayshark_battle_report.patch && cargo build --release -p replayshark`,然后 cp 到 `report/replayshark`。

### 4.2 Python 依赖

只要 Pillow 和 polib:

```bash
# 优先 apt
sudo apt install -y python3-pil python3-polib

# 如果你用 pyenv / 虚拟环境,apt 包装的位置不在 PATH 上 — 用 pip
sudo pip3 install --break-system-packages -i https://pypi.tuna.tsinghua.edu.cn/simple Pillow polib

# 验证
python3 -c "import polib, PIL; print('polib', polib.__version__, 'PIL', PIL.__version__)"
```

> ⚠️ 用 pyenv 的话: apt 装的 `python3-polib` 会进系统 Python (`/usr/lib/python3/dist-packages`),
> pyenv 的 Python 看不见。直接 `pip3 install` 一份给当前 `python3` 最稳。

### 4.3 软链 specs 到第 2 节的 extracted (一行)

```bash
sudo bash /opt/wows-bot/tools/link_specs.sh
# 默认扫 /var/lib/wows-data/extracted/ 挑版本号最大的,把 report/specs 下
# content / scripts / metadata.toml 三个软链全建好
```

完成后:

```bash
ls -la /opt/wows-bot/report/specs/
# content -> /var/lib/wows-data/extracted/15.3.0_12267945/vfs/content
# scripts -> /var/lib/wows-data/extracted/15.3.0_12267945/vfs/scripts
# metadata.toml -> /var/lib/wows-data/extracted/15.3.0_12267945/metadata.toml
cat /opt/wows-bot/report/specs/metadata.toml
# version = "15.3.0"
# build = 12267945
```

> 离线/不想软链的场景可以用 `tools/build_specs_from_local.py`,
> 但通常场景下软链方案就够了 (版本更新一句 `link_specs.sh` 搞定,见 UPDATE.md)。

### 4.4 手工跑一次验证

```bash
/opt/wows-bot/report/bin/wows_full_report /path/to/some.wowsreplay /tmp/test_out
# stdout 最后一行 = 生成的 .full.png 路径
```

打开看一眼,中文船名、地图名、勋带都得正常。

## 5. 部署 NoneBot 插件

### 5.1 装 NoneBot 框架 (如果还没有)

```bash
sudo pip3 install --break-system-packages -i https://pypi.tuna.tsinghua.edu.cn/simple \
    "nonebot2[fastapi]" nonebot-adapter-onebot aiohttp Pillow
```

还没 NoneBot 项目的话,装 nb-cli 然后 `nb create`:

```bash
sudo pip3 install --break-system-packages -i https://pypi.tuna.tsinghua.edu.cn/simple nb-cli
nb create   # 选 simple / onebot-v11
```

最终目录大致 `~/my-bot/src/plugins/`。

### 5.2 挂接本插件

```bash
cp /opt/wows-bot/plugin/minimap.py ~/my-bot/src/plugins/minimap.py
```

> ⚠️ 别用软链。NoneBot 会 resolve 符号链接,发现真实路径不在你 bot 项目子目录就拒载
> (`ValueError: '...' is not in the subpath of '...'`)。直接 `cp` 最省事;
> 仓库更新后再 cp 一遍。

### 5.3 (可选) 启用 LLM 战后复盘

战报 PNG 发完后,bot 可以再追一条 DeepSeek 出的中文复盘文本。功能是开关型 — 用户在 QQ 发 `/分析 开` 才会启用 (按聊天上下文记,群和私聊独立)。

要让这个开关有用,bot 启动前 export DeepSeek API key:

```bash
export WOWS_DEEPSEEK_KEY=sk-xxxxxxxx   # https://platform.deepseek.com 申请
# 可选覆盖:
# export WOWS_DEEPSEEK_MODEL=deepseek-chat   # 也可换 deepseek-reasoner
# export WOWS_DEEPSEEK_URL=https://api.deepseek.com/chat/completions
```

放进 systemd unit 的 `Environment=` 或者 bot 启动脚本里都行。

没设 key 也不会崩,只是用户开了 `/分析 开` 之后那条尾消息会显示 `⚠️ LLM 分析失败: 缺 WOWS_DEEPSEEK_KEY 环境变量`,正常发 MP4+PNG 不受影响。

用户侧指令:

- `/分析 开` — 开启
- `/分析 关` — 关闭
- `/分析 状态` — 看当前是开是关

状态默认存到 `~/wows-bot-replay/analyze_toggle.json`,可用 `WOWS_TOGGLE_FILE` env 覆盖。

**自定义人格 / 风格** — system prompt 放在 `/opt/wows-bot/report/data/analyze_prompt.txt`,
直接编辑就能改 LLM 的称呼、口吻、分析侧重点,**不需要重启 bot** (每次调用都重新读)。
默认是"埃酱"人设 (傲娇雌小鬼参谋 + 称呼指挥官,但战术分析专业)。
想换路径用 `WOWS_ANALYZE_PROMPT=/your/prompt.txt`。

### 5.4 (可选) 覆盖默认路径

如果你没按 `/opt/wows-bot` 默认布局,启动 nb 前 export:

```bash
export WOWS_RENDER_SH=/your/path/minimap/render.sh
export WOWS_REPORT_CMD=/your/path/report/bin/wows_full_report
export WOWS_ANALYZE_CMD=/your/path/report/bin/wows_analyze
export WOWS_REPLAY_BASEDIR=~/wows-bot-replay   # 中转目录,bot 自动建/删
export WOWS_MP4_TIMEOUT=600                    # MP4 超时秒数
export WOWS_PNG_TIMEOUT=300                    # PNG 超时秒数
export WOWS_ANALYZE_TIMEOUT=120                # LLM 分析超时秒数
```

## 6. 启动

```bash
cd ~/my-bot
nb run
```

OneBot v11 客户端 (napcat 等) 连上后,在 QQ 发个 `.wowsreplay` 文件给 bot,
应该看到:

1. 立刻回 `✅ 已接收 replay 文件,当前队列位置:1`
2. 接着 `🎬 开始渲染...`
3. 几分钟后:MP4 作为群文件/私聊文件上传,同条消息附上战报 PNG

## 常见问题

- **PNG 里船名/地图全是英文** — polib 没装在 NoneBot 用的 Python 里。
  `which python3` 确认,再给那个 Python `pip3 install polib`。
- **PNG 失败 `战报 PNG 不存在`** — 多半 specs 缺/版本对不上。
  比对 `cat /opt/wows-bot/report/specs/metadata.toml` 和回放的 build 号。
- **MP4 失败** — `WOWS_DATA_DIR` 路径错,或者 wows-toolkit 版本和回放版本差太多。
- **`No CJK font found`** — 装 `fonts-noto-cjk` 或设 `WOWS_CJK_FONT`。

排错直接手跑,看 stderr:

```bash
/opt/wows-bot/report/bin/wows_full_report /tmp/x.wowsreplay /tmp/out 2>&1 | tail -50
/opt/wows-bot/minimap/render.sh /tmp/x.wowsreplay /tmp/x.mp4 2>&1 | tail -50
```
