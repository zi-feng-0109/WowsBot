#!/usr/bin/env python3
"""build_ships_json.py — generate report/data/ships.json (战舰数值字典).

`/船 <中文名>` 渲染端 (render_ship.py) 读这份 json 出数值卡。运行时 bot 不打任何
外部 API —— 全部数据在打版本时这里一次性吃掉,跟 builds.json 一个套路。

三源 join:
  1. specs/content/GameParams.data (Python unpickle) → 每船:
     ship_id ↔ index ↔ species ↔ level ↔ nation + 消耗品槽 (ShipAbilities)。
     WG API 不给消耗品,这是唯一来源。
  2. WG public API encyclopedia (需 application_id) → default_profile 数值
     (HP/主炮/鱼雷/隐蔽/机动/副炮/装甲) + images 预览图 URL。
     多船体船 default 是白板 → 用顶级模块走 shipprofile 拿满配覆盖。
     **丢弃 WG 的 zh-cn 梗名** (饺子皮/水表船),只取 en 名 + 数值。
  3. report/data/zh_sg.mo → IDS_<index> 标准中文名 (跟 /查询 一致)。

为什么 ship_id 能直接 join:实测 WG API ship_id == GameParams ship.id (同一
WG GameParamId),例:大和 4276041424 → index PJSB018 → IDS_PJSB018 = 大和。

每次游戏大版本更新后跟 build_builds_json.py 一并重跑 (UPDATE.md 里有挂)。
"""
import argparse
import io
import json
import os
import pickle
import sys
import time
import types
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "report" / "lib"))
from wowsbot import paths                # noqa: E402

DEFAULT_GAMEPARAMS = Path(paths.GAME_PARAMS_DATA)  # 原 BOT_HOME/"specs"/"content"/... —— 少了 report/
DEFAULT_MO = Path(paths.TRANSLATIONS_MO)
DEFAULT_OUT = Path(paths.SHIPS_JSON)
DEFAULT_HOST = "api.worldofwarships.asia"
# 用户的 ESSEXBOT app_id (eu/asia 都认,realm 无关);仅构建期用,运行时 bot 不碰。
DEFAULT_APP_ID = "8ea66b76f5483555ae2594a68882cbf9"

# species / nation → 中文 (稳定集合,直接打表,省得过 zh_sg)
SPECIES_ZH = {
    "Battleship": "战列舰", "Cruiser": "巡洋舰", "Destroyer": "驱逐舰",
    "AirCarrier": "航空母舰", "Submarine": "潜艇", "Auxiliary": "辅助舰",
}
NATION_ZH = {
    # GameParams typeinfo.nation 用的代号 (注意苏联=Russia、英国=United_Kingdom)
    "Japan": "日本", "USA": "美国", "Russia": "苏联", "Germany": "德国",
    "United_Kingdom": "英国", "France": "法国", "Italy": "意大利", "Pan_Asia": "泛亚",
    "Commonwealth": "英联邦", "Poland": "波兰", "Netherlands": "荷兰",
    "Spain": "西班牙", "Pan_America": "泛美", "Europe": "欧洲", "Brazil": "巴西",
    "Common": "通用",
    # WG public API 小写代号兜底 (以防来源切换)
    "Ussr": "苏联", "Uk": "英国",
}

# shipprofile 接口的模块类型 → query 参数名
MODULE_PARAM = {
    "Hull": "hull_id", "Artillery": "artillery_id", "Engine": "engine_id",
    "Suo": "fire_control_id", "Torpedoes": "torpedoes_id",
    "FlightControl": "flight_control_id", "DiveBomber": "dive_bomber_id",
    "Fighter": "fighter_id", "TorpedoBomber": "torpedo_bomber_id",
}


# ───────────────────────── GameParams unpickle ──────────────────────────────

class _GP:
    """通配 shim:接住 GameParams pickle 里所有自定义类,只留 __dict__。"""
    def __init__(self, *a, **k):
        self.__dict__.update(k)

    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)
        elif isinstance(state, tuple) and len(state) == 2 and isinstance(state[1], dict):
            self.__dict__.update(state[1])


class _Unpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module not in sys.modules:
            sys.modules[module] = types.ModuleType(module)
        if not hasattr(sys.modules[module], name):
            setattr(sys.modules[module], name, _GP)
        return getattr(sys.modules[module], name)


def _d(o) -> dict:
    return getattr(o, "__dict__", {}) if not isinstance(o, dict) else o


def load_gameparams(path: Path) -> dict:
    """unpickle GameParams.data → 主区 dict {gameparam_name: obj}。"""
    raw = zlib.decompress(path.read_bytes()[::-1])
    gp = _Unpickler(io.BytesIO(raw)).load()
    return gp[""] if isinstance(gp, dict) and "" in gp else gp


def extract_ships_from_gp(gp: dict) -> dict:
    """{ship_id(int): {index, level, species, nation, consumables}}。

    consumables = [[ability_name, ...], ...] 每个非空 slot 一个内层 list
    (内层多个 = 玩家二选一,如 侦察机/战斗机)。
    """
    ships = {}
    for name, obj in gp.items():
        d = _d(obj)
        ti = _d(d.get("typeinfo"))
        if ti.get("type") != "Ship":
            continue
        sid = d.get("id")
        if sid is None:
            continue
        # 消耗品:ShipAbilities → AbilitySlot* → abils = [(ability_name, variant)]
        # 每个 slot 可能多个 (玩家二选一);装填数 numConsumables 在具体 variant 里
        # (-1 = 无限,正数 = 装填次数)
        consumables = []
        sa = _d(d.get("ShipAbilities"))
        for slot_key in sorted(sa.keys()):
            slot = _d(sa[slot_key])
            abils = slot.get("abils") or []
            if not abils:
                continue
            alts = []
            seen = set()
            for entry in abils:
                # entry = (ability_name, variant)
                if not (isinstance(entry, (list, tuple)) and entry):
                    continue
                nm = entry[0]
                variant = entry[1] if len(entry) > 1 else None
                if not nm or nm in seen:
                    continue
                seen.add(nm)
                charges = work_s = range_km = None
                ab = _d(gp.get(nm))
                reload_s = prep_s = None
                if variant and variant in ab:
                    var = _d(ab[variant])
                    charges = var.get("numConsumables")
                    wt = var.get("workTime")
                    if isinstance(wt, (int, float)) and wt > 0:
                        work_s = round(wt, 1)
                    rl = var.get("reloadTime")
                    if isinstance(rl, (int, float)) and rl > 0:
                        reload_s = round(rl, 1)
                    pp = var.get("preparationTime")
                    if isinstance(pp, (int, float)):
                        prep_s = round(pp, 1)
                    # 作用范围:按 wows-toolkit 的换算 (BW_TO_METERS=30)。
                    #   distShip/distTorpedo/radius = BigWorld 距离 (×30→米→÷1000 km = ×0.03)
                    #   hydrophoneWaveRadius = 米 (÷1000 km)
                    # 雷达/监视=distShip,声呐=distShip+distTorpedo,水听器=hydrophoneWaveRadius,
                    # 烟雾/战斗机/巡逻战斗机=radius。
                    lg = _d(var.get("logic"))
                    def _bw(v):  # BigWorld → km
                        return round(v * 0.03, 2) if isinstance(v, (int, float)) and v > 0 else None
                    def _m(v):   # 米 → km
                        return round(v / 1000, 2) if isinstance(v, (int, float)) and v > 0 else None
                    range_km = (_bw(lg.get("distShip")) or _m(lg.get("hydrophoneWaveRadius"))
                                or _bw(lg.get("radius")))
                    range_torp_km = _bw(lg.get("distTorpedo"))
                alts.append({"ability": nm, "charges": charges, "work_s": work_s,
                             "reload_s": reload_s, "prep_s": prep_s,
                             "range_km": range_km, "range_torp_km": range_torp_km})
            if alts:
                consumables.append(alts)
        # 主炮 AP 弹道参数 (供 /穿透 用)。Ship.A_Artillery.HP_*.ammoList → 找 AP Projectile。
        # 多个炮塔通常共用一组弹种,取第一个找到的即可。
        ap_ballistic = None
        art = _d(d.get("A_Artillery"))
        for hp_key, hp_obj in art.items():
            hp = _d(hp_obj)
            hp_ti = _d(hp.get("typeinfo"))
            if hp_ti.get("type") != "Gun" or hp_ti.get("species") != "Main":
                continue
            for ammo_name in (hp.get("ammoList") or ()):
                proj = _d(gp.get(ammo_name))
                if proj.get("ammoType") != "AP":
                    continue
                ap_ballistic = {
                    "shell_index": proj.get("index"),
                    "krupp": proj.get("bulletKrupp"),
                    "mass": proj.get("bulletMass"),
                    "diameter": proj.get("bulletDiametr"),
                    "drag": proj.get("bulletAirDrag"),
                    "velocity": proj.get("bulletSpeed"),
                    "ricochet": proj.get("bulletRicochetAt"),
                    "always_ricochet": proj.get("bulletAlwaysRicochetAt"),
                    "cap_normalize": proj.get("bulletCapNormalizeMaxAngle"),
                    "fuse_threshold": proj.get("bulletDetonatorThreshold"),
                    "alpha_damage": proj.get("alphaDamage"),
                }
                break
            if ap_ballistic:
                break

        ships[int(sid)] = {
            "index": d.get("index"),
            "level": d.get("level"),
            "species": ti.get("species"),
            "nation": ti.get("nation"),
            "consumables": consumables,
            "ap_ballistic": ap_ballistic,
        }
    return ships


# ───────────────────────────── 翻译 ─────────────────────────────────────────

def load_translations(mo_path: Path) -> dict:
    import polib
    return {e.msgid: e.msgstr for e in polib.mofile(str(mo_path)) if e.msgstr}


def clean_ship_name(raw: str) -> str:
    """PJSB018_Yamato_1944 → Yamato。跟 render_battle_report 同款。"""
    if not raw:
        return "?"
    parts = raw.split("_")
    if len(parts) >= 2:
        parts = parts[1:]
    while parts and parts[-1].isdigit() and len(parts[-1]) == 4:
        parts.pop()
    return "_".join(parts) or raw


def consumable_zh(ability_name: str, tr: dict) -> str:
    """跟 render_criminals.consumable_display 一致:IDS_DOCK_CONSUME_TITLE_<UPPER>。"""
    return tr.get(f"IDS_DOCK_CONSUME_TITLE_{ability_name.upper()}", ability_name)


# ──────────────────────────── WG API ────────────────────────────────────────

def wg_get(host: str, app_id: str, path: str, **params) -> dict:
    params["application_id"] = app_id
    url = f"https://{host}{path}?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "wows-bot/1"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))  # 指数退避
    raise RuntimeError(f"WG API failed after 3 tries: {path} ({last})")


def fetch_all_ships(host: str, app_id: str, language: str) -> dict:
    """分页拉全船 (含 default_profile/images/modules_tree)。返回 {ship_id_str: ship}。"""
    fields = ("ship_id,name,tier,type,nation,default_profile,images,modules_tree,"
              "next_ships,is_premium,is_special,price_credit")  # next_ships 等供 /线 科技树
    out = {}
    page = 1
    while True:
        d = wg_get(host, app_id, "/wows/encyclopedia/ships/",
                   fields=fields, language=language, page_no=page, limit=100)
        if d.get("status") != "ok":
            raise RuntimeError(f"ships list error: {d.get('error')}")
        data = d.get("data") or {}
        out.update({k: v for k, v in data.items() if v})
        meta = d.get("meta") or {}
        if page >= int(meta.get("page_total") or 1):
            break
        page += 1
    return out


def fetch_zh_names(host: str, app_id: str) -> dict:
    """拉 WG zh-cn 名 (国服梗名),当搜索别名用。{ship_id_str: name}。"""
    out = {}
    page = 1
    while True:
        d = wg_get(host, app_id, "/wows/encyclopedia/ships/",
                   fields="ship_id,name", language="zh-cn", page_no=page, limit=100)
        if d.get("status") != "ok":
            break
        data = d.get("data") or {}
        out.update({k: v["name"] for k, v in data.items() if v and v.get("name")})
        meta = d.get("meta") or {}
        if page >= int(meta.get("page_total") or 1):
            break
        page += 1
    return out


def top_modules(modules_tree: dict) -> dict:
    """从 modules_tree 选每个类型的链末端 (最高级) 模块 → {param_name: module_id}。"""
    by_type: dict = {}
    for m in modules_tree.values():
        by_type.setdefault(m.get("type"), []).append(m)
    params = {}
    for t, mods in by_type.items():
        if t not in MODULE_PARAM:
            continue
        # 链末端 = 没有 next_modules 的那个 (线性升级链的最高级)
        leaves = [m for m in mods if not m.get("next_modules")]
        pick = leaves[-1] if leaves else mods[-1]
        mid = pick.get("module_id")
        if mid:
            params[MODULE_PARAM[t]] = mid
    return params


def resolve_top_profile(host: str, app_id: str, ship_id: str, modules_tree: dict) -> Optional[dict]:
    """多船体船:用顶级模块拿满配 profile。失败返回 None (调用方回退 default)。"""
    params = top_modules(modules_tree)
    if not params:
        return None
    try:
        d = wg_get(host, app_id, "/wows/encyclopedia/shipprofile/",
                   ship_id=ship_id, language="en", **params)
        if d.get("status") == "ok":
            return (d.get("data") or {}).get(ship_id)
    except Exception:  # noqa: BLE001
        pass
    return None


# ──────────────────────── profile → 数值结构 ────────────────────────────────

def _round(v, n=1):
    return round(v, n) if isinstance(v, (int, float)) else None


def extract_stats(profile: dict) -> dict:
    """WG default_profile / shipprofile → 渲染端用的扁平数值。"""
    out = {}
    hull = profile.get("hull") or {}
    out["hp"] = hull.get("health")

    a = profile.get("artillery")
    if a:
        shells = {}
        for typ, s in (a.get("shells") or {}).items():
            shells[typ] = {
                "dmg": s.get("damage"),
                "speed": s.get("bullet_speed"),
                "fire": s.get("burn_probability"),
                "name": s.get("name"),
            }
        out["artillery"] = {
            "range_km": _round(a.get("distance")),
            "reload_s": _round(a.get("shot_delay")),
            "rpm": _round(a.get("gun_rate")),
            "dispersion": a.get("max_dispersion"),
            "traverse_s": _round(a.get("rotation_time")),
            "shells": shells,
        }

    t = profile.get("torpedoes")
    if t:
        slots = t.get("slots") or {}
        tubes = " + ".join(
            f"{sl.get('guns')}×{sl.get('barrels')} ({sl.get('caliber')}mm)"
            for sl in slots.values()
        ) or None
        out["torpedoes"] = {
            "dmg": t.get("max_damage"),
            "speed_kt": t.get("torpedo_speed"),
            "range_km": _round(t.get("distance")),
            "reload_s": _round(t.get("reload_time")),
            "detect_km": _round(t.get("visibility_dist"), 2),
            "tubes": tubes,
            "name": t.get("torpedo_name"),
        }

    atba = profile.get("atbas")
    if atba and atba.get("distance"):
        out["secondary"] = {"range_km": _round(atba.get("distance"))}

    c = profile.get("concealment") or {}
    out["concealment"] = {
        "sea_km": _round(c.get("detect_distance_by_ship"), 2),
        "air_km": _round(c.get("detect_distance_by_plane"), 2),
    }

    m = profile.get("mobility") or {}
    out["mobility"] = {
        "speed_kt": _round(m.get("max_speed")),
        "turn_m": m.get("turning_radius"),
        "rudder_s": _round(m.get("rudder_time")),
    }

    armour = profile.get("armour") or {}
    if armour:
        out["armour"] = {
            "citadel": armour.get("citadel"),
            "extremities": armour.get("extremities"),
        }
    return out


# ─────────────────────────────── main ───────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gameparams", type=Path, default=DEFAULT_GAMEPARAMS,
                    help=f"GameParams.data (default: {DEFAULT_GAMEPARAMS})")
    ap.add_argument("--mo", type=Path, default=DEFAULT_MO)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--app-id", default=os.environ.get("WOWS_WG_APP_ID", DEFAULT_APP_ID))
    ap.add_argument("--parallel", type=int, default=4, help="shipprofile 并发")
    ap.add_argument("--no-aliases", action="store_true", help="跳过拉 WG zh-cn 梗名别名")
    args = ap.parse_args()

    if not args.gameparams.is_file():
        sys.exit(f"error: GameParams.data not found at {args.gameparams}")

    print(f"  unpickling {args.gameparams} ...", file=sys.stderr)
    gp = load_gameparams(args.gameparams)
    gp_ships = extract_ships_from_gp(gp)
    print(f"  GameParams: {len(gp_ships)} ships", file=sys.stderr)

    tr = load_translations(args.mo)
    print(f"  loaded {len(tr)} translations", file=sys.stderr)

    print(f"  fetching WG ship list from {args.host} ...", file=sys.stderr)
    wg_ships = fetch_all_ships(args.host, args.app_id, "en")
    print(f"  WG API: {len(wg_ships)} ships", file=sys.stderr)

    aliases_raw = {}
    if not args.no_aliases:
        print("  fetching WG zh-cn names (aliases) ...", file=sys.stderr)
        aliases_raw = fetch_zh_names(args.host, args.app_id)

    # 多船体船:并发拿满配 profile
    multi = [(sid, s) for sid, s in wg_ships.items()
             if int(sid) in gp_ships
             and len([m for m in (s.get("modules_tree") or {}).values()
                      if m.get("type") == "Hull"]) > 1]
    print(f"  resolving {len(multi)} multi-hull top profiles (parallel={args.parallel}) ...",
          file=sys.stderr)
    top_profiles: dict = {}
    with ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futs = {ex.submit(resolve_top_profile, args.host, args.app_id,
                          sid, s.get("modules_tree") or {}): sid
                for sid, s in multi}
        for fut in as_completed(futs):
            prof = fut.result()
            if prof:
                top_profiles[futs[fut]] = prof

    ships = {}
    by_zh, by_en, aliases = {}, {}, {}
    miss_name = skipped = 0
    for sid_str, w in wg_ships.items():
        sid = int(sid_str)
        gpe = gp_ships.get(sid)
        if not gpe or not gpe.get("index"):
            skipped += 1
            continue
        index = gpe["index"]
        species = gpe["species"]
        nation = gpe["nation"]

        name_zh = tr.get(f"IDS_{index}")
        if not name_zh:
            miss_name += 1
            name_zh = clean_ship_name(w.get("name") or index)
        name_en = w.get("name") or clean_ship_name(index)

        profile = top_profiles.get(sid_str) or w.get("default_profile") or {}
        stats = extract_stats(profile)

        # 消耗品 → 中文 (每个 slot 内多个 = 二选一);带装填数 charges
        consumables = []
        for slot in gpe.get("consumables") or []:
            alts = []
            seen = set()
            for a in slot:
                zh = consumable_zh(a["ability"], tr)
                if zh in seen:
                    continue
                seen.add(zh)
                alts.append({"name": zh, "charges": a.get("charges"),
                             "work_s": a.get("work_s"), "reload_s": a.get("reload_s"),
                             "prep_s": a.get("prep_s"), "range_km": a.get("range_km"),
                             "range_torp_km": a.get("range_torp_km")})
            if alts:
                consumables.append(alts)

        ships[sid_str] = {
            "index": index,
            "name_zh": name_zh,
            "name_en": name_en,
            "tier": w.get("tier") or gpe.get("level"),
            "species": species,
            "species_zh": SPECIES_ZH.get(species, species),
            "nation": nation,
            "nation_zh": NATION_ZH.get(nation, nation),
            "icon": index,
            "consumables": consumables,
            # 科技树(/线)用:next_ships={下一艘sid: 研发xp},研发关系沿此走
            "next_ships": {str(k): int(v) for k, v in (w.get("next_ships") or {}).items()},
            "is_premium": bool(w.get("is_premium")),
            "is_special": bool(w.get("is_special")),
            "price_credit": int(w.get("price_credit") or 0),  # 购买银币价
            # /穿透 用:AP 弹道+穿深参数(GameParams,无 AP 主炮的船=None)
            "ap_ballistic": gpe.get("ap_ballistic"),
            **stats,
        }

        # 搜索索引
        by_zh[name_zh] = sid_str
        if name_en:
            by_en[name_en.lower()] = sid_str
        wg_zh = aliases_raw.get(sid_str)
        if wg_zh and wg_zh != name_zh:
            aliases[wg_zh] = sid_str

    info = wg_get(args.host, args.app_id, "/wows/encyclopedia/info/")
    out = {
        "version": (info.get("data") or {}).get("game_version", "?"),
        "ships": ships,
        "search_index": {"by_zh": by_zh, "by_en": by_en, "aliases": aliases},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    print(
        f"  wrote {args.out} ({args.out.stat().st_size / 1024:.0f} KB): "
        f"{len(ships)} ships, {len(aliases)} aliases | "
        f"skipped {skipped} (no GameParams match) | name fallback {miss_name}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
