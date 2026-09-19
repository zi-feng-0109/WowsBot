# 重建带 battle-report 的 replayshark

这篇文档解决一个具体的历史债:生产在用的 `report/prebuilt/replayshark-linux-x86_64`
(2026-05-27 编出来的)**没人能再造出来了**。本文给出可复现的配方。

读这篇之前先明确三个名字:

| 名字 | 是什么 |
| --- | --- |
| **上游** | `https://github.com/landaire/wows-toolkit`,Rust workspace,不是我们的仓库 |
| **基线** | 上游 commit `2effcd31`,patch 唯一能套上的那个点 |
| **patch** | 本仓库 `tools/replayshark_float64.patch` + `tools/replayshark_battle_report.patch` |

---

## 1. 为什么不能从当前上游源码直接编

`replayshark` 是上游的调试 CLI,上游版本**没有** `battle-report` / `builds-dump` /
`consumables-dump` 这三个子命令 —— 它们是我们自己加的,靠
`tools/replayshark_battle_report.patch` 注入。

这个 patch 挂靠在 `crates/wows-replays/src/analyzer/battle_controller/controller.rs` 里的
`BattleController` 与 `BattleReport` 上。上游 2026-06-05 的

```
fbc415d5  refactor: remove old BattleController;
          replace differential tests with BattleWorld golden snapshots
```

把这套东西整体重写成了 ECS:

- `struct BattleController` 在当前 `upstream/main` 里**已经不存在**(全仓搜不到);
- `BattleReport` 搬到了新 crate,现在住在 `crates/wows-battle-world/src/report.rs`;
- `controller.rs` 这个文件路径还在,但内容被重写,体积从 129719 字节缩到 47706 字节,
  patch 的上下文一行都对不上。

实测(把当前 `upstream/main` 的 5 个目标文件取出来跑 `patch --dry-run`):

| patch 版本 | 总 hunk | 失败 | 其中 `controller.rs` |
| --- | --- | --- | --- |
| 旧的 2026-05 版(CRLF) | 22 | **15** | 9/9 全失败 |
| 本次重新导出的版本 | 22 | **13** | 9/9 全失败 |

`controller.rs` 的 9 个 hunk 是战报逻辑的全部,它们全失败就意味着**在重构后的源码上没有
任何补救余地**。这不是「手工调一下 offset 就行」的级别,而是要把整套提取逻辑对着 ECS 重写。

所以结论:**这个二进制只能在重构之前的基线上编。** 下面写死基线。

---

## 2. 基线:`2effcd31`

```
2effcd31  2026-05-21  feat: add support for WASM compilation
```

- 它在公开上游的 `main` 分支上(`git branch -r --contains 2effcd31` → `upstream/main`),
  不是某台机器上的私货,所以任何人都能取到。
- 大陆网络走镜像:`https://ghfast.top/https://github.com/landaire/wows-toolkit.git`

**为什么确定是这个 commit,而不是附近某个:** 旧 patch 的 diff 头部记录了它当初的基线
blob 哈希。对 `controller.rs` 这一条:

```
index 98a527d..12c9f68 100644
       ^^^^^^^ 旧 patch 的输入 blob
```

而 `2effcd31` 里那份 `controller.rs` 的 blob 恰好就是 `98a527d`。更进一步,我们在基线上重建
出来的结果 blob 也是 `12c9f68` —— **输入和输出两端都对上了**,说明重建出的 `controller.rs`
与 2026-05 那个二进制编译时用的那一份逐字节相同。战报逻辑的核心文件完全可信。

(旁注:`main.rs` 的基线 blob 旧 patch 记的是 `bd80d52`,基线上是 `87e964b` —— 旧 patch 的
`main.rs` 部分是对着一棵稍有差异的树写的。这也正是旧 patch 需要重新导出的原因之一。)

---

## 3. patch 应用顺序

**先 float64,后 battle-report。**

```
tools/replayshark_float64.patch          ~20 行,只改 crates/wowsunpack/src/rpc/typedefs.rs
tools/replayshark_battle_report.patch    ~1030 行,改 5 个文件
```

`replayshark_battle_report.patch` 是在「基线 + float64」之上生成的,按这个顺序套才与导出时的
状态一致。(两个 patch 实际没有文件重叠,反序也不会冲突,但别依赖这一点 —— 以后往 float64
patch 里加东西就可能重叠了。)

`replayshark_float64.patch` 做的事:给 `parse_type` 加上 `FLOAT64` 分支。游戏 15.7 引入了这个
实体类型,不认它的话 GameParams 的 rkyv 派生直接失败。**这一条是我们摆脱「FLOAT64 手术」
的关键** —— 详见第 8 节。

两个 patch 文件都是 **LF 换行**。以后重新导出时务必保持,CRLF 的 patch 在 Linux 上会出诡异
的上下文不匹配。

### 验证结论(2026-09-19)

在干净的 `2effcd31` 上按序套两个 patch,得到的工作区与已经**实测跑通过 15.8 原始数据**的
开发分支 HEAD **逐字节相同**(`git diff <那个分支>` 全路径零输出),并且
`cargo check -p replayshark` 零 error。也就是说:这份配方重建出的源码状态,就是那个验证过的
源码状态,不是「看起来差不多」。

---

## 4. 工具链

基线的 `rust-toolchain.toml` 把 channel pin 在 **`1.92.0`**:

```toml
[toolchain]
channel = "1.92.0"
components = [ "rustfmt", "clippy" ]
targets = [ "wasm32-unknown-unknown" ]
```

已确认开发机与服务器的 cargo 都是 `1.92.0 (344c4567c 2025-10-21)`,不需要额外装 toolchain。
如果服务器上 rustup 没有 1.92.0,`rust-toolchain.toml` 会触发自动下载 —— 离线机器上要先准备好。

---

## 5. 取源与构建

### 取源两条路

**A) 从上游 clone(推荐,可复现性最强)**

```bash
git clone https://ghfast.top/https://github.com/landaire/wows-toolkit.git /opt/wows-replayshark-build
cd /opt/wows-replayshark-build
git checkout 2effcd31
```

**B) 从开发机 scp 一份准备好的源码树**

开发机上如果已经有 checkout 到基线的干净树,直接打包传上去即可。注意**别把 `target/` 和
本机的 `extracted/` 一起传**(前者几个 G,后者几百 M)。

### 构建

```bash
bash tools/build_replayshark.sh
```

默认源码目录 `/opt/wows-replayshark-build`,可用 `SRC=...` 覆盖。脚本会:

1. 检查源码目录像不像 toolkit 树,报告 HEAD;
2. 按序套两个 patch(`patch --dry-run --forward` 先探一次,已套上的跳过,所以**可以重跑**);
3. `cargo build --release -p replayshark`(首次 5-15 分钟);
4. **自检三个子命令都在 `--help` 里** —— 这一步是防「patch 被静默跳过、编出个上游原版
   replayshark」的兜底。基线不对时第 2 步会跳过 battle-report patch,编译仍然会成功,
   只有这个自检能抓到。缺子命令就直接 `die`,不给你拿它去换装的机会。

可调环境变量:`SRC`、`CARGO`(默认 `/home/zifeng/.cargo/bin/cargo`)、`BUILD_USER`(默认
`zifeng`,编译用 `sudo -u` 降权跑,免得 root 在 `~/.cargo` 里留下 root 拥有的缓存)。

### 绝对不要在 `/opt/wows-toolkit` 里编

服务器上的 `/opt/wows-toolkit` 是 2026-06-27 的源码副本,**在重构之后**,patch 套不上;
更要紧的是它的 `target/release/minimap_renderer` 是生产在用的小地图渲染二进制,
在那里跑 `cargo build` 会扰动生产产物。`build_replayshark.sh` 里对这个路径有硬性拒绝
(`readlink -f` 之后匹配,软链绕不过去)。

---

## 6. 换装前必须过等价性闸门

编出来 ≠ 可以换装。重建的源码虽然与旧二进制的源码对得上,但编译器版本、依赖 lockfile 都
可能有细微差异,而这个二进制的输出直接进战报,任何字段变动都是线上事故。

```bash
bash tools/verify_replayshark_equiv.sh <fixture 目录>
```

闸门内容:**同一批真实回放**,

- 旧二进制读**手术过的** specs(`specs-patched/<ver>_<build>/scripts`,FLOAT64 已 sed 成 FLOAT)
- 新二进制读**未手术的原始** scripts(`extracted/<ver>_<build>/vfs/scripts`)

两边 `battle-report` 输出的 JSON 必须**逐字节一致**。脚本按每局回放头部的
`clientVersionFromExe` 自己解出 build 号去找对应版本的数据,所以 fixture 里混着多个版本的回放
也没问题。

脚本还带一道防假绿灯:如果 `OLD_BIN` 与 `NEW_BIN` 内容相同(比如已经手动换装过了),
它拒绝运行 —— 「旧 vs 旧」必然全 SAME,这种假绿灯比报错危险得多。

`SAME=n DIFF=0 ERROR=0` 才算过闸。有 DIFF 就别换,先看脚本打出的 JSON diff 摘要。

---

## 7. specs 目录布局(最容易踩的坑)

这个二进制的 `-e <目录>` 要求目录里有**三样并列的东西**:

```
<specs 目录>/
├── metadata.toml
├── content/            # 里面得有 GameParams.data
└── scripts/
```

而 `wows-data-mgr` 解出来的 `extracted/<ver>_<build>/` 布局是:

```
extracted/15.8.0_13187581/
├── metadata.toml
└── vfs/
    ├── content/
    └── scripts/
```

**把 `-e` 直接指向 `extracted/<ver>_<build>/` 会 panic:**

```
Could not open file for '/content/GameParams.data'
```

因为它去找 `<那个目录>/content/`,而实际在 `vfs/content/`。

正确做法是组一份三个软链的目录。生产里有两个地方干这件事:

- `tools/link_specs.sh` —— 维护固定的 `/opt/wows-bot/report/specs`,挑最新版本;
- `report/bin/wows_report` 的 `resolve_specs_for_build()` —— 按回放自己的 build 号组临时目录。
  这个函数还解释了为什么不能只用单一 specs + spoof build 号:entity defs 在版本间会变
  (15.7→15.8 的 `Avatar.def` 就变了),用错版本的 defs 解析会 panic
  `failed to deserialize player_states`。

`verify_replayshark_equiv.sh` 里的 `make_specs()` 是同一套逻辑的最小实现,可以照抄。

---

## 8. 下次 WG 加新实体类型怎么办

这是本次重建最大的收益点。**旧流程**:每个游戏大版本手工把数据里的 `FLOAT64` sed 成
`FLOAT`(所谓「FLOAT64 手术」),产物堆在 `specs-patched/`。漏做一次战报就挂。

**新流程**(假设 WG 以后加了个 `FLOAT128` 之类):

1. 在基线上给 `crates/wowsunpack/src/rpc/typedefs.rs` 的 `parse_type` 加一个分支;
2. 重新导出 `tools/replayshark_float64.patch`(或新加一个 patch,记得同步
   `build_replayshark.sh` 里的 patch 列表);
3. `bash tools/build_replayshark.sh` 重编;
4. **重新过一遍第 6 节的等价性闸门**。

代价是「每个大版本重编一次」换掉了「每个大版本手工改一遍几百 M 数据」—— 好得多,但注意
它**仍然不是零成本**,不要以为换装之后就再也不用管了。

导出 patch 的命令(在 toolkit 源码树里,`<基线>..<你的 HEAD>`):

```bash
git diff 2effcd31..<改完 float64 的 commit> -- crates/wowsunpack/src/rpc/typedefs.rs \
    > /path/to/wows-bot/tools/replayshark_float64.patch
```

务必确认产出是 LF(`file` 的输出里不该出现 `CRLF`)。

---

## 9. 已知的 patch 行为,不要顺手「修」

`plane_refs`(CV 舰载机引用)的提取**只扫三个组件**:

```rust
for comp_key in ["A_TorpedoBomber", "A_DiveBomber", "A_SkipBomber"] {
```

而紧挨着的注释写的是:

```rust
// 提取 CV 飞机引用: A_TorpedoBomber.planes / A_DiveBomber.planes /
// A_SkipBomber.planes / A_AirArmament.hangar_1.planes 等。
```

**注释提到的 `A_AirArmament.hangar_1.planes` 实际上没有被扫**,循环里没有它。这是 patch 原文
就有的注释与代码不符,不是导出时弄丢的。生产在用的老二进制有**完全相同**的盲点。

(如果你在别处看到「还漏了 `A_Fighter`」的说法:`A_Fighter` 在 patch 里根本没出现过,
代码和注释都没提,那个说法不准确。实际没被扫的、且注释声称会扫的,只有 `A_AirArmament`。)

不要在重建过程里「顺手补全」:

- 补上会改变 `plane_refs` 的输出内容,**直接毁掉第 6 节的逐字节闸门** —— 而那个闸门是本次
  重建唯一的安全网;
- 一旦闸门失效,就没法区分「我有意扩的字段」和「重建引入的回归」了。

要扩这个功能,等换装完成、新二进制成为生产基线之后,**单独做一个变更**,并以新二进制的
输出重新建立对比基线。

---

## 10. 速查

```bash
# 从零重建(服务器上)
git clone https://ghfast.top/https://github.com/landaire/wows-toolkit.git /opt/wows-replayshark-build
git -C /opt/wows-replayshark-build checkout 2effcd31
bash tools/build_replayshark.sh
bash tools/verify_replayshark_equiv.sh /path/to/fixtures     # 必须 DIFF=0 ERROR=0
# 过闸门之后才换装
```

| 东西 | 位置 |
| --- | --- |
| 生产在用的二进制 | `report/prebuilt/replayshark-linux-x86_64`(部署后 `/opt/wows-bot/report/replayshark`) |
| 基线 | 上游 `2effcd31` |
| patch | `tools/replayshark_float64.patch` → `tools/replayshark_battle_report.patch` |
| 构建脚本 | `tools/build_replayshark.sh` |
| 等价性闸门 | `tools/verify_replayshark_equiv.sh` |
| 默认构建目录 | `/opt/wows-replayshark-build`(**不是** `/opt/wows-toolkit`) |
