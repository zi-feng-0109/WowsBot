"""所有路径/开关的唯一声明表。

为什么需要它:重构前 78 处 os.environ.get 散在 12 个文件里,而且 `BOT_HOME` 这个
名字在两处含义不同 —— report/bin/* 里指 `report/`,tools/* 里指仓库根。同名不同义
直接造成 tools/build_builds_json.py 的 --specs / --replayshark 默认值少一层
`report/`(同文件的 DEFAULT_MO / DEFAULT_OUT 又是对的),所以刷 builds.json 每次
都得手动带参数。这里改用两个不会混淆的名字:REPO_ROOT / REPORT_ROOT。

约束:只放常量与纯派生。不 import nonebot、不 subprocess、不碰 PIL —— 三类
consumer(nonebot 环境的 plugin/*、venv 环境的 report/bin/*、将来 P1 的网站)
都要能 import 同一份。

兼容:env 变量名与重构前完全一致(含已弃用的 WOWS_REPORT_CMD),部署不需改 .env。
一律用 os.environ.get(name, default) —— 不要写成 `get(name) or default`,后者在
env 被设为空串时行为不同。
"""
import os
from pathlib import Path

# ---------- 根 ----------
# 默认从本文件自身位置推导:<repo>/report/lib/wowsbot/paths.py -> parents[3] = <repo>。
# 这样服务器上自然是 /opt/wows-bot,开发机上是本地 checkout —— 否则硬编码
# /opt/wows-bot 会让开发机找不到 data/ 下的 zh_sg.mo、constants.json,
# 而 Task 0 的基线与后续 sha256 比对全靠开发机渲染。
# WOWS_BOT_HOME 仍可覆盖(plugin/* 被 cp 到别处时用它 bootstrap 找到本目录)。
_SELF_REPO = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("WOWS_BOT_HOME", str(_SELF_REPO)))
REPORT_ROOT = REPO_ROOT / "report"      # 旧代码里 report/bin/* 的 "BOT_HOME"
BIN_DIR = REPORT_ROOT / "bin"
DATA_DIR = REPORT_ROOT / "data"
# 注意:没有 LIB_DIR —— bootstrap 要在 import paths 之前就把 lib 加进 sys.path,
# 存在鸡生蛋问题,所以各 consumer 自己拼这段路径,这里声明了也没人能用。

# ---------- 二进制 ----------
REPLAYSHARK = os.environ.get("WOWS_REPLAYSHARK", str(REPORT_ROOT / "replayshark"))
REPLAYSHARK_LESTA = os.environ.get("WOWS_REPLAYSHARK_LESTA",
                                   str(REPORT_ROOT / "replayshark-lesta"))
RENDER_SH = os.environ.get("WOWS_RENDER_SH", str(REPO_ROOT / "minimap" / "render.sh"))

# ---------- 目录 ----------
# 同一目录历史上有两个 env 名:WOWS_DATA_DIR(plugin/minimap.py、render_chat.py)与
# WOWS_EXTRACTED_ROOT(report/bin/wows_report)。两个都读,老名字为兼容保留。
EXTRACTED_ROOT = os.environ.get(
    "WOWS_EXTRACTED_ROOT",
    os.environ.get("WOWS_DATA_DIR", "/var/lib/wows-data/extracted"),
)
SPECS_DIR = os.environ.get("WOWS_SPECS_DIR", str(REPORT_ROOT / "specs"))
SPECS_PATCHED_ROOT = os.environ.get("WOWS_SPECS_PATCHED_ROOT",
                                    "/var/lib/wows-data/specs-patched")
OUT_DIR = os.environ.get("WOWS_OUT_DIR", "/tmp/wows_report")
REPLAY_BASEDIR = os.path.expanduser(
    os.environ.get("WOWS_REPLAY_BASEDIR", "~/wows-bot-replay"))

# ---------- 命令(report/bin 下的入口) ----------
REPORT_FULL_CMD = os.environ.get("WOWS_REPORT_FULL_CMD", str(BIN_DIR / "wows_full_report"))
REPORT_BATTLE_CMD = os.environ.get("WOWS_REPORT_BATTLE_CMD", str(BIN_DIR / "wows_report"))
REPORT_DAMAGE_CMD = os.environ.get("WOWS_REPORT_DAMAGE_CMD",
                                   str(BIN_DIR / "wows_damage_report"))
REPORT_FULL_LESTA_CMD = os.environ.get("WOWS_REPORT_FULL_LESTA_CMD",
                                       str(BIN_DIR / "wows_full_report_normalized"))
ANALYZE_CMD = os.environ.get("WOWS_ANALYZE_CMD", str(BIN_DIR / "wows_analyze"))
RENDER_CRIMINALS_PY = os.environ.get("WOWS_RENDER_CRIMINALS",
                                     str(BIN_DIR / "render_criminals.py"))
RENDER_CHAT_PY = os.environ.get("WOWS_RENDER_CHAT", str(BIN_DIR / "render_chat.py"))
RENDER_BATTLE_PY = os.environ.get("WOWS_RENDER_PY",
                                  str(BIN_DIR / "render_battle_report.py"))
RENDER_DAMAGE_PY = str(BIN_DIR / "render_damage_chart.py")
RENDER_MENU_PY = str(BIN_DIR / "render_menu.py")
# 已弃用:早期只有一条报告命令时的名字,.env 里可能还有。保留读取,值同 REPORT_FULL_CMD。
REPORT_CMD = os.environ.get("WOWS_REPORT_CMD", REPORT_FULL_CMD)

# ---------- 数据文件 ----------
SHIPS_JSON = os.environ.get("WOWS_SHIPS_JSON", str(DATA_DIR / "ships.json"))
ARMOR_JSON = os.environ.get("WOWS_ARMOR_JSON", str(DATA_DIR / "armor.json"))
BUILDS_JSON = os.environ.get("WOWS_BUILDS_JSON", str(DATA_DIR / "builds.json"))
CONSTANTS_JSON = os.environ.get("WOWS_CONSTANTS_JSON", str(DATA_DIR / "constants.json"))
ACHIEVEMENTS_JSON = os.environ.get("WOWS_ACHIEVEMENTS_JSON",
                                   str(DATA_DIR / "achievements.json"))
ACHIEVEMENT_ICON_DIR = os.environ.get("WOWS_ACHIEVEMENT_ICONS",
                                      str(DATA_DIR / "achievement_icons"))
TRANSLATIONS_MO = os.environ.get("WOWS_TRANSLATIONS_MO", str(DATA_DIR / "zh_sg.mo"))
UPGRADE_ICON_DIR = str(DATA_DIR / "upgrade_icons")
SKILL_ICON_DIR = str(DATA_DIR / "skill_icons")
# 勋带图标目录:render_damage_chart.py 读的是 WOWS_RIBBON_ICONS,这里保持同一个 env 名,
# 免得将来谁把它改成从本表取值时,把那个 override 悄悄弄丢。
RIBBON_ICON_DIR = os.environ.get("WOWS_RIBBON_ICONS", str(DATA_DIR / "ribbon_icons"))
SHIP_ICON_DIR = str(DATA_DIR / "ship_icons")
# tools/build_ships_json.py 要读的 GameParams(在 specs 里,不在 data 里)
GAME_PARAMS_DATA = str(Path(SPECS_DIR) / "content" / "GameParams.data")

# ---------- 字体 ----------
# 查找链在 theme.py 里(它要按 OS 逐个探测文件是否存在),这里只负责"env 覆盖"这一层,
# 好让本表确实是所有 env 的唯一入口。未设时为 None,theme 会继续往后试内置候选。
CJK_FONT_OVERRIDE = os.environ.get("WOWS_CJK_FONT")
MONO_FONT_OVERRIDE = os.environ.get("WOWS_MONO_FONT")

# ---------- 超时(秒) ----------
MP4_TIMEOUT = int(os.environ.get("WOWS_MP4_TIMEOUT", "600"))
PNG_TIMEOUT = int(os.environ.get("WOWS_PNG_TIMEOUT", "300"))
ANALYZE_TIMEOUT = int(os.environ.get("WOWS_ANALYZE_TIMEOUT", "120"))
