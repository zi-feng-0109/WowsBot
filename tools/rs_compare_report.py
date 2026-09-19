#!/usr/bin/env python3
"""rs_compare_report.py — 比较两份 battle-report JSON 是否等价。

为什么不能直接 cmp 字节
-----------------------
battle-report 的输出**本身就不确定**:2026-09-19 实测,同一个二进制、同一局回放、
跑两次,输出大小相同但字节不同。差异有两种,都源于 HashMap 的迭代顺序随机:

1. **顺序**:`damage_events`(1115 条)、`deaths`(15 条)的多重集完全相同,只是排列不同。
2. **浮点末位**:`players[].stats.damage_dealt` 出现 `87423.05902516741` vs `...43` ——
   同一批伤害事件按不同顺序累加,浮点尾数差一个 ULP。

所以「逐字节一致」这个判据连旧二进制自己跟自己比都过不了,拿它当换装闸门是错的。
本脚本改为:递归规范化(dict 按键排序、list 按规范化后的文本排序)+ 浮点相对容差。

用法
----
    rs_compare_report.py <old.json> <new.json> [--tol 1e-9]

退出码 0 = 等价。非零 = 有实质差异,会打印差异位置。
同时会打出观测到的最大浮点相对偏差,便于判断它是 ULP 级还是语义级。
"""
import json
import math
import sys

_max_rel = 0.0
_float_cmps = 0


def _num_close(a, b, tol):
    """数值比较,记录最大相对偏差。整数与布尔按原值比。"""
    global _max_rel, _float_cmps
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if a == b:
        return True
    if not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return False
    if math.isnan(a) and math.isnan(b):
        return True
    scale = max(abs(a), abs(b))
    rel = abs(a - b) / scale if scale else abs(a - b)
    _float_cmps += 1
    _max_rel = max(_max_rel, rel)
    return rel <= tol


def canon(x):
    """递归规范化:dict 按键排序,list 按其规范化后的 JSON 文本排序。

    对 list 排序会丢掉顺序信息 —— 这是有意的:上面已证明顺序本身是随机的,
    所以顺序不承载信息。若将来输出变成确定有序的,这个判据要重新设计。
    """
    if isinstance(x, dict):
        return {k: canon(x[k]) for k in sorted(x)}
    if isinstance(x, list):
        items = [canon(i) for i in x]
        return sorted(items, key=lambda i: json.dumps(i, sort_keys=True, ensure_ascii=False))
    return x


def diff(a, b, tol, path="$", out=None):
    """比较两个已规范化的结构,把差异路径写进 out。"""
    if out is None:
        out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}: 只在新的里")
            elif k not in b:
                out.append(f"{path}.{k}: 只在旧的里")
            else:
                diff(a[k], b[k], tol, f"{path}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: 长度不同 旧 {len(a)} / 新 {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, tol, f"{path}[{i}]", out)
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not _num_close(a, b, tol):
            out.append(f"{path}: {a!r} vs {b!r}")
    elif a != b:
        out.append(f"{path}: {a!r} vs {b!r}")
    return out


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    tol = 1e-9
    if "--tol" in argv:
        tol = float(argv[argv.index("--tol") + 1])
    with open(argv[1], encoding="utf-8") as f:
        old = json.load(f)
    with open(argv[2], encoding="utf-8") as f:
        new = json.load(f)

    problems = diff(canon(old), canon(new), tol)
    if _float_cmps:
        print(f"  浮点:{_float_cmps} 处需要容差,最大相对偏差 {_max_rel:.3e}(容差 {tol:.0e})")
    if problems:
        print(f"  实质差异 {len(problems)} 处,前 20 处:")
        for p in problems[:20]:
            print(f"    {p}")
        return 1
    print("  规范化后等价")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
