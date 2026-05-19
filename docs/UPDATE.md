# UPDATE.md — WoWs 大版本更新后刷新数据

游戏出大版本 (15.3 → 15.4 之类) 后,bot 拿到新版本回放会爆解析错误,
要刷新两份数据:

1. **战报 specs** — 给 `report/bin/wows_full_report` 用 (`report/specs/`)
2. **MP4 extracted** — 给 `minimap/render.sh` 用 (`/var/lib/wows-data/extracted/`)

> 小 build 号变动 (同大版本 Asia ↔ CN 服) `wows_full_report` 自带 auto-spoof 通常能处理,
> 不一定要重刷。MP4 那边没这个机制,差太多就重刷一次。

## 战报 specs

### 方案 A:本地拉 (推荐)

适合你 Windows 上有 wows-toolkit GUI 解包过 (产物在 `%APPDATA%\wows-toolkit\game_data\builds\<build>\`),
或者干脆有 `vfs/scripts/` + `vfs/content/GameParams.data` 这种布局的解包目录。

```powershell
# 1. (Windows) 在仓库根目录跑
python tools\build_specs_from_local.py
# 默认从 C:\Users\<you>\Desktop\minimap\extracted\<version>_<build>\ 抽
# 不是这条路径就改脚本里的 EXTRACTED_ROOT

# 2. 检查
cat specs_out\metadata.toml

# 3. scp 上服务器
scp -r specs_out user@bot主机:/tmp/
```

```bash
# 4. (服务器) 替换
rm -rf /opt/wows-bot/report/specs/{content,scripts,metadata.toml}
mv /tmp/specs_out/* /opt/wows-bot/report/specs/ && rmdir /tmp/specs_out
cat /opt/wows-bot/report/specs/metadata.toml
```

### 方案 B:服务器联网拉

直接在 Linux 跑 (要能访问 GitHub):

```bash
cd /opt/wows-bot
python3 tools/update_specs.py    # 生成 specs_out/
rm -rf report/specs/{content,scripts,metadata.toml}
mv specs_out/* report/specs/ && rmdir specs_out
```

国内走镜像 (任选):

```bash
python3 tools/update_specs.py --repo https://gitclone.com/github.com/wowsinfo/data.git
# 或
python3 tools/update_specs.py --repo https://ghfast.top/https://github.com/wowsinfo/data.git
```

## MP4 extracted

Windows 上用 wows-toolkit 自带的 `wows-data-mgr` CLI (见 DEPLOY.md 3.2,首次部署做过的话以后只需重复 dump 那一步):

```powershell
cd C:\wows-toolkit
# WoWs 自动更新到新版本后,本地安装路径不变,直接重新 dump:
.\target\release\wows-data-mgr.exe dump-renderer-data --latest -o .\extracted
# 产物会出现一个新的 <新 version>_<新 build>\

# scp 到服务器
scp -r .\extracted\<新 version>_<新 build> <user>@<bot-host>:/var/lib/wows-data/extracted/
```

`/var/lib/wows-data/extracted/` 下可以同时留多个 `<version>_<build>` 子目录,
`minimap_renderer` 会按回放的 build 号自动选对应的。老版本想清理直接删对应子目录即可。

## 在 bot 主机验证

```bash
# 战报
/opt/wows-bot/report/bin/wows_full_report /tmp/最新回放.wowsreplay /tmp/test_out
# stderr 不应该再出现 "[spoof] ..." (版本对得上)

# MP4
/opt/wows-bot/minimap/render.sh /tmp/最新回放.wowsreplay /tmp/test.mp4
```

两个都跑通就行,bot 不用重启 (renderer 是 subprocess,每次新拉)。
