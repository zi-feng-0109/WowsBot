# P4-1:重建 replayshark,消灭 FLOAT64 手术

2026-09-19

## 背景

`/opt/wows-bot/report/replayshark`(4806528 B,2026-05-27)是仓库里的**预编译**二进制
(`report/prebuilt/replayshark-linux-x86_64`),独有 `battle-report` / `builds-dump` /
`consumables-dump` 三个子命令 —— 它们来自 `tools/replayshark_battle_report.patch`(865 行,5 个文件)。
WG 战报(`/战报`、`/查询` 的配装面板、builds.json)全靠它。

WG 15.7 起实体定义引入 `FLOAT64` 类型,这个二进制不认,会 panic。现行绕过办法是
**每个大版本给它单独做一份 scripts 副本并把 FLOAT64 sed 成 FLOAT**:

```
cp -rL extracted/<ver>_<build>/vfs/scripts  specs-patched/<ver>_<build>/scripts
sed -i 's|FLOAT64|FLOAT|g' .../entity_defs/alias.xml .../entity_defs/interfaces/BattleStarterClient.def
```

代价:每个大版本重做一次,且下次 WG 再加一个新类型时会以同样方式突然挂掉,
而症状(`Unrecognized type X`)出现在数据更新流程的深处,不看日志发现不了。

## 目标

让 `report/replayshark` 变成「**当前源码 + battle-report patch** 重新编译」的二进制:

1. 当前源码已带 `FLOAT64 => PrimitiveType::Float64`(toolkit `8d2a8205`),新二进制天生认这个类型 → **手术从此不需要**
2. 以后 WG 再加新类型,是「改 Rust 一行 + 重编」,而不是「每版重做 sed 手术」
3. 顺带:当前源码还有 `battle-results --format normalized`(Lesta 在用)和 `armor-dump`。
   重编后**一个二进制同时具备 battle-report + normalized + armor-dump**,三个来源合一,
   这是后续统一战报管线(P5)的前提

## 非目标

- 不改战报外观 —— 这是本项目的**硬约束**,见「验收」
- 不碰 normalized 管线、不动 Lesta 路径、不动 `minimap_renderer`
- 不改 `wows_report` 里 specs-patched 优先逻辑的**行为**(老数据目录里已有的手术产物留着不碰,
  是幂等的);只允许给它补注释说明「已不再需要」
- 不做更新流程自动化 —— 那是 P4-2

## 现状事实(2026-09-19 实测,不是回忆)

| 项 | 实测结果 |
|---|---|
| patch 三方合并 | **可用**。patch 记录的 5 个基线 blob 都还在 toolkit 仓历史里,`git apply -3` 后 1 个文件干净套上、4 个文件共 **8 个冲突块** |
| 「patch 套不上了」的成因 | 一半是假象:patch 文件是 CRLF、源码是 LF,`git apply` 直接判不匹配。去掉 CR 后错误信息才可读 |
| patch 基线 | 不对应单一 commit(各文件 blob 分别来自 `4b0ea0fd` / `2effcd31` / 两者之外),所以走 blob 三方合并,不走 rebase |
| 两棵 toolkit 源码树 | `Desktop/minimap/wows-toolkit`(上游 fork,有 git 历史)与 `wows-bot-review/wows-toolkit`(vendored,属 bot 仓)**crates/ 逐字节一致**,只差 `wows-replay-insights/tests/fixtures`。5 个 patch 目标文件全部 `same` |
| 服务器 cargo | `cargo 1.92.0`,在 zifeng 用户下 |
| 服务器回放 | **一局都没有**(处理完即删)→ 对比用的 fixture 必须从本机 scp 上去 |
| 服务器 extracted | WG 15.3 / 15.4 / 15.5 / 15.6 / 15.7 / 15.8 + Lesta 26.7 / 26.8 + vfs_common |
| 本机回放版本 | 只有 15.7.0(build 13015811 与 13016054)和 15.8.0 —— 没有 15.3–15.6 的 |

## 方案

四个阶段,每阶段都有独立可判定的产出。

### 阶段 1:解冲突(本机)

在上游 fork 仓(有基线 blob 的那棵)开分支,`git apply -3` 后逐个解 8 个冲突块。

**解冲突原则**:冲突处**保留上游新代码,只叠加 patch 的新增**,不擅自改上游语义。
patch 的意图是「新增 battle-report 需要的数据通路」,不是修改既有行为;凡是看起来要
改上游既有行为的冲突,停下来记录并单独判断。

产出:
- 源码改动(4 个冲突文件 + 1 个干净套上的 `main.rs`)
- 重新生成的 `tools/replayshark_battle_report.patch`(对当前源码能干净套上,LF 换行)
- 同步到 bot 仓 vendored 树(两棵树逐字节一致,直接搬即可)

编译在本机先过一遍(`cargo check -p replayshark`),把「patch 的新增代码引用了半年里
改过的 API」这类问题在上服务器之前暴露掉。

### 阶段 2:服务器重编

前提:阶段 1 的改动已推到 gitee 并在服务器 `git pull`(vendored 源码就在 bot 仓里)。

```
sudo -u zifeng /home/zifeng/.cargo/bin/cargo build --release \
    --manifest-path /opt/wows-bot/wows-toolkit/Cargo.toml -p replayshark
```

产出:`/opt/wows-bot/wows-toolkit/target/release/replayshark`(先不换装)。

### 阶段 3:等价性验证(关键闸门)

这是本项目的核心。**同一批真实回放**,两边跑 `battle-report`,比 JSON:

| | 二进制 | specs |
|---|---|---|
| 旧 | `/opt/wows-bot/report/replayshark` | 手术过的(`specs-patched/<ver>/scripts`) |
| 新 | 刚编出来的 | **未手术的原始** `extracted/<ver>/vfs/scripts` |

两边都带 `-c <constants.json>`,与生产一致。

**fixture 集**:从本机挑一组 scp 到服务器 `/var/lib/wows-data/fixtures/`,覆盖
15.7.0_13015811 与 15.8.0_13187581 两个版本 × 舰种(CV / SS / DD / BB / CA),
因为战报里各舰种走的字段不同(CV 有中队、SS 有下潜、DD 有鱼雷/烟雾)。
15.3–15.6 无回放可用,这是覆盖缺口,如实记录。

判定:
1. JSON 逐字节一致 → 通过
2. 不一致 → **停下来**,逐字段 diff,把每处差异连同证据报告给用户,**由用户决定是否接受**。
   「上游修了 bug」这种归因必须拿实际战斗数据佐证才算,不允许「看起来差不多就放过」
3. 再对渲染出的战报 PNG 做正文哈希对比(裁掉底部 48px 页脚,因为页脚含 `datetime.now()`
   会让整图哈希漂移 —— P2 已验证过这个方法跨分钟稳定)

另有一项独立检查:新二进制在**未手术的** 15.8 原始 scripts 上 `builds-dump` 成功,
且计数与 15.8 实测一致(118 升级品 / 2345 涂装 / 662 舰长 / 82 技能)。

### 阶段 4:换装与收尾

1. 旧二进制备份到**仓库外** `/root/replayshark-prebuilt-20260527.bak`
   (`report/prebuilt/replayshark-linux-x86_64` 是 git 跟踪的,旧版本 git 历史里本来就有;
   `report/replayshark` 是 gitignore 的部署副本。备份放仓库外,免得多提交一份 4.8MB 二进制)
2. 新二进制进 `report/prebuilt/replayshark-linux-x86_64`,并 `cp` 到 `report/replayshark`
3. 用真实回放跑一遍生产入口(`report/bin/wows_full_report`)确认端到端可用
4. 文档:`docs/UPDATE.md` 删掉 FLOAT64 手术步骤;记忆 `wg_1570_update_notes.md` 同步更新
5. `wows_report` 的 specs-patched 优先逻辑**保留**,并补一行注释说明「已不再需要,
   保留是为了兼容老数据目录里已有的手术产物」

不重启 nonebot —— 渲染器是 subprocess 现拉。

## 验收标准

- [ ] `cargo build --release -p replayshark` 在服务器上零错误
- [ ] 新二进制 `builds-dump` 在**未手术**的 15.8 原始 scripts 上成功,计数 118 / 2345 / 662 / 82
- [ ] fixture 集每一局的 `battle-report` JSON,新旧逐字节一致;若有差异,已逐处附证据报告给用户并获接受
- [ ] fixture 集每一局的战报 PNG 正文哈希(裁掉底部 48px)新旧一致
- [ ] 确认参与验证的那批 scripts 里 `FLOAT64` 仍然存在(证明真的没做手术)
- [ ] `report/bin/wows_full_report` 端到端跑通一局 15.8 回放
- [ ] 新 patch 文件对当前源码 `git apply --check` 干净通过

## 风险与回滚

| 风险 | 应对 |
|---|---|
| JSON 出现无法归因为「上游修复」的差异 | **停止,不换装**,向用户报告差异内容。退回 P4-2 里自动化手术的老方案 |
| patch 新增代码引用的 API 半年里改了,编不过 | 阶段 1 的 `cargo check` 提前暴露;属于解冲突工作的一部分 |
| 新二进制体积/依赖与旧的差异导致服务器跑不起来 | 同机编译,glibc 一致;换装前先直接跑 `--version` 与 `builds-dump` |
| 换装后才发现问题 | 一条 `cp` 从 `/root/*.bak` 回滚,不需要重启任何服务 |

## 交付物

1. toolkit 上游 fork:解冲突后的源码 commit
2. bot 仓:vendored 源码同步、`tools/replayshark_battle_report.patch` 更新、
   `report/prebuilt/replayshark-linux-x86_64` 换新、`docs/UPDATE.md` 删手术步骤
3. 验证记录:fixture 清单 + 新旧 JSON/PNG 哈希对比结果,写进 plan 的执行记录
