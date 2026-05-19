# wows_report_bot

从战舰世界（WoWs）的 `.wowsreplay` 回放文件生成中文战报 PNG，便于 QQ 机器人调用。

## 数据流

```
.wowsreplay (15.x+，Asia 服 / CN 服都支持)
   → replayshark (Rust)           输出 JSON（每人战绩、死亡、聊天）
   → render_battle_report.py (PIL) 输出 PNG（深色游戏风战报）
```

PNG 包含：双队完整战绩表（击杀 / 击伤 / 侦查 / 潜在 / 裸经验 / 血量 / 死因 / 凶手 / 成就图标），死亡时间轴，回放主角个人战绩区。

## 目录结构

```
wows_report_bot/
├── bin/
│   ├── wows_report                # 主入口（Python）
│   └── render_battle_report.py    # PNG 渲染器
├── data/                          # 长期资源（很少变）
│   ├── achievement_icons/         # ~400 张成就图标
│   ├── achievements.json          # ID → index 映射
│   ├── constants.json             # 结算字段下标表
│   └── zh_sg.mo                   # 中文翻译 gettext 词条
├── specs/                         # 每个大版本一次（家里跑 update_specs.py 后 scp 上来）
│   ├── metadata.toml              # 版本号 + build 号
│   ├── scripts/                   # entity 定义 XML
│   └── content/GameParams.data    # 船 / 成就参数字典
├── tools/
│   ├── update_specs.py            # 从 wowsinfo/data 拉最新 specs
│   └── replayshark_battle_report.patch
├── replayshark                    # Rust 二进制（每个平台单独 build，见 DEPLOY.md）
└── venv/                          # Python 虚拟环境（每个平台单独建，见 DEPLOY.md）
```

## 快速调用

`DEPLOY.md` 一次性配好 Linux 后：

```bash
/path/to/wows_report_bot/bin/wows_report /path/to/replay.wowsreplay [输出目录]
# stdout 最后一行 = 生成的 PNG 绝对路径
```

## 工作流程

| 频率 | 在哪 | 干什么 |
|---|---|---|
| 一次 | Linux bot 主机 | 跟 **DEPLOY.md** 部署（装 Rust、build replayshark、建 venv） |
| WoWs 每次大版本更新 | 家里 Win/Mac | 跑 `tools/update_specs.py`，然后 `scp specs_out/ → bot:specs/` |
| 每次玩家请求战报 | Linux bot | subprocess 调 `bin/wows_report` |

更多见 `DEPLOY.md` 和 `UPDATE.md`。
