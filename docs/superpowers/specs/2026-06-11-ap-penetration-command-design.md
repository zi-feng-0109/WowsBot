# `/穿透 <我船> <敌船> [距离 km] [角度°]` AP 穿深判定 — 实现设计

> 状态:**设计待实现**(2026-06-11)。完全可在 mac 实现,不依赖 Win 客户端。
> 数据全在本地 GameParams + 已有 armor.json,公式来自 wows-toolkit `docs/BALLISTICS.md`
> 和社区项目 [jcw780/wows_shell](https://github.com/jcw780/wows_shell)。

## 1. 目标

新命令 `/穿透 大和 蒙大拿` → 返回一张 PNG 卡:**大和 AP 在 5–25 km 各距离对蒙大拿
各装甲分面**(舷侧带 / 甲板 / 核心区 / 上层 / 炮塔)的判定结果(穿透 / 过穿 /
未穿 / 弹开),含建议交战距离区间。

可选参数:`[距离 km]`(锁定单距离详查)、`[角度°]`(目标船相对炮口的航向角,默认 30°
半角=典型对舷)。

## 2. 数据来源(全部本地,免外部 API)

### 2.1 已有
- **`report/data/armor.json`** —— 目标船分面厚度(`hull[zone][].mm` + `turrets[].faces[].mm`),
  我们已经在用,渲染 `/船 装甲` 表的同一份。

### 2.2 待补:主炮 AP 弹种参数(GameParams Projectile)
build_ships_json 现在抽了 artillery 的射程/装填/单发伤害,但**漏了穿深公式要的参数**。
GameParams 里每艘船的主炮 AP 弹有(实测大和 PJSA419 类似条目):
```
bulletKrupp            克虏伯系数(穿深核心)
bulletMass             质量 kg
bulletDiametr          口径 m
bulletAirDrag          空气阻力系数
bulletSpeed            初速 m/s
bulletRicochetAt       主跳弹角度(>此角跳弹概率↑)
bulletAlwaysRicochetAt 绝对跳弹角度(>此角必跳)
bulletCapNormalizeMaxAngle  法线化最大角(弹芯让冲击角更"正")
bulletDetonatorThreshold    引信触发厚度(<此厚度=过穿)
alphaDamage            单发 AP 伤害
```
**新增动作**:`build_ships_json.py` 抽 Ship 的 `A_Artillery` → 取 AP `ammoType` 那个
Projectile,把上面这些字段烤进 ships.json 的 `artillery.ap_ballistic = {...}`。
HE/SAP 同理可选(SAP 也吃跳弹/法线化)。重建 ships.json 一次。

## 3. 弹道 + 穿深算法(纯 Python,~150 行)

### 3.1 弹道(ISA 大气 + 阻力,沿用 wows_shell / ap_pen.py)
给定 (m, d, drag, v0, α₀ 仰角) → 数值积分(forward Euler,dt=0.1s):
```
ρ(h) = 国际标准大气密度
drag_const = 0.5 * drag * (d/2)² * π / m
cw_lin = 100 + 1000/3 * d   # 经验线性阻力修正(来自社区拟合)
loop:  v_x -= dt * drag_const * ρ * (v_x² + cw_lin*v_x)
       v_y -= dt * G - dt * drag_const * ρ * (v_y² + cw_lin*|v_y|)*sign(v_y)
       直到 y < 0 (落地)
→ 落点 x(距离), v_total(撞击速度), impact_angle(落角)
```
对仰角 α₀ 扫一遍(0° → 15°,步 0.1°),得到 **(距离 → 落速, 落角)** 表。

### 3.2 穿深(wows_shell 经验拟合,跟 BALLISTICS.md §7.3 一致)
```
p_ppc = 1e-7 * krupp * mass^0.69 * caliber^(-1.07)
raw_pen = p_ppc * v_impact^1.38
```
落点处的"裸"穿深(mm,法向)。

### 3.3 装甲交互(BALLISTICS.md §8)
对每块装甲板 (厚度 T_mm),给定**总碰撞角**(落角 + 目标航向角 + 板自身倾角 — 简化:
按几何分面预设倾角,如 belt=垂直 / deck=水平 / 上层=垂直):
```
α = 综合冲击角(0° = 法向, 90° = 切向)
# 法线化:cap 让冲击角变"正",但有上限
α_eff = max(0, α - cap_normalize * min(1, 14.3 * d / T_mm))
# 跳弹判定 (硬阈值)
if α_eff >= alwaysRicochetAt: 结果 = 弹开
elif α_eff >= ricochetAt:     结果 = 概率跳弹(0..1 线性),按 50% 算
# 实际穿深 (cos 法向投影)
pen_effective = raw_pen * cos(α_eff)
# 厚度判定
if pen_effective < T_mm:                     未穿
elif pen_effective < detonatorThreshold:     穿但不引信(罕见)
elif T_mm < detonatorThreshold:              过穿 (over-penetration, 1/3 伤害)
else:                                        穿透 + 引信触发 (full 伤害)
```

### 3.4 一次查询输出
对每块板,扫 5/10/15/20/25 km(可选更密),给:
- 该距离落速/落角
- 综合冲击角(含法线化)
- 实际穿深 mm vs 该板厚度
- 判定:**穿透 / 过穿 / 未穿 / 弹开**(分别 ✓/△/✗/⤴)
- 实际伤害(full / 1/3 / 0)

## 4. 渲染(`report/bin/render_pen.py`,新建)

复用 `render_ship` / `render_query` 调色板和 helper。布局:

- **Header**:`我船 vs 敌船` + 国家·舰种·tier
- **距离 × 装甲板 矩阵表**:列=距离(5/10/15/20/25 km),行=敌方关键装甲板
  (核心区装甲带 / 核心区甲板 / 上层建筑侧 / 舰艏 / 炮郭...,**只挑玩家关心的~8 块**),
  每格用色块 + 图标表示判定(绿✓穿透 / 黄△过穿 / 红✗未穿 / 灰⤴弹开)
- **底部小结**:"建议交战距离 8–14 km(可穿核心区舷侧)" / "甲板始终未穿,避免远距离"
- **可选 `[距离 km]` 参数**:返回该单距离的**详细数值表**(每板厚度、综合角、有效穿、判定、伤害)

## 5. 命令解析(`plugin/minimap.py`)

`on_command("穿透", aliases={"穿深","pen"})`,handler 类似 `/对比`:
- 两个船名 → `ship_index.find()` 各自解析(沿用现有模糊/消歧)
- 可选第三参数距离、第四参数角度
- 异常船(无 AP 主炮,如纯鱼雷潜艇)→ 友好文案
- `to_thread` 调 `render_pen.render_pen_png` → `MessageSegment.image`

## 6. 文件清单

新增:
- `report/bin/calc_penetration.py` — 算法核心(弹道 + 穿深 + 装甲交互,纯函数,可独立 import / CLI 测)
- `report/bin/render_pen.py` — 卡片渲染(库 + CLI)
- 改 `plugin/minimap.py` — `/穿透` handler

改:
- `tools/build_ships_json.py` — Ship→A_Artillery→取 AP Projectile,
  烤 `bullet*` 字段进 `ships[id].artillery.ap_ballistic`。重建 ships.json 一次。
- `report/bin/render_menu.py` — 菜单 +1 行
- `docs/UPDATE.md` / `docs/DEPLOY.md` — 不用大改(数据搭 build_ships_json 自动出)

## 7. 风险 & 边界

- **公式社区拟合,非客户端权威**:BALLISTICS.md §7 明确"穿深计算服务端 only,
  客户端没有"。我们用 wows_shell 同款拟合,跟游戏内**非常接近但非 100% 一致**。
  卡片底部加小字"基于社区拟合公式,误差 ±3%"。
- **装甲倾角简化**:我们 armor.json 只有厚度,没有每块板的几何法向。MVP 用预设倾角
  (belt=0°舷侧、deck=90°水平、bow_trans=斜横…),已足够判定大方向;真精确得加倾角数据
  (要从 .geometry 拿,跟装甲 3D 一样要 Win)。
- **法线化和跳弹**:GameParams 给的 `bulletCapNormalizeMaxAngle` / `bulletRicochetAt` 直接用,
  这部分可信度高(参数本身就在客户端)。
- **CV/潜艇**:无主炮 → 友好提示"该船无 AP 主炮";潜艇深弹/鱼雷不在本命令范畴。
- **超口径(overmatch)**:当弹径 ≥ 14.3 × 板厚,装甲完全失效(直穿不跳)。要单独判定。
- **概率跳弹区间**:`bulletRicochetAt` 到 `bulletAlwaysRicochetAt` 之间是概率跳弹,
  实际游戏内是 0→100% 线性。MVP 显示"跳弹概率 N%"或简化按 50% 当弹开,二期可加。

## 8. 验证步骤

1. 算法 CLI:`python report/bin/calc_penetration.py --shell Yamato_AP --target 大和 --range 15 --angle 30`
   对照 wows_ballistics 在线计算器(jcw780.github.io)同条件结果,误差应 <5%。
2. 经典对照点:大和 AP @ 10km 打蒙大拿核心区舷侧应**穿透+引信**;@ 20km 打甲板应**未穿**;
   @ 20km 直角打 19mm 上层应**过穿**。
3. bot 联调:`/穿透 大和 蒙大拿`、`/穿透 大和 蒙大拿 15`、`/穿透 巴劳鱵 大和`(潜艇无 AP→提示)、
   `/穿透 大和`(缺参→用法)。
4. `/菜单` 新行不错位。

## 附:参考资料

- wows-toolkit `docs/BALLISTICS.md` §7-§8(公式来源)
- [jcw780/wows_shell](https://github.com/jcw780/wows_shell)(C++ 参考实现)
- [jcw780.github.io/wows_ballistics](https://jcw780.github.io/wows_ballistics/)(在线计算器,做对照)
- [wowsinfo/WoWs-Game-Data/ap_pen.py](https://github.com/wowsinfo/WoWs-Game-Data/blob/master/ap_pen.py)(纯 Python 简版,已下载分析过)
