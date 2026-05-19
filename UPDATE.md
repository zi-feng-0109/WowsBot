# UPDATE.md — WoWs 大版本更新后刷新数据

在家里随便哪台机器（Win/Mac/Linux，有 Python 3 + git + 能上 GitHub 即可）跑。

## 什么时候要跑

WoWs 出大版本（15.3 → 15.4 之类）以后。否则 bot 拿到新版本回放会爆解析错误。

> 同一大版本里小 build 号变动（比如 Asia ↔ CN 服）`bin/wows_report` 自带的
> auto-spoof 会自动处理，不一定要重新拉 specs。但更新一下更稳。

## 方案 A — 拉 wowsinfo/data 镜像（推荐）

任何系统都行，靠社区镜像（一般游戏发版 24 小时内更新）。

```bash
cd /path/to/wows_report_bot
python tools/update_specs.py        # 生成 specs_out/

# 检查一下
cat specs_out/metadata.toml         # 看版本 + build 对不对

# scp 到 Linux bot
scp -r specs_out/ user@bot主机:/tmp/specs_new/
ssh user@bot主机 '
    cd /path/to/wows_report_bot
    rm -rf specs/scripts specs/content specs/metadata.toml
    mv /tmp/specs_new/specs_out/* specs/
'
```

## 方案 B — 从本地 WoWs 安装提取（Win，最新鲜）

如果不想等社区镜像，可以用 wows-toolkit GUI（Windows 预编译版）跑一遍：
工具会自动从你的 WoWs 安装目录抽取数据到
`%APPDATA%\wows-toolkit\game_data\builds\<build>\`。

把那个目录按方案 A 输出的结构整一下（必须含 `scripts/` +
`content/GameParams.data` + `metadata.toml`）再 scp 上传。

## 在 bot 主机验证

```bash
./bin/wows_report /path/to/最新回放.wowsreplay
# stderr 不应该再出现 "[spoof] ..." 的日志（版本对得上）
```
