# P4-2:WoWs 大版本更新流程自动化

2026-09-19

前置:[P4-1 重建 replayshark](2026-09-19-replayshark-rebuild-design.md) 已消灭 FLOAT64 手术,
本流程比 15.7/15.8 时期短了一整步。

## 背景

WoWs 出大版本后,玩家上传新版本回放会解析失败。要让机器人重新工作,现在得手工做这些:

```
Windows: wows-data-mgr dump-renderer-data … → 检查产物 → scp 到服务器
Linux:   link_specs.sh <显式版本目录> → build_builds_json.py → fetch_build_icons.py → 验证
```

问题不在步骤多,在于**每一步都有一个只有做过才知道的坑**:

- `dump-renderer-data` 遇到未知实体类型时会**静默跳过 GameParams 重新派生,只打一行 WARN,
  仍然 exit 0** —— 产出的 extracted 缺 `game_params.rkyv`(船名/船只数据全无)。15.7 那次就是
  这么中招的,不盯日志发现不了
- `link_specs.sh` 裸跑挑版本号最大的子目录,而 Lesta 是 `26.x` > WG 的 `15.x`,会把 WG 战报的
  specs 错指到 Lesta 数据
- 客户端可能是公开测试服或国服(build 体系独立),从它提数据只会污染数据集

所以这件事的价值不只是"少敲几条命令",而是**把这些坑变成脚本里的硬性校验**。

## 目标

1. PC 侧一个一键脚本:提数据 → 校验 → 上传。校验不过就**停,不上传**
2. 服务器侧一个超管 QQ 指令 `/更新wg版本`:拉代码 → 搬数据 → 软链 → 刷 builds.json 与图标 → 汇报
3. 管理员手工要做的只剩三件:更新游戏、双击脚本、发指令

## 非目标

- 不自动重启 nonebot。`plugin/*.py` 有变动时只在汇报里提示,由人决定
- 不自动删旧版本数据。只在汇报里带上版本数与磁盘占用 —— 旧版本回放还在被玩家上传,删了就解析不了
- 不碰 `minimap.py`。它已 1658 行 / 约 15 个职责,拆它是 P3 的事;新功能进独立模块
- 不做 Lesta 侧的自动化。Lesta 数据来源与节奏不同,等有需要再说
- PC 侧不往 git 推任何东西。数据走 scp,仓库只承载代码

## 架构

两段式,中间隔一个**暂存区** `/var/lib/wows-data/incoming/`。

```
[Windows]                          [服务器]
update_wg.bat                      /更新wg版本 (QQ 超管指令)
  认 build / 校验区服                 扫 incoming 找带标记的版本
  提数据                             git pull + 同步 plugin
  校验产物 ──失败→ 停                 复校验 ──失败→ 停
  scp → incoming/<ver>_<build>/      mv → extracted/<ver>_<build>/
  写 <ver>_<build>.done 标记         link_specs(显式指版本)
  提示去发指令                        builds.json + 图标
                                    汇报
```

**为什么要暂存区**:渲染器是按 build 号扫 `extracted/` 目录的。294MB 的 scp 传到一半断了,
而此时正好有玩家发新版本回放,就会挑中那个半截目录然后诡异报错。走暂存区 + 完成标记,
这种情况不可能发生。

**为什么 `mv` 而不是 `cp`**:`incoming/` 与 `extracted/` 在同一文件系统,`mv` 是 rename,
瞬间完成。若将来不在同一 fs,会退化成 294MB 复制 —— 仍然正确,但脚本要提示。

## 组件

### 1. `tools/update_wg.bat`(PC 侧,管理员运行)

一个 `.bat` 外壳 + 内嵌 PowerShell 干活(`.bat` 双击即跑、不受 ExecutionPolicy 限制、
跑完 `pause` 留窗口看结果)。配置写在文件顶部,可用环境变量覆盖:

| 变量 | 默认 |
|---|---|
| `WOWS_GAME_DIR` | `C:\Program Files (x86)\Steam\steamapps\common\World of Warships` |
| `WOWS_DATA_MGR` | `%USERPROFILE%\Desktop\minimap\wows-toolkit\target\release\wows-data-mgr.exe` |
| `WOWS_EXTRACTED_OUT` | `%USERPROFILE%\Desktop\minimap\wows-toolkit\extracted` |
| `WOWS_SSH_TARGET` | `<user>@<bot-host>` |
| `WOWS_INCOMING` | `/var/lib/wows-data/incoming` |

流程,任何一步失败就停:

1. **认 build** —— 游戏目录 `bin/` 下取最大的纯数字目录名(实测:当前是 `13187581` = 15.8)
2. **校验区服** —— 读 `<游戏目录>/currentrealm.txt`,必须是 `asia`。不是就停并说明原因
3. **判断要不要干活** —— 该 build 若本机已提取、且服务器 `extracted/` 里已有 → 打印
   「游戏还没更新(当前 build 已是最新)」退出 0
4. **提数据** ——
   `wows-data-mgr dump-renderer-data --game-dir <游戏目录> --build <build> -o <输出目录>`,
   完整日志存到 `<输出目录>/../dump-<build>.log`
5. **校验产物**(最要紧的一步):
   - 日志里不许出现 `panic` / `WARN` / `Unrecognized type`
   - `game_params.rkyv` 存在且 > 30 MB(实测 15.8 是 49 MB)
   - `constants.json` / `metadata.toml` / `vfs/content/GameParams.data` / `vfs/scripts` /
     `vfs/spaces` 全部存在
   - 任一不满足 → **停,不上传**,并**打印触发的那几行日志原文**,指出是哪一项。
     若是 `Unrecognized type <X>`,提示这是 WG 加了新实体类型,按
     `docs/REPLAYSHARK_BUILD.md` §8 处理
   - **逃生口 `--allow-warn`**:`WARN` 这条判据是宽口径的 —— 将来某个版本冒出一条无害告警,
     就会把整条自动化卡死。所以校验失败时打印原文让人判断,确认无害后用 `--allow-warn`
     跳过**仅 WARN 这一项**(`panic` / `Unrecognized type` / 缺文件**不可跳过**)。
     用了这个参数时,完成标记里记一笔,服务器侧汇报也带出来 —— 免得悄悄放过
6. **上传** —— `ssh <target> mkdir -p <incoming>/<ver>_<build>` 然后 `scp -r`
7. **写完成标记** —— `<incoming>/<ver>_<build>.done`(**与版本目录同级的文件,不放在目录里面**
   —— 否则 `mv` 会把它一起搬进 `extracted/`,留下一个无用文件)。内容含 build、几个关键文件的
   字节数、时间戳。**没有这个标记,服务器侧指令不会碰那个目录**
8. 打印下一步:「去 QQ 发 `/更新wg版本`」

`--dry-run` 参数:跑到第 5 步为止,不上传。用于验证脚本本身。

### 2. `plugin/wg_update.py`(服务器侧)

**为什么是新模块**:`announcement.py` / `auto_accept.py` 已经证明「独立文件自己注册 matcher」
在这套部署方式(`cp plugin/*.py` 到 NoneBot 的 plugins 目录)下可行。`minimap.py` 不该再变大。

注册 `on_command("更新wg版本")`,权限走 `permissions.is_super_admin`(与 `/sa`、`/渲染模式`、
`/用户统计` 一致)。阻塞工作放 `asyncio.to_thread`,进度用现成的 `send_message()` 逐步汇报。

步骤:

1. **权限校验** —— 非超管直接拒绝
2. **扫 incoming** —— 找**带标记**的 `<ver>_<build>` 目录
   (「带标记」= 同级存在 `<ver>_<build>.done` 文件)
   - 0 个 → 「`incoming/` 里没有待处理的数据。PC 侧的 `update_wg.bat` 跑了吗?」
   - 1 个 → 直接处理
   - 多个 → 列出来,要求显式指定:`/更新wg版本 15.9.0_13xxxxxx`
   - 带参数时校验该目录存在且有同级标记文件
   - 处理成功后删掉标记文件(目录已经 `mv` 走了,标记留着会让下次扫描看到幽灵条目)
3. **拉代码** —— `git pull` in `/opt/wows-bot`。若 `plugin/*.py` 有变动:
   `cp plugin/*.py <NoneBot plugins 目录>`,并记下「需重启」写进最终汇报。**不自动重启**
4. **复校验** —— 重跑一遍第 5 步那套结构校验(标记只能证明「传完了」,不能证明「传对了」)
5. **搬运** —— `mv incoming/<ver>_<build> extracted/<ver>_<build>`。
   若目标已存在则**拒绝**并提示:「`extracted/` 里已有这个版本。要覆盖请先手工
   `rm -rf extracted/<ver>_<build>` 再重发指令。」
   正常情况下走不到这里 —— PC 侧第 3 步发现服务器已有该 build 就退出了;能走到这里说明
   有人绕过了 PC 脚本,或者上一次更新只做了一半。让人来判断比自动覆盖 294MB 安全
6. **specs 软链** —— `bash tools/link_specs.sh /var/lib/wows-data/extracted/<ver>_<build>`,
   **显式指版本目录**
7. **刷数据** —— 依次:
   - `replayshark --extracted <specs> builds-dump -o /tmp/...` 验证新数据能读
   - `python3 tools/build_builds_json.py`
   - `python3 tools/fetch_build_icons.py`
8. **汇报** —— 版本号、每步结果、builds.json 的四类条目数(升级品/涂装/舰长/技能)、
   新增图标数、`extracted/` 现有版本数与总占用、剩余磁盘、以及是否需要重启 bot

### 3. 文档

`docs/UPDATE.md` 增一节「自动化流程」,放在现有手工流程之前,并说明手工流程保留作为
自动化失败时的退路。

## 错误处理

| 失败位置 | 处理 |
|---|---|
| PC 侧第 1–5 步 | 停,什么都没上传。屏幕上指出哪一项不满足 |
| 服务器侧第 2–4 步 | 停,什么都没动。`incoming/` 原样留着,修完重发指令即可 |
| 服务器侧第 5 步(mv) | 罕见(同 fs rename)。失败就停,`incoming/` 仍完整 |
| 服务器侧第 6–7 步 | **不回滚。** 第 4 步已校验数据完整,`extracted/` 里多这个版本是好事 —— 回放渲染立刻可用,失败的只是 `/查询` 的配装面板数据。汇报写明「回放渲染已可用,builds.json 未刷新,重跑指令即可」 |

**为什么第 6 步指错 specs 不致命**:P2 之后战报渲染走 `resolve_specs_for_build()`,按回放的
build 号自己去 `extracted/` 找对应版本,**不看 `report/specs` 软链**。软链只给构建期脚本
(`build_builds_json.py` / `fetch_build_icons.py` / `build_ships_json.py`)用。

**已知的脆弱点**:`fetch_build_icons.py` 从 `raw.githubusercontent.com` 拉图标,服务器在国内
可能慢或失败。已存在的会跳过,所以通常新增 0 张。真失败了汇报里写清 —— 缺图标只让
`/查询` 的配装块走灰色兜底,功能不挂。

## 测试

**不需要等 WG 出新版本就能端到端验证。**

1. **服务器侧指令**:拿现有 15.8 数据造演练 —— 复制成一个不可能的版本号
   (`15.8.0_99999999`)放进 `incoming/`、加完成标记,发指令,逐步核对汇报,然后删掉那个
   假版本并把 specs 软链指回真的 15.8。用不可能的 build 号是为了防止渲染器真挑中它
2. **PC 侧脚本**:`--dry-run` 跑到校验为止。另外单独验证三个失败路径:
   区服不是 asia、日志里有 `WARN`、`game_params.rkyv` 缺失 —— 都必须停下且指出原因
3. **权限**:非超管发指令必须被拒
4. **既有测试**:7 个套件保持全绿

## 验收标准

- [ ] `update_wg.bat` 在游戏未更新时正确识别并退出,不做无用功
- [ ] `update_wg.bat` 在区服不是 `asia` 时拒绝,并说明原因
- [ ] `update_wg.bat` 在日志含 `WARN` / 缺 `game_params.rkyv` 时拒绝上传,并指出是哪一项
- [ ] `update_wg.bat --dry-run` 跑通到校验为止,不产生任何上传
- [ ] `--allow-warn` 只跳过 WARN 这一项;`panic` / `Unrecognized type` / 缺文件仍然拒绝
- [ ] 用过 `--allow-warn` 时,标记文件里有记录且服务器侧汇报会带出来
- [ ] `/更新wg版本` 非超管调用被拒
- [ ] `incoming/` 为空时给出可操作的提示而不是报错
- [ ] `incoming/` 有多个待处理版本时要求显式指定
- [ ] 没有 `.done` 标记的目录被忽略(模拟 scp 中断:只传目录不写标记)
- [ ] 处理成功后 `.done` 标记被删掉,再发一次指令不会看到幽灵条目
- [ ] `extracted/` 里已有同版本时拒绝搬运,并给出手工删除的恢复提示
- [ ] 假版本演练:指令逐步汇报正确,builds.json 四类条目数与 15.8 实测一致
      (118 升级品 / 2345 涂装 / 662 舰长 / 82 技能)
- [ ] `plugin/*.py` 有变动时汇报里出现「需重启」,且**没有**自动重启
- [ ] 汇报里包含版本数与磁盘占用
- [ ] `minimap.py` 未被修改
- [ ] 7 个既有测试套件全绿

## 交付物

1. `tools/update_wg.bat` —— PC 侧一键脚本
2. `plugin/wg_update.py` —— 服务器侧超管指令
3. `docs/UPDATE.md` 增「自动化流程」一节
4. 演练记录:假版本走一遍的实际汇报内容,写进 plan 的执行记录
