#!/usr/bin/env bash
# MP4 渲染 wrapper — 把 .wowsreplay 渲染成小地图 MP4
#
# 用法:
#   render.sh <input.wowsreplay> <output.mp4>
#
# 可调环境变量:
#   WOWS_TOOLKIT_BIN  minimap_renderer 二进制
#                     默认 /opt/wows-toolkit/target/release/minimap_renderer
#   WOWS_DATA_DIR     wows-toolkit 解包出的 extracted 根目录
#                     默认 /var/lib/wows-data/extracted
#   WOWS_RENDER_LANG  渲染界面文字 locale,对应 extracted/<ver>/translations/<lang>/。
#                     默认 zh_sg(亚服简中,跟游戏内一致)。
#                     置空跳过 --lang(用 binary 默认 en)。可选 zh / zh_tw / en / ru ...
#
# 任何额外参数都会原样传给 minimap_renderer (放在 -o/输入文件之前)。
set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "usage: render.sh <input.wowsreplay> <output.mp4> [extra minimap_renderer args ...]" >&2
    exit 2
fi

INPUT="$1"
OUTPUT="$2"
shift 2

TOOLKIT_BIN="${WOWS_TOOLKIT_BIN:-/opt/wows-toolkit/target/release/minimap_renderer}"
DATA_DIR="${WOWS_DATA_DIR:-/var/lib/wows-data/extracted}"
RENDER_LANG="${WOWS_RENDER_LANG-zh_sg}"

# Optimus 笔记本(NVIDIA dGPU + AMD/Intel iGPU)Vulkan loader 默认枚举所有
# Vulkan device,wgpu 经常挑到 iGPU(RENOIR / Intel)。强制只用 NVIDIA ICD
# → minimap_renderer 必走 NVENC 硬编(快得多、质量更好)。
# 文件不存在 / 没装 NVIDIA driver 时不 set,自然 fallback 到 iGPU/CPU。
if [ -z "${VK_DRIVER_FILES:-}" ] && [ -f /usr/share/vulkan/icd.d/nvidia_icd.json ]; then
    export VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.json
fi

if [ ! -x "$TOOLKIT_BIN" ]; then
    echo "error: $TOOLKIT_BIN 不存在或不可执行 (设 WOWS_TOOLKIT_BIN 覆盖)" >&2
    exit 1
fi
if [ ! -d "$DATA_DIR" ]; then
    echo "error: $DATA_DIR 不存在 (设 WOWS_DATA_DIR 覆盖, 或先用 wows-toolkit 解包)" >&2
    exit 1
fi

LANG_ARG=()
if [ -n "$RENDER_LANG" ]; then
    LANG_ARG=(--lang "$RENDER_LANG")
fi

exec "$TOOLKIT_BIN" \
    --extracted-dir "$DATA_DIR" \
    --codec h264 \
    --max-size-mib 10 \
    --team-rosters \
    --no-progress \
    --recreate-game-params \
    "${LANG_ARG[@]}" \
    -o "$OUTPUT" \
    "$@" \
    "$INPUT"
