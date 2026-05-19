#!/usr/bin/env bash
# link_specs.sh — 把战报渲染器的 specs 目录软链到 wows-data-mgr 解出的 extracted 数据
#
# 一份 extracted 同时喂 MP4 渲染器 (minimap_renderer) 和战报渲染器
# (wows_full_report),省一次拷贝。
#
# 用法:
#   link_specs.sh                              # 扫 $WOWS_EXTRACTED_ROOT 挑最新版本
#   link_specs.sh /path/to/extracted_root      # 扫指定根目录挑最新
#   link_specs.sh /path/to/.../15.3.0_12267945 # 直接指定某个 <ver>_<build> 版本目录
#
# 可调环境变量:
#   WOWS_EXTRACTED_ROOT  默认 /var/lib/wows-data/extracted
#   WOWS_SPECS_DIR       默认 /opt/wows-bot/report/specs

set -euo pipefail

EXTRACTED_ROOT="${WOWS_EXTRACTED_ROOT:-/var/lib/wows-data/extracted}"
SPECS_DIR="${WOWS_SPECS_DIR:-/opt/wows-bot/report/specs}"

target="${1:-$EXTRACTED_ROOT}"

# 判断 target 是 <ver>_<build> 版本目录,还是包含多个版本目录的根
if [[ -f "$target/metadata.toml" && -d "$target/vfs/content" ]]; then
    version_dir="$target"
else
    if [[ ! -d "$target" ]]; then
        echo "error: $target 不是目录" >&2
        exit 1
    fi
    latest=$(cd "$target" && ls -1 2>/dev/null \
        | grep -E '^[0-9]+(\.[0-9]+)+_[0-9]+$' \
        | sort -V | tail -1)
    if [[ -z "$latest" ]]; then
        echo "error: $target 下没找到 <version>_<build> 格式子目录 (如 15.3.0_12267945)" >&2
        exit 1
    fi
    version_dir="$target/$latest"
fi

# 必要文件检查
for p in "metadata.toml" "vfs/content/GameParams.data" "vfs/scripts"; do
    if [[ ! -e "$version_dir/$p" ]]; then
        echo "error: 缺少 $version_dir/$p" >&2
        exit 1
    fi
done

mkdir -p "$SPECS_DIR"

# 老的真目录/真文件先挪开备份,避免误删
for name in content scripts; do
    if [[ -e "$SPECS_DIR/$name" && ! -L "$SPECS_DIR/$name" ]]; then
        bak="$SPECS_DIR/$name.bak.$$"
        echo "[backup] $SPECS_DIR/$name 是真目录,挪到 $bak"
        mv "$SPECS_DIR/$name" "$bak"
    fi
done
if [[ -e "$SPECS_DIR/metadata.toml" && ! -L "$SPECS_DIR/metadata.toml" ]]; then
    bak="$SPECS_DIR/metadata.toml.bak.$$"
    echo "[backup] $SPECS_DIR/metadata.toml 是真文件,挪到 $bak"
    mv "$SPECS_DIR/metadata.toml" "$bak"
fi

ln -sfn "$version_dir/vfs/content"   "$SPECS_DIR/content"
ln -sfn "$version_dir/vfs/scripts"   "$SPECS_DIR/scripts"
ln -sfn "$version_dir/metadata.toml" "$SPECS_DIR/metadata.toml"

echo "linked $SPECS_DIR -> $version_dir"
echo "---"
cat "$SPECS_DIR/metadata.toml"
