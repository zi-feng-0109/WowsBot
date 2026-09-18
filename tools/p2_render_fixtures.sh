#!/usr/bin/env bash
# P2 重构专用:确定性渲染 fixture 并产出「正文哈希」,供逐字节比对。
#
# 为什么要脚本:基线与后续每次检查**必须用完全相同的调用**,否则比对没有意义。
# 抄多份命令必然漂移。
#
# 为什么哈希「正文」而不是整个文件:两个渲染器都在底部画了带**分钟级时间戳**的 footer
#   - render_battle_report.py::_draw_footer  (datetime.now().strftime("%Y-%m-%d %H:%M"))
#   - render_review_normalized.py 末行直接调 dc._draw_footer(...),**绕过**了
#     dc.render() 里的 WOWS_SKIP_FOOTER 判断,所以那个开关对它无效
# 隔一分钟渲染整图 sha256 就变。已实测定位:两次相隔数分钟的渲染,差异仅在 footer 区
# (review 的差异是 10x14px 的一个字符 = 分钟数字),裁掉底部 48px 后正文逐字节一致。
#
# 所以这里**照生产原样渲染**(footer 照画,不设 WOWS_SKIP_FOOTER),只在哈希时裁掉
# 底部 48px(足以覆盖 report 的 48px footer 与 review 的 34px footer)。
# 这样既不改生产行为,又把唯一的时变元素排除在比对之外。
#
# 用法:tools/p2_render_fixtures.sh <输出目录>
# 产物:<输出目录>/{report.png,review.png,fixtures.sha256}
#       fixtures.sha256 里是「裁掉底部 48px 后的像素哈希」,不是文件哈希。
#
# 本脚本是重构期脚手架,P2 收尾(Task 11)时删除。
set -euo pipefail

OUT="${1:?用法: $0 <输出目录>}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FOOTER_PX=48

# 字体固定,保证两端一致(开发机没有 Linux 字体路径)
export WOWS_CJK_FONT="${WOWS_CJK_FONT:-C:/Windows/Fonts/msyh.ttc}"
export WOWS_MONO_FONT="${WOWS_MONO_FONT:-C:/Windows/Fonts/consola.ttf}"
# 版本号也会画进 footer,固定住(虽然 footer 不参与比对,固定它便于人工看图)
export WOWS_BOT_VERSION="${WOWS_BOT_VERSION:-p2-fixture}"

JSON="${P2_REPORT_JSON:-$(python -c 'import tempfile,os;print(os.path.join(tempfile.gettempdir(),"p2_baseline","report.json"))')}"
if [ ! -f "$JSON" ]; then
    echo "error: 找不到 $JSON —— 先按 Task 0 Step 3 产出 report.json" >&2
    exit 1
fi

mkdir -p "$OUT"
python "$REPO/report/bin/render_report_normalized.py" "$JSON" "$OUT/report.png" >/dev/null
python "$REPO/report/bin/render_review_normalized.py" "$JSON" "$OUT/review.png" >/dev/null

FOOTER_PX="$FOOTER_PX" OUT="$OUT" python - <<'PY'
import hashlib, os
from PIL import Image
out = os.environ["OUT"]
cut = int(os.environ["FOOTER_PX"])
lines = []
for name in ("report.png", "review.png"):
    im = Image.open(os.path.join(out, name)).convert("RGB")
    w, h = im.size
    body = im.crop((0, 0, w, h - cut)).tobytes()
    lines.append(f"{hashlib.sha256(body).hexdigest()}  {name}  body({w}x{h - cut})")
text = "\n".join(lines) + "\n"
with open(os.path.join(out, "fixtures.sha256"), "w", encoding="utf-8", newline="\n") as f:
    f.write(text)
print(text, end="")
PY
