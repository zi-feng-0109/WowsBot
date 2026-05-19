# specs/

每个游戏大版本一份的数据 —— **不入 git**。

第一次跑前需要先填这个目录。两种方式：

## A. 从 wowsinfo/data 镜像拉（最简单）

```bash
cd ..   # 回到仓库根目录
python tools/update_specs.py
# 输出到 specs_out/；把内容挪到 specs/：
rm -rf specs/scripts specs/content specs/metadata.toml
mv specs_out/* specs/
rmdir specs_out
```

## B. 从本地 WoWs 安装提取（Win，最新鲜）

详见仓库根目录的 `UPDATE.md`。

## 预期目录结构

```
specs/
├── metadata.toml          # version = "15.3.0"   build = 12267945
├── scripts/               # entity 定义 XML（~500 KB）
│   ├── entities.xml
│   ├── components.xml
│   └── entity_defs/
└── content/
    └── GameParams.data    # 游戏参数字典（~15 MB）
```

填好之后 `bin/wows_report 某回放.wowsreplay` 就能跑通。
