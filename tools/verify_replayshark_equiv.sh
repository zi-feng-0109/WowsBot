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
# 这个闸门的性质:假绿灯比误报危险得多
# ----------------------------------
# 它存在的唯一意义是在换装前拦住「重建改变了战报」。所以凡是判据本身失效的路径
# (哈希算不出来、版本数据缺失被跳过、差异区域解释不通)都按失败处理 —— 宁可多报
# 几次假警报让人来看,也不能在判据失效时宣布通过。
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
PNGDIFF_PY="$REPO_DIR/tools/rs_png_diff.py"

# 渲染要 PIL,跟生产用同一套解释器解析顺序(见 report/bin/wows_report 的 find_python)
PY="${WOWS_PYTHON:-}"
if [[ -z "$PY" ]]; then
    PY="$REPO_DIR/report/venv/bin/python"
    [[ -x "$PY" ]] || PY=python3
fi

for b in "$OLD_BIN" "$NEW_BIN"; do
    [[ -x "$b" ]] || { echo "error: 没有可执行的 $b" >&2; exit 1; }
done
for f in "$RENDER_PY" "$COMPARE_PY" "$PNGDIFF_PY"; do
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
# 失败必须以非零码退出并且不打任何东西到 stdout —— 否则调用方拿到空串,
# 而「两个空串相等」会被当成「哈希一致」(假绿灯)。
FOOTER_PX=48
png_hash() {
    "$PY" - "$1" "$FOOTER_PX" <<'PY'
import hashlib, sys
try:
    from PIL import Image
    footer = int(sys.argv[2])
    im = Image.open(sys.argv[1]).convert("RGB")
    if im.height <= footer or im.width <= 0:
        sys.stderr.write(f"png_hash: {sys.argv[1]} 尺寸 {im.width}x{im.height},裁掉页脚 {footer}px 后没内容\n")
        sys.exit(3)
    im = im.crop((0, 0, im.width, im.height - footer))
except SystemExit:
    raise
except Exception as e:
    sys.stderr.write(f"png_hash: {sys.argv[1]} 读不出来:{e!r}\n")
    sys.exit(3)
print(hashlib.sha256(im.tobytes()).hexdigest()[:16], f"{im.width}x{im.height}")
PY
}

# 拿到的东西得像个哈希才算成功。png_hash 打的是「16 位十六进制 空格 宽x高」,
# 所以第一段必须是 16 个十六进制字符。空串 / 半截输出一律算失败。
hash_ok() {
    local h="${1%% *}"
    [[ ${#h} -ge 16 && "$h" =~ ^[0-9a-f]{16} ]]
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
    h1="$(png_hash "$OUT/_selftest.1.png")" || h1=""
    h2="$(png_hash "$OUT/_selftest.2.png")" || h2=""
    echo "  run1 ${h1:-<算不出哈希>}"
    echo "  run2 ${h2:-<算不出哈希>}"
    if ! hash_ok "$h1" || ! hash_ok "$h2"; then
        echo "  → png_hash 没能算出哈希(PNG 截断 / 高度不足 ${FOOTER_PX}px / PIL 异常)。" >&2
        echo "    两边都失败时都是空串,而空串相等会把这一步伪装成「稳定」,所以这里直接停。" >&2
        exit 1
    fi
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
total=0; ok=0; bad=0; err=0; moot=0; skip=0
declare -a BAD_LIST=()
declare -a MOOT_LIST=()
declare -a SKIP_LIST=()
for r in "$FIXTURES"/*.wowsreplay; do
    [[ -f "$r" ]] || continue
    total=$((total+1))
    name="$(basename "$r" .wowsreplay)"
    short="${name:0:50}"
    build="$(read_build "$r" 2>/dev/null)"
    if [[ -z "$build" ]]; then
        printf "%-52s %-10s %s\n" "$short" "-" "ERROR 读不出 build"; err=$((err+1)); continue
    fi
    # 跳过必须计数、必须进汇总、必须影响退出码:「服务器上某个版本数据被清过」
    # 是会真实发生的事,9 局跳 8 局却打「通过 1 / 不通过 0」+ 退出码 0 就是假绿灯。
    vdir="$(version_dir "$build")" || {
        printf "%-52s %-10s %s\n" "$short" "$build" "SKIP extracted 里没这个 build"
        skip=$((skip+1)); SKIP_LIST+=("$name  (缺 build $build)")
        continue; }
    vname="$(basename "$vdir")"
    consts="$vdir/constants.json"; [[ -f "$consts" ]] || consts=""

    # 旧二进制本该读「手术过的 scripts」。那份不在时这里会回落到原始 scripts ——
    # 回落本身对老版本是合理的(那些版本从来不需要手术),但这一局就不再是
    # 「手术 vs 未手术」的对比了,判据的含义变弱。所以必须说出来,别让它静默发生。
    old_scripts="$PATCHED/$vname/scripts"
    old_note=""
    if [[ ! -d "$old_scripts" ]]; then
        old_scripts="$vdir/vfs/scripts"
        old_note="注意:没有 $PATCHED/$vname/scripts,旧二进制读的也是原始 scripts —— 这一局比的不是「手术 vs 未手术」"
    fi

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
    jout="$("$PY" "$COMPARE_PY" "$j_old" "$j_new" 2>&1)"; rc_cmp=$?
    # 以退出码为准,不要只 grep 输出里的「规范化后等价」:比较器崩了、参数用错(退出码 2)
    # 时都不该算等价,而 grep 一句中文提示既可能被措辞改动弄成误报,也可能被差异路径里
    # 的巧合文本弄成假绿灯。退出码是它唯一的正式判据。
    if [[ $rc_cmp -eq 0 ]]; then json_v="等价"; else json_v="不等价"; fi

    # PNG:正文哈希
    png_v="?"
    if render "$j_old" "$OUT/$name.old.png" && render "$j_new" "$OUT/$name.new.png"; then
        ho="$(png_hash "$OUT/$name.old.png")" || ho=""
        hn="$(png_hash "$OUT/$name.new.png")" || hn=""
        if ! hash_ok "$ho" || ! hash_ok "$hn"; then
            # 算不出哈希 → 没有判据,绝不能因为「两个空串相等」而报一致
            png_v="哈希失败"
        elif [[ "$ho" == "$hn" ]]; then
            png_v="一致"
        else
            png_v="不一致"
        fi
    else
        png_v="渲染失败"
    fi

    # PNG 不一致时,要过两道关才算「判据失效」:
    #   关一:旧二进制自己跑两次是不是也不一致?(报告本身是否不确定)
    #   关二:old↔new 的差异区域是不是落在 old↔old 自身抖动的区域里?
    # 只问关一是不够的 —— 一局回放可以同时「本身不确定」和「真的被重建改坏了一处」,
    # 两者都只表现为哈希不同,光凭关一会把后者一起放过;JSON 那层刻意丢了列表顺序,
    # 补不上这个洞。关二由 tools/rs_png_diff.py 用包围盒回答,并打出两个盒子供人复核。
    png_moot=0; hA=""; hB=""; pngdiff=""
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
            hA="$(png_hash "$OUT/$name.oldA.png")" || hA=""
            hB="$(png_hash "$OUT/$name.oldB.png")" || hB=""
            if ! hash_ok "$hA" || ! hash_ok "$hB"; then
                png_v="不一致(旧二进制复跑的哈希算不出来,无法判断)"
            elif [[ "$hA" == "$hB" ]]; then
                png_v="不一致(旧二进制自身稳定,是真差异)"
            else
                # 关二:差异区域必须被自身抖动区域覆盖。三张旧图(old / oldA / oldB)
                # 两两互比得到抖动区域,比只用两张更接近真实抖动范围。
                pngdiff="$("$PY" "$PNGDIFF_PY" --footer "$FOOTER_PX" \
                    --new "$OUT/$name.new.png" \
                    --old "$OUT/$name.old.png" "$OUT/$name.oldA.png" "$OUT/$name.oldB.png" 2>&1)"
                rc_diff=$?
                if [[ $rc_diff -eq 0 ]]; then
                    png_moot=1
                    png_v="判据失效"
                else
                    png_v="不一致(差异区域超出自身抖动范围)"
                fi
            fi
        else
            png_v="不一致(旧二进制复跑失败,无法判断)"
        fi
    fi

    printf "%-52s %-10s %-8s %s\n" "$short" "$build" "$json_v" "$png_v"
    echo "$jout" | sed 's/^/      /'
    [[ -n "$old_note" ]] && echo "      $old_note"
    if [[ -n "$hA$hB" ]]; then
        echo "      旧二进制自己跑两次的 PNG:${hA:-<算不出>} vs ${hB:-<算不出>}"
    fi
    if [[ -n "$pngdiff" ]]; then
        echo "$pngdiff" | sed 's/^/      /'
    fi
    if [[ $png_moot -eq 1 ]]; then
        echo "      → 这一局报告本身不确定、且差异只落在它自己会抖的区域里,"
        echo "        PNG 判据对它无鉴别力;数据等价仍由 JSON 那栏保证"
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
echo "[2/2] 汇总:共 $total 局 —— 通过 $ok / 判据失效 $moot / 不通过 $bad / 出错 $err / 跳过 $skip"
if [[ ${#SKIP_LIST[@]} -gt 0 ]]; then
    echo
    echo "被跳过的局(extracted/ 里没有对应版本,这一局什么都没验证):"
    for n in "${SKIP_LIST[@]}"; do echo "  $n"; done
    echo "  跳过不是通过 —— 退出码会因此为非零。要么把缺的版本数据补回 $EXTRACTED,"
    echo "  要么把这些回放从 fixture 里挑掉,不要让它们冒充「验过了」。"
fi
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
if [[ $total -eq 0 ]]; then
    echo "error: 一局都没跑到 —— 没有验证过任何东西,不要据此换装。" >&2
    exit 1
fi
[[ $bad -eq 0 && $err -eq 0 && $skip -eq 0 ]]
