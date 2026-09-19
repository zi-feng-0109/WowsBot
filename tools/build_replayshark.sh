#!/usr/bin/env bash
# build_replayshark.sh — 可复现地重建带 battle-report 的 replayshark
#
# 为什么需要这个:report/prebuilt/replayshark-linux-x86_64 里的 battle-report /
# builds-dump / consumables-dump 三个子命令来自 tools/replayshark_battle_report.patch。
# 上游 2026-06-05 删掉了这个 patch 挂靠的 BattleController(改成 BattleWorld/ECS),
# 所以 patch 只能套在那次重构之前的基线上。
#
# 关于下面的 BASELINE:它是**记录**,不是强制。脚本只把它打印出来跟实际 HEAD 对照,
# 并不校验、也不会因为 HEAD 不是它而拒绝构建(源码可以不是 git 仓)。真正的强制来自
# [2/4] 套 patch 和 [4/4] 自检:patch 套不上或没生效,那两步会拦住。
# patch 顺序则是写死的(float64 先、battle_report 后),两个 patch 改的文件不重叠。
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
# float64 patch 改的就是这个文件,[2/4] 之后要靠它确认 patch 真的生效
TYPEDEFS_RS="crates/wowsunpack/src/rpc/typedefs.rs"

die() { echo "error: $*" >&2; exit 1; }

# 构建用户:rustup 装在普通用户的家目录里,而本脚本通常用 sudo 跑 ——
# 所以默认取 $SUDO_USER(sudo 会把调用者放这里),没有再退到当前用户。
# 为什么不直接用 root 构建:源码树归普通用户,root 跑 cargo 会把 target/ 弄成 root 所有,
# 下次那个用户再构建就写不进去了。要指定就 BUILD_USER=<用户名>。
BUILD_USER="${BUILD_USER:-${SUDO_USER:-$(id -un)}}"

# cargo:先试构建用户家目录里的 rustup 安装位置,不在就回落到 PATH 里的 cargo。
CARGO="${CARGO:-}"
if [[ -z "$CARGO" ]]; then
    _bu_home="$(getent passwd "$BUILD_USER" 2>/dev/null | cut -d: -f6)"
    [[ -n "$_bu_home" ]] && CARGO="$_bu_home/.cargo/bin/cargo"
    [[ -n "$CARGO" && -x "$CARGO" ]] || CARGO="$(command -v cargo 2>/dev/null || true)"
fi
[[ -n "$CARGO" && -x "$CARGO" ]] || die "找不到 cargo(试过 ~$BUILD_USER/.cargo/bin/cargo 和 PATH);用 CARGO=/path/to/cargo 指定"
USE_SUDO=1
if [[ "$BUILD_USER" == "$(id -un)" ]]; then
    USE_SUDO=0
elif ! id "$BUILD_USER" >/dev/null 2>&1; then
    echo "note: 没有用户 $BUILD_USER,改以当前用户 $(id -un) 构建(可用 BUILD_USER= 指定)"
    BUILD_USER="$(id -un)"; USE_SUDO=0
elif ! command -v sudo >/dev/null 2>&1; then
    echo "note: 没有 sudo,改以当前用户 $(id -un) 构建"
    BUILD_USER="$(id -un)"; USE_SUDO=0
fi
as_builder() {   # 以构建用户跑一条命令(不需要/不能切用户时就直接跑)
    if [[ $USE_SUDO -eq 1 ]]; then sudo -u "$BUILD_USER" "$@"; else "$@"; fi
}

[[ -d "$SRC" ]] || die "源码目录不存在:$SRC(见 docs/REPLAYSHARK_BUILD.md 取源两条路)"
[[ -f "$SRC/Cargo.toml" ]] || die "$SRC 不像 toolkit 源码树(缺 Cargo.toml)"

# 绝不在 /opt/wows-toolkit 里编 —— 那里的 target/release/minimap_renderer 是生产在用的
case "$(readlink -f "$SRC")" in
    /opt/wows-toolkit|/opt/wows-toolkit/*)
        die "拒绝在 /opt/wows-toolkit 下编译:它的 target/ 放着生产用的 minimap_renderer" ;;
esac

echo "[1/4] 检查源码基线"
# 纯信息性的一步,失败绝不能弄死构建(曾经就是:root 读普通用户拥有的仓触发 git 的
# dubious-ownership 保护,set -e 让整个脚本死在这儿)。用构建用户去读,并且兜住失败。
if [[ -d "$SRC/.git" ]]; then
    head="$(as_builder git -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo '读不到')"
    echo "  HEAD = $head (期望基线 $BASELINE 或其上已套 patch 的提交)"
else
    echo "  (非 git 仓,跳过)"
fi

echo "[2/4] 应用 patch(已套上的会被跳过)"
for p in replayshark_float64 replayshark_battle_report; do
    f="$REPO_DIR/tools/$p.patch"
    [[ -f "$f" ]] || die "缺 patch 文件:$f"
    if as_builder patch -p1 -d "$SRC" --dry-run --forward --silent < "$f" >/dev/null 2>&1; then
        as_builder patch -p1 -d "$SRC" --forward --silent < "$f"
        echo "  applied  $p"
    else
        echo "  skipped  $p(已套上,或套不上 —— 下面的源码检查与编译会暴露)"
    fi
done

# float64 patch 不产生任何子命令,所以 [4/4] 的子命令自检覆盖不到它:它被静默跳过时
# 编译照样成功、三个子命令照样都在、脚本照样宣布 done,而这个二进制仍然会 panic
# "Unrecognized type FLOAT64",等于白干。所以在这里直接查源码,且趁编译之前查(省 15 分钟)。
#
# 注意匹配的是代码而不是裸的 FLOAT64:**未打 patch 的**原文里就有一行注释
# `// Note that "FLOAT64" is Float64`(patch 正是把它换掉的),grep 'FLOAT64' 会命中它,
# 那就又是一个假绿灯。`t == "FLOAT64"` 这个分支只在 patch 生效后才存在。
float64_applied() { grep -Fq 't == "FLOAT64"' "$SRC/$TYPEDEFS_RS"; }
[[ -f "$SRC/$TYPEDEFS_RS" ]] || die "源码树里没有 $TYPEDEFS_RS,基线不对?"
float64_applied \
    || die "float64 patch 没生效($TYPEDEFS_RS 里没有 t == \"FLOAT64\" 分支)。
  这个 patch 不产生子命令,编译和子命令自检都拦不住它 —— 拿这个二进制跑 15.7+ 的
  数据会 panic \"Unrecognized type FLOAT64\"。先弄清 patch 为什么套不上。"
echo "  ok       float64 patch 已在源码里生效($TYPEDEFS_RS)"

echo "[3/4] 编译(release,首次约 5-15 分钟)"
as_builder "$CARGO" build --release \
    --manifest-path "$SRC/Cargo.toml" -p replayshark

BIN="$SRC/target/release/replayshark"
[[ -x "$BIN" ]] || die "编完了但没找到 $BIN"

echo "[4/4] 自检:两个 patch 各查一遍"
missing=0
# --help 先存进变量再 grep:直接 "$BIN" --help | grep -q 在 pipefail 下有风险 ——
# grep -q 首个匹配就退出,可能把左侧 SIGPIPE 掉,于是**匹配成功**反而被判成失败(假红)。
# --help 输出很小,实践中不触发,但没理由留着。
helptext="$("$BIN" --help 2>&1 || true)"
# 这三个子命令全部来自 battle_report patch,所以它们只能证明那一个 patch 生效了
for sub in battle-report builds-dump consumables-dump; do
    if printf '%s\n' "$helptext" | grep -Fq -- "$sub"; then
        echo "  ok   $sub  (battle_report patch)"
    else
        echo "  缺!  $sub"; missing=1
    fi
done
# float64 patch 一个子命令都不产生,只能查源码(同一个判据,[2/4] 之后也查过一次;
# 这里再查是为了让 [4/4] 单独看也是完整的 —— 它是「防 patch 被静默跳过」的兜底)
if float64_applied; then
    echo "  ok   FLOAT64 分支  (float64 patch,查的是 $TYPEDEFS_RS)"
else
    echo "  缺!  FLOAT64 分支($TYPEDEFS_RS 里没有 t == \"FLOAT64\")"; missing=1
fi
[[ $missing -eq 0 ]] || die "patch 没真正生效,不要拿这个二进制换装"

echo
echo "done: $BIN"
ls -la "$BIN" | awk '{print "  " $5 " 字节  " $6 " " $7 " " $8}'
# 不要问它 --version:这个基线的 replayshark 没有这个参数,问了会以非零码退出,
# 让调用方误判构建失败(2026-09-19 实跑踩到)。真正的自检是 [4/4] 那四项。
echo "下一步:等价性验证,见 tools/verify_replayshark_equiv.sh"
