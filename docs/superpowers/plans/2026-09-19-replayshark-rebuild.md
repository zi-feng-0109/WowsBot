# P4-1 重建 replayshark 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `report/replayshark` 换成「patch 同期源码 + FLOAT64 修复」重编的二进制,使 WoWs 大版本更新不再需要 FLOAT64 sed 手术,同时把构建配方写进仓库。

**Architecture:** 不动当前源码(上游 2026-06-05 删掉了 patch 挂靠的 `BattleController`)。改为以上游 `2effcd31`(2026-05-21)为基线,叠加两个 patch(FLOAT64 修复、battle-report 功能),在服务器上编译,用「同一批回放的 battle-report JSON 逐字节一致」作为换装闸门。

**Tech Stack:** Rust 1.92.0 / cargo(本机与服务器版本一致)、`git apply -3` 与 `patch(1)`、Python 3(哈希对比)、bash。

**设计文档:** `docs/superpowers/specs/2026-09-19-replayshark-rebuild-design.md`

---

## 执行须知(违反会出事,先读)

1. **不要连服务器。** 所有服务器命令由用户在他自己的终端里跑,你只负责给命令、读他贴回来的输出。
   涉及服务器的任务(Task 4、5、6、7、8)**不能交给 subagent** —— subagent 没法跟用户对话。
   这些任务必须在主会话里执行。
2. **不要重启任何服务。** 纯数据/二进制更新不需要重启 nonebot(渲染器是 subprocess 现拉)。
   哪怕看起来该重启,也只是提示用户,由他决定。
3. **不要在 `/opt/wows-toolkit` 里编译。** 它的 `target/release/minimap_renderer` 是**生产在用的**
   小地图二进制(2026-08-14)。构建目录必须隔离到 `/opt/wows-replayshark-build/`。
4. **两个仓库,别搞混:**
   - toolkit fork:`C:\Users\29801\Desktop\minimap\wows-toolkit`(有 git 历史,只有 `upstream` remote,
     本地 commit 没推到任何地方)—— 在这里建分支、解 patch
   - bot 仓:`C:\Users\29801\Desktop\wows-bot-review`(推 gitee,服务器 `/opt/wows-bot` 就是它)
     —— 这里放 patch 文件、构建文档、prebuilt 二进制
5. **写文件用 Write 工具,不要用 bash heredoc。** 本项目文档含中文全角括号与引号,
   heredoc 在这台机器上反复出过字符串截断问题。
6. Windows 上 `patch` / `git` 在 Git Bash 里跑;注意 CRLF —— 现成的 patch 文件是 CRLF 的,
   必须先 `tr -d '\r'`,否则 `git apply` 直接判不匹配(这正是当初"patch 套不上了"的一半原因)。

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
cd /c/Users/29801/Desktop/minimap/wows-toolkit
git status --short | grep -v '^?? extracted/'
git branch --show-current
```

期望:第一条无输出(除了 untracked 的 `extracted/`),第二条输出 `master`。
如果有未提交改动,**停下来问用户**,不要 stash 或丢弃。

- [ ] **Step 2:从基线建分支**

```bash
cd /c/Users/29801/Desktop/minimap/wows-toolkit
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
tr -d '\r' < /c/Users/29801/Desktop/wows-bot-review/tools/replayshark_battle_report.patch > /tmp/bp_lf.patch
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
cd /c/Users/29801/Desktop/minimap/wows-toolkit
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
- Create:`C:\Users\29801\Desktop\wows-bot-review\tools\replayshark_float64.patch`
- Modify:`C:\Users\29801\Desktop\wows-bot-review\tools\replayshark_battle_report.patch`
- Create:`C:\Users\29801\Desktop\wows-bot-review\tools\build_replayshark.sh`
- Create:`C:\Users\29801\Desktop\wows-bot-review\docs\REPLAYSHARK_BUILD.md`

- [ ] **Step 1:导出两个 patch**

```bash
cd /c/Users/29801/Desktop/minimap/wows-toolkit
BOT=/c/Users/29801/Desktop/wows-bot-review
git diff 2effcd31..HEAD~1 -- crates/wowsunpack/src/rpc/typedefs.rs > "$BOT/tools/replayshark_float64.patch"
git diff HEAD~1..HEAD > "$BOT/tools/replayshark_battle_report.patch"
wc -l "$BOT/tools/replayshark_float64.patch" "$BOT/tools/replayshark_battle_report.patch"
```

期望:float64 patch 约 20 行;battle-report patch 约 900 行。

- [ ] **Step 2:在干净基线上验证两个 patch 能按顺序套上**

```bash
cd /c/Users/29801/Desktop/minimap/wows-toolkit
git stash list | head -1            # 确认没有意外 stash
git checkout --quiet -b _patchtest 2effcd31
BOT=/c/Users/29801/Desktop/wows-bot-review
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
cd /c/Users/29801/Desktop/minimap/wows-toolkit
git apply /c/Users/29801/Desktop/wows-bot-review/tools/replayshark_battle_report.patch
cargo check -p replayshark 2>&1 | tail -20
```

期望:`Finished`,零 error。与 Task 1 Step 6 共享 target 目录,是增量编译,不会很慢。

若这里失败而 Task 1 Step 6 成功,说明导出 patch 时漏了东西(比如手工放的 hunk 没
`git add`)—— 回 Task 2 Step 1 重新导出。

- [ ] **Step 3:清理测试分支**

```bash
cd /c/Users/29801/Desktop/minimap/wows-toolkit
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
CARGO="${CARGO:-/home/zifeng/.cargo/bin/cargo}"
BUILD_USER="${BUILD_USER:-zifeng}"

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
cd /c/Users/29801/Desktop/wows-bot-review
git add tools/replayshark_float64.patch tools/replayshark_battle_report.patch tools/build_replayshark.sh docs/REPLAYSHARK_BUILD.md
git commit -F /c/Users/29801/AppData/Local/Temp/p41_t2_msg.txt
```

先用 Write 工具把消息写到那个路径(中文内容不要用 heredoc)。消息要点:基线为什么是
`2effcd31`、patch 应用顺序、可复现性现在靠「公开上游 commit + 仓库里两个 patch」
而不是靠某台机器上的本地分支。末尾加 `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`。

---

## Task 3:写等价性验证脚本

**Files:**
- Create:`C:\Users\29801\Desktop\wows-bot-review\tools\verify_replayshark_equiv.sh`

- [ ] **Step 1:用 Write 工具创建脚本**

```bash
#!/usr/bin/env bash
# verify_replayshark_equiv.sh — 新旧 replayshark 的 battle-report 输出等价性对比
#
# 换装闸门:旧二进制读「手术过的 specs」,新二进制读「未手术的原始 scripts」,
# 同一批回放跑 battle-report,JSON 必须逐字节一致。一致才说明重建没改变战报。
#
# 用法:
#   bash tools/verify_replayshark_equiv.sh <fixture 目录> [输出目录]
#
# fixture 目录里放 .wowsreplay;脚本按每局回放自己的 build 号去 extracted/ 找对应版本数据。

set -uo pipefail

FIXTURES="${1:?用法: verify_replayshark_equiv.sh <fixture 目录> [输出目录]}"
OUT="${2:-/tmp/rs_equiv}"
OLD_BIN="${OLD_BIN:-/opt/wows-bot/report/replayshark}"
NEW_BIN="${NEW_BIN:-/opt/wows-replayshark-build/target/release/replayshark}"
EXTRACTED="${EXTRACTED:-/var/lib/wows-data/extracted}"
PATCHED="${PATCHED:-/var/lib/wows-data/specs-patched}"

for b in "$OLD_BIN" "$NEW_BIN"; do
    [[ -x "$b" ]] || { echo "error: 没有可执行的 $b" >&2; exit 1; }
done
mkdir -p "$OUT"

# 从回放头部读 build 号:magic(4) blockCount(4) meta_len(4) 然后是 UTF-8 JSON meta,
# clientVersionFromExe 形如 "15,8,0,13187581",最后一段就是 build
read_build() {
    python3 - "$1" <<'PY'
import json, struct, sys
with open(sys.argv[1], 'rb') as f:
    if f.read(4) != b'\x12\x32\x34\x11': sys.exit(1)
    f.read(4)
    n = struct.unpack('<I', f.read(4))[0]
    meta = json.loads(f.read(n).decode('utf-8'))
print(meta['clientVersionFromExe'].split(',')[-1].strip())
PY
}

# 按 build 号定位 extracted 下的 <ver>_<build> 目录
version_dir() {
    local build="$1"
    for d in "$EXTRACTED"/*_"$build"; do
        [[ -d "$d" ]] && { echo "$d"; return 0; }
    done
    return 1
}

# 组一份 specs:三个软链指向 metadata/content/scripts
make_specs() {
    local vdir="$1" scripts="$2" tmp
    tmp="$(mktemp -d /tmp/rs_specs_XXXXXX)"
    ln -s "$vdir/metadata.toml" "$tmp/metadata.toml"
    ln -s "$vdir/vfs/content"   "$tmp/content"
    ln -s "$scripts"            "$tmp/scripts"
    echo "$tmp"
}

total=0; same=0; diff_n=0; err=0
printf "%-58s %-10s %s\n" "回放" "build" "结果"
for r in "$FIXTURES"/*.wowsreplay; do
    [[ -f "$r" ]] || continue
    total=$((total+1))
    name="$(basename "$r" .wowsreplay)"
    build="$(read_build "$r" 2>/dev/null)"
    if [[ -z "$build" ]]; then
        printf "%-58s %-10s %s\n" "$name" "-" "ERROR 读不出 build"; err=$((err+1)); continue
    fi
    vdir="$(version_dir "$build")" || {
        printf "%-58s %-10s %s\n" "$name" "$build" "SKIP extracted 里没这个 build"; continue; }
    vname="$(basename "$vdir")"
    consts="$vdir/constants.json"

    old_scripts="$PATCHED/$vname/scripts"
    [[ -d "$old_scripts" ]] || old_scripts="$vdir/vfs/scripts"
    new_scripts="$vdir/vfs/scripts"

    s_old="$(make_specs "$vdir" "$old_scripts")"
    s_new="$(make_specs "$vdir" "$new_scripts")"
    j_old="$OUT/$name.old.json"; j_new="$OUT/$name.new.json"

    rc_old=0; rc_new=0
    "$OLD_BIN" -e "$s_old" ${consts:+-c "$consts"} battle-report "$r" -o "$j_old" \
        >"$OUT/$name.old.log" 2>&1 || rc_old=$?
    "$NEW_BIN" -e "$s_new" ${consts:+-c "$consts"} battle-report "$r" -o "$j_new" \
        >"$OUT/$name.new.log" 2>&1 || rc_new=$?
    rm -rf "$s_old" "$s_new"

    if [[ $rc_old -ne 0 || $rc_new -ne 0 ]]; then
        printf "%-58s %-10s %s\n" "$name" "$build" "ERROR old_rc=$rc_old new_rc=$rc_new(见 $OUT/$name.*.log)"
        err=$((err+1)); continue
    fi
    if cmp -s "$j_old" "$j_new"; then
        printf "%-58s %-10s %s\n" "$name" "$build" "SAME"; same=$((same+1))
    else
        printf "%-58s %-10s %s\n" "$name" "$build" "DIFF(见下方摘要)"; diff_n=$((diff_n+1))
    fi
done

echo
echo "共 $total 局:SAME=$same  DIFF=$diff_n  ERROR=$err"
if [[ $diff_n -gt 0 ]]; then
    echo
    echo "=== DIFF 摘要(每局最多 20 行) ==="
    for j in "$OUT"/*.old.json; do
        n="$(basename "$j" .old.json)"
        cmp -s "$j" "$OUT/$n.new.json" && continue
        echo "--- $n"
        diff <(python3 -m json.tool "$j" 2>/dev/null) \
             <(python3 -m json.tool "$OUT/$n.new.json" 2>/dev/null) | head -20
    done
fi
[[ $diff_n -eq 0 && $err -eq 0 ]]
```

- [ ] **Step 2:检查脚本语法**

```bash
bash -n /c/Users/29801/Desktop/wows-bot-review/tools/verify_replayshark_equiv.sh && echo "语法 OK"
```

期望:`语法 OK`

- [ ] **Step 3:提交并推到 gitee**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add tools/verify_replayshark_equiv.sh
git commit -F /c/Users/29801/AppData/Local/Temp/p41_t3_msg.txt
git log --oneline -5
git push
```

消息同样先用 Write 工具写到那个路径。**push 前把 `git log --oneline -5` 的结果给用户看**,
确认要推的就是这几个 commit。

---

## Task 4:准备 fixture 并上传(需要主会话与用户交互)

**Files:**
- Create(本机临时):`C:\Users\29801\AppData\Local\Temp\rs_fixtures\`

- [ ] **Step 1:本机组装 fixture 目录**

9 局,覆盖两个版本 × 舰种。源目录:
`C:\Program Files (x86)\Steam\steamapps\common\World of Warships\replays\`

```bash
mkdir -p /c/Users/29801/AppData/Local/Temp/rs_fixtures
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
  cp "$f.wowsreplay" /c/Users/29801/AppData/Local/Temp/rs_fixtures/
done
ls /c/Users/29801/AppData/Local/Temp/rs_fixtures/ | wc -l
du -sh /c/Users/29801/AppData/Local/Temp/rs_fixtures/
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
cd /c/Users/29801/Desktop/wows-bot-review && python -c "
import sys, glob, os
sys.path.insert(0, 'report/lib')
from wowsbot import replay
for f in sorted(glob.glob(r'C:/Users/29801/AppData/Local/Temp/rs_fixtures/*.wowsreplay')):
    print(replay.version_of(f), replay.build_of(f), os.path.basename(f)[:50])
"
```

期望:只出现 `15.7.0 13015811` 与 `15.8.0 13187581` 两种组合,没有 `13016054`
(那个 build 服务器上没有数据,会被验证脚本 SKIP,白占时间)。

- [ ] **Step 3:让用户先把 SSH 免密配好**

给用户这三条(他在自己的 Git Bash 里跑,`ssh-copy-id` 那步要输一次密码):

```
ssh-keygen -t ed25519 -C "win-dev"
ssh-copy-id zifeng@192.168.31.252
ssh zifeng@192.168.31.252 'echo 免密成功'
```

已有 `~/.ssh/id_ed25519` 就跳过第一条。等他贴回 `免密成功`。

如果他不想配免密,改让他自己跑 Step 4 的 scp 命令(要输密码)。

- [ ] **Step 4:上传 fixture**

```bash
ssh zifeng@192.168.31.252 'mkdir -p /tmp/rs_fixtures'
scp /c/Users/29801/AppData/Local/Temp/rs_fixtures/*.wowsreplay zifeng@192.168.31.252:/tmp/rs_fixtures/
ssh zifeng@192.168.31.252 'ls /tmp/rs_fixtures | wc -l'
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
sudo chown zifeng:zifeng /opt/wows-replayshark-build
sudo -u zifeng git clone https://ghfast.top/https://github.com/landaire/wows-toolkit.git /opt/wows-replayshark-build 2>&1 | tail -5
```

成功则继续 Step 3;失败(网络不通)则跳到 Step 2b。

- [ ] **Step 2b:方案 B —— 从本机 scp 源码树**

本机把基线分支导成干净树再传(排除 `.git` / `target` / 本地数据):

```bash
cd /c/Users/29801/Desktop/minimap/wows-toolkit
git archive --format=tar replayshark-battle-report | gzip > /c/Users/29801/AppData/Local/Temp/rs_src.tar.gz
ls -la /c/Users/29801/AppData/Local/Temp/rs_src.tar.gz
scp /c/Users/29801/AppData/Local/Temp/rs_src.tar.gz zifeng@192.168.31.252:/tmp/
```

然后给用户:

```
sudo mkdir -p /opt/wows-replayshark-build
sudo chown zifeng:zifeng /opt/wows-replayshark-build
sudo -u zifeng tar xzf /tmp/rs_src.tar.gz -C /opt/wows-replayshark-build
ls /opt/wows-replayshark-build/crates/
```

走方案 B 时源码里**已经带着两个 patch 的内容**(`git archive` 导的是分支 HEAD),
所以 `build_replayshark.sh` 的 patch 步骤会打印 `skipped`,这是正常的。

- [ ] **Step 3:(仅方案 A)切到基线**

给用户:

```
cd /opt/wows-replayshark-build && sudo -u zifeng git checkout 2effcd31 2>&1 | tail -3
sudo -u zifeng git log -1 --format='%h %ad %s' --date=short
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

```
grep -rl 'FLOAT64' /var/lib/wows-data/extracted/15.8.0_13187581/vfs/scripts/ | head -5
```

期望:能列出文件(至少 `entity_defs/alias.xml` 与 `entity_defs/interfaces/BattleStarterClient.def`)。
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

- [ ] **Step 1:跑验证脚本**

给用户:

```
cd /opt/wows-bot && sudo bash tools/verify_replayshark_equiv.sh /tmp/rs_fixtures /tmp/rs_equiv
```

期望:9 行结果全 `SAME`,末尾 `共 9 局:SAME=9  DIFF=0  ERROR=0`。

- [ ] **Step 2:按结果分三种情况处理**

- **全 SAME** → 通过,进 Task 8
- **有 ERROR** → 看 `/tmp/rs_equiv/<name>.{old,new}.log`。常见原因:该 build 的
  `specs-patched` 不存在导致旧二进制读原始 scripts 而 panic(15.7/15.8 都已确认存在,
  所以不该发生);或 constants.json 缺失
- **有 DIFF** → **停下,不换装**。把脚本打的 DIFF 摘要完整交给用户,逐处说明差异字段
  和可能成因,由**用户决定**是否接受。不要自己判断"差不多"

- [ ] **Step 3:PNG 正文哈希对比**

battle-report JSON 一致的话 PNG 理论上必然一致,但渲染器读 JSON 的路径值得实测一次。
给用户(挑 fixture 里的 CV 那局,字段最多):

渲染器要 PIL,系统 `python3` 不一定有 —— 生产走 `find_python()`,优先
`/opt/wows-bot/report/venv/bin/python`。所以先解析解释器再用:

```
PY=/opt/wows-bot/report/venv/bin/python; [ -x "$PY" ] || PY=python3; echo "用 $PY"
cd /opt/wows-bot/report/bin
sudo $PY render_battle_report.py /tmp/rs_equiv/20260918_230201_PBSA108-Implacable_52_Britain.old.json /tmp/rs_equiv/old.png
sudo $PY render_battle_report.py /tmp/rs_equiv/20260918_230201_PBSA108-Implacable_52_Britain.new.json /tmp/rs_equiv/new.png
sudo $PY -c "
from PIL import Image; import hashlib
def h(p):
    im = Image.open(p).convert('RGB')
    im = im.crop((0, 0, im.width, im.height - 48))   # 裁掉含 datetime.now() 的页脚
    return hashlib.sha256(im.tobytes()).hexdigest()[:16], im.size
print('old', *h('/tmp/rs_equiv/old.png'))
print('new', *h('/tmp/rs_equiv/new.png'))
"
```

期望:两行哈希与尺寸都相同。

---

## Task 8:换装与收尾(需要主会话与用户交互)

**Files:**
- Modify:`C:\Users\29801\Desktop\wows-bot-review\report\prebuilt\replayshark-linux-x86_64`
- Modify:`C:\Users\29801\Desktop\wows-bot-review\docs\UPDATE.md`
- Modify:`C:\Users\29801\Desktop\wows-bot-review\report\bin\wows_report`(仅注释)

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
cd /c/Users/29801/Desktop/wows-bot-review
scp zifeng@192.168.31.252:/opt/wows-replayshark-build/target/release/replayshark report/prebuilt/replayshark-linux-x86_64
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
cd /c/Users/29801/Desktop/wows-bot-review
for t in tests/test_*.py; do echo "--- $t"; python "$t" 2>&1 | tail -3; done
```

期望:7 个套件全部通过。这些测试不碰 replayshark,但要确认注释改动没弄坏语法。

- [ ] **Step 8:提交并推送**

```bash
cd /c/Users/29801/Desktop/wows-bot-review
git add report/prebuilt/replayshark-linux-x86_64 docs/UPDATE.md report/bin/wows_report
git commit -F /c/Users/29801/AppData/Local/Temp/p41_t8_msg.txt
git log --oneline -3
git push
```

消息先用 Write 工具写到那个路径,要点:等价性验证结果(9 局 SAME)、PNG 哈希一致、
旧二进制备份位置 `/root/replayshark-prebuilt-20260527.bak`、回滚方法(一条 cp)。
末尾加 `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`。

- [ ] **Step 9:更新记忆**

改 `C:\Users\29801\.claude\projects\C--Users-29801-Desktop-minimap-wows-toolkit\memory\wg_1570_update_notes.md`:

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
