"""wowsbot 的 theme / text / i18n / results 测试。无 pytest 依赖。
用法: python tests/test_wowsbot_lib.py"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "report" / "lib"))

# 字体环境变量必须在 import theme 之前设(theme 找不到 CJK 字体会直接 raise)。
# 跟 tests/test_render_menu.py / test_render_armor.py 同一约定,保证裸环境也能跑。
os.environ.setdefault("WOWS_CJK_FONT", "C:/Windows/Fonts/msyh.ttc")
os.environ.setdefault("WOWS_MONO_FONT", "C:/Windows/Fonts/consola.ttf")

LIB = ROOT / "report" / "lib" / "wowsbot"


def test_theme_palette_values_unchanged():
    """调色板必须与重构前 render_battle_report.py 里的值逐一相同 —— 改了就是改了外观。"""
    from wowsbot import theme
    assert theme.GAME_BG == (18, 24, 38)
    assert theme.GAME_PANEL == (32, 42, 64)
    assert theme.GAME_PANEL_ALT == (28, 36, 56)
    assert theme.GAME_GREEN == (74, 200, 132)
    assert theme.GAME_RED == (235, 86, 75)
    assert theme.GAME_GOLD == (242, 196, 87)
    assert theme.GAME_PURPLE == (188, 122, 232)
    assert theme.GAME_TEXT == (228, 233, 245)
    assert theme.GAME_DIM == (140, 155, 180)
    assert theme.GAME_BORDER == (60, 75, 100)
    print("  test_theme_palette_values_unchanged PASS")


def test_theme_font_env_override_wins():
    """WOWS_CJK_FONT 覆盖内置候选链。

    注意 reload 顺序:env 由 paths 采样(paths.CJK_FONT_OVERRIDE),theme 只是把它当作
    候选链的第一项。所以要先 reload paths 再 reload theme —— 只 reload theme 会拿到
    paths 里的旧值。实际进程里两者都在启动时 import 一次,没有这个问题。
    """
    import importlib
    from wowsbot import paths, theme
    saved = os.environ.get("WOWS_CJK_FONT")
    # 用一个确实存在的文件当字体路径(内容不重要,theme 只做存在性检查)
    probe = str(ROOT / "README.md") if (ROOT / "README.md").is_file() else __file__
    os.environ["WOWS_CJK_FONT"] = probe
    try:
        importlib.reload(paths)
        t = importlib.reload(theme)
        assert t.CJK_FONT == probe, t.CJK_FONT
        # MONO 未设时回落到 CJK
        assert t.MONO_FONT is not None
    finally:
        if saved is None:
            os.environ.pop("WOWS_CJK_FONT", None)
        else:
            os.environ["WOWS_CJK_FONT"] = saved
        importlib.reload(paths)
        importlib.reload(theme)
    print("  test_theme_font_env_override_wins PASS")


def test_text_helpers():
    from wowsbot import text
    assert text.strip_id("AccountId(12345)") == 12345
    assert text.strip_id("EntityId(7)") == 7
    assert text.strip_id("GameParamId(42)") == 42
    assert text.strip_id("") == 0
    assert text.strip_id("garbage") == 0
    assert text.strip_known("Known(Battleship)") == "Battleship"
    assert text.strip_known("Battleship") == "Battleship"
    assert text.strip_known("") == ""
    assert text.relation_name("Relation(0)") == "self"
    assert text.relation_name("Relation(1)") == "friendly"
    assert text.relation_name("Relation(2)") == "enemy"
    assert text.relation_name("") == "?"
    assert text.clean_ship_name("PASS208_Salmon") == "Salmon"
    assert text.clean_ship_name("PASC108_Baltimore_1944") == "Baltimore"
    assert text.clean_ship_name("") == "?"
    assert text.fmt_time(0) == "00:00"
    assert text.fmt_time(65) == "01:05"
    assert text.fmt_time(600) == "10:00"
    print("  test_text_helpers PASS")


def test_i18n_labels_present():
    from wowsbot import i18n
    assert i18n.SPECIES_SHORT["Battleship"] == "BB"
    assert i18n.SPECIES_SHORT["AirCarrier"] == "CV"
    assert i18n.DEATH_CAUSE_CN["ApShell"] == "AP"
    assert i18n.DEATH_CAUSE_CN["Flooding"] == "进水"
    assert i18n.MATCH_GROUP_CN["pvp"] == "随机战"
    print("  test_i18n_labels_present PASS")


def test_i18n_t_falls_back_to_key():
    from wowsbot import i18n
    # 不存在的键返回自身;给了 default 就返回 default
    assert i18n.t("IDS_DEFINITELY_NOT_A_KEY") == "IDS_DEFINITELY_NOT_A_KEY"
    assert i18n.t("IDS_DEFINITELY_NOT_A_KEY", "回退") == "回退"
    print("  test_i18n_t_falls_back_to_key PASS")


def test_results_field_bounds():
    from wowsbot import results
    # 索引表可能加载失败(缺 constants.json),此时一律返回 default 而不抛
    assert results.result_field(None, "damage", "D") == "D"
    assert results.result_field([], "damage", "D") == "D"
    assert results.result_field("not a list", "damage", "D") == "D"
    assert results.result_field([1, 2, 3], "definitely_not_a_field", "D") == "D"
    print("  test_results_field_bounds PASS")


if __name__ == "__main__":
    print("== test_wowsbot_lib ==")
    test_theme_palette_values_unchanged()
    test_theme_font_env_override_wins()
    test_text_helpers()
    test_i18n_labels_present()
    test_i18n_t_falls_back_to_key()
    test_results_field_bounds()
    print("== ALL PASS ==")
