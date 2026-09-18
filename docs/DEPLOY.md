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
cp /opt/wows-bot/plugin/*.py ~/my-bot/src/plugins/
```

当前包含 11 个文件:
- `minimap.py` — 主入口 (replay → 全套渲染;所有命令 handler)
- `permissions.py` — 群级开关 / 全局黑名单 / 超管识别
- `query_index.py` — `/查询` 索引 (战报 msg_id → 玩家列表)
- `ship_index.py` — `/船` 战舰名 → 数值查找/消歧 (读 ships.json)
- `tech_tree.py` — `/线` 科技树重建 (从 ships.json 的 next_ships)
- `render_mode.py` — `/sa` 渲染模式 (普通/极简/详细)
- `render_backend.py` — `/渲染模式` MP4 渲染后端切换 (CPU/GPU)
- `user_stats.py` — `/用户统计` 数据层 (排除超管)
- `version.py` — 版本号工具,菜单/战报 footer 共用
- `wg_api.py` — vortex 接口封装 (`/查询` 拉生涯数据)
- `announcement.py` — 超管 `/全群公告` `/定向公告` (见 §5.2.1)

> ⚠️ 别用软链。NoneBot 会 resolve 符号链接,发现真实路径不在你 bot 项目子目录就拒载
> (`ValueError: '...' is not in the subpath of '...'`)。直接 `cp` 最省事;
> 仓库更新后再 cp 一遍。

### 5.2.1 (可选) 配置公告超管白名单

`announcement.py` 启动时读 `<NoneBot 项目根>/data/admins.json`(注意是 NoneBot 项目
目录,不是 wows-bot 目录),格式是一个 QQ 号 JSON 数组:

```bash
mkdir -p ~/my-bot/data
cat > ~/my-bot/data/admins.json <<'EOF'
["你的QQ号"]
EOF
```

不存在 / 为空就是没人能发公告。修改后要重启 bot 才生效(只在 `on_startup` 加载一次)。

> 为什么不复用 §7.1 的 `SUPERUSERS`:公告会发到全部群,权限语义比"能调试 bot"更敏感,
> 单独留一份白名单方便缩小授权范围。

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

用户侧指令在 §7 统一介绍 (`/分析 开|关|状态` 是其中一个,跟 `/视频 /战报 /复盘` 同构)。
状态默认存到 `~/wows-bot-replay/toggle_state.json`,可用 `WOWS_TOGGLE_FILE` env 覆盖;
启动时会自动迁移老的 `analyze_toggle.json`(见 §7.4)。

**自定义人格 / 风格** — `wows_analyze` 不再用单一 prompt,改成从 `report/data/personas/*.txt`
随机抽。仓库自带 3 个: `aichan / michelle / shion`,每次调用前都重新读文件,**不需要重启 bot**。

- 固定某个人格: `export WOWS_PERSONA=aichan`
- 不设环境变量 = 每次随机
- 加新人格: 在 `report/data/personas/` 下放 `<名字>.txt`,文件内容就是 system prompt 全文

### 5.3.1 (可选) WG application_id —— 仅构建期用,运行时不需要

`/船 <中文舰名>` 战舰数值卡读的是预构建的 `report/data/ships.json`,**运行时 bot
不打任何外部 API**。这份 json 由 `tools/build_ships_json.py` 在大版本更新时生成
(见 UPDATE.md §2.6),那一步需要一个 WG application_id 去拉官方数值:

```bash
# developers.wargaming.net 免费申请;eu/asia host 都认,realm 无关
export WOWS_WG_APP_ID=<你的 application_id>
sudo -E python3 tools/build_ships_json.py
sudo -E python3 tools/fetch_ship_icons.py
```

**这个 key 只在构建机/构建步骤用,不用进 systemd unit、不用进运行时环境。**
ships.json + ship_icons/ 生成好提交进仓库后,生产端 `git pull` 即可,bot 重启加载。

`report/data/` 主要数据文件一览:
- `ships.json` — 每船数值卡数据(build_ships_json.py 产出,见 UPDATE.md §2.6)
- `armor.json` — 每船分面装甲厚度(replayshark armor-dump 产出,见 UPDATE.md §2.7)

`report/bin/` 主要渲染脚本一览:
- `render_ship.py` — `/船 <名>` 战舰数值卡渲染
- `render_armor.py` — `/船 <名> 装甲` 装甲分面图渲染

### 5.4 (可选) 覆盖默认路径

如果你没按 `/opt/wows-bot` 默认布局,启动 nb 前 export:

```bash
export WOWS_RENDER_SH=/your/path/minimap/render.sh
export WOWS_REPORT_FULL_CMD=/your/path/report/bin/wows_full_report     # 战报+复盘合并 PNG
export WOWS_REPORT_BATTLE_CMD=/your/path/report/bin/wows_report        # 仅战报 PNG
export WOWS_REPORT_DAMAGE_CMD=/your/path/report/bin/wows_damage_report # 仅复盘 PNG
export WOWS_ANALYZE_CMD=/your/path/report/bin/wows_analyze
export WOWS_RENDER_CRIMINALS=/your/path/report/bin/render_criminals.py  # 战犯榜 (subprocess)
export WOWS_RENDER_CHAT=/your/path/report/bin/render_chat.py            # 聊天记录 (subprocess)
export WOWS_REPLAY_BASEDIR=~/wows-bot-replay   # 中转目录,bot 自动建/删
export WOWS_SHIPS_JSON=                        # /船 /线 用,默认 report/data/ships.json
export WOWS_ARMOR_JSON=                        # /船 装甲 用,默认 report/data/armor.json
export WOWS_TOGGLE_FILE=                       # toggle_state.json 路径,默认 $WOWS_REPLAY_BASEDIR/
export WOWS_MP4_TIMEOUT=600                    # MP4 超时秒数
export WOWS_PNG_TIMEOUT=300                    # PNG 超时秒数
export WOWS_ANALYZE_TIMEOUT=120                # LLM 分析超时秒数

# 旧 alias 仍认 WOWS_REPORT_CMD (= WOWS_REPORT_FULL_CMD), 兼容老 .env
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

## 7. 超管 & 群级开关 & 版本号

### 7.1 配置超管

在 NoneBot 应用 (`EssexBot/.env` 之类) 里:

```
SUPERUSERS=["你的QQ号"]
```

多个超管: `SUPERUSERS=["111", "222"]`。超管能在任意群 toggle 任意 feature,也能用 `/sa` 命令操作全局黑名单。

### 7.1.1 配置 bot 版本号 (建议跟 CHANGELOG 同步)

同样在 `EssexBot/.env` 里:

```
WOWS_BOT_VERSION=1.3.0
```

NoneBot 启动时 dotenv 会把 .env 里的键全部塞进 `os.environ`,所以这个变量
同时被 **菜单 footer** (`plugin/version.py` → `version_str()`) 和
**战报 / 复盘 PNG footer** (`report/bin/render_*.py` 读 `WOWS_BOT_VERSION`) 共用,
不会出现菜单 v1.3.0、战报 v1.2.0 之类的不一致。

没设这一行时,`plugin/version.py` 兜底用 `_DEFAULT_VERSION` (代码里最新发布号),
战报 footer 直接不显示版本字段。日常发版只改这一行 + `sudo systemctl restart wows-bot` 即可,
不必动代码。

### 7.2 6 个 feature 开关

每个聊天 (群 / 私聊) 独立开关,默认值见 `plugin/permissions.DEFAULT_ENABLED`:

- `视频` (默认开) —— MP4 战斗回放
- `战报` (默认开) —— 全队成绩单 PNG
- `复盘` (默认开) —— 主角伤害分布 PNG
- `分析` (默认关) —— DeepSeek 文字复盘 (需 §5.3 配 key)
- `战犯` (默认关) —— 败方战犯榜 PNG
- `聊天` (默认关) —— 本局聊天记录 + 击杀时间轴 PNG

群管 / 群主 / 超管可用 `/视频 开|关|状态`、`/战报 开|关|状态` 等命令切换本群。
丢一份 `.wowsreplay` 进群时,bot 只跑当前**开着的**输出 —— 全关就静默跳过。

### 7.3 超管命令 `/sa` + 其它超管命令

```
/sa list                                # 看全局黑名单
/sa ban <视频|战报|复盘|分析|战犯|聊天>  # 全局禁用某 feature (所有群都开不了)
/sa unban <feature>                     # 解禁
/sa stats                               # 各 feature 在所有群里的开关分布
```

其它仅超管可见的命令:

- `/渲染模式 cpu|gpu|状态` —— 切换 MP4 渲染后端 (默认 CPU;有 GPU 且驱动装好切 gpu 更快)
- `/用户统计` —— 触发过非菜单功能的用户榜 PNG (**已排除超管自身**,避免调试污染指标)
- `/全群公告 <文本>` / `/定向公告 <群号> <文本>` —— 广播 (见 §5.2.1 白名单配置)

### 7.4 状态文件

位置: `<WOWS_REPLAY_BASEDIR>/toggle_state.json` (默认 `~/wows-bot-replay/toggle_state.json`)。
可用 `WOWS_TOGGLE_FILE` env 完全自定义路径。

格式见 `plugin/permissions.py` 顶部 docstring。Bot 启动时如果发现同目录有老的 `analyze_toggle.json`,会自动迁移:

- 读出来,把每条 `g:xxx → true|false` 翻译成 `groups["xxx"].分析 = true|false`
- 写新的 `toggle_state.json`
- 把旧文件改名 `analyze_toggle.json.bak`

迁移是幂等的(目标文件存在就跳过),多次重启不会反复折腾。

### 7.5 菜单触发

- 用户发 `/菜单`、`/menu` 或 `/help` —— 任意群/私聊都回一张菜单 PNG (显示本群 4 个开关当前状态)
- Bot 被拉进新群 —— 自动延迟 1 秒发一次菜单当自我介绍
- 用户在群里 **只 @bot** 且没附别的内容 —— 同样回菜单

## 8. 已知限制

### 8.1 不支持 RU 服 (Lesta «Мир кораблей»)

WG 2022 年退出俄罗斯,把俄区业务卖给 Lesta Games,后者独立开发 «Мир кораблей»
(原 World of Warships RU 客户端),从此 RU 服跟 WG 国际服 (CN/Asia/EU/NA)
**协议、GameParams、消耗品 ID、Ribbon ID 全部分叉**。

我们用的 `wows-toolkit` 上游 (landaire/wows-toolkit) 没有针对 Lesta 的适配,
源码零 region 分支、零 Lesta 相关 commit、零 Lesta replay 测试,
解析 RU replay 大概率挂或者输出乱码。

支持 WG 国际服:
- ✓ CN (Lesta CN 之外的 360 / WeGame / NetEase 等渠道)
- ✓ Asia
- ✓ EU
- ✓ NA (未实测,但跟 CN/Asia 同协议)

短期不计划支持 RU。如果你是 Lesta 用户想自己适配:需要 dump 一份 Lesta
客户端的 `extracted/`,自己造 `constants.json`,然后 fork wows-toolkit 跟
Lesta 协议演进 — 工作量中等偏大,不建议作为本仓库的目标。

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

## 公共层 `report/lib/wowsbot/`

bot 的 Python 公共层。路径/配置、回放元数据、主题、文本、翻译、结算字段各一个模块。

- **谁在用**:`plugin/*`(nonebot 环境)、`report/bin/*`(venv 环境)、`tools/*`。
- **怎么被找到**:纯 `sys.path`,不需要 pip install(运行时存在多个 Python 环境,
  见 `wows_report::find_python`)。`report/bin/*` 与 `tools/*` 用相对路径;
  `plugin/*` 因为会被 `cp` 到 EssexBot 目录,靠 `WOWS_BOT_HOME`(默认 `/opt/wows-bot`)。
- **硬约束**:`wowsbot/` 内不 import `nonebot`、不 `subprocess`、不做 PIL 绘图 ——
  否则三类环境无法共用。CI/收尾验证里有 grep 断言。
- **env 变量**:全部在 `wowsbot/paths.py` 里集中声明(名字与历史完全兼容)。
  加新路径请只改那里,不要在别处再写 `os.environ.get`。
- **注意 `BOT_HOME` 的历史含义冲突**:老代码里它在 `report/bin/*` 指 `report/`、
  在 `tools/*` 指仓库根。新代码用 `paths.REPO_ROOT` / `paths.REPORT_ROOT`,别再用这个名字。
