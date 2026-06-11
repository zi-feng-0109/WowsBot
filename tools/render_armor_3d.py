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
import sys

import numpy as np
from PIL import Image

BG = (38, 52, 78)          # 跟 /船 卡同底色
STEEL = (150, 165, 185)    # 无顶点色时的默认钢灰
AMBIENT = 0.35             # 环境光,避免背面全黑


def load_glb(path):
    """GLB → (verts Nx3, faces Mx3, vcolors Nx3 float[0,1] | None)。"""
    import trimesh
    scene = trimesh.load(path, force="scene")
    geos = scene.dump() if hasattr(scene, "dump") else [scene]
    V, F, C = [], [], []
    off = 0
    any_color = False
    for g in geos:
        if not hasattr(g, "vertices") or len(g.vertices) == 0:
            continue
        v = np.asarray(g.vertices, np.float64)
        f = np.asarray(g.faces, np.int64) + off
        # 顶点色
        vc = None
        try:
            vis = g.visual
            raw = None
            if hasattr(vis, "vertex_colors") and vis.vertex_colors is not None:
                raw = np.asarray(vis.vertex_colors)
            elif hasattr(vis, "to_color"):           # TextureVisuals 兜底
                cc = vis.to_color()
                if hasattr(cc, "vertex_colors") and cc.vertex_colors is not None:
                    raw = np.asarray(cc.vertex_colors)
            # 顶点色有变化才用 (全同色 = 没真上色,退默认钢灰)
            if raw is not None and len(raw) == len(v) and len(np.unique(raw[:, :3], axis=0)) > 1:
                vc = raw[:, :3].astype(np.float64) / 255.0
                any_color = True
        except Exception:
            pass
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


def _label(im_arr, text):
    from PIL import ImageDraw, ImageFont
    im = Image.fromarray(im_arr)
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc", 20)
    except Exception:
        f = ImageFont.load_default()
    d.text((10, 8), text, (235, 242, 255), font=f)
    return im


def render(glb_path, out_prefix, size=520, frames=36, gif=True):
    V, F, Vc, has_color = load_glb(glb_path)
    V = _normalize(V)
    Cface = Vc[F].mean(1)                             # 每面取顶点色均值
    print(f"  顶点 {len(V)}  面 {len(F)}  顶点色: {'有(直接出彩)' if has_color else '无(默认钢灰)'}",
          file=sys.stderr)

    # 四视角 2×2
    views = _view_mats()
    tiles = [_label(rasterize(V, F, Cface, R, size), name) for name, R in views.items()]
    grid = Image.new("RGB", (size * 2, size * 2), BG)
    for i, t in enumerate(tiles):
        grid.paste(t, ((i % 2) * size, (i // 2) * size))
    grid.save(out_prefix + ".png")
    print(f"  → {out_prefix}.png ({grid.width}×{grid.height})", file=sys.stderr)

    if gif:
        gsz = max(360, size - 120)                    # GIF 小一点控体积
        imgs = []
        base = _rot("x", 18)                          # 略微俯角
        for k in range(frames):
            R = _rot("y", 360 * k / frames) @ base
            imgs.append(Image.fromarray(rasterize(V, F, Cface, R, gsz)).convert("P"))
        imgs[0].save(out_prefix + ".gif", save_all=True, append_images=imgs[1:],
                     duration=120, loop=0, optimize=True)
        print(f"  → {out_prefix}.gif ({gsz}×{gsz}, {frames} 帧)", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glb")
    ap.add_argument("out_prefix")
    ap.add_argument("--size", type=int, default=520)
    ap.add_argument("--frames", type=int, default=36)
    ap.add_argument("--no-gif", action="store_true")
    args = ap.parse_args()
    render(args.glb, args.out_prefix, args.size, args.frames, gif=not args.no_gif)


if __name__ == "__main__":
    main()
