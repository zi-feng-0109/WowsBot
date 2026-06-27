#!/usr/bin/env bash
# MP4 渲染 wrapper — 把 .wowsreplay 渲染成小地图 MP4
#
# 用法:
#   render.sh <input.wowsreplay> <output.mp4>
#
# 可调环境变量:
#   WOWS_TOOLKIT_BIN     minimap_renderer 二进制
#                        默认 /opt/wows-toolkit/target/release/minimap_renderer
#   WOWS_DATA_DIR        wows-toolkit 解包出的 extracted 根目录
#                        默认 /var/lib/wows-data/extracted
#   WOWS_RENDER_LANG     渲染界面文字 locale,对应 extracted/<ver>/translations/<lang>/。
#                        默认 zh_sg(亚服简中)。空跳过 --lang(binary 默认 en)。
#   WOWS_RENDER_BACKEND  cpu | gpu。默认 cpu。
#                        - cpu: --cpu + 默认 AV1 软编(稳、画质好 ~7 MB / 20min,慢 2-3min)
#                        - gpu: 走 NVIDIA Vulkan ICD + NVENC H.264 --max-size-mib 10
#                          (快 ~20s / 20min,需要 NVIDIA driver + nvidia_icd.json)
#                        bot 端按超管 /渲染模式 状态自动 set;命令行直接调时也可手设。
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
RENDER_BACKEND="${WOWS_RENDER_BACKEND:-cpu}"

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

# Backend 分支:
#   cpu: --cpu 强制 CPU,默认 codec 走 AV1 软编(画质好、慢、稳定)。
#   gpu: 走 GPU NVENC H.264 硬编(快、画质 OK)。Optimus 笔记本要强制 Vulkan
#        loader 只看 NVIDIA ICD,否则 wgpu 会挑到 iGPU。
BACKEND_ARGS=()
case "$RENDER_BACKEND" in
    cpu)
        BACKEND_ARGS=(--cpu)
        ;;
    gpu)
        if [ -z "${VK_DRIVER_FILES:-}" ] && [ -f /usr/share/vulkan/icd.d/nvidia_icd.json ]; then
            export VK_DRIVER_FILES=/usr/share/vulkan/icd.d/nvidia_icd.json
        fi
        BACKEND_ARGS=(--codec h264 --max-size-mib 10)
        ;;
    *)
        echo "error: WOWS_RENDER_BACKEND='$RENDER_BACKEND' 不合法 (只能 cpu / gpu)" >&2
        exit 1
        ;;
esac

exec "$TOOLKIT_BIN" \
    --extracted-dir "$DATA_DIR" \
    "${BACKEND_ARGS[@]}" \
    --team-rosters \
    --no-progress \
    --recreate-game-params \
    "${LANG_ARG[@]}" \
    -o "$OUTPUT" \
    "$@" \
    "$INPUT"
