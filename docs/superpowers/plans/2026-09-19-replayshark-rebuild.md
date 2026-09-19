# P4-1 重建 replayshark 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `report/replayshark` 换成「patch 同期源码 + FLOAT64 修复」重编的二进制,使 WoWs 大版本更新不再需要 FLOAT64 sed 手术,同时把构建配方写进仓库。

**Architecture:** 不动当前源码(上游 2026-06-05 删掉了 patch 挂靠的 `BattleController`)。改为以上游 `2effcd31`(2026-05-21)为基线,叠加两个 patch(FLOAT64 修复、battle-report 功能),在服务器上编译,用「同一批回放的 battle-report JSON 逐字节一致」作为换装闸门。

**Tech Stack:** Rust 1.92.0 / cargo(本机与服务器版本一致)、`git apply -3` 与 `patch(1)`、Python 3(哈希对比)、bash。

**设计文档:** `docs/superpowers/specs/2026-09-19-replayshark-rebuild-design.md`

---

## 执行须知(违反会出事,先读)

1. **服务器操作的边界**(2026-09-19 用户配好 SSH 免密后明确):
   - **允许**:传文件到 `/tmp`、只读检查(`ls` / `grep` / `cat`)
   - **禁止**:任何写生产状态的命令 —— 编译、改软链、换二进制、动服务、写
     `/opt/wows-bot/` 或 `/var/lib/wows-data/` 下的东西。这些**一律给用户命令、由他自己跑**
   - **永远不重启服务**,哪怕看起来该重启,也只提示
   涉及服务器的任务(Task 4、5、6、7、8)**不能交给 subagent** —— subagent 没法跟用户对话。
   这些任务必须在主会话里执行。
2. **不要重启任何服务。** 纯数据/二进制更新不需要重启 nonebot(渲染器是 subprocess 现拉)。
   哪怕看起来该重启,也只是提示用户,由他决定。
3. **不要在 `/opt/wows-toolkit` 里编译。** 它的 `target/release/minimap_renderer` 是**生产在用的**
   小地图二进制(2026-08-14)。构建目录必须隔离到 `/opt/wows-replayshark-build/`。
4. **两个仓库,别搞混:**
   - toolkit fork:`%USERPROFILE%\Desktop\minimap\wows-toolkit`(有 git 历史,只有 `upstream` remote,
     本地 commit 没推到任何地方)—— 在这里建分支、解 patch
   - bot 仓:`%USERPROFILE%\Desktop\wows-bot-review`(推 gitee,服务器 `/opt/wows-bot` 就是它)
     —— 这里放 patch 文件、构建文档、prebuilt 二进制
5. **写文件用 Write 工具,不要用 bash heredoc。** 本项目文档含中文全角括号与引号,
   heredoc 在这台机器上反复出过字符串截断问题。
6. Windows 上 `patch` / `git` 在 Git Bash 里跑。**patch 文件在 git 库里是 LF**
   (`git cat-file blob` 验证 CR 数为 0),但 `.gitattributes` 的 `* text=auto` 会把 Windows
   工作副本转成 CRLF,`git apply` 于是判不匹配 —— 本机操作前先 `tr -d` 去掉 CR。
   **更正**:这只影响错误输出可读性,**不是**「patch 套不上」的原因 —— 去掉 CR 后对当前源码
   仍然 15/22 失败,真正原因从头到尾只有一个:上游删了 `BattleController`。
   (`git show <rev>:<path>` 在 Windows 上会做 CRLF 转换,查库内真实换行必须用 `git cat-file blob`。)

---

## 文件结构

**toolkit fork(`Desktop/minimap/wows-toolkit`)**

| 文件 | 变更 | 责任 |
|---|---|---|
| 新分支 `replayshark-battle-report` | 创建 | 承载「2effcd31 + FLOAT64 + battle-report」这个构建状态 |
| `crates/wowsunpack/src/rpc/typedefs.rs` | cherry-pick 修改 | `FLOAT64` → `PrimitiveType::Float64` 分支 |
| `crates/replayshark/src/main.rs` | patch 新增 580 行 | `battle-report` / `builds-dump` / `consumables-dump` 三个子命令 |
| `crates/wows-replays/src/analyzer/battle_controller/controller.rs` | patch 新增 136 行 | `DamageEventOut` / `ConsumableUseOut` / `SquadronConsumableUseOut` 三个输出结构与访问器 |
| `crates/wows-replays/src/analyzer/decoder/decode.rs` | patch 新增 63 行 | 消耗品激活包的解码分支 |
| `crates/wowsunpack/src/game_params/provider.rs` | patch 新增 63 行(其中 2 个 hunk 手工放) | 从 GameParams 提取 `ShipAbilities` / `PlaneAbilities` |
| `crates/wowsunpack/src/game_params/types.rs` | patch 新增 19 行 | `Vehicle` / `Aircraft` 上的 abilities 字段与访问器 |

**bot 仓(`Desktop/wows-bot-review`)**

| 文件 | 变更 | 责任 |
|---|---|---|
| `tools/replayshark_float64.patch` | 创建 | FLOAT64 修复,独立成 patch(构建配方第一步) |
| `tools/replayshark_battle_report.patch` | 重新生成 | battle-report 功能,对「2effcd31 + float64」干净套上,LF 换行 |
| `tools/build_replayshark.sh` | 创建 | 可复现构建脚本:准备源码 → 套两个 patch → cargo build → 自检 |
| `tools/verify_replayshark_equiv.sh` | 创建 | 等价性验证脚本:对一批回放跑新旧两个二进制并逐字节比 JSON |
| `docs/REPLAYSHARK_BUILD.md` | 创建 | 构建配方文档:基线 commit、patch 顺序、工具链版本、验证方法 |
| `report/prebuilt/replayshark-linux-x86_64` | 替换 | 新二进制 |
| `docs/UPDATE.md` | 修改 | 删掉 FLOAT64 手术步骤 |
| `report/bin/wows_report` | 修改(仅注释) | 说明 specs-patched 优先逻辑已不再必需、保留是为兼容老数据 |

---

## Task 1:建分支、cherry-pick FLOAT64、套 patch

**Files:**
- Modify(toolkit fork):`crates/wowsunpack/src/rpc/typedefs.rs`、`crates/replayshark/src/main.rs`、`crates/wows-replays/src/analyzer/battle_controller/controller.rs`、`crates/wows-replays/src/analyzer/decoder/decode.rs`、`crates/wowsunpack/src/game_params/provider.rs`、`crates/wowsunpack/src/game_params/types.rs`

- [ ] **Step 1:确认工作区干净,记录当前分支**

```bash
cd <toolkit>
git status --short | grep -v '^?? extracted/'
git branch --show-current
```

期望:第一条无输出(除了 untracked 的 `extracted/`),第二条输出 `master`。
如果有未提交改动,**停下来问用户**,不要 stash 或丢弃。

- [ ] **Step 2:从基线建分支**

```bash
cd <toolkit>
git checkout -b replayshark-battle-report 2effcd31
git log -1 --format='%h %ad %s' --date=short
```

期望:`2effcd31 2026-05-21 feat: add support for WASM compilation`

- [ ] **Step 3:cherry-pick FLOAT64 修复**

```bash
git cherry-pick 8d2a8205
grep -n 'FLOAT64' crates/wowsunpack/src/rpc/typedefs.rs
```

期望:cherry-pick 无冲突(已实测干净自动合并);grep 能看到 `} else if t == "FLOAT64" {`。
`8d2a8205` 只改一个文件、7 行新增。

- [ ] **Step 4:生成 LF 版 patch 并套上**

```bash
tr -d '\r' < <repo>/tools/replayshark_battle_report.patch > /tmp/bp_lf.patch
patch -p1 --forward < /tmp/bp_lf.patch
```

期望输出(已实测):`main.rs` / `controller.rs` / `decode.rs` / `types.rs` 全部成功,
`provider.rs` 报 `Hunk #3 FAILED at 1172` 与 `Hunk #4 FAILED at 1209`、`2 out of 4 hunks FAILED`,
并生成 `crates/wowsunpack/src/game_params/provider.rs.rej`。

**注意**:某些 hunk 会带 `with fuzz 1/2` 成功 —— 那意味着 patch 忽略了 1–2 行上下文。
这些位置要在 Step 6 的 `cargo check` 之后额外肉眼过一遍,确认插入点对。

- [ ] **Step 5:手工放 provider.rs 那 2 个失败 hunk**

读 `crates/wowsunpack/src/game_params/provider.rs.rej` 拿到两段内容,插到当前源码对应位置:

**hunk 3** —— 插在 `impl GameMetadataProvider` 内、`ParamType::Aircraft => {` 分支里
`let subtypes: Vec<String> = param_data` 这一行**之前**,内容是从 `PlaneAbilities` 提取
每个 slot 的 `(ability_name, variant)` 列表:

```rust
                                // 提取 PlaneAbilities (跟 Vehicle 的 ShipAbilities 同结构):
                                // 外层 = slot 索引,内层 = 该 slot 的 (ability_name, variant) 列表。
                                // 飞机消耗品(巡逻战斗机/引擎冷却 等)在这里。
                                let plane_abilities: Option<Vec<Vec<(String, String)>>> =
                                    param_data.get(&pk("PlaneAbilities"))
                                        .and_then(|v| v.dict_or_object_dict())
                                        .map(|ab_dict| {
                                            ab_dict.inner().iter()
                                                .filter_map(|(_slot_name, slot_data)| {
                                                    if slot_data.is_none() { return None; }
                                                    let slot_data = slot_data.dict_or_object_dict()?;
                                                    let slot_data = slot_data.inner();
                                                    let slot = game_param_to_type!(slot_data, "slot", usize);
                                                    let abils = game_param_to_type!(slot_data, "abils", &[()]).inner();
                                                    let abils: Vec<(String, String)> = abils.iter()
                                                        .filter_map(|abil| {
                                                            let map_abil = |abil: &Vec<Value>| -> Option<(String,String)> {
                                                                Some((
                                                                    abil.get(0)?.string_ref()?.inner().clone(),
                                                                    abil.get(1)?.string_ref()?.inner().clone(),
                                                                ))
                                                            };
                                                            match abil {
                                                                Value::Tuple(inner) => map_abil(inner.inner()),
                                                                Value::List(inner) => map_abil(&inner.inner()),
                                                                _ => None,
                                                            }
                                                        })
                                                        .collect();
                                                    Some((slot, abils))
                                                })
                                                .sorted_by(|a, b| a.0.cmp(&b.0))
                                                .map(|(_slot, abils)| abils)
                                                .collect()
                                        });
```

**hunk 4** —— 同一个 `ParamType::Aircraft` 分支末尾,把 `Aircraft::builder()` 调用链
加上 `.maybe_abilities(plane_abilities)`:

```rust
                                Some(ParamData::Aircraft(
                                    Aircraft::builder()
                                        .category(category)
                                        .ammo_type(ammo_type)
                                        .maybe_abilities(plane_abilities)
                                        .build(),
                                ))
```

放完删掉 `.rej` 与 `.orig` 残留:

```bash
rm -f crates/wowsunpack/src/game_params/provider.rs.rej crates/wowsunpack/src/game_params/provider.rs.orig
find . -name '*.rej' -o -name '*.orig' | grep -v extracted | head
```

期望:最后一条无输出。

- [ ] **Step 6:编译检查**

```bash
cd <toolkit>
cargo check -p replayshark 2>&1 | tail -30
```

期望:`Finished`,零 error。

若报错:大概率是 `maybe_abilities` 这类 builder 方法名对不上(`bon`/`typed-builder` 版本差异)
或 `sorted_by` 需要 `use itertools::Itertools`。按报错逐个修,**不要改 patch 的语义** ——
只允许改到"能编译"为止。若出现需要改变输出字段的修法,停下来报告给用户。

- [ ] **Step 7:确认三个子命令都在**

```bash
cargo run --release -p replayshark -- --help 2>&1 | grep -E "battle-report|builds-dump|consumables-dump"
```

期望:三行都出现。这一步会跑一次 release 编译,较慢(首次 5–15 分钟)。

- [ ] **Step 8:提交**

```bash
git add -A crates/
git commit -m "feat(replayshark): battle-report 功能套到 2effcd31 基线"
git log --oneline 2effcd31..HEAD
```

期望:两个 commit —— cherry-pick 的 FLOAT64 + 这一个。

---

## Task 2:把构建配方落到 bot 仓

**Files:**
- Create:`%USERPROFILE%\Desktop\wows-bot-review\tools\replayshark_float64.patch`
- Modify:`%USERPROFILE%\Desktop\wows-bot-review\tools\replayshark_battle_report.patch`
- Create:`%USERPROFILE%\Desktop\wows-bot-review\tools\build_replayshark.sh`
- Create:`%USERPROFILE%\Desktop\wows-bot-review\docs\REPLAYSHARK_BUILD.md`

- [ ] **Step 1:导出两个 patch**

```bash
cd <toolkit>
BOT=<repo>
git diff 2effcd31..HEAD~1 -- crates/wowsunpack/src/rpc/typedefs.rs > "$BOT/tools/replayshark_float64.patch"
git diff HEAD~1..HEAD > "$BOT/tools/replayshark_battle_report.patch"
wc -l "$BOT/tools/replayshark_float64.patch" "$BOT/tools/replayshark_battle_report.patch"
```

期望:float64 patch 约 20 行;battle-report patch 约 900 行。

- [ ] **Step 2:在干净基线上验证两个 patch 能按顺序套上**

```bash
cd <toolkit>
git stash list | head -1            # 确认没有意外 stash
git checkout --quiet -b _patchtest 2effcd31
BOT=<repo>
git apply --check "$BOT/tools/replayshark_float64.patch" && echo "float64 OK"
git apply "$BOT/tools/replayshark_float64.patch"
git apply --check "$BOT/tools/replayshark_battle_report.patch" && echo "battle-report OK"
```

期望:两行 `OK` 都打出来。

- [ ] **Step 2b:在测试分支上真的编一次 —— 验证配方本身**

只 `git apply --check` 不够:如果走 Task 5 的方案 B(scp 分支源码树),这两个 patch
从头到尾没被"用来构建"过,而「照配方能从零重建」正是本项目的一半目标。所以在
`_patchtest` 分支(= 干净基线 + 两个导出的 patch)上真跑一次编译:

```bash
cd <toolkit>
git apply <repo>/tools/replayshark_battle_report.patch
cargo check -p replayshark 2>&1 | tail -20
```

期望:`Finished`,零 error。与 Task 1 Step 6 共享 target 目录,是增量编译,不会很慢。

若这里失败而 Task 1 Step 6 成功,说明导出 patch 时漏了东西(比如手工放的 hunk 没
`git add`)—— 回 Task 2 Step 1 重新导出。

- [ ] **Step 3:清理测试分支**

```bash
cd <toolkit>
git checkout --quiet -- .
git checkout --quiet replayshark-battle-report
git branch -D _patchtest
git status --short | grep -v '^?? extracted/'
```

期望:最后一条无输出。

- [ ] **Step 4:写构建脚本 `tools/build_replayshark.sh`**

用 Write 工具创建(内容见下)。它要满足:幂等、不碰 `/opt/wows-toolkit`、源码缺失时给出
明确的两条取源路径、编完自检三个子命令在不在。

```bash
#!/usr/bin/env bash
# build_replayshark.sh — 可复现地重建带 battle-report 的 replayshark
#
# 为什么需要这个:report/prebuilt/replayshark-linux-x86_64 里的 battle-report /
# builds-dump / consumables-dump 三个子命令来自 tools/replayshark_battle_report.patch。
# 上游 2026-06-05 删掉了这个 patch 挂靠的 BattleController(改成 BattleWorld/ECS),
# 所以 patch 只能套在那次重构之前的基线上。基线与 patch 顺序都写死在这里。
#
# 用法:
#   bash tools/build_replayshark.sh                 # 默认 /opt/wows-replayshark-build
#   SRC=/path/to/src bash tools/build_replayshark.sh
#
# 前置:源码目录必须已经是基线 commit 的干净树。取源两条路:
#   A) git clone <上游> && git checkout 2effcd31
#   B) 从开发机 scp 一份准备好的源码树上来
# 详见 docs/REPLAYSHARK_BUILD.md

set -euo pipefail

BASELINE=2effcd31
SRC="${SRC:-/opt/wows-replayshark-build}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CARGO="${CARGO:-~<user>/.cargo/bin/cargo}"
BUILD_USER="${BUILD_USER:-<user>}"

die() { echo "error: $*" >&2; exit 1; }

[[ -d "$SRC" ]] || die "源码目录不存在:$SRC(见 docs/REPLAYSHARK_BUILD.md 取源两条路)"
[[ -f "$SRC/Cargo.toml" ]] || die "$SRC 不像 toolkit 源码树(缺 Cargo.toml)"
[[ -x "$CARGO" ]] || die "cargo 不在 $CARGO"

# 绝不在 /opt/wows-toolkit 里编 —— 那里的 target/release/minimap_renderer 是生产在用的
case "$(readlink -f "$SRC")" in
    /opt/wows-toolkit|/opt/wows-toolkit/*)
        die "拒绝在 /opt/wows-toolkit 下编译:它的 target/ 放着生产用的 minimap_renderer" ;;
esac

echo "[1/4] 检查源码基线"
if [[ -d "$SRC/.git" ]]; then
    head="$(git -C "$SRC" rev-parse --short HEAD)"
    echo "  HEAD = $head (期望基线 $BASELINE 或其上已套 patch 的提交)"
fi

echo "[2/4] 应用 patch(已套上的会被跳过)"
for p in replayshark_float64 replayshark_battle_report; do
    f="$REPO_DIR/tools/$p.patch"
    [[ -f "$f" ]] || die "缺 patch 文件:$f"
    if patch -p1 -d "$SRC" --dry-run --forward --silent < "$f" >/dev/null 2>&1; then
        patch -p1 -d "$SRC" --forward --silent < "$f"
        echo "  applied  $p"
    else
        echo "  skipped  $p(已套上,或套不上 —— 下一步编译会暴露)"
    fi
done

echo "[3/4] 编译(release,首次约 5-15 分钟)"
sudo -u "$BUILD_USER" "$CARGO" build --release \
    --manifest-path "$SRC/Cargo.toml" -p replayshark

BIN="$SRC/target/release/replayshark"
[[ -x "$BIN" ]] || die "编完了但没找到 $BIN"

echo "[4/4] 自检三个子命令"
missing=0
for sub in battle-report builds-dump consumables-dump; do
    if "$BIN" --help 2>&1 | grep -q -- "$sub"; then
        echo "  ok   $sub"
    else
        echo "  缺!  $sub"; missing=1
    fi
done
[[ $missing -eq 0 ]] || die "patch 没真正生效(子命令缺失),不要拿这个二进制换装"

echo
echo "done: $BIN"
"$BIN" --version 2>&1 | head -1
echo "下一步:等价性验证,见 tools/verify_replayshark_equiv.sh"
```

- [ ] **Step 5:写 `docs/REPLAYSHARK_BUILD.md`**

用 Write 工具创建,必须写清:

- 为什么二进制不能从当前源码编(上游 `fbc415d5` 删了 `BattleController`)
- 基线 commit `2effcd31`,上游仓库 `https://github.com/landaire/wows-toolkit`
  (本机走 `https://ghfast.top/https://github.com/...` 镜像)
- patch 应用顺序:先 `replayshark_float64.patch`,再 `replayshark_battle_report.patch`
- 工具链:`rust-toolchain.toml` pin `1.92.0`,本机与服务器 cargo 均为 1.92.0
- 构建:`bash tools/build_replayshark.sh`
- 验证:`bash tools/verify_replayshark_equiv.sh`
- 「下次 WG 加新实体类型怎么办」:在基线分支上给 `crates/wowsunpack/src/rpc/typedefs.rs`
  的 `parse_type` 加一个分支,重新导出 `replayshark_float64.patch`(或新加一个 patch),重编

- [ ] **Step 6:提交(先不 push,等 Task 3 一起)**

```bash
cd <repo>
git add tools/replayshark_float64.patch tools/replayshark_battle_report.patch tools/build_replayshark.sh docs/REPLAYSHARK_BUILD.md
git commit -F %TEMP%/p41_t2_msg.txt
```

先用 Write 工具把消息写到那个路径(中文内容不要用 heredoc)。消息要点:基线为什么是
`2effcd31`、patch 应用顺序、可复现性现在靠「公开上游 commit + 仓库里两个 patch」
而不是靠某台机器上的本地分支。末尾加 `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`。

---

## Task 3:写等价性验证脚本

**Files:**
- Create:`%USERPROFILE%\Desktop\wows-bot-review\tools\verify_replayshark_equiv.sh`

- [x] **Step 1:用 Write 工具创建脚本**

> **原计划在这里内嵌了脚本全文,已删除 —— 它被重写过两次,留着只会误导。**
> 以仓库里的 `tools/verify_replayshark_equiv.sh` 为准。演进过程:
>
> 1. **初版**:`cmp -s` 比 JSON 逐字节。首轮实跑 9 局全 DIFF —— 判据在原理上不可能通过,
>    因为 `battle-report` 的输出本身不确定(同一二进制同一局跑两次字节就不同)
> 2. **重做**:改成「深度规范化 + 浮点容差」的 JSON 判据(`tools/rs_compare_report.py`)
>    加「PNG 正文哈希」判据,并加 `[0/2]` 自证步骤先证明 PNG 判据本身有效
> 3. **加分类**:PNG 不一致时自动判断旧二进制自己是否也不稳定 → 「判据失效」类
> 4. **硬化**(最终复审后):堵掉五条假绿灯 —— 整数走相对容差、`png_hash` 失败时空串相等、
>    SKIP 不计入退出码、「判据失效」不比较差异区域(新增 `tools/rs_png_diff.py`)、
>    构建脚本自检覆盖不到 float64 patch
>
> 完整判据说明见 `docs/REPLAYSHARK_BUILD.md` §6。


- [ ] **Step 2:检查脚本语法**

```bash
bash -n <repo>/tools/verify_replayshark_equiv.sh && echo "语法 OK"
```

期望:`语法 OK`

- [ ] **Step 3:提交并推到 gitee**

```bash
cd <repo>
git add tools/verify_replayshark_equiv.sh
git commit -F %TEMP%/p41_t3_msg.txt
git log --oneline -5
git push
```

消息同样先用 Write 工具写到那个路径。**push 前把 `git log --oneline -5` 的结果给用户看**,
确认要推的就是这几个 commit。

---

## Task 4:准备 fixture 并上传(需要主会话与用户交互)

**Files:**
- Create(本机临时):`%TEMP%\rs_fixtures\`

- [ ] **Step 1:本机组装 fixture 目录**

9 局,覆盖两个版本 × 舰种。源目录:
`C:\Program Files (x86)\Steam\steamapps\common\World of Warships\replays\`

```bash
mkdir -p %TEMP%/rs_fixtures
cd "/c/Program Files (x86)/Steam/steamapps/common/World of Warships/replays"
for f in \
 20260918_230201_PBSA108-Implacable_52_Britain \
 20260912_002504_PASS210-Balao_47_Sleeping_Giant \
 20260917_231314_PJSD208-Kagero_46_Estuary \
 20260918_214210_PBSB110-Conqueror_23_Shards \
 20260829_183229_PGSA106-Weser_41_Conquest \
 20260828_001022_PBSS106-Undine_41_Conquest \
 20260824_200315_PZSD910-Black-Lushun_58_RidgeNew \
 20260829_173236_PBSB110-Conqueror_52_Britain \
 20260823_112702_PASC718-AZUR-Montpelier_51_Greece ; do
  cp "$f.wowsreplay" %TEMP%/rs_fixtures/
done
ls %TEMP%/rs_fixtures/ | wc -l
du -sh %TEMP%/rs_fixtures/
```

期望:`9`,约 18 MB。

舰种覆盖(WoWs index 第 4 个字母:A=航母 B=战列 C=巡洋 D=驱逐 S=潜艇):

| 版本 | 航母 | 战列 | 巡洋 | 驱逐 | 潜艇 |
|---|---|---|---|---|---|
| 15.8.0_13187581 | Implacable | Conqueror | **无** | Kagero | Balao |
| 15.7.0_13015811 | Weser | Conqueror | Montpelier | Black-Lushun | Undine |

已知缺口:15.8 本机没有巡洋舰回放;15.3–15.6 完全没有回放。两处都不阻塞 —— 巡洋舰
代码路径由 15.7 那局覆盖。

- [ ] **Step 2:核对每局的 build 号**

```bash
cd <repo> && python -c "
import sys, glob, os
sys.path.insert(0, 'report/lib')
from wowsbot import replay
for f in sorted(glob.glob(r'C:/Users/<you>/AppData/Local/Temp/rs_fixtures/*.wowsreplay')):
    print(replay.version_of(f), replay.build_of(f), os.path.basename(f)[:50])
"
```

期望:只出现 `15.7.0 13015811` 与 `15.8.0 13187581` 两种组合,没有 `13016054`
(那个 build 服务器上没有数据,会被验证脚本 SKIP,白占时间)。

- [ ] **Step 3:让用户先把 SSH 免密配好**

给用户这三条(他在自己的 Git Bash 里跑,`ssh-copy-id` 那步要输一次密码):

```
ssh-keygen -t ed25519 -C "win-dev"
ssh-copy-id <user>@<bot-host>
ssh <user>@<bot-host> 'echo 免密成功'
```

已有 `~/.ssh/id_ed25519` 就跳过第一条。等他贴回 `免密成功`。

如果他不想配免密,改让他自己跑 Step 4 的 scp 命令(要输密码)。

- [ ] **Step 4:上传 fixture**

```bash
ssh <user>@<bot-host> 'mkdir -p /tmp/rs_fixtures'
scp %TEMP%/rs_fixtures/*.wowsreplay <user>@<bot-host>:/tmp/rs_fixtures/
ssh <user>@<bot-host> 'ls /tmp/rs_fixtures | wc -l'
```

期望:`9`

放 `/tmp` 而不是 `/var/lib/wows-data/` —— fixture 是验证用的临时数据,不该混进生产数据目录。
注意 `/tmp` 可能被清理,验证做完就不再需要。

---

## Task 5:服务器取源与编译(需要主会话与用户交互)

- [ ] **Step 1:服务器拉最新 bot 代码**

给用户:

```
cd /opt/wows-bot && sudo git pull
ls -la /opt/wows-bot/tools/build_replayshark.sh /opt/wows-bot/tools/verify_replayshark_equiv.sh
```

期望:两个脚本都在。

- [ ] **Step 2:先试方案 A —— 服务器直接 clone 上游**

给用户:

```
sudo mkdir -p /opt/wows-replayshark-build
sudo chown <user>:<user> /opt/wows-replayshark-build
sudo -u <user> git clone https://ghfast.top/https://github.com/landaire/wows-toolkit.git /opt/wows-replayshark-build 2>&1 | tail -5
```

成功则继续 Step 3;失败(网络不通)则跳到 Step 2b。

- [ ] **Step 2b:方案 B —— 从本机 scp 源码树**

本机把基线分支导成干净树再传(排除 `.git` / `target` / 本地数据):

```bash
cd <toolkit>
git archive --format=tar replayshark-battle-report | gzip > %TEMP%/rs_src.tar.gz
ls -la %TEMP%/rs_src.tar.gz
scp %TEMP%/rs_src.tar.gz <user>@<bot-host>:/tmp/
```

然后给用户:

```
sudo mkdir -p /opt/wows-replayshark-build
sudo chown <user>:<user> /opt/wows-replayshark-build
sudo -u <user> tar xzf /tmp/rs_src.tar.gz -C /opt/wows-replayshark-build
ls /opt/wows-replayshark-build/crates/
```

走方案 B 时源码里**已经带着两个 patch 的内容**(`git archive` 导的是分支 HEAD),
所以 `build_replayshark.sh` 的 patch 步骤会打印 `skipped`,这是正常的。

- [ ] **Step 3:(仅方案 A)切到基线**

给用户:

```
cd /opt/wows-replayshark-build && sudo -u <user> git checkout 2effcd31 2>&1 | tail -3
sudo -u <user> git log -1 --format='%h %ad %s' --date=short
```

期望:`2effcd31 2026-05-21 feat: add support for WASM compilation`

- [ ] **Step 4:编译**

给用户:

```
cd /opt/wows-bot && sudo bash tools/build_replayshark.sh
```

期望:`[4/4] 自检三个子命令` 下面三行 `ok`,最后打出 `done: /opt/wows-replayshark-build/target/release/replayshark`。

首次编译 5–15 分钟。若报编译错误,把完整错误贴回来 —— 大概率是本机 `cargo check`
没覆盖到的 feature 组合,回 Task 1 Step 6 处理。

---

## Task 6:builds-dump 独立检查(需要主会话与用户交互)

- [ ] **Step 1:确认 15.8 原始 scripts 里 FLOAT64 还在**

给用户:

**必须用 `-R` 不是 `-r`** —— extracted 里的 `.def` 是指向 `common/` 内容寻址目录的符号链接,
`grep -r` 不跟软链,会查不到 FLOAT64 从而得出完全相反的结论。

```
grep -Roh 'FLOAT[0-9]*' /var/lib/wows-data/extracted/15.8.0_13187581/vfs/scripts/ | sort | uniq -c
```

期望:`FLOAT64` 计数为 **2**(另有约 211 个 `FLOAT`、39 个 `FLOAT32`)。那 2 处是
`entity_defs/alias.xml` 的 `originalEnqueueTime` 与
`entity_defs/interfaces/BattleStarterClient.def` 的同名参数。

**已于 2026-09-19 通过只读检查提前验证**:15.7.0_13015811 与 15.8.0_13187581 的
原始 `vfs/scripts/` 里 FLOAT64 计数都是 2 —— 原始数据没被手术污染,对比前提成立。
**这一步是为了证明后面的成功不是因为数据被动过手术。** 如果输出为空,停下来 —— 说明
原始数据已被污染,验证无意义。

- [ ] **Step 2:用新二进制在未手术数据上跑 builds-dump**

给用户:

```
sudo mkdir -p /tmp/rs_check
cd /tmp/rs_check && sudo ln -sfn /var/lib/wows-data/extracted/15.8.0_13187581/metadata.toml metadata.toml
sudo ln -sfn /var/lib/wows-data/extracted/15.8.0_13187581/vfs/content content
sudo ln -sfn /var/lib/wows-data/extracted/15.8.0_13187581/vfs/scripts scripts
/opt/wows-replayshark-build/target/release/replayshark -e /tmp/rs_check builds-dump -o /tmp/rs_check/bd.json 2>&1 | tail -5
```

期望:无 panic,打印 `found 118 modernizations / 2345 exteriors / 662 crews / 82 skills`。
数字必须与 15.8 实测一致 —— 少了说明 `PlaneAbilities` 那两个手工 hunk 放错了。

- [ ] **Step 3:对照旧二进制在同一份未手术数据上的表现**

给用户:

```
/opt/wows-bot/report/replayshark -e /tmp/rs_check builds-dump -o /tmp/rs_check/bd_old.json 2>&1 | tail -5
```

期望:**失败**,报 `Unrecognized type FLOAT64` 之类。这是对照组 —— 证明新二进制解决的
正是这个问题。若旧二进制也成功,那 FLOAT64 手术本来就不需要,整个 P4-1 的前提要重新审视,
停下来报告。

---

## Task 7:等价性验证(需要主会话与用户交互)

> **2026-09-19 执行时判据被推翻重做过一次。** 原计划写的是「JSON 逐字节一致」,首轮实跑
> 9 局全 DIFF;诊断发现 `battle-report` 的输出本身就不确定(同一二进制同一局跑两次,
> 大小相同字节不同),所以那个判据连旧二进制自己跟自己比都过不了。下面是最终的判据。
> 完整说明见 `docs/REPLAYSHARK_BUILD.md` §6。

- [x] **Step 1:跑验证脚本**

给用户(**必须 root** —— `specs-patched` 是 `drwx------ root`):

```
cd /opt/wows-bot && sudo bash tools/verify_replayshark_equiv.sh /tmp/rs_fixtures /tmp/rs_equiv
```

脚本先做 `[0/2]` 自证(新二进制同一局跑两遍、渲染两遍、比 PNG 正文哈希),不稳定就退出 ——
不在一个本身无效的判据上宣布通过。然后逐局打 JSON / PNG 两栏。

期望汇总行:`共 9 局 —— 通过 9 / 判据失效 0 / 不通过 0 / 出错 0 / 跳过 0`。
**退出码 0 的条件是「不通过 = 出错 = 跳过 = 0」;「跳过」不是通过。**

- [x] **Step 2:按结果分情况处理**

- **全通过** → 进 Task 8
- **判据失效** → 该局报告本身不确定(排序键并列 + 输入顺序随机),PNG 判据无鉴别力。
  不算失败,但要在记录里点明是哪一局、为什么
- **不通过** → **停下,不换装**。原因会写在那一栏:`不等价` / `哈希失败` / `渲染失败` /
  `不一致(差异区域超出自身抖动范围)` / `不一致(旧二进制自身稳定,是真差异)`。
  把差异连同产物目录交给用户,由**用户决定**是否接受。不要自己判断「差不多」
- **出错 / 跳过** → 跑不起来或缺版本数据,先修环境再说

- [x] **Step 3:PNG 正文哈希对比**

已并入 Step 1 —— PNG 层就是闸门的第二层判据,脚本每局都做,不再单独跑。


## Task 8:换装与收尾(需要主会话与用户交互)

**Files:**
- Modify:`%USERPROFILE%\Desktop\wows-bot-review\report\prebuilt\replayshark-linux-x86_64`
- Modify:`%USERPROFILE%\Desktop\wows-bot-review\docs\UPDATE.md`
- Modify:`%USERPROFILE%\Desktop\wows-bot-review\report\bin\wows_report`(仅注释)

- [ ] **Step 1:备份旧二进制到仓库外**

给用户:

```
sudo cp /opt/wows-bot/report/prebuilt/replayshark-linux-x86_64 /root/replayshark-prebuilt-20260527.bak
ls -la /root/replayshark-prebuilt-20260527.bak
```

期望:4806528 字节。

- [ ] **Step 2:换装**

给用户:

```
sudo cp /opt/wows-replayshark-build/target/release/replayshark /opt/wows-bot/report/prebuilt/replayshark-linux-x86_64
sudo cp /opt/wows-replayshark-build/target/release/replayshark /opt/wows-bot/report/replayshark
sudo chmod +x /opt/wows-bot/report/prebuilt/replayshark-linux-x86_64 /opt/wows-bot/report/replayshark
ls -la /opt/wows-bot/report/replayshark /opt/wows-bot/report/prebuilt/replayshark-linux-x86_64
```

期望:两个文件时间戳是刚才、大小相同(与旧的 4806528 不同是正常的)。

- [ ] **Step 3:端到端跑生产入口**

给用户:

```
/opt/wows-bot/report/bin/wows_full_report /tmp/rs_fixtures/20260918_230201_PBSA108-Implacable_52_Britain.wowsreplay /tmp/rs_e2e 2>&1 | tail -15
ls -la /tmp/rs_e2e/
```

期望:最后打出 PNG 路径,目录里有生成的图。stderr 里**不该**有 `[spoof]`(版本数据齐全)。

**不要重启 nonebot** —— 渲染器是 subprocess 现拉,换二进制立即生效。

- [ ] **Step 4:把新二进制提交进仓库**

```bash
cd <repo>
scp <user>@<bot-host>:/opt/wows-replayshark-build/target/release/replayshark report/prebuilt/replayshark-linux-x86_64
git status --short report/prebuilt/
ls -la report/prebuilt/
```

- [ ] **Step 5:改 `docs/UPDATE.md`**

当前 UPDATE.md 的流程里没有 FLOAT64 手术(手术是 15.7 之后加的债,只记在记忆里),
但 §2 的 `link_specs.sh` 说明有两个问题要顺手修正:

1. 裸跑会挑到 Lesta 26.x(`sort -V | tail -1`)—— 补一句必须显式指定 WG 版本目录
2. 补一句「不再需要 FLOAT64 手术」的说明,并指向 `docs/REPLAYSHARK_BUILD.md`

用 Edit 工具改,不要重写整个文件。

- [ ] **Step 6:给 `report/bin/wows_report` 的 specs-patched 逻辑补注释**

`resolve_specs_for_build` 里这两行:

```python
    scripts = Path(SPECS_PATCHED_ROOT) / match.name / "scripts"
    if not scripts.is_dir():
        scripts = match / "vfs" / "scripts"
```

上面加注释说明:自 P4-1 重建 replayshark 之后,二进制已原生支持 FLOAT64,
specs-patched 不再必需;这段保留是为了兼容老数据目录里已经做过手术的版本,
且优先用它是无害的(手术只把 FLOAT64 换成 FLOAT,对战报数据流零影响)。

**只加注释,不改行为。**

- [ ] **Step 7:跑现有测试套件**

```bash
cd <repo>
for t in tests/test_*.py; do echo "--- $t"; python "$t" 2>&1 | tail -3; done
```

期望:7 个套件全部通过。这些测试不碰 replayshark,但要确认注释改动没弄坏语法。

- [ ] **Step 8:提交并推送**

```bash
cd <repo>
git add report/prebuilt/replayshark-linux-x86_64 docs/UPDATE.md report/bin/wows_report
git commit -F %TEMP%/p41_t8_msg.txt
git log --oneline -3
git push
```

消息先用 Write 工具写到那个路径,要点:等价性验证结果(9 局 SAME)、PNG 哈希一致、
旧二进制备份位置 `/root/replayshark-prebuilt-20260527.bak`、回滚方法(一条 cp)。
末尾加 `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`。

- [ ] **Step 9:更新记忆**

改 `<claude 配置目录>\projects\C--Users-<you>-Desktop-minimap-wows-toolkit\memory\wg_1570_update_notes.md`:

- 「坑 2」整段改写:FLOAT64 手术**已消灭**,指向 `docs/REPLAYSHARK_BUILD.md`
- 「标准更新流程」里删掉第 3 步(手术)与第 4 步的第二条(`ln -sfn specs-patched`)
- 「彻底解法两条(都没做)」改成:已走第 ② 条的变体(在 patch 同期基线上重建),
  第 ① 条(切 normalized)仍未做、属于 P5
- 补一条:`build_builds_json.py` / `fetch_build_icons.py` 的默认路径 P2 已修好,
  现在裸跑即可,不用再带 `WOWS_REPLAYSHARK=` 和 `--specs`

同时在 `MEMORY.md` 里确认那条指针的描述仍然准确。

- [ ] **Step 10:清理服务器临时文件**

给用户(可选,他自己决定要不要留着):

```
sudo rm -rf /tmp/rs_fixtures /tmp/rs_equiv /tmp/rs_check /tmp/rs_e2e /tmp/rs_src.tar.gz
```

`/opt/wows-replayshark-build` **保留** —— 下次要改 replayshark 就在那里改,是可复现构建现场。

---

## 完成标准

对照设计文档的验收清单逐条核:

- [ ] 本机 `cargo check -p replayshark` 零错误(Task 1 Step 6)
- [ ] 重新生成的两个 patch 在干净 `2effcd31` 上按序 `git apply --check` 通过(Task 2 Step 2)
- [ ] 服务器 `cargo build --release -p replayshark` 零错误(Task 5 Step 4)
- [ ] 新二进制在**未手术**的 15.8 scripts 上 `builds-dump` 成功,计数 118 / 2345 / 662 / 82(Task 6 Step 2)
- [ ] 旧二进制在同一份数据上**失败**(对照组,Task 6 Step 3)
- [ ] 9 局 fixture 的 battle-report JSON 全部 SAME(Task 7 Step 1)
- [ ] CV 那局的战报 PNG 正文哈希新旧一致(Task 7 Step 3)
- [ ] `wows_full_report` 端到端跑通且 stderr 无 `[spoof]`(Task 8 Step 3)
- [ ] `docs/REPLAYSHARK_BUILD.md` 的配方完整到照着能从零重建
- [ ] 记忆里的 FLOAT64 手术步骤已删除


---

## 执行记录(2026-09-19)

### 结果

| Task | 结果 |
|---|---|
| 1 建分支 + 套 patch | 完成。`c7760c47`(FLOAT64 cherry-pick)+ `86e9d7ba`(patch)。**零 fuzz、零编译错误**;`provider.rs` 那 2 个 hunk 手工放,缩进比 patch 浅 16 空格(上游把该 match 从嵌套闭包里提了出来) |
| 2 导出构建配方 | 完成。两个 patch + `build_replayshark.sh` + `REPLAYSHARK_BUILD.md`。在干净基线上重建的树与 Task 1 分支 `git diff` **整棵树零字节差异**;正序反序皆可、幂等 |
| 3 等价性验证脚本 | 完成,后续因判据推翻而重写,并补了 `rs_compare_report.py` / `rs_png_diff.py` |
| 4 fixture | 9 局上传到服务器 `/tmp/rs_fixtures`(18 MB) |
| 5 服务器编译 | 完成。方案 A(clone 上游)可行,`cargo 1.92.0`,release 编译 30 秒 |
| 6 builds-dump 独立检查 | 新二进制在**未手术** 15.8 上 `118 / 2345 / 662 / 82`;旧二进制同一份数据 `panicked: Unrecognized type FLOAT64` —— 对照组成立 |
| 7 等价性闸门 | 见下 |
| 8 换装 | 完成。`0c1bf7a`。端到端 `wows_full_report` 四段全过,无 `[spoof]` |

### 闸门结果

- **数据层**:9/9 规范化后等价。浮点容差只在 1 处被用到,最大相对偏差 **1.665e-16**(一个 ULP)
- **外观层**:8/9 PNG 正文哈希逐像素一致
- **第 9 局**(`20260824_200315_PZSD910-Black-Lushun_58_RidgeNew`,15.7 驱逐舰)判**判据失效**:
  差异是玩家表最后两行(两个 0 伤害玩家)互换,区域 `y=935..995 / x=78..1337`、占 0.26% 像素。
  旧二进制自己跑三次得到三个不同哈希(`1cbb9bae69f0c2de` / `f117dcc14c36d75f` /
  `dbc4fd06888a0089`)→ 该局报告本身不确定,与重建无关。
  成因:`render_battle_report.py:369` `sorted(key=lambda p: -p.damage_dealt)` 并列时靠输入顺序,
  而输入顺序来自随机的 HashMap 迭代。**用户已知情并决定不修这个排序 bug。**

### 二进制

| | 大小 | sha256 |
|---|---|---|
| 旧(2026-05-27) | 4806528 | `19764382…`,备份在 `/root/replayshark-prebuilt-20260527.bak` |
| 新(2026-09-19) | 5919456 | `f6b9af57de554df0471d2411a03cf7acba9c74bef14a45a447b6ef5e1cdbafee` |

### 判据被推翻这件事

首轮闸门 9 局全 DIFF。诊断:`battle-report` 输出本身不确定 —— 同一二进制同一局跑两次,
大小相同(1021979)字节不同;`damage_events`(1115 条)与 `deaths`(15 条)多重集相同仅排列不同;
`players[].stats.damage_dealt` 差一个 ULP。所以「逐字节一致」在原理上不可能通过。
改为「深度规范化 + 浮点容差」+「PNG 正文哈希」两层,并加 `[0/2]` 自证步骤。
**这是计划的设计错误,不是重建的问题。**

### 未覆盖 / 已知缺口

- **15.3–15.6 无回放可验**。风险已量化为低:回放解码路径 `decode.rs` 相对 patch 基线只漂 2 行,
  且是 `u32` → `PacketTypeId` newtype 的纯类型改动,零语义
- **15.8 缺巡洋舰回放**(巡洋只在 15.7 覆盖)
- **`builds-dump` 只做了计数校验,未逐字段 diff**。`types.rs` 的 11 行漂移是 `CrewPersonality`
  字段 Option 化,已查实当前消费侧只读 `id`/`name` 所以无影响 —— 是运气不是覆盖
- **二进制不是比特级可复现**(rustc 默认不保证)。已建立的是「源码状态可复现」
- 玩家表排序在并列时不稳定(用户决定不修)→ 闸门的「判据失效」这一类将长期存在,
  而它的包围盒判定对「落在抖动矩形内部的回归」是盲的

### 最终复审后的修正

一次独立整体复审找出 18 条问题,无一条要推翻换装。已处理:

- `docs/UPDATE.md` / `docs/DEPLOY.md` 两处「从源码重编」配方陈旧且危险(叫人在
  `/opt/wows-toolkit` 里编 —— 那是构建脚本硬性拒绝的路径,它的 `target/` 放着生产用的
  `minimap_renderer`;且不切基线、漏 float64 patch)
- 回滚命令此前只在设计文档里,而两篇例行文档有一条会静默撤销回滚的 `cp`
- 闸门五条假绿灯:整数走相对容差、`png_hash` 失败时空串相等、SKIP 不计入退出码、
  「判据失效」不比较差异区域、构建脚本自检覆盖不到 float64 patch
  (顺带:原本建议的 `grep -q 'FLOAT64'` 判据**本身**也是假绿灯 —— 未打 patch 的原文里
  就有一行注释含这个词,改用 `grep -F 't == "FLOAT64"'`)
- `REPLAYSHARK_BUILD.md` §6/§10 描述的还是被废弃的逐字节闸门,已重写并补 fixture 组法、
  环境变量、回滚一节
