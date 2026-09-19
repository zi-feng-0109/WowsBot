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
# 纯信息性的一步,失败绝不能弄死构建(曾经就是:root 读 zifeng 拥有的仓触发 git 的
# dubious-ownership 保护,set -e 让整个脚本死在这儿)。用构建用户去读,并且兜住失败。
if [[ -d "$SRC/.git" ]]; then
    head="$(sudo -u "$BUILD_USER" git -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo '读不到')"
    echo "  HEAD = $head (期望基线 $BASELINE 或其上已套 patch 的提交)"
else
    echo "  (非 git 仓,跳过)"
fi

echo "[2/4] 应用 patch(已套上的会被跳过)"
for p in replayshark_float64 replayshark_battle_report; do
    f="$REPO_DIR/tools/$p.patch"
    [[ -f "$f" ]] || die "缺 patch 文件:$f"
    if sudo -u "$BUILD_USER" patch -p1 -d "$SRC" --dry-run --forward --silent < "$f" >/dev/null 2>&1; then
        sudo -u "$BUILD_USER" patch -p1 -d "$SRC" --forward --silent < "$f"
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
