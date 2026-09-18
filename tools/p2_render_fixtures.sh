#!/usr/bin/env bash
# P2 重构专用:确定性渲染基线 fixture,供 sha256 逐字节比对。
#
# 为什么要脚本而不是把命令抄进每个任务:基线与后续每次检查**必须用完全相同的调用**,
# 否则比对结果没有意义。抄多份必然漂移。
#
# 为什么 WOWS_SKIP_FOOTER=1:footer 里画了分钟级时间戳
# (render_battle_report.py::_draw_footer 用 datetime.now().strftime("%Y-%m-%d %H:%M")),
# 隔一分钟渲染 sha256 就不同。已严格验证:两次相隔数分钟的渲染,去掉 footer 后
# 正文逐字节一致、仅 footer 区不同。跳过 footer 后整图完全确定。
#
# 用法:tools/p2_render_fixtures.sh <输出目录>
# 产物:<输出目录>/{report.png,review.png,fixtures.sha256}
#
# 本脚本是重构期的脚手架,P2 收尾(Task 11)时删除。
set -euo pipefail

OUT="${1:?用法: $0 <输出目录>}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 字体:CI/开发机没有 Linux 字体路径,显式指定 Windows 字体保证两端一致
export WOWS_CJK_FONT="${WOWS_CJK_FONT:-C:/Windows/Fonts/msyh.ttc}"
export WOWS_MONO_FONT="${WOWS_MONO_FONT:-C:/Windows/Fonts/consola.ttf}"
# 关掉带时间戳的 footer —— 这是整图可确定复现的前提
export WOWS_SKIP_FOOTER=1
# 版本号也会画进图里,固定住免得 .env 变动影响比对
export WOWS_BOT_VERSION="${WOWS_BOT_VERSION:-p2-fixture}"

JSON="${P2_REPORT_JSON:-$(python -c 'import tempfile,os;print(os.path.join(tempfile.gettempdir(),"p2_baseline","report.json"))')}"
if [ ! -f "$JSON" ]; then
    echo "error: 找不到 $JSON —— 先按 Task 0 Step 3 产出 report.json" >&2
    exit 1
fi

mkdir -p "$OUT"
python "$REPO/report/bin/render_report_normalized.py" "$JSON" "$OUT/report.png"
python "$REPO/report/bin/render_review_normalized.py" "$JSON" "$OUT/review.png"

cd "$OUT"
sha256sum report.png review.png > fixtures.sha256
cat fixtures.sha256
