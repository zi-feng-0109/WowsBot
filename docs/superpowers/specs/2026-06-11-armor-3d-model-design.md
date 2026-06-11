# `/船 <名>` 装甲 3D 模型图(多视角 PNG + 转圈 GIF)— 实现设计

> 状态:**设计待实现**(2026-06-11)。需有 GPU/能跑 Blender 的离线机器(Win 优先)。
> 先读 [[ship_info_data_sources]](项目记忆)。这是 `/船 装甲` 文字表的 3D 可视化升级。

## 1. 目标

`/船 <名>` 现在发 [数值卡 + 分面装甲表]。再追发一张**装甲 3D 图**:战舰模型按
装甲厚度上色(像 wows-toolkit 的装甲查看器),给两种产物:
- **多视角静态 PNG**:舷侧 / 俯视 / 正面 / ¾ 透视 四格 + 厚度色阶图例
- **稍慢速转圈 GIF**:360° turntable,观感接近 wows-toolkit

两者**全量覆盖**所有船。

## 2. 关键发现:最硬的部分 wowsunpack 已经做好

`wows-toolkit` 的 `wowsunpack::export::gltf_export` 模块已有:
- `.geometry` 网格解析 + 装甲模型(逐面厚度)
- `thickness_to_color` / `armor_color_legend`(厚度→颜色映射 + 图例)
- `InteractiveArmorMesh` / `export_glb`(GUI"导出模型"就是把厚度色烤进 GLB)

所以**装甲上色 + 导 GLB 这条最难的链不用自己写**。新写的只有两小块:① 给
wowsunpack 加个 headless 导出子命令;② GLB→图片的离线渲染脚本。

## 3. 架构:离线渲染 → 产物传服务器(不进 git)

跟游戏 `extracted/` 数据同模式(scp 到 `/var/lib/wows-data/`、不进仓库)。
**服务器不渲染**,只发离线渲好的图。

```
[离线机 Win/GPU]                          [Linux 服务器]
wowsunpack export-armor-glb  →  <idx>.glb
        ↓ (Blender headless)
  <idx>.png (多视角) + <idx>.gif (转圈)   ──rsync──►  /var/lib/wows-data/armor_models/
                                                          ↓
                                              bot /船 <名> 有图就追发,没图跳过
```

### 3.1 导色彩 GLB(wowsunpack 新增 headless 子命令)
- `wowsunpack export-armor-glb --extracted <specs> --ship <index> -o <index>.glb`
- 复用 `gltf_export`:导出战舰外壳 + 装甲网格,**厚度色烤进顶点色**。积木都在库里,工作量小。

### 3.2 GLB → 图片 —— **已实现并验证:`tools/render_armor_3d.py`(纯 numpy 软件渲染)**
2026-06-11 在 mac 上跑通(无 GPU/无 Blender/无显示):自带 numpy z-buffer 光栅器 +
朗伯着色 + 顶点色支持,`trimesh` 读 GLB。出 4 视角(舷侧/俯视/正面/立体)2×2 合成 PNG
+ 绕竖轴转圈 GIF。**顶点色路径已验证**:喂带"厚度色"的网格能正确出 蓝薄→红厚 渐变
(真实装甲 GLB 把厚度烤进顶点色,直接出彩;无色模型退默认钢灰)。
```
python tools/render_armor_3d.py <in.glb> <out_prefix> [--size 520] [--frames 36] [--no-gif]
```
- **优点**:零依赖(numpy+Pillow+trimesh),mac/Linux 服务器都能跑,不用 Blender/GPU。
- **代价**:纯 Python 光栅慢(~12 万面、4 视角 +24 帧 ≈ 70s/船)。全量 ~960 船一次性
  约十几小时;增量(每版本几艘新船)无所谓。嫌慢可换 Blender(GPU,快很多)出图,
  但产物格式/管线不变。
- **待补**:① 厚度色阶图例条(复用 wowsunpack `armor_color_legend` 的 mm→色);
  ② 加 `--skip-existing`(增量,同 fetch_ship_icons)+ `--force <index>`;
  ③ 套 /船 卡 header(T10 大和…)统一风格(可选)。
- 真实装甲 GLB 由 §3.1 的 wowsunpack `export-armor-glb` 提供(顶点色已烤厚度)。

### 3.3 一次性 vs 增量(成本)
- **一次性全量**:~960 船 × (多视角 PNG + 36 帧 GIF),Blender 跑一遍是唯一大头(几小时)。
- **以后每版本**:WG 基本不动现有船装甲 → 只渲**新增的几艘**(增量 skip 已存在的),近乎零成本。
- PNG ~140MB / GIF 几个 GB,都在服务器磁盘(不进 git),rsync 一次。

## 4. bot 集成(`plugin/minimap.py`)

- 新 env:`WOWS_ARMOR_DIR`(默认 `/var/lib/wows-data/armor_models`)。
- `/船 <名>` 现有流程末尾:查 `<index>.png`、`<index>.gif` 是否存在 → 有则
  `MessageSegment.image(file://...)` 追发(GIF 也走 image 段,QQ 支持动图);**缺则静默跳过**,
  数值卡 + 装甲表照常。零外部依赖、零运行时渲染。
- 可选:`/船 <名> 模型` 只发 3D 图(不发数值/表),省流量;或默认都发,看你定。

## 5. 文件清单

- `wows-toolkit`(上游 fork):`wowsunpack` 加 `export-armor-glb` 子命令(复用 gltf_export)。
- `tools/render_armor_3d.py`(或 Blender 脚本):GLB → 多视角 PNG + 转圈 GIF,增量 + `--force`。
- `tools/batch_armor_3d.sh`(可选):遍历 ships.json 的 index,导 GLB + 渲图,rsync。
- 改 `plugin/minimap.py`:`WOWS_ARMOR_DIR` + `/船` 追发图逻辑(优雅降级)。
- `docs/UPDATE.md`:加一步"渲新增船装甲 3D 图 + rsync 到服务器"(挂在 §2.6 后)。
- `docs/DEPLOY.md`:`WOWS_ARMOR_DIR` 路径说明 + armor_models 目录约定。

## 6. 取舍 / 待定

- **Blender vs pyrender**:先 Blender 跑通(离线一次性,质量优先);嫌重再换 pyrender。
- **GIF 参数**:帧数(24~36)、分辨率(~600×400)、转速(慢,一圈 ~4–6s)、循环;权衡体积。
- **配色**:直接用 `armor_color_legend` 的色阶,保证跟 wows-toolkit 一致、玩家认得。
- **是否服务器按需渲染**:本设计不做(离线渲完传)。以后若服务器有富余 CPU 可上 osMesa
  软件渲染做按需+缓存,免全量预渲——但当前"离线渲完 rsync"更简单可控。

## 7. 验证

1. wowsunpack 导大和 `PJSB018.glb`,Blender 打开看装甲色对不对(跟 wows-toolkit 比)。
2. 渲染脚本出 `PJSB018.png`(四视角 + 图例)+ `PJSB018.gif`(转圈)肉眼看。
3. 增量:再跑一次应全 skip;`--force PJSB018` 应只重渲大和。
4. bot:`WOWS_ARMOR_DIR` 指向测试目录,`/船 大和` 应在数值卡+装甲表后追发 PNG+GIF;
   删掉图再 `/船 大和` 应优雅跳过、不报错。
5. rsync 后服务器 `ls armor_models/ | wc -l` ≈ 渲染数。

## 附:实现要点

- ship index ↔ GLB 文件名用 `<index>`(如 PJSB018),跟 ships.json `icon`/`index` 一致。
- 服务器无 GPU 也行:Blender 可 CPU 渲(慢但离线无所谓);bot 端完全不碰 3D。
- 极少数 reworked 船(装甲真变了)→ `--force <index>` 重渲并 rsync 覆盖。
