# B 站订阅 UP 主动态/直播功能 — 实现设计

> 状态:**设计待实现**(2026-06-12)。完全可以做,不依赖任何专有数据。
> 本档把今天的讨论 + 路线选型 + 关键技术决定都打包好,动手前不用再调研。

## 1. 目标

bot 提供 `/订阅 <UID或B站名>` 命令,本群/本会话订阅一个 B 站 UP 主。订阅后,
该 UP 主**发新动态(图文/视频/转发)/ 开播**时,bot 主动推到本群。

复用现有 `permissions` 模块控制权限(加/删 = 群主/群管/超管,看列表 = 任何人)。

## 2. 关键调研结论(2026-06-12 实测)

### 2.1 现成插件 HarukaBot 不能直接用
- 最后版本 v1.6.0.post5 发布于 2023-07-11,**近 2 年没更新**
- 实测它依赖的所有 API 都已被 B 站风控:
  | HarukaBot 核心接口 | 实测结果 |
  |---|---|
  | `polymer/web-dynamic/v1/feed/space`(动态) | **HTTP 412 风控** |
  | `space/wbi/acc/info`(直播状态) | **code -352 风控** |
  | `space/acc/info`(UP 信息) | **code -401 非法访问** |
  | `web-interface/card`(用户卡片,公开) | ✓ 还能用 |
- 装上去 90% 的命令直接报错,Issue #416 作者也承认了,**结论:走自写路线**

### 2.2 自写依赖
- **`bilibili-api-python`**(社区还活跃,2025 仍在更新):内置 wbi 签名 + Credential 类 + 自动 refresh,踩过的坑都填了
- 不要再用 SK-415 自己的 `bilireq`(同作者,跟 HarukaBot 一起停更)

## 3. 架构 & 命令

| 命令 | 作用 | 谁可用 |
|---|---|---|
| `/订阅 <UID或B站名>` | 本群加订阅 | 群主/群管/超管(`permissions.can_toggle`) |
| `/取消订阅 <UID或名>` | 本群删订阅 | 同上 |
| `/订阅列表` | 看本群订阅了谁 | 任何人 |

订阅默认**动态+直播都推**(简化,跟 `/船` 同款不分独立开关;以后真要可加)。

### 3.1 数据存储 `~/wows-bot-replay/bili_subs.json`

跟现有 `query_index.json` / `permissions.json` 同目录同模式:

```jsonc
{
  "groups": {
    "<group_id>": {
      "<uid>": {
        "name": "雷军",
        "added_at": 1718200000,
        "last_dyn_id": "987654321...",   // 已推过的最新动态 id
        "live_on": false                  // 上次轮询时是否在播
      }
    }
  },
  "private": { "<user_id>": { ... } }
}
```

### 3.2 轮询(NoneBot scheduler)

| 频率 | 接口 | 备注 |
|---|---|---|
| 90 s | `/x/polymer/web-dynamic/v1/feed/all`(关注的全部 UP 一次拉) | **批量** — 不逐 UP 调,免风控核心 |
| 30 s | `/room/v1/Room/get_status_info_by_uids` POST 多 UID | 批量直播状态 |

只推新增:`id > last_dyn_id` 或 `live_on false→true`。下播**不推**(免吵)。

## 4. 账号策略:挂 B 站小号 + 自动续 cookies(无限期)

### 4.1 为什么必须挂小号
2.1 实测确认:**完全匿名当下会被 412 风控**。不挂账号做不了。

### 4.2 浏览器为什么"不过期":自动续期机制
浏览器一直登着 B 站不需要重新登,因为每次请求时:
- 响应可能带新的 `Set-Cookie: SESSDATA=...`,浏览器吞下
- B 站有专门的 `cookie/info`(查需不需要刷新)+ `cookie/refresh`(主动刷新)端点

**bot 复刻这套 = SESSDATA 无限期**。`bilibili-api-python` 的 `Credential.check_refresh()` + `Credential.refresh()` 已经封好。

### 4.3 实现机制

```python
# 启动时
cred = load_from_file(BILI_COOKIE_FILE) or build_from_env(SESSDATA_env)

# 每次请求 (库层 hook)
save_to_file(cred)   # 接住可能下发的新 SESSDATA

# 每天 @scheduler 调一次
if await cred.check_refresh():
    await cred.refresh()
    save_to_file(cred)
```

### 4.4 部署体验
- **首次**:你提供一次 `WOWS_BILI_SESSDATA` env(B 站浏览器 F12 → Cookies → SESSDATA 那串值)
- **之后**:bot 把完整 cookies(SESSDATA + bili_jct + DedeUserID + refresh_token)存到
  `~/wows-bot-replay/bili_cookies.json`(权限 600),自动续期
- **你不用再管**(除非 B 站全量挤下线 / 账号被封停,这是另两件事)

### 4.5 用什么小号
- 实名认证过的、新或旧都行
- **别用主号**(轮询行为可能被风控关注,不影响登录但烦)
- 这个号本身不要做任何"敏感操作"(只用来给 bot 当 cookies 容器)

## 5. 风控规避三铁律(自写比 HarukaBot 强的地方)

1. **批量接口**:`feed/all` 一次拉所有订阅的动态,`get_status_info_by_uids` 一次查所有直播状态。**绝不逐 UP 调**(HarukaBot 的死穴就在这)
2. **指数退避**:连续 412/-352 → 暂停 5 / 15 / 60 分钟,不死磕
3. **缓存优先**:已推送的 `dyn_id` 入 set,绝不重推

## 6. 推送内容

### 6.1 动态
- 文本 + B 站动态自带的图(多图按 QQ 合并消息)+ 动态链接
- 视频动态额外:封面 + 标题 + 链接
- 转发动态:写"转发了 XXX 的动态: ..." + 原动态简要

### 6.2 直播开播
- "✓ <name> 开播了\n房间标题\n[封面图]\nhttps://live.bilibili.com/<room>"
- 下播不推

## 7. 文件清单

- 新 `plugin/bili_subs.py` — 数据层(load/save bili_subs.json,加/删/查 订阅)
- 新 `plugin/bili_client.py` — bilibili-api-python 封装 + cookies 持久化/续期
- 新 `plugin/bili_poll.py` — 轮询器(@scheduler,推送 logic)
- 改 `plugin/minimap.py` — 加 3 个命令 handler;启动 init
- 改 `report/bin/render_menu.py` — 菜单加 /订阅 /取消订阅 /订阅列表 行
- 改 `docs/DEPLOY.md` — 新增 §5.5 "B 站订阅 cookies",说明 SESSDATA env + 自动续期
- 改 `requirements.txt` / `pyproject.toml` — 加 `bilibili-api-python`,`nonebot-plugin-apscheduler`

## 8. 风险 & 边界

- **小号被封停**(非过期):cookies 续不动,bot 日志报错。换号即可,数据不丢。
- **B 站接口大改**:bilibili-api-python 跟得勤,跟着升级版本就行;HarukaBot 那种 2 年不动的不会发生。
- **图片下载失败**:动态封面/直播封面下不到 → 文本 + 链接照常推,封面降级。
- **轮询频率**:90s/30s 已经非常温和。如果哪天 412 仍频发,改成 120s/60s。

## 9. 验证步骤

1. **登录 cookies**:`export WOWS_BILI_SESSDATA=<...>` → 跑 `python plugin/bili_client.py` 验证能拉到自己的 `me/info`。
2. **续期**:首次跑后 cookies 文件应自动生成;手动改文件里的 SESSDATA 一个字符制造"过期",再跑应触发 refresh。
3. **批量接口**:验证 feed/all 能拿到多 UP 动态混合流;get_status_info_by_uids 多 UID 一次返回。
4. **bot 联调**:`/订阅 雷军`、`/订阅 2329183`(同人 UID)、`/订阅列表`、`/取消订阅 雷军`;手工往 bili_subs.json 灌一条临过期 last_dyn_id 看是否会推一次;等真开播一次看直播推送。
5. **风控演练**:把轮询频率降到 5s 强压几小时,看 412 出现时退避机制是否生效(应静默暂停,不刷屏)。

## 10. 仍然简单的几条

- **不做 @全体成员**(腾讯有 10 次/天限额,容易招麻烦,纯文本推送够用)
- **不做截图式渲染**(playwright/headless 浏览器太重;B 站动态自带图够看)
- **不做"动态/直播单独开关"**(简化;真要再加)
