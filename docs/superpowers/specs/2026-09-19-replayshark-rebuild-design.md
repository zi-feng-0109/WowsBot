# P4-1:重建 replayshark,消灭 FLOAT64 手术

2026-09-19

> 本文档在同一天内被重写过一次。初版方案是「把 battle-report patch 套到当前源码」,
> 实测后发现不可行(见「为什么不走当前源码」),改为「在 patch 同期源码上重建」。
> 决策变更已由用户确认。

## 背景

`/opt/wows-bot/report/replayshark`(4806528 B,2026-05-27)是仓库里的**预编译**二进制
(`report/prebuilt/replayshark-linux-x86_64`),独有 `battle-report` / `builds-dump` /
`consumables-dump` 三个子命令 —— 它们来自 `tools/replayshark_battle_report.patch`(860 行新增,5 个文件)。
WG 战报(`/战报`、`/查询` 的配装面板、builds.json、升级/技能图标)全靠它。

WG 15.7 起实体定义引入 `FLOAT64` 类型,这个二进制不认,会 panic。现行绕过办法是
**每个大版本给它单独做一份 scripts 副本、把 FLOAT64 sed 成 FLOAT**:

```
cp -rL extracted/<ver>_<build>/vfs/scripts  specs-patched/<ver>_<build>/scripts
sed -i 's|FLOAT64|FLOAT|g' .../entity_defs/alias.xml .../entity_defs/interfaces/BattleStarterClient.def
```

代价:每个大版本重做一次;下次 WG 再加一个新类型时会以同样方式突然挂掉,而症状
(`Unrecognized type X`)出现在数据更新流程深处,不看日志发现不了。

## 目标

让 `report/replayshark` 变成**可复现构建**的二进制,且天生认 `FLOAT64`:

1. 手术从此不需要
2. 下次 WG 再加新类型,是「切到固定基线 + 加一行 + 重编」,而不是「patch 套不上了、从头考古」
3. **构建配方进仓库** —— 这是本项目的另一半价值。今天的状况是二进制在仓库里、
   但没人能再造出它;做完之后配方(基线 commit + 两个 patch + 构建步骤)全在仓库里

## 非目标

- 不改战报外观 —— 这是本项目的**硬约束**,见「验收」
- 不碰 normalized 管线、不动 Lesta 路径、不动 `minimap_renderer`
- 不改 `wows_report` 里 specs-patched 优先逻辑的**行为**(老数据目录里已有的手术产物
  留着不碰,是幂等的);只允许给它补注释说明「已不再需要」
- 不追求「一个二进制同时有 battle-report + normalized + armor-dump」—— 那要迁到
  BattleWorld 新架构,会改战报外观,属于 P5
- 不做更新流程自动化 —— 那是 P4-2

## 为什么不走当前源码(实测记录)

初版方案想把 patch 套到当前源码。实测否掉了:

- patch 共 **22 个 hunk / 860 行新增**(main 3 / controller 9 / decode 2 / provider 4 / types 4)。
  对**当前源码**干跑:**15 个失败**,
  其中 `controller.rs` 的 9 个 hunk **全部失败**
- 原因不是行偏移,是上游 `2026-06-05` 的一次大重构:
  `fbc415d5 refactor: remove old BattleController; replace differential tests with BattleWorld golden snapshots`。
  patch 挂靠的 `BattleController` **已被删除**,`BattleReport` 搬进了新 crate
  `wows-battle-world/src/report.rs` 并改成 ECS 架构
- 上游新 `BattleReport` 比 patch 那版丰富(多了 `ribbon_events` / `salvos` / `hit_history` /
  `presence` / `self_ribbons` 等),但**缺** patch 要加的三样:`damage_events` /
  `consumable_uses` / `squadron_consumable_uses` —— 而战报 PNG 的伤害图与消耗品图正是靠这三样
- 结论:「套到当前源码」实际上等于**在新架构上重新实现一遍 WG 战报**,那就是 P5,
  且必然改变输出 → 与硬约束冲突

## 方案:在 patch 同期源码上重建

基线选 **`2effcd31`**(2026-05-21,`feat: add support for WASM compilation`)。选它的依据:

- patch 记录的 `controller.rs` 基线 blob(`98a527d`)**正是 `2effcd31` 的那一份** ——
  战报逻辑的核心文件完全对得上
- 实测在 `2effcd31` 上套 patch:**22 个 hunk 只差 2 个**,都在 `provider.rs` 的
  `PlaneAbilities` 提取块(CV 飞机消耗品),自成一块、好手工放
- 实测 cherry-pick FLOAT64 修复(toolkit `8d2a8205`)到 `2effcd31`:**干净自动合并**
- `rust-toolchain.toml` 在 `2effcd31` pin 的是 `1.92.0`,本机与服务器的 cargo
  **正好都是 1.92.0** → 工具链零风险

已知残余漂移(2026-09-19 复审实测,比初稿的描述精确):旧 patch 的 5 个目标文件里
**4 个**的基线 blob 与 `2effcd31` 不同,只有 `controller.rs`(战报逻辑的核心)精确吻合。
初稿只提了 main / decode / types,**漏了 provider.rs** —— 而它恰好是那 2 个 hunk 手工放的地方。
逐文件量出来的漂移如下:

| 文件 | 漂移 | 性质 |
|---|---|---|
| `controller.rs` | 0 | 基线 blob `98a527d` 精确吻合 |
| `decode.rs` | 2 行 | 纯类型:`packet_type: u32` → `PacketTypeId` newtype。**零语义改动** |
| `main.rs` | 2 行 | `.raw()` 类型适配 + `Commands::Spec` 的 `load_game_data` 签名(battle-report 不走这条) |
| `types.rs` | 11 行 | `CrewPersonality` 的 10 个字段 `bool`/`String`/`u32` → `Option<>`(容错增强) |
| `provider.rs` | 319+/328− | 来自 `da9fb551 wowsunpack: support older WoWs game versions` 与 WASM commit |

结论:**回放解码路径(`decode.rs`)只漂了 2 行且零语义**,所以旧版本回放的解析风险接近于零;
`provider.rs` 的 churn 是 GameParams 提取,与回放版本无关,已被 15.7/15.8 两版充分走过。
这让「15.3–15.6 未验证」这个缺口的实际风险比初稿措辞小得多。

⚠️ 但 `types.rs` 那 11 行是个初稿没提到的缺口:`CrewPersonality` 正是 `builds-dump`
输出的「662 舰长」,`Option<bool>` 序列化成 `null` 而旧版出 `false`,**builds.json 的字段形状
可能变**。而闸门对 `builds-dump` 只做了计数校验(118/2345/662/82),**从未逐字段 diff**。
已查实消费侧:`tools/build_builds_json.py` 从 `raw["crews"]` 只读 `id` 和 `name`,那 10 个
Option 化字段名在 `tools/*.py` 与 `report/bin/*.py` 里零命中 —— 所以**当前无影响**。
但这是运气不是覆盖:谁将来开始读那些字段,要先补一次逐字段对比。

### 阶段 1:本机准备源码与构建配方

在本机 toolkit fork(有 git 历史的那棵)建分支 `replayshark-battle-report`,基于 `2effcd31`:

1. cherry-pick `8d2a8205`(FLOAT64 支持)
2. `patch -p1` 套 `tools/replayshark_battle_report.patch`(去 CR 后的 LF 版)
3. 手工补 `provider.rs` 那 2 个失败 hunk(`PlaneAbilities` 提取 + `Aircraft::builder().maybe_abilities(...)`)
4. `cargo check -p replayshark` 必须过

**产出到 bot 仓**(这才是推到 gitee、真正承载可复现性的东西):

- `tools/replayshark_float64.patch` —— FLOAT64 那处改动,独立成 patch
- `tools/replayshark_battle_report.patch` —— 重新生成,对 `2effcd31` 能干净套上(含 `PlaneAbilities` 修正),LF 换行
- `docs/REPLAYSHARK_BUILD.md` —— 构建配方:上游仓库地址、基线 commit `2effcd31`、
  两个 patch 的应用顺序、cargo 版本、验证命令

说明:本机 toolkit fork 只有 `upstream` 一个 remote(landaire 的 GitHub),我们自己的
commit 都只在本地。所以**可复现性不依赖本机仓库** —— 它依赖「公开的上游 commit +
仓库里的两个 patch 文件」,这两样都可离线保存。

### 阶段 2:服务器编译

新建独立构建目录 `/opt/wows-replayshark-build/`。**不能在 `/opt/wows-toolkit` 里编** ——
那是 2026-06-27 的源码副本(已含 `wows-battle-world`,是重构之后的),且它的
`target/release/` 里放着**生产在用的 `minimap_renderer`**(2026-08-14),不能扰动。

源码来源,按顺序试:

- **A** 服务器直接 clone 上游到 `2effcd31`(若能访问 GitHub 或 ghfast 镜像)
- **B** 从本机 scp 阶段 1 准备好的源码树(约 89 MB)

两条路都要接着确认工作区状态与两个 patch 已应用,然后:

```
sudo -u zifeng /home/zifeng/.cargo/bin/cargo build --release \
    --manifest-path /opt/wows-replayshark-build/Cargo.toml -p replayshark
```

产出:`/opt/wows-replayshark-build/target/release/replayshark`(先不换装)。

### 阶段 3:等价性验证(关键闸门)

**同一批真实回放**,两边跑 `battle-report`,比 JSON:

| | 二进制 | specs |
|---|---|---|
| 旧 | `/opt/wows-bot/report/replayshark` | 手术过的 `specs-patched/<ver>_<build>/scripts` |
| 新 | 刚编出来的 | **未手术的原始** `extracted/<ver>_<build>/vfs/scripts` |

两边都带 `-c <该版本 constants.json>`,与生产一致。

**fixture 集**:从本机挑一组 scp 到服务器,覆盖 `15.7.0_13015811` 与 `15.8.0_13187581`
两个版本 × 舰种(CV / SS / DD / BB / CA),因为战报里各舰种走的字段不同(CV 有中队、
SS 有下潜、DD 有鱼雷/烟雾)。两个版本的手术产物在服务器上都还在(已确认),所以旧二进制
两个版本都能读。15.3–15.6 本机无回放可用,这是覆盖缺口,如实记录。

判定:

1. JSON 逐字节一致 → 通过
2. 不一致 → **停下来**,逐字段 diff,把每处差异连同证据报告给用户,**由用户决定是否接受**。
   「上游修了 bug」这种归因必须拿实际战斗数据佐证才算,不允许「看起来差不多就放过」
3. 再对渲染出的战报 PNG 做正文哈希对比(裁掉底部 48 px 页脚 —— 页脚含 `datetime.now()`,
   整图哈希会漂移;P2 已验证这个方法跨分钟稳定)

另有一项独立检查:新二进制在**未手术的** 15.8 原始 scripts 上 `builds-dump` 成功,
计数与 15.8 实测一致(118 升级品 / 2345 涂装 / 662 舰长 / 82 技能)。

### 阶段 4:换装与收尾

1. 旧二进制备份到**仓库外** `/root/replayshark-prebuilt-20260527.bak`
   (`report/prebuilt/replayshark-linux-x86_64` 是 git 跟踪的,旧版本 git 历史里本来就有;
   `report/replayshark` 是 gitignore 的部署副本。备份放仓库外,免得多提交一份 4.8 MB 二进制)
2. 新二进制进 `report/prebuilt/replayshark-linux-x86_64`,并 `cp` 到 `report/replayshark`
3. 用真实回放跑一遍生产入口(`report/bin/wows_full_report`)确认端到端可用
4. 文档:`docs/UPDATE.md` 删掉 FLOAT64 手术步骤;记忆 `wg_1570_update_notes.md` 同步更新
5. `wows_report` 的 specs-patched 优先逻辑保留,补一行注释说明「已不再需要,
   保留是为了兼容老数据目录里已有的手术产物」

不重启 nonebot —— 渲染器是 subprocess 现拉。

## 验收标准

- [ ] 阶段 1 后 `cargo check -p replayshark` 在本机零错误
- [ ] 重新生成的 `tools/replayshark_battle_report.patch` 对 `2effcd31` `git apply --check` 干净通过
- [ ] `cargo build --release -p replayshark` 在服务器上零错误
- [ ] 新二进制 `builds-dump` 在**未手术**的 15.8 原始 scripts 上成功,计数 118 / 2345 / 662 / 82
- [ ] fixture 集每一局的 `battle-report` JSON,新旧逐字节一致;若有差异,已逐处附证据报告给用户并获接受
- [ ] fixture 集每一局的战报 PNG 正文哈希(裁掉底部 48 px)新旧一致
- [ ] 确认参与验证的那批 scripts 里 `FLOAT64` 仍然存在(证明真的没做手术)
- [ ] `report/bin/wows_full_report` 端到端跑通一局 15.8 回放
- [x] `docs/REPLAYSHARK_BUILD.md` 里的配方,照着能从零重建出**同一个源码状态**
      (2026-09-19 复审实测:在干净 `2effcd31` 上按序套两个 patch,与已验证分支整棵树
      零字节差异;正序反序皆可、幂等。注意**不是**二进制比特级可复现 —— rustc 默认
      不保证那个,本项目也从未建立过这条)

## 风险与回滚

| 风险 | 应对 |
|---|---|
| JSON 出现无法归因为「上游修复」的差异(3–5 月漂移导致) | **停止,不换装**,向用户报告差异内容。退路:改基线到 `4b0ea0fd`(main/decode/types 三个文件的 blob 精确匹配),或回到 P4-2 自动化手术 |
| `PlaneAbilities` 那 2 个 hunk 手工放错 → CV 消耗品数据不对 | 验证集里必须有 CV 回放;JSON 逐字节对比会直接抓到 |
| 服务器访问不到 GitHub | 走方案 B(scp 源码树);可复现性靠仓库里的 patch 文件,不靠服务器能不能 clone |
| 在 `/opt/wows-toolkit` 里误编,破坏生产 `minimap_renderer` | 构建目录物理隔离到 `/opt/wows-replayshark-build/`;不碰前者的 `target/` |
| 换装后才发现问题 | 一条 `cp` 从 `/root/*.bak` 回滚,不需要重启任何服务 |

## 交付物

1. 本机 toolkit fork:分支 `replayshark-battle-report`(基线 + FLOAT64 + patch + 2 个手工 hunk)
2. bot 仓:`tools/replayshark_float64.patch`、重新生成的 `tools/replayshark_battle_report.patch`、
   `tools/build_replayshark.sh`(可复现构建)、`tools/verify_replayshark_equiv.sh`(等价性验证,
   下次重建还要用)、`docs/REPLAYSHARK_BUILD.md`、`report/prebuilt/replayshark-linux-x86_64` 换新、
   `docs/UPDATE.md` 补上「手术已取消」与「不要裸跑 link_specs」的说明
   (更正:UPDATE.md 里**从来没有过**手术步骤 —— 手术只记在记忆文件里,所以这里是「加说明」而非「删步骤」)
3. 验证记录:fixture 清单 + 新旧 JSON/PNG 哈希对比结果,写进 plan 的执行记录
