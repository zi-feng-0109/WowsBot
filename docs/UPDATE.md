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

## MP4 extracted

Windows 上用 wows-toolkit GUI 解一遍 (会从你的 WoWs 安装目录抽数据出来),
默认产物在 `%APPDATA%\wows-toolkit\game_data\builds\<build>\`。
整个目录 scp 到服务器:

```powershell
scp -r %APPDATA%\wows-toolkit\game_data\builds\<新 build> user@bot主机:/var/lib/wows-data/extracted/
```

或者你 `/var/lib/wows-data/extracted/` 是个版本目录的爹,
能保留多个版本时 `render.sh` 默认 `WOWS_DATA_DIR` 指向那个爹,具体看 `minimap/render.sh` 里默认值和 wows-toolkit 的目录约定。

## 在 bot 主机验证

```bash
# 战报
/opt/wows-bot/report/bin/wows_full_report /tmp/最新回放.wowsreplay /tmp/test_out
# stderr 不应该再出现 "[spoof] ..." (版本对得上)

# MP4
/opt/wows-bot/minimap/render.sh /tmp/最新回放.wowsreplay /tmp/test.mp4
```

两个都跑通就行,bot 不用重启 (renderer 是 subprocess,每次新拉)。
