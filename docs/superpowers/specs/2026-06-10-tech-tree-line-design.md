# `/线 [国家] [舰种]` 科技树等级线 — 实现设计

> 状态:**设计待实现**(2026-06-10)。数据已验证可得,不需要 Win 客户端。
> 作者换设备后照此实现。先读 [[ship_info_data_sources]](项目记忆)。

## 1. 目标

新命令 `/线 日本 战列舰` → 返回该国该舰种**整条科技树**的 PNG(T1→T11 各舰
缩略图 + 研发 XP),分叉线一起画出来。视觉复用 `/船` / `/查询` 那套调色板。

`/船` 是查单船数值;`/线` 是查"这条线怎么爬、有哪些船、研发要多少经验"。

## 2. 数据来源(已实测,**无需 Win 客户端**)

跟 `/船` 同一个 WG public API encyclopedia,我们 build 脚本已经在拉:

- 每船 `next_ships = {下一艘 ship_id: 研发XP}` —— 沿着走就是科技线。973 船里 349 艘有(科技树船);金币/特种/线尾 T10/T11 没有。
- 配 `tier` + `nation` + `type` + `is_premium`/`is_special` + `price_xp`(研发经验)+ `price_credit`(银币价)。
- **注意:WG API 的 `nation` 是小写**(`usa`/`japan`/`ussr`/`germany`/`uk`/`france`/`italy`/`pan_asia`/`europe`/`netherlands`/`pan_america`/`commonwealth`/`spain`),`type` 首字母大写(`Battleship`/`Cruiser`/`Destroyer`/`AirCarrier`/`Submarine`)。但运行时 `/线` 只读本地 `ships.json`(nation 已存成首字母大写 `Japan`...),不直接打 API,所以大小写在 build 时统一即可。

**线的真实结构(实测 15.4.0):**
- **每个 (国家, 舰种) 只有一个根**(无多根)。所谓"两条战列线/巡洋线"是**从根在某 tier 分叉**出来的,不是两个独立起点。
- 分叉点举例(`next_ships` 同国同舰种 >1):
  - usa Battleship 科罗拉多(T7) → 堪萨斯 / 内布拉斯加 / 北卡罗来纳(**三叉**)
  - japan Battleship 鲨(T7) → 鳐 / 鲶;germany Battleship 拿骚(T3) → 凯撒 / 冯·德·坦恩
  - usa Cruiser 奥马哈(T5) → 达拉斯 / 彭萨科拉;ussr Cruiser 肖尔斯(T7) → 塔林 / 恰巴耶夫
  - usa AirCarrier 突击者(T6) → 列克星敦(T8) / 独立(T6)  ← 注意 CV 有跨 tier 跳级
- 所以一条 (国家,舰种) 是**一棵树**:根唯一,中途分叉。"各条线" = 枚举所有"根→叶"最长路径(前段共享)。

## 3. 数据层改动:把 next_ships 烤进 ships.json

运行时零外部 API,所以 `tools/build_ships_json.py` 要把树数据存进 `ships.json`:

每船的 `ship` dict 增加:
```jsonc
"next_ships": {"<ship_id>": <研发xp>, ...},   // 空则不加 / 存 {}
"price_xp": <int>,        // 研发本舰所需经验 (根/金币船为 0)
"price_credit": <int>,    // 银币价
"is_premium": bool, "is_special": bool
```
- WG API list 接口 `fields` 里直接加 `next_ships,price_xp,price_credit,is_premium,is_special`(分页那次一并拉,不额外加请求)。
- ship_id 用字符串 key,跟现有 `ships` 字典 key 一致,`/线` 直接图遍历。

## 4. 线重建算法(纯本地,从 ships.json)

```
给定 nation(中文→大写 code)、type(中文→code):
1. 候选 = {sid: s for s in ships if s.nation==nation and s.type==type and not s.is_premium and not s.is_special}
   (金币/特种船不进科技树图)
2. 在候选内建边:sid → [j for j in s.next_ships if j in 候选]
   (只保留同国同舰种的后继;跨舰种的 next 罕见但要过滤)
3. 找根:候选里 入度==0 的(没被任何候选指向)。正常唯一;若 0 个(全是孤立金币)→ 回错误文案。
4. 从根 DFS 枚举所有最长路径 = 各条线;分叉点产生多条,前缀共享。
   也可直接保留"树"结构(节点带 tier 当 x、分支当 y)给渲染用。
```
注意:`next_ships` 偶有跨 tier(CV 突击者 T6→列克星敦 T8),所以**别假设 tier 连续递增 +1**,按边走、按 tier 定 x 坐标。

## 5. 命令解析(`plugin/minimap.py`,照 `/船` handler)

`on_command("线", aliases={"线路","科技树","tree"})`,参数两个:国家 + 舰种。

- 国家中文→code 表(用 `build_ships_json.NATION_ZH` 的反查,大小写跟 ships.json 一致):
  日本→Japan、美国→USA、苏联→Ussr、德国→Germany、英国→Uk、法国→France、
  意大利→Italy、泛亚→Pan_Asia、欧洲→Europe、荷兰→Netherlands、泛美→Pan_America、
  英联邦→Commonwealth、西班牙→Spain。别名:美→USA、日→Japan、德→Germany、苏→Ussr…
- 舰种中文→code:战列舰/战列/BB→Battleship、巡洋舰/巡洋/CA/CL→Cruiser、
  驱逐舰/驱逐/DD→Destroyer、航母/CV→AirCarrier、潜艇/SS→Submarine。
- 参数缺失/无法识别 → 用法提示 + 可选国家/舰种列表。
- 该 (国家,舰种) 没有科技线(如某些国家没航母)→ 友好文案。

复用 `ship_index`(已 load ships.json);可在 `ship_index.py` 加一个
`lines(nation, type) -> tree/paths` 帮手,或新建 `plugin/tech_tree.py`。

## 6. 渲染设计(`report/bin/render_line.py`,新建,库+CLI)

复用 `render_ship`/`render_query` 的 `_font`/`_load_icon`/`_draw_footer`/调色板/
`W=1100`(树宽可能要超过 1100,见下)/船图标 `ship_icons/<index>.png`。

**布局:tier 当横轴,分支当纵轴的科技树图。**
- x:按 tier 排列(T1…T11),每 tier 一列,列宽固定(~95px)。注意跨 tier 跳级要留空位。
- y:每条分支一行;分叉前共享的船画在同一行,分叉后新分支另起行,用连接线(折线)从父船连到子船。
- 每个节点:小船图(`ship_icons`,缩到 ~64px 宽)+ 名字 + `T{tier}` + 研发 `xp`(根/免费船标"初始")。
- 连接线:父 → 子 画浅色折线(`GAME_BORDER`),分叉处一对多。
- 图高 = 行数 × 行高;图宽 = max_tier 列数 × 列宽(**可能 >1100,W 要动态算**,不像 /船 固定 1100)。

**MVP 简化(若树渲染太麻烦,先做这个):** 每条"根→叶"最长路径渲成**一行**(横向
T1→T11 船图 + xp),多条路径多行,共享前缀重复出现。简单、可读;以后再升级成
合并前缀的真·树。文档建议先 MVP 跑通,再迭代树连线。

## 7. 文件清单

- 改 `tools/build_ships_json.py`:fields 加 next_ships/price_xp/price_credit/is_premium/is_special,写进每船 dict。重跑 ships.json(UPDATE.md §2.6 那步,~4 分钟)。
- 新 `plugin/tech_tree.py`(或 `ship_index.py` 加帮手):`build_lines(nation, type)` 重建树/路径。
- 新 `report/bin/render_line.py`:库 `render_line_png(out, nation, type, lines)` + CLI。
- 改 `plugin/minimap.py`:`on_command("线")` handler(解析→重建→to_thread 渲染→发图→错误文案)。
- 改 `report/bin/render_menu.py`:【全部指令】加 `("/线 <国家> <舰种>", "查整条科技树线", "任何人")`,该 section 行数 +1。
- 文档:UPDATE.md 不用改(数据搭 §2.6 build_ships_json 一并出);DEPLOY.md 插件文件清单若新增 tech_tree.py 记得 +1。

## 8. 边界 & 验证

- 分叉(2~3 叉)必须都画出;跨 tier 跳级(CV)别假设 +1。
- 金币/特种船不进线(`is_premium`/`is_special` 过滤);它们没 next_ships 本来也连不进。
- 超级船 T11(如杰克逊维尔)是线尾,要画进去。
- nation/type 未识别、该组合无线 → 友好兜底,不崩。
- 验证:
  1. 重建 `美国 巡洋舰` 应得 伊利湖→…→伍斯特→杰克逊维尔(T1→T11)主干 + 奥马哈(T5)分叉出 彭萨科拉…(重炮线)。
  2. `美国 战列舰` 科罗拉多(T7) 后三叉(堪萨斯/内布拉斯加/北卡罗来纳)都在。
  3. `德国 战列舰`、`苏联 驱逐舰` 各自的分叉正确。
  4. CLI 出图肉眼看分支连线没错位;`/线 美国 巡洋舰`、`/线 美`(缺舰种→提示)、`/线 法国 潜艇`(无→友好文案)。
  5. `/菜单` 新行不错位。

## 附:本设计验证时用的探测要点(实测 15.4.0,Asia host,app_id ESSEXBOT)

- `GET /wows/encyclopedia/ships/?fields=name,tier,type,nation,next_ships,price_xp,is_premium,is_special&language=zh-cn&page_no=N&limit=100`,10 页拿全 973 船。
- 349 艘有非空 next_ships;每 (nation,type) 单根;分叉点见 §2。
- nation 小写、type 大写;运行时只读 ships.json 故 build 时统一成大写 code 即可。
