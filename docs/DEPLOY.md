# DEPLOY.md — Linux 一站式部署

把 wows-bot 完整跑起来需要三块:

1. **MP4 渲染器** — wows-toolkit 的 `minimap_renderer` (Rust),独立项目,本仓库不内置
2. **战报 PNG 渲染器** — 本仓库 `report/`,Python + 自带 replayshark
3. **NoneBot 框架 + 插件** — 你自己的 NoneBot 2 项目 + 本仓库 `plugin/minimap.py`

每台 bot 主机部署一次。Ubuntu/Debian 写法,其他发行版改包名。

> ⚠️ napcat (或别的 OneBot v11 客户端) 安装/登录不在本文档范围,自行准备。

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
cd /opt/wows-bot
```

后续示例都假设安装在 `/opt/wows-bot`。换位置就改下面对应路径。

## 2. 部署战报 PNG 渲染器

### 2.1 replayshark 二进制

```bash
cd /opt/wows-bot
cp report/prebuilt/replayshark-linux-x86_64 report/replayshark
chmod +x report/replayshark
./report/replayshark --help | head -3   # 验证
```

aarch64 / 其他架构自己 build (装 Rust + clone wows-toolkit + apply `tools/replayshark_battle_report.patch` + `cargo build --release -p replayshark`)。

### 2.2 Python 依赖

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

### 2.3 specs (entity_defs + GameParams.data)

这是和 WoWs 游戏版本绑死的二进制数据,**仓库不内置**,自己准备。两种方式:

- **本地拉 (推荐)**: 你 Windows 上有 wows-toolkit GUI 解过包 → 跑 `tools/build_specs_from_local.py` → scp。见 [UPDATE.md](UPDATE.md)。
- **服务器联网拉**: 直接在服务器跑 `tools/update_specs.py`,从 wowsinfo/data GitHub 镜像拉 (要能访问 GitHub)。

不论哪种,最后 `/opt/wows-bot/report/specs/` 下应该有 `content/`, `scripts/`, `metadata.toml`:

```bash
ls /opt/wows-bot/report/specs/
# content  metadata.toml  scripts
cat /opt/wows-bot/report/specs/metadata.toml
# version = "15.3.0"
# build = 12267945
```

### 2.4 手工跑一次验证

```bash
/opt/wows-bot/report/bin/wows_full_report /path/to/some.wowsreplay /tmp/test_out
# stdout 最后一行 = 生成的 .full.png 路径
```

打开看一眼,中文船名、地图名、勋带都得正常。

## 3. 部署 MP4 渲染器 (外部 wows-toolkit)

`minimap/render.sh` 只是个 wrapper,真正的渲染靠 [landaire/wows-toolkit](https://github.com/landaire/wows-toolkit) 的 `minimap_renderer` 二进制。默认路径 `/opt/wows-toolkit/target/release/minimap_renderer`。

```bash
# Rust 工具链
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
source "$HOME/.cargo/env"

# clone + build
sudo git clone https://github.com/landaire/wows-toolkit /opt/wows-toolkit
cd /opt/wows-toolkit
cargo build --release -p minimap_renderer
ls target/release/minimap_renderer    # 验证
```

### 3.1 准备 extracted 数据

`minimap_renderer` 需要 WoWs 游戏目录解出来的数据 (跟战报 specs 同源但布局不同)。用 wows-toolkit GUI 在 Windows 上解一遍,产物 scp 到 Linux 的 `/var/lib/wows-data/extracted/<version>_<build>/`。

```bash
sudo mkdir -p /var/lib/wows-data/extracted
sudo chown -R $USER /var/lib/wows-data/extracted
# Windows 上 wows-toolkit 解的产物默认在 %APPDATA%\wows-toolkit\game_data\builds\<build>\,
# 整个目录 scp 上来即可。
```

### 3.2 验证 render.sh

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

## 4. 部署 NoneBot 插件

### 4.1 装 NoneBot 框架 (如果还没有)

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

### 4.2 挂接本插件

```bash
cp /opt/wows-bot/plugin/minimap.py ~/my-bot/src/plugins/minimap.py
```

> ⚠️ 别用软链。NoneBot 会 resolve 符号链接,发现真实路径不在你 bot 项目子目录就拒载
> (`ValueError: '...' is not in the subpath of '...'`)。直接 `cp` 最省事;
> 仓库更新后再 cp 一遍。

### 4.3 (可选) 覆盖默认路径

如果你没按 `/opt/wows-bot` 默认布局,启动 nb 前 export:

```bash
export WOWS_RENDER_SH=/your/path/minimap/render.sh
export WOWS_REPORT_CMD=/your/path/report/bin/wows_full_report
export WOWS_REPLAY_BASEDIR=~/wows-bot-replay   # 中转目录,bot 自动建/删
export WOWS_MP4_TIMEOUT=600                    # MP4 超时秒数
export WOWS_PNG_TIMEOUT=300                    # PNG 超时秒数
```

## 5. 启动

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
