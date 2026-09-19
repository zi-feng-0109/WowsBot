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
# ⚠️ 这条 cp 会把仓库里的 prebuilt 装成正在用的二进制。若当前处于回滚状态
#    (见下面「回滚」),它会静默把被回滚掉的那一版装回去 —— 先确认 prebuilt 是你要的那版。
sudo cp /opt/wows-bot/report/prebuilt/replayshark-linux-x86_64 /opt/wows-bot/report/replayshark
sudo chmod +x /opt/wows-bot/report/replayshark
# 验证: ls -la /opt/wows-bot/report/replayshark
#   时间戳应该是刚 cp 的;大小 5919456 = 2026-09-19 重建版,4806528 = 2026-05-27 旧版
#
# 从源码重编 (架构非 x86_64 / 想自己验证): **见 docs/REPLAYSHARK_BUILD.md**,
# 不要照老办法 `cd /opt/wows-toolkit && git pull && git apply` —— 那条路现在三点全错:
#   1. /opt/wows-toolkit 是禁止的构建位置,它的 target/release/minimap_renderer 是
#      生产在用的小地图二进制;tools/build_replayshark.sh 对这个路径有硬性拒绝
#   2. 必须先 `git checkout 2effcd31`(上游 2026-06-05 的 fbc415d5 删掉了 patch 挂靠的
#      BattleController,对当前上游套 patch 必然 22 个 hunk 挂 13 个)
#   3. 要套**两个** patch:先 replayshark_float64.patch 再 replayshark_battle_report.patch。
#      少了前者,编出来的二进制不认 FLOAT64,等于退回「每版手工改数据」的时代
# 正确做法就一条:  sudo bash /opt/wows-bot/tools/build_replayshark.sh

# 回滚到 2026-05-27 旧版 (仅在新版出问题时):
#   sudo cp /root/replayshark-prebuilt-20260527.bak /opt/wows-bot/report/replayshark
# 不需要重启任何服务 (渲染器是 subprocess 现拉)。
# ⚠️ 这只改了**部署副本**。仓库里 report/prebuilt/ 那份仍是新版,所以下次任何人走上面
#    那条 cp、或 DEPLOY.md §4.1,都会把新版装回来。要让回滚持久,还得二选一:
#      a) git revert 换装那次提交 (0c1bf7a),让仓库里的 prebuilt 也回到旧版;或
#      b) sudo cp /root/replayshark-prebuilt-20260527.bak \
#             /opt/wows-bot/report/prebuilt/replayshark-linux-x86_64   (会让工作区变脏)

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
# 必须显式指定版本目录! 见下面的警告
sudo bash /opt/wows-bot/tools/link_specs.sh /var/lib/wows-data/extracted/<新 version>_<新 build>
```

> ⚠️ **不要裸跑 `link_specs.sh`。** 它挑的是 `sort -V | tail -1`,也就是版本号最大的子目录 ——
> 而 Lesta(俄服)的版本号是 `26.x`,比 WG 的 `15.x` 大。裸跑会把 WG 战报的 specs
> 错指到 Lesta 数据上。**始终带上 WG 的版本目录参数。**
>
> 影响面其实很小:`report/specs` 现在只有「回放 build 号恰好等于软链指向的 build」这一条
> 快路径在用;对不上时 `wows_report` 的 `resolve_specs_for_build()` 会按 build 号自己去
> `extracted/` 里找对应版本。MP4 / Lesta / 聊天从来不看 `report/specs`。
> 但 §2.5 的 `build_builds_json.py` / `fetch_build_icons.py` 默认读的就是它,所以还是要指对。

bot 不用重启 (renderer 是 subprocess,每次新拉)。

> **关于 FLOAT64 手术:已经不需要了。** 15.7~15.8 期间,每个大版本都要给旧 replayshark
> 单独做一份 scripts 副本、把 `FLOAT64` sed 成 `FLOAT`,否则它会 panic
> `Unrecognized type FLOAT64`。2026-09-19 重建了 replayshark(原生支持 FLOAT64),
> 这一步从此取消。`/var/lib/wows-data/specs-patched/` 下已有的手术产物留着不碰即可
> (`resolve_specs_for_build()` 仍会优先用它们,无害)。
> 重建配方与「下次 WG 又加新实体类型怎么办」见 [REPLAYSHARK_BUILD.md](REPLAYSHARK_BUILD.md)。

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

### 2.6 刷新 ships.json + 战舰预览图 (/船 战舰数值卡用)

```bash
cd /opt/wows-bot
# 需要 WG application_id (developers.wargaming.net 免费申请,仅构建期用,运行时 bot 不碰)
export WOWS_WG_APP_ID=<你的 application_id>

# 生成 ships.json (GameParams unpickle + WG API 数值 + zh_sg.mo 中文名 三源 join)
sudo -E python3 tools/build_ships_json.py
# 产物:report/data/ships.json (~1.2 MB,~960 船)
# 多船体老船会并发走 shipprofile 拿满配,跑 ~4 分钟 (含 ~300 次请求)

# 拉战舰预览图 (从 WG wgcdn,文件名按 ship index)
sudo -E python3 tools/fetch_ship_icons.py
# 产物:report/data/ship_icons/ (~960 张 medium 渲染图,~17 MB)
# 已存在的会跳过,加 --force 强刷
```

跳过会让 `/船` 提示"战舰数据未生成";只缺预览图则卡片不贴船图,数值照出。
bot 重启后才会重新 load ships.json (ship_index 启动时读一次)。

### 2.7 刷新 armor.json (/船 <名> 装甲 装甲分面图用)

装甲厚度只能从本地客户端 GameParams 解析(WG API 无此数据),用 replayshark
的 armor-dump 子命令产出:

```bash
replayshark.exe --extracted <GameParams 目录,如 extracted/15.4.0_xxxx> \
  armor-dump -o report/data/armor.json
```

缺这步只影响 `/船 <名> 装甲`(会回「暂无装甲数据」);`/船 <名>` 数值卡不受影响。

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
