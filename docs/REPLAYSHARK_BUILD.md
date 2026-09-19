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
| 旧的 2026-05 版 | 22 | **15** | 9/9 全失败 |
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

两个 patch 文件**在 git 库里是 LF**(`git cat-file blob` 验证 CR 数为 0)。但 `.gitattributes`
原先只给 `*.sh` 指定了 `eol=lf`,`*.patch` 走 `* text=auto` —— 于是 Windows 上 clone 出来的工作
副本是 CRLF,`git apply` 判不匹配,而错误输出里 CR 显示成 `?` 极难看懂。2026-09-19 为此白查过
一轮,已给 `.gitattributes` 补上 `*.patch text eol=lf` 根治。Linux 上 checkout 直接就是 LF。
以后重新导出时务必保持 LF,CRLF 的 patch 在 Linux 上会出诡异的上下文不匹配。

> 查库内真实换行符要用 `git cat-file blob <sha>`,**不能**用 `git show <rev>:<path>` ——
> 后者在 Windows 上会套用 smudge filter 做 CRLF 转换,看到的是转换后的结果。

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

### 依赖锁定:基线自带 `Cargo.lock`

基线 commit `2effcd31` **已跟踪 `Cargo.lock`**(271903 字节,`git ls-tree 2effcd31` 可确认),
所以按本文档 clone + checkout 出来的树带着当时锁定的依赖版本,`cargo build` 不会重新解析
semver 范围 —— 「半年后重编因依赖漂移而失败」这个风险因此小得多。

残余风险只有两种:某个传递依赖被 yank(yank 过的版本仍可下载,只是不能新增引用,
所以通常不影响),或 crates.io 不可达。**不要 `cargo update`** —— 那会丢掉锁定,
是唯一能自己把这个风险引进来的操作。

### 绝对不要在 `/opt/wows-toolkit` 里编

服务器上的 `/opt/wows-toolkit` 是 2026-06-27 的源码副本,**在重构之后**,patch 套不上;
更要紧的是它的 `target/release/minimap_renderer` 是生产在用的小地图渲染二进制,
在那里跑 `cargo build` 会扰动生产产物。`build_replayshark.sh` 里对这个路径有硬性拒绝
(`readlink -f` 之后匹配,软链绕不过去)。

---

## 6. 换装前必须过等价性闸门

编出来 ≠ 可以换装。这个二进制的输出直接进战报,任何字段变动都是线上事故。

```bash
# 必须 root —— specs-patched 是 drwx------ root,普通用户读不到会 panic PermissionDenied
sudo bash tools/verify_replayshark_equiv.sh <fixture 目录> [输出目录]
```

闸门内容:**同一批真实回放**,

- 旧二进制读**手术过的** specs(`specs-patched/<ver>_<build>/scripts`,FLOAT64 已 sed 成 FLOAT)
- 新二进制读**未手术的原始** scripts(`extracted/<ver>_<build>/vfs/scripts`)

脚本按每局回放头部的 `clientVersionFromExe` 自己解出 build 号去找对应版本的数据,
所以 fixture 里混着多个版本的回放没问题。

### 两层判据,以及为什么不是「JSON 逐字节一致」

**`battle-report` 的输出本身就不确定。** 2026-09-19 实测:同一个二进制、同一局回放跑两次,
输出大小相同但字节不同 —— `damage_events`(1115 条)与 `deaths`(15 条)的多重集完全相同、
只是排列不同(HashMap 迭代顺序随机),并且 `players[].stats.damage_dealt` 会差一个 ULP
(同一批伤害按不同顺序累加的必然结果,实测最大相对偏差 1.665e-16)。

所以「逐字节一致」这个判据**连旧二进制自己跟自己比都过不了**,拿它当闸门是错的。实际判据:

| 层 | 判据 | 证明什么 | 实现 |
|---|---|---|---|
| 数据 | 深度规范化(dict 按键排序、list 按规范化文本排序)+ **浮点**相对容差 1e-9 | 数据内容一致,不受顺序影响 | `tools/rs_compare_report.py` |
| 外观 | 战报 PNG **正文哈希**(裁掉底部 48px 页脚,页脚含 `datetime.now()`) | 可见结果逐像素一致 | `render_battle_report.py` + PIL |

容差只给浮点,**整数精确比** —— 相对容差对大整数等于「差 1 也算等」,而 account_id 在 10^9
量级、毫秒时间戳在 10^12,最松的判据会正好落在最不该松的身份字段上。

PNG 之所以能当判据,是因为实测它跨运行稳定(渲染器不依赖 JSON 顺序,那个 ULP 也不影响任何
像素)。脚本把这一点做成 **`[0/2]` 自证**:先用新二进制把第一局跑两遍、渲染两遍、比正文哈希,
不稳定就直接退出 —— 免得在一个本身无效的判据上得出「通过」。

### 「判据失效」这一类是什么

有些回放的报告**本身**就不确定:`render_battle_report.py:369` 的
`sorted(key=lambda p: -p.damage_dealt)` 在排序键并列时靠输入顺序,而输入顺序随机。
实测有一局 15.7 驱逐舰回放,玩家表最后两行(两个 0 伤害玩家)会互换,差异是
`y=935..995 / x=78..1337` 一条 60px 窄带、占 0.26% 像素;旧二进制自己跑三次得到三个不同哈希。

对这种局,PNG 判据没有鉴别力。脚本的处理是**两道关**,不是一道:

1. 旧二进制在同一局上自己跑两次,PNG 哈希是否也不同?
2. `old↔new` 的差异包围盒,是否被 `old↔old` 的抖动包围盒**覆盖**?
   (`tools/rs_png_diff.py`,三张图两两互比取并集当抖动范围)

两关都过才判 `判据失效`(不计入失败);只过第 1 关但差异区域超出抖动范围,仍判**不通过** ——
否则「一局同时既有抖动、又有真回归」会被一起扫掉。

残留盲区,如实记着:包围盒是矩形近似,**落在抖动矩形内部**的回归看不见;抖动范围只由有限
几次运行采样。真正的解法是给渲染器排序加确定性 tiebreaker,但那会改变并列情况下的输出,
用户已明确决定不修 —— 所以这个盲区是长期存在的。

### 汇总行怎么读

```
[2/2] 汇总:共 N 局 —— 通过 x / 判据失效 y / 不通过 z / 出错 e / 跳过 s
```

**退出码 0 的条件是 `不通过 = 出错 = 跳过 = 0`。** 注意:

- **跳过不是通过。** 某局的 build 在 `extracted/` 里找不到就会 SKIP,脚本会列出缺的 build 号。
  「服务器上某个版本数据被清过」正是会真实发生的事,所以 SKIP 计入退出码
- `不通过` 里会写明具体原因:`不等价` / `哈希失败` / `渲染失败` /
  `不一致(差异区域超出自身抖动范围)` / `不一致(旧二进制自身稳定,是真差异)`
- 有 `不通过` 就**别换装**,把产物目录连同输出交给人判断

另一道防假绿灯:`OLD_BIN` 与 `NEW_BIN` 内容相同时(比如已经手动换装过了)脚本**拒绝运行** ——
「旧 vs 旧」必然全过,这种假绿灯比报错危险得多。

### 可调环境变量

| 变量 | 默认 |
|---|---|
| `OLD_BIN` | `/opt/wows-bot/report/replayshark` |
| `NEW_BIN` | `/opt/wows-replayshark-build/target/release/replayshark` |
| `EXTRACTED` | `/var/lib/wows-data/extracted` |
| `PATCHED` | `/var/lib/wows-data/specs-patched` |
| `WOWS_PYTHON` | 未设时试 `report/venv/bin/python`,再回落 `python3`(要有 PIL) |

第二个位置参数是输出目录,默认 `/tmp/rs_equiv`。

### fixture 集怎么组(闸门的唯一输入,文档里必须留)

闸门要真实回放,而**服务器上一局都没有**(处理完即删),所以每次都得从开发机传上去:

```bash
# 开发机(Windows,Steam 的 replays 目录)
mkdir -p /tmp/rs_fixtures && cp <挑好的>.wowsreplay /tmp/rs_fixtures/
ssh <user>@<host> 'mkdir -p /tmp/rs_fixtures'
scp /tmp/rs_fixtures/*.wowsreplay <user>@<host>:/tmp/rs_fixtures/
```

**挑选原则**:覆盖「多个版本 × 多个舰种」。各舰种在战报里走的字段不同(航母有中队、
潜艇有下潜、驱逐有鱼雷/烟雾),版本则决定 entity defs。回放文件名里 index 的第 4 个字母
就是舰种:`A`=航母 `B`=战列 `C`=巡洋 `D`=驱逐 `S`=潜艇(例:`PBSA108-Implacable` → `A` → 航母)。

2026-09-19 实际用的 9 局(**15.7 五舰种齐 + 15.8 四舰种、缺巡洋**):

| build | 航母 | 战列 | 巡洋 | 驱逐 | 潜艇 |
|---|---|---|---|---|---|
| `15.8.0_13187581` | Implacable | Conqueror | **缺** | Kagero | Balao |
| `15.7.0_13015811` | Weser | Conqueror | AZUR-Montpelier | Black-Lushun | Undine |

完整文件名见 `docs/superpowers/plans/2026-09-19-replayshark-rebuild.md` 的 Task 4。

已知覆盖缺口:**15.3–15.6 没有回放可用**。实际风险已量化为低 —— 回放解码路径
(`decode.rs`)相对 patch 基线只漂了 2 行,且是 `u32` → `PacketTypeId` newtype 的纯类型
改动,零语义(逐文件漂移表见设计文档)。

另一个缺口:闸门对 `builds-dump` **只做了计数校验**(118 升级品 / 2345 涂装 / 662 舰长 /
82 技能),**从未逐字段 diff**。而 `types.rs` 相对基线的 11 行漂移正好是 `CrewPersonality`
的 10 个字段 Option 化(`Option<bool>` 序列化成 `null` 而旧版出 `false`)—— 已查实当前
消费侧(`tools/build_builds_json.py`)只读 `id` 和 `name`,那些字段名在全仓零命中,
**所以当前无影响**。这是运气不是覆盖:谁将来开始读那些字段,要先补一次逐字段对比。

---

## 6.5 回滚

```bash
sudo cp /root/replayshark-prebuilt-20260527.bak /opt/wows-bot/report/replayshark
```

不需要重启任何服务 —— 渲染器是 subprocess 现拉,换完立即生效。

⚠️ **这只改了部署副本,回滚不持久。** 仓库里 `report/prebuilt/replayshark-linux-x86_64`
是 git 跟踪的、`report/replayshark` 是 gitignore 的**部署副本**,生产执行的是后者。回滚之后
仓库里那份 prebuilt 仍是新版,所以下次任何人走 `docs/UPDATE.md` §0.3 或
`docs/DEPLOY.md` §4.1 的那条 `cp prebuilt → replayshark`,**会静默把新版装回来**,
而他以为自己在做常规部署。

要让回滚持久,二选一:

```bash
# a) 让仓库里的 prebuilt 也回到旧版
git revert 0c1bf7a        # 换装那次提交

# b) 直接覆盖(会让服务器工作区变脏,下次 git pull 要处理冲突)
sudo cp /root/replayshark-prebuilt-20260527.bak \
        /opt/wows-bot/report/prebuilt/replayshark-linux-x86_64
```

辨认在用的是哪一版,看大小:**5919456** = 2026-09-19 重建版,**4806528** = 2026-05-27 旧版。

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
# 从零重建(服务器上)。构建目录必须隔离 —— 不能是 /opt/wows-toolkit
sudo mkdir -p /opt/wows-replayshark-build && sudo chown <构建用户> /opt/wows-replayshark-build
sudo -u <构建用户> git clone https://ghfast.top/https://github.com/landaire/wows-toolkit.git \
        /opt/wows-replayshark-build
sudo -u <构建用户> git -C /opt/wows-replayshark-build checkout 2effcd31
cd /opt/wows-bot && sudo bash tools/build_replayshark.sh

# 换装前过闸门(必须 root:specs-patched 是 drwx------ root)
sudo bash tools/verify_replayshark_equiv.sh /tmp/rs_fixtures
#   退出码 0 的条件:不通过 = 出错 = 跳过 = 0。「跳过」不是通过。
#   「判据失效」不算失败 —— 那是该局报告本身不确定,见 §6。

# 过闸门之后才换装:先备份,再换部署副本,最后把 prebuilt 提交进仓库
sudo cp /opt/wows-bot/report/prebuilt/replayshark-linux-x86_64 /root/replayshark-prebuilt-<日期>.bak
sudo cp /opt/wows-replayshark-build/target/release/replayshark /opt/wows-bot/report/replayshark
```

| 东西 | 位置 |
| --- | --- |
| 生产实际执行的二进制 | `/opt/wows-bot/report/replayshark`(gitignore 的部署副本) |
| 仓库里跟踪的那份 | `report/prebuilt/replayshark-linux-x86_64`(换装时一并提交) |
| 基线 | 上游 `2effcd31` |
| patch(**顺序固定**) | `tools/replayshark_float64.patch` → `tools/replayshark_battle_report.patch` |
| 构建脚本 | `tools/build_replayshark.sh` |
| 等价性闸门 | `tools/verify_replayshark_equiv.sh` |
| 闸门的 JSON 比较器 | `tools/rs_compare_report.py` |
| 闸门的 PNG 区域比较 | `tools/rs_png_diff.py` |
| 默认构建目录 | `/opt/wows-replayshark-build`(**不是** `/opt/wows-toolkit`) |
| 回滚备份 | `/root/replayshark-prebuilt-20260527.bak`,见 §6.5 |
| 辨认版本 | 5919456 字节 = 2026-09-19 重建版;4806528 = 2026-05-27 旧版 |
