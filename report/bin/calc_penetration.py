# report/bin/calc_penetration.py
"""calc_penetration.py — AP 弹道 + 穿深 + 装甲交互(纯函数,可独立 CLI)。

公式来自 wows-toolkit `docs/BALLISTICS.md` + jcw780/wows_shell(社区拟合,±3%)。
覆盖:跳弹角 / 法线化 / 超口径(overmatch)/ 引信触发(detonator)/ 过穿 / 弹开。

库用法:
    from calc_penetration import shoot
    r = shoot(shell, distance_m, plate_mm, plate_tilt_deg, target_angle_deg)
    # r = {"verdict": "PEN|OVER|NO_PEN|RICOCHET", "damage": float, ...}

CLI:
    python report/bin/calc_penetration.py --ship-id PJSB018 --target PASB119 --range 15 --angle 30
"""
import argparse
import json
import math
import sys
from pathlib import Path

import math
from typing import Optional

# 物理 / 大气
G = 9.81
T0 = 288.15            # 海平面温度 K
LAPSE = 0.0065         # 温度递减率 K/m
P0 = 101325            # 海平面气压 Pa
R_UNIV = 8.31447       # 通用气体常数
M_AIR = 0.0289644      # 干空气摩尔质量

DT = 0.05              # 弹道积分步长 s


def _air_density(h):
    """ISA 大气密度 kg/m³(h<11000m,我们用不到那么高)。"""
    if h < 0:
        h = 0
    T = T0 - LAPSE * h
    if T <= 0:
        return 0.0
    p = P0 * (1 - LAPSE * h / T0) ** (G * M_AIR / (R_UNIV * LAPSE))
    return p * M_AIR / (R_UNIV * T)


def trajectory(v0, drag, diameter, mass, elevation_rad):
    """单条弹道:积分到落地。返回 (distance_m, v_impact, impact_angle_rad)。"""
    drag_const = 0.5 * drag * (diameter / 2) ** 2 * math.pi / mass
    cw_lin = 100 + 1000 / 3 * diameter                # 经验线性修正
    vx = math.cos(elevation_rad) * v0
    vy = math.sin(elevation_rad) * v0
    x = 0.0
    y = 0.0
    while True:
        x += DT * vx
        y += DT * vy
        if y < 0:
            break
        rho = _air_density(y)
        vx -= DT * drag_const * rho * (vx * vx + cw_lin * vx)
        vy_sign = 1 if vy >= 0 else -1
        vy -= DT * G + DT * drag_const * rho * (vy * vy + cw_lin * abs(vy)) * vy_sign
        # 防发散保险
        if x > 60000:
            break
    v_imp = math.hypot(vx, vy)
    angle = math.atan2(abs(vy), abs(vx)) if vx > 0 else math.pi / 2
    return x, v_imp, angle


def range_table(shell, max_range_m=30000, step_deg=0.05):
    """扫仰角 → (distance, v_impact, fall_angle) 表(按距离升序)。"""
    out = []
    v0 = shell["velocity"]; drag = shell["drag"]
    d = shell["diameter"]; m = shell["mass"]
    e = 0.0
    last_x = -1
    while e < math.radians(45):
        x, v, a = trajectory(v0, drag, d, m, e)
        if x <= last_x and out:                       # 已经到最大射程,过抛物顶点
            break
        if x > max_range_m and out:
            out.append((x, v, a))
            break
        out.append((x, v, a))
        last_x = x
        e += math.radians(step_deg)
    out.sort(key=lambda t: t[0])
    return out


def at_range(table, target_m):
    """从弹道表线性插值出指定距离的 (v_impact, fall_angle)。距离超出返回 None。"""
    if not table or target_m < table[0][0] or target_m > table[-1][0]:
        return None
    for i in range(1, len(table)):
        x1, v1, a1 = table[i]
        if x1 >= target_m:
            x0, v0_, a0 = table[i - 1]
            t = (target_m - x0) / (x1 - x0) if x1 > x0 else 0
            return (v0_ + (v1 - v0_) * t, a0 + (a1 - a0) * t)
    return None


def raw_pen_mm(krupp, mass, diameter, v_impact):
    """wows_shell 公式:法向裸穿(mm)。
    p_ppc = 1e-7 * krupp * mass^0.69 * caliber^(-1.07)
    raw_pen = p_ppc * v^1.38     单位实际拟合到 mm。
    """
    if v_impact <= 0:
        return 0.0
    p_ppc = 1e-7 * krupp * (mass ** 0.69) * (diameter ** -1.07)
    return p_ppc * (v_impact ** 1.38)


# ── 装甲交互 ────────────────────────────────────────────────────────────────
# verdict 取值 (对应游戏内勋带):
#   "CITADEL"  核心区命中  → full damage    (打中装甲核心区且穿透引信)
#   "PEN"      击穿        → 1/3 damage     (打中非核心区且穿透引信)
#   "OVERMATCH"超口径      → 同 PEN/CITADEL (按打中 zone 给伤,绕过跳弹)
#   "OVER"     过穿        → 1/10 damage    (穿透但厚度 < 引信触发阈值)
#   "NO_PEN"   未击穿      → 0
#   "RICOCHET" 跳弹        → 0
# WoWs 内伤害系数 (alpha 是弹种 alphaDamage):
#   核心区命中 = alpha
#   非核心击穿 = alpha / 3
#   过穿       = alpha / 10

def _impact_geometry(fall_angle_rad, target_yaw_deg, plate_tilt_deg):
    """综合冲击角(0=法向 / 直角命中,90=切向 / 擦过)。

    分两种板分别计算,因为水平甲板和垂直舷侧的几何关系不同:

    - **水平甲板** (plate_tilt_deg≈90):
      板法线朝上,弹道与法线夹角 = 90° − 落角(落角越大越接近垂直命中)。
      航向角对甲板无影响(船怎么转,甲板都朝上)。

    - **垂直/斜舷侧板** (plate_tilt_deg<60):
      在水平面投影:综合角 = 航向角(0=对舷正打,90=对头掠过) + 板自身倾角。
      落角在垂直面贡献:cos(综合) = cos(水平综合) × cos(落角)。
    """
    fall = abs(fall_angle_rad)
    yaw = math.radians(abs(target_yaw_deg))
    tilt = math.radians(abs(plate_tilt_deg))
    if plate_tilt_deg >= 60:                                 # 水平甲板
        alpha = math.pi / 2 - fall                           # 落角 30° → 综合 60°
        return max(0.0, math.degrees(alpha))
    # 垂直/斜舷侧板
    horiz = yaw + tilt                                       # 水平面综合角
    cos_alpha = math.cos(horiz) * math.cos(fall)
    cos_alpha = max(-1.0, min(1.0, cos_alpha))
    return math.degrees(math.acos(cos_alpha))


def shoot(shell, table, distance_m, plate_mm, plate_tilt_deg=0.0,
          target_yaw_deg=30.0, is_citadel=False):
    """单次"打一发"判定。
    shell        : ap_ballistic dict
    table        : range_table(shell) 结果
    plate_mm     : 装甲厚度 mm(可 list,取最大一层)
    plate_tilt_deg: 该板倾角(0=垂直舷侧,90=水平甲板)
    target_yaw_deg: 目标船相对弹道的水平航向角(0=对舷,90=对头)
    is_citadel   : 该板是否属于装甲核心区 (Citadel zone) — 影响击穿伤害归类

    判定流程:
      1. 算落点参数 (落速/落角/综合冲击角/法线化)
      2. 碾压标志 = (弹径 mm ≥ 14.3 × 板厚) — 跳过跳弹判定但仍走穿深/引信
      3. 非碾压 → 跳弹判定(超过 always_ricochet 必跳)
      4. 算有效穿深 vs 板厚 → 未击穿 / 过穿 / 击穿
      5. 击穿且命中核心区 → 核心区命中
    伤害系数(WoWs 内):核心区=满, 击穿=1/3, 过穿=1/10, 其它=0
    """
    if isinstance(plate_mm, (list, tuple)):
        plate_mm = max(plate_mm)
    if not plate_mm:
        return {"verdict": "NO_PEN", "damage": 0, "reason": "无装甲数据"}
    r = at_range(table, distance_m)
    if r is None:
        return {"verdict": "NO_PEN", "damage": 0,
                "reason": f"超出射程({int(table[-1][0])} m)"}
    v_imp, fall = r

    alpha = _impact_geometry(fall, target_yaw_deg, plate_tilt_deg)
    cap = shell.get("cap_normalize") or 0.0
    norm_eff = cap * min(1.0, 14.3 * shell["diameter"] / plate_mm)
    alpha_eff = max(0.0, alpha - norm_eff)
    raw = raw_pen_mm(shell["krupp"], shell["mass"], shell["diameter"], v_imp)
    alpha_dmg = shell["alpha_damage"]

    # 碾压(overmatch):弹径 mm ≥ 14.3 × 板厚 → 跳过跳弹判定,但仍走穿深/引信
    is_overmatch = (shell["diameter"] * 1000) >= (14.3 * plate_mm)

    base = {
        "v_impact": v_imp, "fall_angle": math.degrees(fall),
        "alpha": alpha, "alpha_eff": alpha_eff,
        "raw_pen": raw, "plate_mm": plate_mm,
        "is_overmatch": is_overmatch, "is_citadel_plate": is_citadel,
    }

    # 跳弹判定 (非碾压时才检查)
    if not is_overmatch:
        ricochet = shell.get("ricochet") or 90.0
        always_ric = shell.get("always_ricochet") or 90.0
        if alpha_eff >= always_ric:
            return {**base, "verdict": "RICOCHET", "damage": 0, "eff_pen": 0}
        if alpha_eff >= ricochet:
            # ricochet → always_ricochet 之间概率 0→100% 线性。MVP 取 50% 阈值。
            prob = (alpha_eff - ricochet) / max(0.1, always_ric - ricochet)
            if prob >= 0.5:
                return {**base, "verdict": "RICOCHET", "damage": 0,
                        "ricochet_prob": prob, "eff_pen": 0}

    # 穿深 (碾压不强制视为有效穿,仍要算 — 但碾压通常薄板,基本都过)
    eff = raw * math.cos(math.radians(alpha_eff))

    # 未击穿 (碾压时把超薄板视为 0 穿深需求,不会走这分支)
    if not is_overmatch and eff < plate_mm:
        return {**base, "verdict": "NO_PEN", "damage": 0, "eff_pen": eff}

    # 过穿:板厚 < 引信触发阈值
    fuse = shell.get("fuse_threshold") or 0
    if plate_mm < fuse:
        return {**base, "verdict": "OVER", "damage": round(alpha_dmg / 10),
                "eff_pen": eff}

    # 击穿:命中核心区 = 满伤,非核心区 = 1/3
    if is_citadel:
        return {**base, "verdict": "CITADEL", "damage": round(alpha_dmg),
                "eff_pen": eff}
    return {**base, "verdict": "PEN", "damage": round(alpha_dmg / 3),
            "eff_pen": eff}


# ── 典型弹 & 临界口径(防御视角 /装甲 分析用)──────────────────────────────
# 同口径不同船 AP 弹差距大 (krupp/mass/velocity 可 ±50%)。这里按口径取所有真实
# AP 弹的"中位弹"作为该口径代表,算出来的"≥X mm 可穿"含义 = 主流战列弹近似。
# 调用方 (render_pen) 把 ships.json 里所有 ap_ballistic 给我,我建表。

_TYPICAL_CACHE = {}      # cal_mm → typical shell dict


def build_typical_shells(all_ap_shells, calibers_mm=None):
    """all_ap_shells: ships.json 里所有 ap_ballistic dict 列表 (过滤掉 None)。
    返回 {cal_mm(int): typical_shell, ...} 同时存到模块缓存。"""
    from statistics import median
    global _TYPICAL_CACHE
    by_cal = {}
    for s in all_ap_shells:
        if not s or not s.get("krupp"): continue
        cal = round(s["diameter"] * 1000)
        if calibers_mm and cal not in calibers_mm:
            continue
        by_cal.setdefault(cal, []).append(s)
    out = {}
    for cal, lst in by_cal.items():
        out[cal] = {
            "diameter": cal / 1000,
            "krupp":    median(s["krupp"] for s in lst),
            "mass":     median(s["mass"] for s in lst),
            "velocity": median(s["velocity"] for s in lst),
            "drag":     median(s["drag"] for s in lst),
            "ricochet":        median(s.get("ricochet") or 45.0 for s in lst),
            "always_ricochet": median(s.get("always_ricochet") or 60.0 for s in lst),
            "cap_normalize":   median(s.get("cap_normalize") or 0.0 for s in lst),
            "fuse_threshold":  median(s.get("fuse_threshold") or 0.0 for s in lst),
            "alpha_damage":    median(s.get("alpha_damage") or 0.0 for s in lst),
            "_n": len(lst),
        }
    _TYPICAL_CACHE = out
    return out


_TABLE_CACHE = {}


def _typical_table(cal_mm):
    t = _TABLE_CACHE.get(cal_mm)
    if t is None:
        s = _TYPICAL_CACHE[cal_mm]
        t = range_table(s, max_range_m=30000)
        _TABLE_CACHE[cal_mm] = t
    return t


# 默认查询的"主流" 口径档(连续值意义有限,玩家心智锚还是这几档)
DEFAULT_CALIBERS_MM = [100, 127, 152, 203, 305, 356, 380, 406, 410, 457, 460, 510]


def critical_caliber(distance_m, plate_mm, plate_tilt_deg, target_yaw_deg,
                     is_citadel=False, want="PEN"):
    """对一个 (距离, 角度, 板厚) 三元,扫每个口径档,找:
       - 最小能拿到 want 结果的口径(want="PEN" 含 CITADEL/PEN/OVER,"CITADEL" 只算核心)
       - 是否必跳(所有口径都跳弹 = 角度真的太大)
       - 是否需要碾压(最小可穿口径 ≥ 14.3 × plate_mm)
    返回 dict: {min_cal, verdict, is_overmatch_only, all_ricochet}
    没任何口径能击穿 → min_cal=None。
    """
    want_set = {"PEN", "CITADEL", "OVER"} if want == "PEN" else {"CITADEL"}
    cals = sorted(_TYPICAL_CACHE.keys())
    found_min = None
    found_verdict = None
    found_overmatch = False
    any_non_ricochet = False
    for cal in cals:
        s = _TYPICAL_CACHE[cal]
        r = shoot(s, _typical_table(cal), distance_m, plate_mm,
                  plate_tilt_deg, target_yaw_deg, is_citadel=is_citadel)
        if r["verdict"] != "RICOCHET":
            any_non_ricochet = True
        if r["verdict"] in want_set:
            if found_min is None or cal < found_min:
                found_min = cal
                found_verdict = r["verdict"]
                found_overmatch = bool(r.get("is_overmatch"))
                break
    return {
        "min_cal": found_min,
        "verdict": found_verdict,
        "is_overmatch_only": found_overmatch,
        "all_ricochet": not any_non_ricochet,
    }


# ── CLI(对照 jcw780 在线计算器用)────────────────────────────────────────
_VERDICT_ZH = {"CITADEL": "核心区", "PEN": "击穿", "OVER": "过穿",
               "NO_PEN": "未击穿", "RICOCHET": "跳弹"}


def _cli():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shell-json", help="弹道参数 JSON(若给则跳过 ships.json 查找)")
    ap.add_argument("--ship-index", help="我船 index(如 PJSB018),从 ships.json 找 ap_ballistic")
    ap.add_argument("--plate-mm", type=float, default=410, help="目标板厚 mm")
    ap.add_argument("--plate-tilt", type=float, default=0, help="板倾角度(0=舷侧、90=甲板)")
    ap.add_argument("--target-yaw", type=float, default=30, help="目标航向角度")
    ap.add_argument("--range", dest="rng", type=float, default=15, help="距离 km")
    args = ap.parse_args()

    if args.shell_json:
        shell = json.loads(args.shell_json)
    elif args.ship_index:
        ships = json.loads(
            (Path(__file__).resolve().parent.parent / "data" / "ships.json").read_text("utf-8")
        )["ships"]
        ship = next((s for s in ships.values() if s.get("index") == args.ship_index), None)
        if not ship or not ship.get("ap_ballistic"):
            sys.exit(f"船 {args.ship_index} 不在 ships.json 或无 AP 弹道")
        shell = ship["ap_ballistic"]
    else:
        sys.exit("需要 --shell-json 或 --ship-index")

    print(f"弹种: {shell.get('shell_index')}  口径{shell['diameter']*1000:.0f}mm "
          f"krupp{shell['krupp']:.0f} 单发{shell['alpha_damage']:.0f}")
    table = range_table(shell)
    r = shoot(shell, table, args.rng * 1000, args.plate_mm,
              args.plate_tilt, args.target_yaw)
    print(f"\n@ {args.rng} km, 板 {args.plate_mm} mm (倾 {args.plate_tilt}°), 目标偏航 {args.target_yaw}°")
    if r.get("v_impact"):
        print(f"  落速 {r['v_impact']:.0f} m/s, 落角 {r['fall_angle']:.1f}°, "
              f"综合角 {r['alpha']:.1f}° → 法线化后 {r['alpha_eff']:.1f}°")
        print(f"  裸穿 {r['raw_pen']:.0f} mm → 有效 {r['eff_pen']:.0f} mm vs {r['plate_mm']} mm")
    tag = _VERDICT_ZH.get(r["verdict"], r["verdict"])
    if r.get("is_overmatch"):
        tag += " (碾压)"
    print(f"  结果: {tag}  伤害 {r['damage']}")


if __name__ == "__main__":
    _cli()