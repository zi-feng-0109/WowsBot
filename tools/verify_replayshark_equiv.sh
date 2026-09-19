#!/usr/bin/env bash
# verify_replayshark_equiv.sh — 新旧 replayshark 的等价性闸门
#
# 换装闸门:旧二进制读「手术过的 specs」,新二进制读「未手术的原始 scripts」,
# 同一批回放跑 battle-report,比较两样东西:
#
#   1. JSON —— 深度规范化 + 浮点容差后必须等价(证明数据内容一致)
#   2. PNG  —— 战报正文哈希必须一致(证明可见结果逐像素一致)
#
# 为什么不是「JSON 逐字节一致」
# ----------------------------
# 2026-09-19 实测:battle-report 的输出本身不确定。同一个二进制、同一局回放跑两次,
# 输出大小相同但字节不同 —— damage_events(1115 条)/ deaths(15 条)的多重集完全相同、
# 只是排列不同(HashMap 迭代顺序随机),并且 players[].stats.damage_dealt 会差一个 ULP
# (同一批伤害按不同顺序累加的必然结果)。所以逐字节判据连旧二进制自己跟自己比都过不了。
#
# PNG 正文哈希则实测跨运行稳定(渲染器不依赖 JSON 顺序,那个 ULP 也不影响任何像素),
# 所以它才是「不改变战报外观」这条硬约束的正确判据。脚本会先自证这一点(见 [0/2])。
#
# 用法(必须 root —— specs-patched 是 drwx------ root):
#   bash tools/verify_replayshark_equiv.sh <fixture 目录> [输出目录]

set -uo pipefail

FIXTURES="${1:?用法: verify_replayshark_equiv.sh <fixture 目录> [输出目录]}"
OUT="${2:-/tmp/rs_equiv}"
OLD_BIN="${OLD_BIN:-/opt/wows-bot/report/replayshark}"
NEW_BIN="${NEW_BIN:-/opt/wows-replayshark-build/target/release/replayshark}"
EXTRACTED="${EXTRACTED:-/var/lib/wows-data/extracted}"
PATCHED="${PATCHED:-/var/lib/wows-data/specs-patched}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RENDER_PY="$REPO_DIR/report/bin/render_battle_report.py"
COMPARE_PY="$REPO_DIR/tools/rs_compare_report.py"

# 渲染要 PIL,跟生产用同一套解释器解析顺序(见 report/bin/wows_report 的 find_python)
PY="${WOWS_PYTHON:-}"
if [[ -z "$PY" ]]; then
    PY="$REPO_DIR/report/venv/bin/python"
    [[ -x "$PY" ]] || PY=python3
fi

for b in "$OLD_BIN" "$NEW_BIN"; do
    [[ -x "$b" ]] || { echo "error: 没有可执行的 $b" >&2; exit 1; }
done
for f in "$RENDER_PY" "$COMPARE_PY"; do
    [[ -f "$f" ]] || { echo "error: 缺 $f" >&2; exit 1; }
done

# 防假绿灯:两个路径指向同一个二进制(比如已经换装过)时对比毫无意义,必然全过。
if cmp -s "$OLD_BIN" "$NEW_BIN"; then
    echo "error: OLD_BIN 与 NEW_BIN 内容完全相同 —— 是不是已经换装过了?" >&2
    echo "  OLD_BIN = $OLD_BIN" >&2
    echo "  NEW_BIN = $NEW_BIN" >&2
    echo "这样比出来的「一致」没有意义,拒绝运行。" >&2
    exit 1
fi

mkdir -p "$OUT"
echo "OLD_BIN: $(ls -la "$OLD_BIN" | awk '{print $5, $6, $7, $8}')  $OLD_BIN"
echo "NEW_BIN: $(ls -la "$NEW_BIN" | awk '{print $5, $6, $7, $8}')  $NEW_BIN"
echo "解释器:  $PY"
echo

# 从回放头部读 build 号:magic(4) blockCount(4) meta_len(4) 然后是 UTF-8 JSON meta,
# clientVersionFromExe 形如 "15,8,0,13187581",最后一段就是 build
read_build() {
    "$PY" - "$1" <<'PY'
import json, struct, sys
with open(sys.argv[1], 'rb') as f:
    if f.read(4) != b'\x12\x32\x34\x11': sys.exit(1)
    f.read(4)
    n = struct.unpack('<I', f.read(4))[0]
    meta = json.loads(f.read(n).decode('utf-8'))
print(meta['clientVersionFromExe'].split(',')[-1].strip())
PY
}

version_dir() {
    local build="$1"
    for d in "$EXTRACTED"/*_"$build"; do
        [[ -d "$d" ]] && { echo "$d"; return 0; }
    done
    return 1
}

# 组一份 specs:三个软链指向 metadata / content / scripts
make_specs() {
    local vdir="$1" scripts="$2" tmp
    tmp="$(mktemp -d /tmp/rs_specs_XXXXXX)"
    ln -s "$vdir/metadata.toml" "$tmp/metadata.toml"
    ln -s "$vdir/vfs/content"   "$tmp/content"
    ln -s "$scripts"            "$tmp/scripts"
    echo "$tmp"
}

# PNG 正文哈希:裁掉底部 48px 页脚(页脚含 datetime.now(),会让整图哈希漂移)
png_hash() {
    "$PY" - "$1" <<'PY'
import hashlib, sys
from PIL import Image
im = Image.open(sys.argv[1]).convert("RGB")
im = im.crop((0, 0, im.width, im.height - 48))
print(hashlib.sha256(im.tobytes()).hexdigest()[:16], f"{im.width}x{im.height}")
PY
}

render() {   # render <json> <png>  —— 成功返回 0
    "$PY" "$RENDER_PY" "$1" "$2" >"$2.log" 2>&1
}

run_report() {   # run_report <bin> <specs> <constants|空> <replay> <out.json>
    if [[ -n "$3" ]]; then
        "$1" -e "$2" -c "$3" battle-report "$4" -o "$5"
    else
        "$1" -e "$2" battle-report "$4" -o "$5"
    fi
}

# ---------- [0/2] 自证:PNG 正文哈希在本机跨运行稳定 ----------
# 不先证明这一点,PNG 判据本身就没有立足之地。
echo "[0/2] 自证 PNG 判据有效(新二进制同一局跑两次,正文哈希必须相同)"
probe=""
for r in "$FIXTURES"/*.wowsreplay; do [[ -f "$r" ]] && { probe="$r"; break; }; done
[[ -n "$probe" ]] || { echo "error: $FIXTURES 里没有 .wowsreplay" >&2; exit 1; }
pb="$(read_build "$probe" 2>/dev/null)"
pv="$(version_dir "$pb")" || { echo "error: extracted 里没有 build $pb" >&2; exit 1; }
pc="$pv/constants.json"; [[ -f "$pc" ]] || pc=""
ps_dir="$(make_specs "$pv" "$pv/vfs/scripts")"
self_ok=1
for i in 1 2; do
    run_report "$NEW_BIN" "$ps_dir" "$pc" "$probe" "$OUT/_selftest.$i.json" >"$OUT/_selftest.$i.log" 2>&1 \
        || { echo "  自证失败:新二进制第 $i 次跑不起来(见 $OUT/_selftest.$i.log)"; self_ok=0; }
done
rm -rf "$ps_dir"
if [[ $self_ok -eq 1 ]]; then
    render "$OUT/_selftest.1.json" "$OUT/_selftest.1.png" && render "$OUT/_selftest.2.json" "$OUT/_selftest.2.png" || self_ok=0
fi
if [[ $self_ok -eq 1 ]]; then
    h1="$(png_hash "$OUT/_selftest.1.png")"; h2="$(png_hash "$OUT/_selftest.2.png")"
    echo "  run1 $h1"
    echo "  run2 $h2"
    if [[ "$h1" == "$h2" ]]; then
        echo "  → 稳定,PNG 判据有效"
        if cmp -s "$OUT/_selftest.1.json" "$OUT/_selftest.2.json"; then
            echo "  (附带:两次 JSON 也逐字节相同 —— 那么本机这一局恰好确定,不影响判据)"
        else
            echo "  (附带:两次 JSON 字节不同,正如预期 —— 这就是逐字节判据不可用的原因)"
        fi
    else
        echo "  → 不稳定!渲染器依赖了 JSON 顺序,PNG 判据不成立。停止,不要据此换装。" >&2
        exit 1
    fi
else
    echo "  → 自证跑不起来,不能继续。" >&2
    exit 1
fi
echo

# ---------- [1/2] 逐局对比 ----------
echo "[1/2] 逐局对比(旧读手术数据 / 新读原始数据)"
printf "%-52s %-10s %-8s %s\n" "回放" "build" "JSON" "PNG"
total=0; ok=0; bad=0; err=0; moot=0
declare -a BAD_LIST=()
declare -a MOOT_LIST=()
for r in "$FIXTURES"/*.wowsreplay; do
    [[ -f "$r" ]] || continue
    total=$((total+1))
    name="$(basename "$r" .wowsreplay)"
    short="${name:0:50}"
    build="$(read_build "$r" 2>/dev/null)"
    if [[ -z "$build" ]]; then
        printf "%-52s %-10s %s\n" "$short" "-" "ERROR 读不出 build"; err=$((err+1)); continue
    fi
    vdir="$(version_dir "$build")" || {
        printf "%-52s %-10s %s\n" "$short" "$build" "SKIP extracted 里没这个 build"; continue; }
    vname="$(basename "$vdir")"
    consts="$vdir/constants.json"; [[ -f "$consts" ]] || consts=""

    old_scripts="$PATCHED/$vname/scripts"
    [[ -d "$old_scripts" ]] || old_scripts="$vdir/vfs/scripts"

    s_old="$(make_specs "$vdir" "$old_scripts")"
    s_new="$(make_specs "$vdir" "$vdir/vfs/scripts")"
    j_old="$OUT/$name.old.json"; j_new="$OUT/$name.new.json"

    rc_old=0; rc_new=0
    run_report "$OLD_BIN" "$s_old" "$consts" "$r" "$j_old" >"$OUT/$name.old.log" 2>&1 || rc_old=$?
    run_report "$NEW_BIN" "$s_new" "$consts" "$r" "$j_new" >"$OUT/$name.new.log" 2>&1 || rc_new=$?
    rm -rf "$s_old" "$s_new"

    if [[ $rc_old -ne 0 || $rc_new -ne 0 ]]; then
        printf "%-52s %-10s %s\n" "$short" "$build" "ERROR old_rc=$rc_old new_rc=$rc_new(见 $OUT/$name.*.log)"
        err=$((err+1)); BAD_LIST+=("$name"); continue
    fi

    # JSON:规范化 + 容差
    jout="$("$PY" "$COMPARE_PY" "$j_old" "$j_new" 2>&1)"
    if echo "$jout" | grep -q "规范化后等价"; then json_v="等价"; else json_v="不等价"; fi

    # PNG:正文哈希
    png_v="?"
    if render "$j_old" "$OUT/$name.old.png" && render "$j_new" "$OUT/$name.new.png"; then
        ho="$(png_hash "$OUT/$name.old.png")"; hn="$(png_hash "$OUT/$name.new.png")"
        [[ "$ho" == "$hn" ]] && png_v="一致" || png_v="不一致"
    else
        png_v="渲染失败"
    fi

    # PNG 不一致时,先问一句:旧二进制自己跑两次是不是也不一致?
    # 若是,说明这一局的报告本来就不确定(实测:并列玩家的表格行序由随机的数组顺序决定),
    # PNG 判据对它没有鉴别力 —— 那就不能算作「重建改变了战报」。
    png_moot=0; hA=""; hB=""
    if [[ "$png_v" == "不一致" ]]; then
        s_o1="$(make_specs "$vdir" "$old_scripts")"
        s_o2="$(make_specs "$vdir" "$old_scripts")"
        rc1=0; rc2=0
        run_report "$OLD_BIN" "$s_o1" "$consts" "$r" "$OUT/$name.oldA.json" >/dev/null 2>&1 || rc1=$?
        run_report "$OLD_BIN" "$s_o2" "$consts" "$r" "$OUT/$name.oldB.json" >/dev/null 2>&1 || rc2=$?
        rm -rf "$s_o1" "$s_o2"
        if [[ $rc1 -eq 0 && $rc2 -eq 0 ]] \
           && render "$OUT/$name.oldA.json" "$OUT/$name.oldA.png" \
           && render "$OUT/$name.oldB.json" "$OUT/$name.oldB.png"; then
            hA="$(png_hash "$OUT/$name.oldA.png")"; hB="$(png_hash "$OUT/$name.oldB.png")"
            if [[ "$hA" != "$hB" ]]; then
                png_moot=1
                png_v="判据失效"
            else
                png_v="不一致(旧二进制自身稳定,是真差异)"
            fi
        else
            png_v="不一致(旧二进制复跑失败,无法判断)"
        fi
    fi

    printf "%-52s %-10s %-8s %s\n" "$short" "$build" "$json_v" "$png_v"
    echo "$jout" | sed 's/^/      /'
    if [[ $png_moot -eq 1 ]]; then
        echo "      旧二进制自己跑两次的 PNG 也不同($hA vs $hB)"
        echo "      → 这一局报告本身不确定,PNG 判据对它无鉴别力;数据等价仍由 JSON 那栏保证"
    fi

    if [[ "$json_v" == "等价" && "$png_v" == "一致" ]]; then
        ok=$((ok+1))
    elif [[ "$json_v" == "等价" && $png_moot -eq 1 ]]; then
        moot=$((moot+1)); MOOT_LIST+=("$name")
    else
        bad=$((bad+1)); BAD_LIST+=("$name")
    fi
done

echo
echo "[2/2] 汇总:共 $total 局 —— 通过 $ok / 判据失效 $moot / 不通过 $bad / 出错 $err"
if [[ ${#MOOT_LIST[@]} -gt 0 ]]; then
    echo
    echo "PNG 判据失效的局(报告本身就不确定,与重建无关;JSON 仍判等价):"
    for n in "${MOOT_LIST[@]}"; do echo "  $n"; done
    echo "  成因实测:玩家表在排序键并列时(例如两人伤害都是 0)行序由随机的数组顺序决定。"
    echo "  这是渲染器既有的排序不稳定,值得单独修 —— 但修它会改变输出,不属于本次换装。"
fi
if [[ ${#BAD_LIST[@]} -gt 0 ]]; then
    echo "不通过的局:"
    for n in "${BAD_LIST[@]}"; do echo "  $n  (产物在 $OUT/$n.*)"; done
    echo
    echo "不要据此换装。把上面的差异连同 $OUT 里的产物交给人判断。"
fi
[[ $bad -eq 0 && $err -eq 0 ]]
