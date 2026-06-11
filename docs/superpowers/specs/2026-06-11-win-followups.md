# 换 Win 设备后要做的事(2026-06-11 打包)

> 本档把今天讨论后**已上线**和**留给 Win 做**的事归到一起。
> 三个相关 spec 仍在,可看细节:
> - `2026-06-11-ship-armor-card-design.md`(`/船 装甲` 已上线)
> - `2026-06-11-armor-3d-model-design.md`(装甲 3D 图)
> - `2026-06-11-ap-penetration-command-design.md`(`/穿透` v1 已上线为 `/装甲分析`)

---

## 1. 现状(mac 上已完成,可直接部署)

### 1.1 `/装甲分析 <船名>`(别名 穿深/穿透/防御分析)— **已上线**
- 5 块代表板 × (距离×角度) 矩阵,每格写"≥X mm 主流战列弹可击穿/碾压"
- 算法 = wows-toolkit `BALLISTICS.md` + jcw780/wows_shell 公式;弹道 ISA 大气 + Euler 积分;穿深 raw_pen = ppc·v^1.38;装甲交互覆盖 法线化 / 跳弹 / 碾压(14.3×板厚)/ 引信 / 过穿 / 击穿 / 核心区,伤害系数按 WoWs 真实给(核心区满 / 击穿 1/3 / 过穿 1/10)
- 文件:`report/bin/calc_penetration.py` + `report/bin/render_pen.py` + `tools/build_ships_json.py`(抽 AP 弹道参数 ap_ballistic)
- 命令在 `plugin/minimap.py`,菜单已加一行

### 1.2 装甲 3D 渲染管线第②段 — **已实现并验证**
- `tools/render_armor_3d.py` 纯 numpy 软件光栅器(zero GPU/Blender/显示),mac 上跑通
- 顶点色路径已验证(假厚度色阶能渲蓝薄→红厚)
- 真实装甲色 GLB 来源(wowsunpack)= 本档 §2.2

---

## 2. 留给 Win 设备做的事(按优先级)

### 2.1 `/装甲分析` 三个细化(已识别的 v1 缺陷)

**(a) 水平甲板也要按口径分列** — 当前致命缺陷
- 现在水平甲板只画一列(用所有口径中位的"典型弹"算落角),把高弹道炮 vs 低伸炮的差异**完全压平**
- 实际战术差异巨大:25km 152mm 巡洋炮高弹道落角大,反而能砸 BB 甲板;460mm 大和低伸落角小,砸不进
- 修法:**所有板统一改成 (距离 × 口径) 双轴矩阵**,每板按各自有意义的角度预设(舷侧 30°/上层 0°/甲板 0°/船头 0°)。详 §2.1 备选 C(讨论时定方案)
- 工作量小,但要重画矩阵和 legend

**(b) 板倾角真实化** — 中等
- 现在用预设倾角(舷侧 0° / 甲板 90° / 斜板 30°),实际每艘船每块板的倾角不同
- 真实倾角在 `.geometry` 装甲网格里(每个三角面有真法向)— wows-toolkit `gltf_export` 已经能拿
- 这步做完后,装甲分析能精确到"蒙大拿 主装实际带 5° 内倾,所以舷侧穿透阈值偏移"

**(c) 舰种过滤** — 小
- 航母 / 潜艇不该出"装甲分析"卡(没主炮塔、没核心区主装,矩阵一半是"无"),改成 handler 友好提示
- 这步在 mac 也能做,但建议跟 (a)(b) 一起改

### 2.2 装甲 3D 模型图(GLB + 多视角 PNG + 转圈 GIF)

完整 spec:`2026-06-11-armor-3d-model-design.md`

**仅缺第①段(wowsunpack 导色彩 GLB)** — 必须 Win 客户端:
- 给 `wowsunpack` 加 `export-armor-glb --ship <index> -o <index>.glb` 子命令
- 复用现成的 `wowsunpack::export::gltf_export`(已有 `thickness_to_color` / `armor_color_legend` / `InteractiveArmorMesh`)
- 把厚度色烤进顶点色 GLB

**②(GLB→图片) 已就绪**(`tools/render_armor_3d.py`),拿到 GLB 直接 `python render_armor_3d.py 大和.glb out/PJSB018`

**③ 部署链**(spec §3 已写):rsync 到 `/var/lib/wows-data/armor_models/`,bot `WOWS_ARMOR_DIR` 找图优雅降级,**产物不进 git**(同 extracted 数据模式)

成本:全量~960 船一次性渲(纯 Python 光栅每船 ~70s × 960 ≈ 18 小时,可挂夜里;若有 Blender + GPU 可数小时)。之后每版本只渲新增船(增量 skip)。

### 2.3 之前积压的项目(早就记在 [[ship-info-data-sources]] 项目记忆)

**(d) 航母舰载机数据**:火箭/炸弹/鱼雷单发伤害、中队数、出击架数。WG API 自 2019 航母重做后这些字段全 null,只能啃本地 GameParams 的中队机制(船 `A_AirArmament` + `plane_refs`)。本地 mac 这份数据缺。

**(e) 作战指令(RageMode)**:射水鱼 / 自由(Libertad)等船的蓄力指令。mac 本地 GameParams(15.4.0)里这两艘连一个 `rage` 相关 key 都没有(扫遍全树 0)— 要么本地数据旧、要么内部名不带 rage,必须 Win 上重新 dump GameParams 再定位。

---

## 3. 换 Win 后建议顺序

1. **拉最新游戏客户端 + dump 一份新 GameParams**,先看作战指令/航母舰载机的真实字段(顺手就能定位)
2. **`/装甲分析` v2**:水平甲板按口径分列、舰种过滤、(可选)真实倾角
3. **装甲 3D 模型图**:wowsunpack 加 `export-armor-glb` → 批量跑 `render_armor_3d.py` → rsync
4. **航母舰载机** + **作战指令**(都是给 `/船` 卡补一块)

---

## 4. 跟我留的钩子

- `tools/build_ships_json.py` 现在已经会抽 ap_ballistic,Win 上 dump 新 GameParams 后跑一次即可同步新船弹道
- `report/bin/render_pen.py` 的 `_KEY_PLATES` 是可配置列表,加新板/换轴只改这表
- `tools/render_armor_3d.py` 的 `_view_mats()` / `_label()` 是模块函数,加色阶图例/换字体只改对应函数

照这份从上往下做即可。
