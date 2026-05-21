# tests/test_permissions.py
"""permissions 模块自测脚本。
用法: python tests/test_permissions.py
退出码 0=全过,非 0=失败。
无 pytest 依赖,纯 assert + print。"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

# 让脚本能 import plugin/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _reset_module():
    """每个 case 起一次新 tempdir + 重导模块,避免单例污染。"""
    if "plugin.permissions" in sys.modules:
        del sys.modules["plugin.permissions"]
    if "plugin" in sys.modules:
        del sys.modules["plugin"]
    # mock nonebot.get_driver 提供假 superusers 配置
    fake_driver = MagicMock()
    fake_driver.config.superusers = {"11111"}
    import nonebot  # noqa
    nonebot.get_driver = lambda: fake_driver
    from plugin import permissions
    return permissions


def test_default_state():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        perms.init(d)
        # 没设过的 group + feature 应该按 DEFAULT_ENABLED
        assert perms.feature_enabled("group", "999", "战报") is True
        assert perms.feature_enabled("group", "999", "视频") is True
        assert perms.feature_enabled("group", "999", "复盘") is True
        # 分析 + 战犯 默认 OFF
        assert perms.feature_enabled("private", "888", "分析") is False
        assert perms.feature_enabled("group", "999", "战犯") is False
        assert perms.feature_enabled("private", "888", "战犯") is False
        # 主动开启之后变 True 并跨实例保留
        perms.set_feature("group", "999", "战犯", True)
        perms.set_feature("group", "999", "分析", True)
        assert perms.feature_enabled("group", "999", "战犯") is True
        assert perms.feature_enabled("group", "999", "分析") is True
    print("  default_state PASS")


def test_set_and_persist():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        perms.init(d)
        perms.set_feature("group", "999", "复盘", False)
        assert perms.feature_enabled("group", "999", "复盘") is False
        # 文件落地了
        state_file = Path(d) / "toggle_state.json"
        assert state_file.is_file()
        data = json.loads(state_file.read_text("utf-8"))
        assert data["groups"]["999"]["复盘"] is False
        # 重新 init 后状态保留
        perms2 = _reset_module()
        perms2.init(d)
        assert perms2.feature_enabled("group", "999", "复盘") is False
    print("  set_and_persist PASS")


def test_global_blacklist_vetoes_group():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        perms.init(d)
        perms.set_feature("group", "999", "分析", True)
        assert perms.feature_enabled("group", "999", "分析") is True
        perms.super_admin_ban("分析")
        # 超管 ban 后,即便 group 自己开着也算关
        assert perms.feature_enabled("group", "999", "分析") is False
        perms.super_admin_unban("分析")
        assert perms.feature_enabled("group", "999", "分析") is True
    print("  global_blacklist_vetoes_group PASS")


def test_is_super_admin():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        perms.init(d)
        assert perms.is_super_admin("11111") is True
        assert perms.is_super_admin(11111) is True  # int 也行
        assert perms.is_super_admin("99999") is False
    print("  is_super_admin PASS")


def test_can_toggle_group_admin():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        perms.init(d)
        # 模拟一个群管 (非超管) 发送群消息
        ev = MagicMock()
        ev.user_id = "22222"
        ev.sender.role = "admin"
        ev.group_id = 999
        # 让 isinstance 检查通过
        from nonebot.adapters.onebot.v11 import GroupMessageEvent
        ev.__class__ = GroupMessageEvent
        assert perms.can_toggle(ev, "999") is True
        # 普通 member 不行
        ev.sender.role = "member"
        assert perms.can_toggle(ev, "999") is False
        # 但超管不论角色都行
        ev.user_id = "11111"
        ev.sender.role = "member"
        assert perms.can_toggle(ev, "999") is True
    print("  can_toggle_group_admin PASS")


def test_unknown_feature_assertion():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        perms.init(d)
        try:
            perms.feature_enabled("group", "999", "猜船")
        except AssertionError:
            pass
        else:
            raise AssertionError("应该 raise AssertionError")
    print("  unknown_feature_assertion PASS")


def test_migrate_legacy():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        legacy = Path(d) / "analyze_toggle.json"
        legacy.write_text(json.dumps({
            "g:111": True,
            "g:222": False,
            "u:333": True,
            "garbage_key": True,  # 应该被跳过
        }), "utf-8")
        ok = perms.migrate_legacy(d)
        assert ok is True
        # 新文件出现
        new = Path(d) / "toggle_state.json"
        assert new.is_file()
        data = json.loads(new.read_text("utf-8"))
        assert data["groups"]["111"]["分析"] is True
        assert data["groups"]["222"]["分析"] is False
        assert data["private"]["333"]["分析"] is True
        assert "garbage_key" not in data["groups"]
        # 旧文件被改名
        assert not legacy.exists()
        assert (Path(d) / "analyze_toggle.json.bak").exists()
        # 再迁一次是 no-op
        assert perms.migrate_legacy(d) is False
    print("  migrate_legacy PASS")


def test_init_auto_migrates():
    perms = _reset_module()
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "analyze_toggle.json").write_text(
            json.dumps({"g:777": True}), "utf-8"
        )
        perms.init(d)
        assert perms.feature_enabled("group", "777", "分析") is True
        # 其他 feature 走 DEFAULT_ENABLED
        assert perms.feature_enabled("group", "777", "视频") is True
        assert perms.feature_enabled("group", "777", "战犯") is False
    print("  init_auto_migrates PASS")


if __name__ == "__main__":
    print("== test_permissions ==")
    test_default_state()
    test_set_and_persist()
    test_global_blacklist_vetoes_group()
    test_is_super_admin()
    test_can_toggle_group_admin()
    test_unknown_feature_assertion()
    test_migrate_legacy()
    test_init_auto_migrates()
    print("== ALL PASS ==")
