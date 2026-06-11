#!/usr/bin/env python3
"""render_armor_3d.py — GLB 战舰模型 → 多视角 PNG + 转圈 GIF(纯软件渲染)。

不依赖 GPU / 显示 / Blender,只要 numpy + Pillow + trimesh(读 GLB)。
自带 numpy z-buffer 光栅器 + 朗伯着色,认 GLB 顶点色(真实装甲 GLB 把厚度色烤进
顶点色,直接出彩;无顶点色的普通模型用默认钢灰)。

用法:
    python tools/render_armor_3d.py <in.glb> <out_prefix> [--size 520] [--frames 36] [--no-gif]
产物:
    <out_prefix>.png   舷侧/俯视/正面/¾ 四视角 2×2 合成
    <out_prefix>.gif   绕竖轴转一圈 turntable

设计文档:docs/superpowers/specs/2026-06-11-armor-3d-model-design.md
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image

BG = (38, 52, 78)          # 跟 /船 卡同底色
STEEL = (150, 165, 185)    # 无顶点色时的默认钢灰
# 装甲图重在"看清不同厚度色块",不在写实光照 —— 高 ambient 让鲜艳的红绿不被光照
# 压成土黄(对照 GUI 装甲查看器:基本无明暗,纯色块)。
AMBIENT = 0.85

# wows-toolkit 的精确装甲色阶 (mm 上界, R, G, B) —— 跟 GLB 顶点色一致。
# 复刻自 crates/wowsunpack/src/export/gltf_export.rs::ARMOR_COLOR_SCALE。
ARMOR_COLOR_SCALE = [
    (14,  (110, 209, 176)),   # teal      青
    (16,  (149, 210, 127)),   # light green 浅绿
    (24,  (170, 201, 102)),   # yellow-green 黄绿
    (26,  (192, 193,  80)),   # olive     橄榄
    (28,  (226, 195,  62)),   # gold      金黄
    (33,  (225, 171,  54)),   # orange-gold 橙金
    (75,  (227, 144,  49)),   # orange    橙
    (160, (230, 115,  49)),   # dark orange 深橙
    (399, (220,  78,  48)),   # red-orange 红橙
    (999, (185,  47,  48)),   # dark red  深红
]


_GLTF_DTYPE = {5126: np.float32, 5125: np.uint32, 5123: np.uint16, 5121: np.uint8}
_GLTF_TS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _read_accessor(g, bin_blob, idx):
    """读 glTF accessor → numpy 数组(SCALAR 是 1D,VEC* 是 (count, n))。"""
    if idx is None:
        return None
    a = g.accessors[idx]
    bv = g.bufferViews[a.bufferView]
    off = (bv.byteOffset or 0) + (a.byteOffset or 0)
    ts = _GLTF_TS[a.type]
    dt = _GLTF_DTYPE[a.componentType]
    raw = bin_blob[off:off + a.count * ts * np.dtype(dt).itemsize]
    arr = np.frombuffer(raw, dtype=dt)
    return arr.reshape(a.count, ts) if ts > 1 else arr


def load_glb(path, armor_only=True):
    """GLB → (verts Nx3, faces Mx3, vcolors Nx3 float[0,1], has_color)。

    用 pygltflib 直接读 POSITION/COLOR_0/INDICES,绕过 trimesh 4.x 把
    `TextureVisuals` 的 COLOR_0 顶点色吞掉的问题(实测装甲网格走 trimesh
    完全读不到厚度色)。

    armor_only=True(默认):只收 mesh.name 以 'Armor_' 开头的网格 ——
    船体外壳没有厚度色,会遮挡内部彩色装甲;
    armor_only=False:全收。
    """
    import pygltflib
    g = pygltflib.GLTF2().load(path)
    bin_blob = g.binary_blob()
    keep = []
    for mesh in g.meshes:
        nm = mesh.name or ""
        if armor_only and not nm.startswith("Armor_"):
            continue
        keep.append(mesh)
    if not keep and armor_only:
        print("  ! 警告:GLB 里没有 Armor_* 网格,fallback 到全收", file=sys.stderr)
        keep = list(g.meshes)
    V, F, C = [], [], []
    off = 0
    any_color = False
    for mesh in keep:
        for prim in mesh.primitives:
            attrs = prim.attributes
            v = _read_accessor(g, bin_blob, attrs.POSITION)
            if v is None or len(v) == 0:
                continue
            v = np.asarray(v, np.float64)
            idx = _read_accessor(g, bin_blob, prim.indices)
            if idx is None:                            # 无索引 = 按顶点顺序三角化
                idx = np.arange(len(v), dtype=np.int64)
            f = np.asarray(idx, np.int64).reshape(-1, 3) + off
            # 顶点色 (VEC4 float[0,1])
            cols = _read_accessor(g, bin_blob, attrs.COLOR_0)
            vc = None
            if cols is not None and len(cols) == len(v):
                rgb = np.asarray(cols[:, :3], np.float64)
                if len(np.unique(rgb, axis=0)) > 1:
                    vc = rgb
                    any_color = True
            if vc is None:
                vc = np.tile(np.array(STEEL) / 255.0, (len(v), 1))
            V.append(v); F.append(f); C.append(vc); off += len(v)
    if not V:
        raise SystemExit("GLB 里没有可渲染网格")
    return np.vstack(V), np.vstack(F), np.vstack(C), any_color


def _normalize(V):
    """居中 + 缩放到 [-1,1]。返回归一化顶点。"""
    V = np.nan_to_num(V, nan=0.0, posinf=0.0, neginf=0.0)
    lo, hi = V.min(0), V.max(0)
    center = (lo + hi) / 2
    scale = (hi - lo).max() / 2 or 1.0
    return (V - center) / scale


# 四个视角的旋转矩阵(模型 → 相机,正交投影看 -Z)。
# 船假设:长(X)、宽(Z)、高(Y)。Blender 导出的 WoWS 模型一般 Y 向上。
def _rot(ax, deg):
    a = np.radians(deg); c, s = np.cos(a), np.sin(a)
    if ax == "x": return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if ax == "y": return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _view_mats():
    Ry = _rot("y", 0)
    return {
        "舷侧": _rot("y", 90),                       # 看船舷
        "俯视": _rot("x", 90),                        # 从上往下
        "正面": Ry,                                   # 舰艏/舰艉朝向相机
        "立体": _rot("y", 35) @ _rot("x", 22),       # 立体感 ¾ 视角
    }


def rasterize(V, F, Cface, R, size):
    """正交投影 + z-buffer 光栅化。V 归一化顶点,Cface 每面 RGB[0,1],R 旋转。"""
    with np.errstate(all="ignore"):                   # 个别退化网格的无害告警
        P = np.nan_to_num(V @ R.T)                     # 旋转到相机系
    # 正交投影:x,y → 屏幕;z 作深度(越大越近)
    m = size * 0.46
    cx = cy = size / 2
    sx = (P[:, 0] * m + cx)
    sy = (-P[:, 1] * m + cy)
    z = P[:, 2]
    # 面法线(相机系)→ 朗伯:面朝相机(法线 +Z)最亮
    tri = P[F]                                        # (M,3,3)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    ln = np.linalg.norm(n, axis=1); ln[ln == 0] = 1
    shade = AMBIENT + (1 - AMBIENT) * np.clip(n[:, 2] / ln, 0, 1)

    img = np.zeros((size, size, 3), np.float64)
    img[:] = np.array(BG) / 255.0
    zbuf = np.full((size, size), -1e9)

    fx = sx[F]; fy = sy[F]; fz = z[F]                 # (M,3)
    # 按深度从远到近画(稳妥;z-buffer 也兜底)
    order = np.argsort(fz.mean(1))
    for ti in order:
        x0, x1, x2 = fx[ti]; y0, y1, y2 = fy[ti]
        zz = fz[ti]
        minx = max(int(np.floor(min(x0, x1, x2))), 0)
        maxx = min(int(np.ceil(max(x0, x1, x2))), size - 1)
        miny = max(int(np.floor(min(y0, y1, y2))), 0)
        maxy = min(int(np.ceil(max(y0, y1, y2))), size - 1)
        if minx > maxx or miny > maxy:
            continue
        xs = np.arange(minx, maxx + 1)
        ys = np.arange(miny, maxy + 1)
        gx, gy = np.meshgrid(xs, ys)
        # 重心坐标
        d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(d) < 1e-9:
            continue
        a = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / d
        b = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / d
        c = 1 - a - b
        inside = (a >= 0) & (b >= 0) & (c >= 0)
        if not inside.any():
            continue
        pz = a * zz[0] + b * zz[1] + c * zz[2]
        sub = zbuf[gy[inside], gx[inside]]
        win = pz[inside] > sub
        if not win.any():
            continue
        yy = gy[inside][win]; xx = gx[inside][win]
        zbuf[yy, xx] = pz[inside][win]
        img[yy, xx] = Cface[ti] * shade[ti]
    return (np.clip(img, 0, 1) * 255).astype(np.uint8)


def _cjk_font(size):
    """跨平台找一个能渲中文的 TTF。WOWS_CJK_FONT 优先;否则按常见路径试。"""
    from PIL import ImageFont
    candidates = [
        os.environ.get("WOWS_CJK_FONT"),
        "C:/Windows/Fonts/msyh.ttc",       # Windows 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",     # Windows 黑体
        "/System/Library/Fonts/Hiragino Sans GB.ttc",  # mac
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # Linux 文泉驿
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        if not path:
            continue
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _label(im_arr, text):
    from PIL import ImageDraw
    im = Image.fromarray(im_arr)
    d = ImageDraw.Draw(im)
    d.text((10, 8), text, (235, 242, 255), font=_cjk_font(22))
    return im


def _legend_bar(width, height=64):
    """画一条 mm→色 图例条:10 个色 bucket + 关键 mm 刻度。"""
    from PIL import ImageDraw
    im = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(im)
    pad_x = 60
    bar_w = width - pad_x * 2
    bar_h = 22
    bar_y = 10
    n = len(ARMOR_COLOR_SCALE)
    # 标题
    d.text((10, bar_y + 2), "装甲厚度", (235, 242, 255), font=_cjk_font(16))
    # 色块
    for i, (mm, rgb) in enumerate(ARMOR_COLOR_SCALE):
        x0 = pad_x + bar_w * i // n
        x1 = pad_x + bar_w * (i + 1) // n
        d.rectangle([x0, bar_y, x1, bar_y + bar_h], fill=rgb)
    # 刻度标签:每桶上界 mm,挑关键的不挤
    f = _cjk_font(13)
    label_y = bar_y + bar_h + 2
    last_x = -1000
    for i, (mm, _rgb) in enumerate(ARMOR_COLOR_SCALE):
        x = pad_x + bar_w * (i + 1) // n
        s = f"{mm}" if mm < 999 else "999+"
        w = int(f.getlength(s))
        if x - w // 2 - last_x < 30:    # 太挤就跳过
            continue
        d.text((x - w // 2, label_y), s, (235, 242, 255), font=f)
        last_x = x + w // 2
    # 单位
    d.text((pad_x + bar_w + 6, bar_y + 2), "mm", (190, 205, 225), font=f)
    return im


def render(glb_path, out_prefix, size=520, frames=36, gif=True,
           gif_duration=250, armor_only=True):
    V, F, Vc, has_color = load_glb(glb_path, armor_only=armor_only)
    V = _normalize(V)
    # 面色取"最厚那个顶点的色"。色阶 teal→绿→黄→橙→红:R 一路升后又略降,
    # G 一路单调降 —— 单一维度都不单调,但 R-G 是单调升的:
    #   teal (0.43, 0.82, 0.69)  R-G=-0.39
    #   亮绿 (0.58, 0.82, 0.50)  R-G=-0.24
    #   黄绿 (0.67, 0.79, 0.40)  R-G=-0.12
    #   黄橙 (0.88, 0.67, 0.21)  R-G= 0.21
    #   橙   (0.89, 0.56, 0.19)  R-G= 0.33
    #   红橙 (0.86, 0.31, 0.19)  R-G= 0.55
    #   深红 (0.73, 0.18, 0.19)  R-G= 0.55
    # 所以 R-G 最大的顶点 ≈ 最厚装甲色。这样不同厚度交界处的三角形会显示最厚那
    # 块的色(不被混合稀释),GUI 那种鲜明色块感才能复现。
    Vc_score = Vc[F][:, :, 0] - Vc[F][:, :, 1]        # (M, 3)
    pick = np.argmax(Vc_score, axis=1)                # 挑 R-G 最大 = 最红/最厚
    Cface = Vc[F][np.arange(len(F)), pick]            # (M, 3)
    src = "Armor_* 子网格" if armor_only else "全部子网格"
    print(f"  顶点 {len(V)}  面 {len(F)}  顶点色: {'有(直接出彩)' if has_color else '无(默认钢灰)'}  来源: {src}",
          file=sys.stderr)

    # 四视角 2×2 + 底部图例条
    views = _view_mats()
    tiles = [_label(rasterize(V, F, Cface, R, size), name) for name, R in views.items()]
    legend_h = 64
    grid = Image.new("RGB", (size * 2, size * 2 + legend_h), BG)
    for i, t in enumerate(tiles):
        grid.paste(t, ((i % 2) * size, (i // 2) * size))
    grid.paste(_legend_bar(size * 2, legend_h), (0, size * 2))
    grid.save(out_prefix + ".png")
    print(f"  → {out_prefix}.png ({grid.width}×{grid.height}, 含图例)", file=sys.stderr)

    if gif:
        gsz = max(360, size - 120)                    # GIF 小一点控体积
        imgs = []
        base = _rot("x", 18)                          # 略微俯角
        # GIF 256 色索引调色板。装甲渲染只有 10 个色阶 + 几档 shade,远少于 256,
        # 关掉 dither 避免伪纹路(用 MEDIANCUT quantize,不近似)。
        for k in range(frames):
            R = _rot("y", 360 * k / frames) @ base
            rgb = Image.fromarray(rasterize(V, F, Cface, R, gsz))
            imgs.append(rgb.quantize(colors=128, method=Image.Quantize.MEDIANCUT,
                                     dither=Image.Dither.NONE))
        imgs[0].save(out_prefix + ".gif", save_all=True, append_images=imgs[1:],
                     duration=gif_duration, loop=0, optimize=True)
        secs = frames * gif_duration / 1000
        print(f"  → {out_prefix}.gif ({gsz}×{gsz}, {frames} 帧, {secs:.1f}s/圈)", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glb")
    ap.add_argument("out_prefix")
    ap.add_argument("--size", type=int, default=520)
    ap.add_argument("--frames", type=int, default=36)
    ap.add_argument("--no-gif", action="store_true")
    ap.add_argument("--gif-duration", type=int, default=250,
                    help="每帧毫秒数,默认 250 (36 帧约 9 秒一圈)")
    ap.add_argument("--include-hull", action="store_true",
                    help="同时渲外壳网格(默认只渲 Armor_*,否则外壳会遮住装甲)")
    args = ap.parse_args()
    render(args.glb, args.out_prefix, args.size, args.frames,
           gif=not args.no_gif, gif_duration=args.gif_duration,
           armor_only=not args.include_hull)


if __name__ == "__main__":
    main()
