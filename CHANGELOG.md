# 更新日志 / CHANGELOG

本项目大致遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 和
[Semantic Versioning](https://semver.org/lang/zh-CN/)。

bot 实际跑哪个版本由 NoneBot `.env` 里的 `WOWS_BOT_VERSION=...` 决定
(同时影响菜单 footer 和 战报/复盘 PNG footer,见 `docs/DEPLOY.md` §7.1.1)。
没配的话 `plugin/version.py` 里的 `_DEFAULT_VERSION` 兜底。

发版流程:
1. 改一下 `plugin/version.py` 里的 `_DEFAULT_VERSION`,跟最新一行 CHANGELOG 一致。
2. 服务器 `EssexBot/.env` 里改 `WOWS_BOT_VERSION=<新版>`。
3. `git pull` → `cp /opt/wows-bot/plugin/*.py ~zifeng/桌面/bot/EssexBot/src/plugins/` → `systemctl restart wows-bot`。
   (只动 `report/bin/*` 的话不用 cp、不用重启,subprocess 现拉。详见 `docs/UPDATE.md` §0.4)

---

## [1.1.0] - 2026-05-27

### 新增

- **`/全群公告` `/定向公告` 公告插件 (`plugin/announcement.py`)**
  之前一直只在生产 NoneBot 项目里散养,这次正式纳入 wows-bot 仓库,跟其它
  `plugin/*.py` 一起走 `git pull` + `cp` 流程。
  - `/全群公告 <内容>` (别名 `/广播` `/公告`):向 bot 所在的全部群广播。
  - `/定向公告 <群号1> [群号2] ... <内容>` (别名 `/指定公告`):只发指定群。
  - **公告内容支持文字 + 图片 + QQ 表情混排**(这一版相对早期纯文字版本的主要升级)。
    解析方式从 `str(args)` 改成遍历 MessageSegment,保留 `text/image/face`,
    自动剔掉 `at/reply` 段 —— 否则群里 `@机器人 /公告 ...` 的 @ 会跟着公告
    一起被广播出去。
  - 超管名单独立维护在 NoneBot 项目根的 `data/admins.json`(一个 QQ 号 JSON 数组),
    不复用 NoneBot `SUPERUSERS`,避免"能调试 bot"和"能向全部群发消息"被同一份名单覆盖。
  - 部署见 `docs/DEPLOY.md` §5.2 + §5.2.1。

### 部署

- 服务器侧:`cd /opt/wows-bot && sudo git pull` + `sudo cp plugin/*.py ~zifeng/桌面/bot/EssexBot/src/plugins/` +
  在 `EssexBot/.env` 改 `WOWS_BOT_VERSION=1.1.0` + `systemctl restart wows-bot`。
- 首次启用公告功能要建 `~zifeng/桌面/bot/EssexBot/data/admins.json` 并填超管 QQ 号(见 DEPLOY.md §5.2.1)。
  之前已经在用本地 `announcement.py` 的话,`admins.json` 已经存在,直接 `cp` 覆盖插件即可。

---

## [1.0.1] - 2026-05-22

### 修复

- **`/菜单` `/menu` `/help` 三个别名都没反应** (`93a0d3b`)
  `on_command(("菜单","menu","help"))` 元组形式被 NoneBot 当作**嵌套子命令路径**
  (要 `/菜单 menu help` 才触发) 而不是别名。改用关键字 `aliases={"menu","help"}` 注册,
  三个名字才都能直接触发。

- **20 min 打满的对局战犯榜不出图** (`eabc99e`)
  战报本身在 `9d091a8` 里加了 timeout → 按 `team_scores` 推断胜方 的兜底,
  但只改了 `render_battle_report.py` 内的局部变量,没回写 JSON。
  `render_criminals.py` 独立从 JSON 读 `battle_result.team_id`,timeout 时
  仍然是 `None` → 直接 `return []` 当成平局跳过。补同源兜底:同分仍跳,
  不同分按 `team_scores` 推胜方。

- **战犯榜伤害和战报对不上** (`be230a6`)
  典型案例:撞沉对方的"马萨诸塞 B"在战报里显示 8 万+ 总伤,战犯榜里只有 7 千+。
  差额 = 撞击伤害。
  根因:两边读不同字段 —— 战报优先用 `results_info.damage` (WG 服务器结算的权威总伤,
  含撞击 / 火灾 / 洪水等所有 DOT),战犯只读 `stats.damage_dealt`
  (replayshark 从 `damage_events` 累加,不含 ramming)。
  改成跟战报同源:`results_info.damage` 优先,缺失才回退到 `stats.damage_dealt`。

### 新增

- **`WOWS_BOT_VERSION` env 化版本号** (本次)
  `plugin/version.py` 改为读 `os.environ.get("WOWS_BOT_VERSION")`,
  兜底 `_DEFAULT_VERSION = "1.0.1"`。今后发小版本只动 .env + 重启即可,
  不必每次 push 代码到 gitee。

### 部署

- 服务器侧:`git pull` + `cp plugin/*.py` (因为 `version.py` 改了) +
  在 `EssexBot/.env` 追加 `WOWS_BOT_VERSION=1.0.1` + `systemctl restart wows-bot`。
- 只想验证战犯 fix:`cd /opt/wows-bot && sudo git pull` 即可
  (`report/bin/*` 是 subprocess,每次现拉,不用重启)。

---

## [1.0.0] - 2026-05-21 (基线)

把"接 replay → 出 MP4 + 战报 + 复盘 + LLM 分析"那条主线之外的几个长期功能
统一收口到 1.0:菜单、群级开关、战犯榜、玩家查询。代码上很多是更早就在了 ——
这一版只是给"对外发布"画个起跑线。

### 新增

- **`/查询` 玩家生涯水平查询** (`637a676` `5ad8067` `444d59b` `1c0b2d5` `4ce1ddc` `453de5d`)
  - 引用一份战报消息 + `/查询 <编号>`,从 WG vortex 接口拉对应 IGN 的生涯数据 (战数/胜率/平均伤害/平均经验/主玩舰种 等),
    渲染成 PNG 卡片回复。
  - **全服直连 vortex**,不再依赖 WG application_id —— 包括 CN 服 (`vortex.korabli.su`) 也直接打通了。
    更早期版本曾因为 WG 把 CN 服 application_id 注册关了而 CN 服永远查不到,现在不存在这个问题。
  - **支持 RU 服 (Lesta «Мир кораблей»)** —— `vortex.korabli.su` 走 Lesta 自己的 vortex 域名,RU 玩家可查。
  - 文案区分"找不到该 IGN"(从来没玩过/拼错) vs"WG 接口超时/限流"(临时性),不再笼统一句"查询失败"。

- **`/菜单` `/menu` `/help`** + 全部指令权限标注 + 当前作用域开关一览
  (基线包含 `d23c02d` `1cb9de2` `1e2479c` `d0b9264` `5e071c1` `063b6f9` `88040ce` 等)
  渲染成 PNG 卡片,左侧本群开关 / 右侧超管全局黑名单两列对照,带 iOS 风 pill toggle。
  超管发命令额外能看到"超管命令"分区。

- **战犯榜独立 PNG** (基线 `1e2479c` `5d63bc8` `37006c9`)
  独立成第三张图,默认关闭 (`/战犯 开` 开启)。甲级独占放大占一整行,乙/丙/丁级并排第二行。
  CV 飞机消耗品检测只看 self-CV (`Avatar.squadronConsumableUsed` 是单播,
  友军 CV 看不到 —— 这是协议限制,不是漏判),footer 有脚注说明。

- **战报最左加全局编号 # 列** (`d03da7d`)
  `/查询 <编号>` 直接对应这一列,自己一队和对面一队连续编号 (1..N + N+1..2N)。

- **战报 / 复盘 PNG 底部加 footer** (`c3af34d` `0196872`)
  "本图由 EssexBot 渲染 · v1.0.0 · 作者 [NUIST]___Ciallo___ · 时间戳"。
  panel 底 + 金顶边 + 18pt 居中。版本号留空时不显示这段。

### 修复

- **打满 20 min 的对局战报误显示"平局"** (`9d091a8`)
  `replayshark` 把 `battle_result.team_id` 留空当平局,但实际只要 `team_scores` 有差就分胜负。
  战报渲染按分数推断兜底。
  (后续发现这个 fix 没回写 JSON,战犯榜读不到 —— v1.0.1 里补齐。)

### 部署 / 文档

- `docs/UPDATE.md` 整理 WoWs 大版本更新后的完整流程 (`8134865` `385ca4b`)
  含第 0 步 "Linux 拉最新 bot 代码 + cp plugin/*.py 到 NoneBot 项目目录",
  避免每次手忙脚乱。
- `docs/DEPLOY.md` §8 标明 RU 服 (Lesta) 限制 —— **此条 1.0.0 → 1.0.1 过渡期已自然失效**,
  因为 `453de5d` 把 RU vortex 接进来了 (CHANGELOG 维护人员注意:下次再开新版前
  顺手把那一节删掉 / 改写)。

### 已知问题 (后续版本处理)

- **战犯榜的"普通消耗品次数统计"也受视野限制**。游戏 `Consumable` ClientMethod 是
  broadcast 但带可见范围 —— 主角没见到的友/敌方消耗品就是没数据 (跟 CV 飞机消耗品同理,
  只是这块还没加视野检查)。1.0.1 暂时跳过,后面再处理 (要么显示 "?"、要么干脆不统计这一项)。
