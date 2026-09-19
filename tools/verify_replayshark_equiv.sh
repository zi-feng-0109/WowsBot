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

# 防假绿灯:如果两个路径指向同一个二进制(比如已经手动换装过),对比就变成「旧 vs 旧」,
# 必然全 SAME —— 而这个脚本的全部意义就是当闸门,假绿灯比报错危险得多。
if cmp -s "$OLD_BIN" "$NEW_BIN"; then
    echo "error: OLD_BIN 与 NEW_BIN 内容完全相同 —— 是不是已经换装过了?" >&2
    echo "  OLD_BIN = $OLD_BIN" >&2
    echo "  NEW_BIN = $NEW_BIN" >&2
    echo "这样比出来的 SAME 没有意义,拒绝运行。" >&2
    exit 1
fi

# 把参与对比的两个二进制记下来,免得事后说不清当时比的到底是哪两个构建
echo "OLD_BIN: $(ls -la "$OLD_BIN" | awk '{print $5, $6, $7, $8}')  $OLD_BIN"
echo "NEW_BIN: $(ls -la "$NEW_BIN" | awk '{print $5, $6, $7, $8}')  $NEW_BIN"
echo

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
    [[ -f "$consts" ]] || consts=""

    old_scripts="$PATCHED/$vname/scripts"
    [[ -d "$old_scripts" ]] || old_scripts="$vdir/vfs/scripts"
    new_scripts="$vdir/vfs/scripts"

    s_old="$(make_specs "$vdir" "$old_scripts")"
    s_new="$(make_specs "$vdir" "$new_scripts")"
    j_old="$OUT/$name.old.json"; j_new="$OUT/$name.new.json"

    rc_old=0; rc_new=0
    if [[ -n "$consts" ]]; then
        "$OLD_BIN" -e "$s_old" -c "$consts" battle-report "$r" -o "$j_old" >"$OUT/$name.old.log" 2>&1 || rc_old=$?
        "$NEW_BIN" -e "$s_new" -c "$consts" battle-report "$r" -o "$j_new" >"$OUT/$name.new.log" 2>&1 || rc_new=$?
    else
        "$OLD_BIN" -e "$s_old" battle-report "$r" -o "$j_old" >"$OUT/$name.old.log" 2>&1 || rc_old=$?
        "$NEW_BIN" -e "$s_new" battle-report "$r" -o "$j_new" >"$OUT/$name.new.log" 2>&1 || rc_new=$?
    fi
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
