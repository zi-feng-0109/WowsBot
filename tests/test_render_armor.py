# tests/test_render_armor.py
"""render_armor 测试:纯逻辑(标签/格式/分组)+ 烟囱渲染(PNG 写出且 >5KB)。
用法: python tests/test_render_armor.py"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "report" / "bin"))
os.environ.setdefault("WOWS_CJK_FONT", "C:/Windows/Fonts/msyh.ttc")

from render_armor import face_zh, _fmt_mm, _armor_sections, render_armor_png  # noqa: E402


def test_face_zh_exact_and_fallback():
    assert face_zh("TurretFront") == "炮塔正面"
    assert face_zh("SideCit") == "SideCit"   # 未精确命中 → 退化原名,不丢
    print("  face_zh PASS")


def test_fmt_mm_multilayer():
    assert _fmt_mm([370, 350]) == "370 / 350 mm"
    assert _fmt_mm([410]) == "410 mm"
    assert _fmt_mm([]) == "-"
    print("  _fmt_mm PASS")


def test_sections_zone_order_and_turret():
    armor = {
        "hull": {
            "Bow": [{"face": "Bow_Belt", "mm": [60]}],
            "Citadel": [{"face": "Belt", "mm": [410]}, {"face": "Deck", "mm": [200]}],
        },
        "turrets": [{"name": "主炮", "faces": [{"face": "TurretFront", "mm": [650]}]}],
    }
    secs = _armor_sections(armor)
    titles = [t for t, _, _ in secs]
    # Citadel(装甲核心)在 Bow(舰艏)之前(_ZONE_ORDER),主炮塔在最后
    assert titles[0] == "装甲核心", titles
    assert "舰艏" in titles
    assert titles[-1] == "主炮装甲", titles
    print("  _armor_sections PASS")


def test_render_smoke():
    ship = {"tier": 10, "name_zh": "大和", "name_en": "Yamato",
            "species_zh": "战列舰", "nation_zh": "日本", "index": "PJSB018"}
    armor = {
        "hull": {"Citadel": [{"face": "Belt", "mm": [410]}, {"face": "Deck", "mm": [200]}],
                 "Bow": [{"face": "Bow_Belt", "mm": [60]}]},
        "turrets": [{"name": "主炮", "faces": [
            {"face": "TurretFront", "mm": [650]}, {"face": "TurretSide", "mm": [250]}]}],
    }
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "armor.png"
        render_armor_png(str(out), ship=ship, armor=armor)
        assert out.is_file(), "PNG 没写出来"
        size = out.stat().st_size
        assert size > 5_000, f"PNG 才 {size} 字节,太小"
        print(f"  render_smoke PASS ({size} bytes)")


if __name__ == "__main__":
    test_face_zh_exact_and_fallback()
    test_fmt_mm_multilayer()
    test_sections_zone_order_and_turret()
    test_render_smoke()
    print("ALL PASS")
