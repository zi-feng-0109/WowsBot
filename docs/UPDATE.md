# UPDATE.md — WoWs 大版本更新后刷新数据

游戏出大版本 (15.3 → 15.4 之类) 后,bot 拿到新版本回放会爆解析错误,
要把新版本 extracted 数据传到服务器,然后改一下 specs 软链指向新版本。

> 同一大版本里小 build 号变动 (Asia ↔ CN 服) 战报渲染器自带 auto-spoof
> 通常能处理,不一定要重刷;但更新一下最稳。

## 完整流程

### 0. Linux: 拉最新 bot 代码 (顺手做,新版本期间 bot 仓库经常也有适配 commit)

```bash
# 0.1 拉源仓库
cd /opt/wows-bot
sudo git pull

# 0.2 同步 plugin/*.py 到 NoneBot 项目 (DEPLOY.md §5.2 强调不能用软链)
# 把下面路径改成你的 NoneBot 项目实际位置, e.g. ~zifeng/桌面/bot/EssexBot/src/plugin
NB_PLUGIN_DIR=~zifeng/桌面/bot/EssexBot/src/plugin
sudo cp /opt/wows-bot/plugin/*.py "$NB_PLUGIN_DIR/"
# (现在有 minimap.py / permissions.py / version.py 三个文件,*.py 一把全 cp)

# 0.3 若 tools/replayshark_battle_report.patch 跟着更新了 (commit 里会写),
# 用预编译二进制最简单 (前提:作者推前已重编 prebuilt):
#
# 注意路径! wows_report 里 BOT_HOME = parent.parent = /opt/wows-bot/report
# (脚本本身在 /opt/wows-bot/report/bin/ 下),所以默认 REPLAYSHARK 路径是
# /opt/wows-bot/report/replayshark 而不是 /opt/wows-bot/replayshark。
sudo cp /opt/wows-bot/report/prebuilt/replayshark-linux-x86_64 /opt/wows-bot/report/replayshark
sudo chmod +x /opt/wows-bot/report/replayshark
# 验证现在在用哪个: ls -la /opt/wows-bot/report/replayshark — 时间戳应该是刚 cp 的
# 或者从源码重编 (架构非 x86_64 / 想自己验证):
#   cd /opt/wows-toolkit && sudo git checkout . && sudo git pull
#   sudo git apply /opt/wows-bot/tools/replayshark_battle_report.patch
#   sudo cargo build --release -p replayshark
#   sudo cp target/release/replayshark /opt/wows-bot/report/replayshark

# 0.4 plugin/* 改了要重启 bot;只改了 report/bin/* 或 specs 软链不用重启 (subprocess 现拉)。
sudo systemctl restart wows-bot   # 改成你的 service 名,或者 kill+nb run
```

### 1. Windows: dump 新版本

```powershell
cd C:\wows-toolkit
# WoWs 自动更新到新版本后,本地安装路径不变,直接重新 dump:
.\target\release\wows-data-mgr.exe dump-renderer-data --latest -o .\extracted
# 产物会出现一个新的 <新 version>_<新 build>\

# scp 到服务器 (改成新版本号)
scp -r .\extracted\<新 version>_<新 build> <user>@<bot-host>:/var/lib/wows-data/extracted/
```

### 2. Linux: 改 specs 软链指向新版本

```bash
sudo bash /opt/wows-bot/tools/link_specs.sh
# 默认重新挑 /var/lib/wows-data/extracted/ 下版本号最大的子目录,改三条软链
```

bot 不用重启 (renderer 是 subprocess,每次新拉)。

### 2.5 刷新 builds.json + 升级/技能图标 (/查询 PNG 本局配装面板用)

```bash
cd /opt/wows-bot
# 依赖 polib (pip install polib),已包含在 requirements 里
sudo python3 tools/build_builds_json.py
# 产物:report/data/builds.json (~130 KB)
# 输出会打印 modernization/exterior/crew/skill 各类的条目数和翻译缺失数

# 拉升级/技能图标 (从 wowsinfo/data 镜像 master 分支)
sudo python3 tools/fetch_build_icons.py
# 产物:report/data/upgrade_icons/ (~120 张) + skill_icons/ (~85 张),~800 KB
# 已存在的会跳过,加 --force 强刷
```

跳过会让 `/查询` 的"本局配装"块走兜底(灰色方块 + 文字截 2 字),功能不挂。

### 3. 验证

```bash
# 战报
/opt/wows-bot/report/bin/wows_full_report /tmp/最新回放.wowsreplay /tmp/test_out
# stderr 不应该再出现 "[spoof] ..." (版本对得上)

# MP4
/opt/wows-bot/minimap/render.sh /tmp/最新回放.wowsreplay /tmp/test.mp4
```

## 多版本并存

`/var/lib/wows-data/extracted/` 下可以同时留多个 `<version>_<build>` 子目录:

```
/var/lib/wows-data/extracted/
├── 15.3.0_12267945/
└── 15.4.0_12345678/
```

- MP4 渲染器 (`minimap_renderer`) 会按回放的 build 号自动选对应版本
- 战报渲染器只看 `report/specs/` 软链指向的那个 (默认最新);
  要切某个老版本测试:`sudo bash link_specs.sh /var/lib/wows-data/extracted/15.3.0_12267945`

老版本不要了,直接 `sudo rm -rf /var/lib/wows-data/extracted/<旧版本>`,
然后 `sudo bash link_specs.sh` 确认软链没指向被删的目录即可。

## 备用方案: build_specs_from_local.py

不想用软链 (比如想给战报渲染器独立打包一份 specs) 时,可以用
`tools/build_specs_from_local.py` 从 Windows 上的 extracted 拷出一份 specs_out,
再 scp 上来覆盖 `report/specs/`。详见脚本 `--help`。日常更新场景不需要这条路径。
