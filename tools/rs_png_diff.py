#!/usr/bin/env python3
"""rs_png_diff.py — 判断「old↔new 的像素差异」是否只是「旧二进制自身的抖动」。

为什么需要它
------------
闸门原来的判据失效逻辑只问一句:旧二进制同一局跑两次,PNG 哈希是不是也不同?
若不同就宣布「这一局报告本身不确定,PNG 判据无鉴别力」,不计入失败、退出码放行。

这问得太粗。一局回放完全可以同时满足两件事:
  (a) 它本身不确定(实测:玩家表排序键并列时,行序由随机的数组顺序决定);
  (b) 重建真的引入了一处可见回归。
两者都只表现为「哈希不同」,于是 (b) 会被 (a) 的借口一起放过。JSON 那层又刻意丢弃了
列表顺序,补不上这个洞。

所以再加一条:old↔new 的差异**区域**必须落在 old↔old 自身抖动的**区域**里。
已知的真实抖动案例(15.7 驱逐舰回放,玩家表最后两行 0 伤害玩家互换)差异区域是
y=935..995 / x=78..1337、占 0.26% 像素;若 new 在别处也改了一个像素,包围盒立刻变大,
越界即判失败。

残留的洞(明说,别以为这一条就把判据失效补严实了):包围盒是矩形近似,落在抖动矩形
**内部**的回归仍然看不见;而抖动区域本身只由有限几次运行采样得来,采样不足会把它估小
(方向安全,会多报),采样里恰好没出现的抖动行则可能让它估小到误报。真正的解法是修掉
渲染器那个排序不稳定,让输出确定;在那之前这一条只是把最粗的漏洞收窄。

为什么单开一个文件,而不塞进 rs_compare_report.py
-------------------------------------------------
rs_compare_report.py 是纯标准库的 JSON 比较器,任何 python3 都能跑(闸门里它跟渲染
用的解释器可以不是一个)。本脚本必须 import PIL,是渲染环境的依赖。把 PIL 拖进 JSON
判据会让「JSON 这层能不能跑」取决于图像库装没装,两层判据的失败面就耦合了。
另外二者领域不同(结构比较 vs 像素几何),rs_compare_report.py 还带模块级全局状态
(_max_rel/_float_cmps),塞第二个入口进去只会把它的 main 语义搞浑。

用法
----
    rs_png_diff.py --new NEW.png --old OLD.png [OLD2.png ...] [--footer 48] [--pad 0]

  --old   同一个旧二进制的多次运行产物(至少两张,越多越准)。它们**互相之间**的
          差异并集就是「自身抖动区域」。
  --new   新二进制的产物。它与每一张 --old 的差异并集就是「待解释区域」。
  --footer 裁掉底部多少像素(页脚含 datetime.now(),必须裁,否则每次都不同)。
          必须与 verify_replayshark_equiv.sh 里 png_hash 的 48 保持一致。
  --pad   允许待解释区域比抖动区域外扩多少像素(默认 0,即严格被覆盖)。

退出码
------
  0  待解释区域被自身抖动区域覆盖 → 判据失效成立,可以不计入失败
  1  不被覆盖(或旧二进制自身根本不抖) → 仍应判失败
  2  用法错误 / 读图失败 / 尺寸不一致 → 无法判断,调用方也应当作失败
"""
import sys

try:
    from PIL import Image, ImageChops
except Exception as e:                                    # noqa: BLE001
    print(f"  rs_png_diff: 没有可用的 PIL({e})", file=sys.stderr)
    sys.exit(2)


def load(path, footer):
    im = Image.open(path).convert("RGB")
    if im.height <= footer:
        raise ValueError(f"{path} 高度 {im.height} <= 页脚 {footer},裁完什么都不剩")
    return im.crop((0, 0, im.width, im.height - footer))


def pair_diff(a, b):
    """返回 (包围盒 or None, 变化像素数)。任何一个通道不同就算这个像素变了。"""
    if a.size != b.size:
        raise ValueError(f"尺寸不一致 {a.size} vs {b.size}")
    d = ImageChops.difference(a, b)
    bbox = d.getbbox()
    if bbox is None:
        return None, 0
    # 不要用 convert("L") 数像素:(1,0,0) 这种差异灰度化后会四舍五入成 0 被漏掉
    mask = None
    for band in d.split():
        b2 = band.point(lambda v: 255 if v else 0)
        mask = b2 if mask is None else ImageChops.lighter(mask, b2)
    return bbox, mask.histogram()[255]


def union(b1, b2):
    if b1 is None:
        return b2
    if b2 is None:
        return b1
    return (min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3]))


def fmt(bbox, size):
    if bbox is None:
        return "无差异"
    l, t, r, b = bbox
    area = (r - l) * (b - t)
    pct = 100.0 * area / (size[0] * size[1]) if size[0] and size[1] else 0.0
    return f"x={l}..{r} y={t}..{b}({r - l}x{b - t},占全图 {pct:.2f}%)"


def contained(inner, outer, pad):
    """inner 是否落在 outer 外扩 pad 之后的范围里。"""
    if inner is None:
        return True
    if outer is None:
        return False
    return (inner[0] >= outer[0] - pad and inner[1] >= outer[1] - pad
            and inner[2] <= outer[2] + pad and inner[3] <= outer[3] + pad)


def overflow(inner, outer, pad):
    """列出越界的边,给人看结论怎么来的。"""
    if inner is None or outer is None:
        return []
    out = []
    if inner[0] < outer[0] - pad:
        out.append(f"左 {inner[0]} < {outer[0] - pad}")
    if inner[1] < outer[1] - pad:
        out.append(f"上 {inner[1]} < {outer[1] - pad}")
    if inner[2] > outer[2] + pad:
        out.append(f"右 {inner[2]} > {outer[2] + pad}")
    if inner[3] > outer[3] + pad:
        out.append(f"下 {inner[3]} > {outer[3] + pad}")
    return out


def main(argv):
    new = None
    olds = []
    footer = 48
    pad = 0
    i = 1
    mode = None
    while i < len(argv):
        a = argv[i]
        if a == "--new":
            mode = "new"
        elif a == "--old":
            mode = "old"
        elif a == "--footer":
            i += 1
            footer = int(argv[i])
            mode = None
        elif a == "--pad":
            i += 1
            pad = int(argv[i])
            mode = None
        elif a.startswith("-"):
            print(__doc__)
            return 2
        elif mode == "new":
            new = a
        elif mode == "old":
            olds.append(a)
        else:
            print(__doc__)
            return 2
        i += 1

    if not new or len(olds) < 2:
        print("  rs_png_diff: 需要 --new 一张 + --old 至少两张", file=sys.stderr)
        return 2

    try:
        im_new = load(new, footer)
        im_olds = [load(p, footer) for p in olds]
    except Exception as e:                                # noqa: BLE001
        print(f"  rs_png_diff: 读图失败:{e}", file=sys.stderr)
        return 2

    try:
        # 自身抖动区域:旧二进制各次运行两两之间的差异并集(样本越多越接近真实抖动范围)
        nondet = None
        nondet_px = 0
        pairs = 0
        for x in range(len(im_olds)):
            for y in range(x + 1, len(im_olds)):
                bb, px = pair_diff(im_olds[x], im_olds[y])
                nondet = union(nondet, bb)
                nondet_px = max(nondet_px, px)
                pairs += 1
        # 待解释区域:新产物与每一张旧产物的差异并集
        suspect = None
        suspect_px = 0
        for om in im_olds:
            bb, px = pair_diff(im_new, om)
            suspect = union(suspect, bb)
            suspect_px = max(suspect_px, px)
    except Exception as e:                                # noqa: BLE001
        print(f"  rs_png_diff: 比较失败:{e}", file=sys.stderr)
        return 2

    size = im_new.size
    print(f"  裁掉页脚 {footer}px 后 {size[0]}x{size[1]};旧二进制 {len(olds)} 次运行、{pairs} 对互比")
    print(f"  old↔old 自身抖动区域: {fmt(nondet, size)}  单对最多 {nondet_px} 像素不同")
    print(f"  old↔new 待解释区域:   {fmt(suspect, size)}  单对最多 {suspect_px} 像素不同")

    if suspect is None:
        print("  → old↔new 在裁剪区内没有任何像素差异,没什么要解释的")
        return 0
    if nondet is None:
        print("  → 旧二进制自己跑出来的图逐像素相同,它解释不了 old↔new 的差异 → 判失败")
        return 1
    if contained(suspect, nondet, pad):
        same = suspect == nondet
        print("  → 待解释区域" + ("与抖动区域完全相同" if same else "落在抖动区域内")
              + ",可归因于报告自身不确定 → 判据失效成立")
        return 0
    print("  → 待解释区域越出抖动区域(" + "; ".join(overflow(suspect, nondet, pad))
          + ")→ 不能归因于自身不确定,判失败")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
