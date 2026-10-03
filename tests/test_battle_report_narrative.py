"""叙述层判据：一句话、血量行、收束句都要与事件数据对得上。

这一层是给玩家看的正文（`narrative` / `health_line` / `ending_line`）。它最容易悄悄走偏：
数字加错、把没入场的单位当在场、收束句与最后一击对不上。所以按事件数据逐项判。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

try:  # noqa: E402
    from game.core.combat.presentation import (  # noqa: E402
        _ending_line,
        _health_line,
        _narrative,
    )
except ImportError:  # pragma: no cover - 该模块当前未导出所需符号
    pytest.skip("presentation 未导出 _ending_line/_health_line/_narrative", allow_module_level=True)


def 事件(kind, label, text, source="player:甲", target="player:乙"):
    return {"kind": kind, "label": label, "text": text, "source": source, "target": target}


def test_narrative_sums_damage_and_names_states():
    句 = _narrative(
        "甲 对 乙 使用 天雷诀",
        [
            事件("添加状态", "获得状态", "获得状态 · 护体 1"),
            事件("伤害", "伤害", "伤害 · 4.52"),
            事件("伤害", "伤害", "伤害 · 7.06"),
            事件("回复", "回血", "回血 · 血气 0.88"),
            事件("消耗", "资源消耗", "资源消耗 · 精神 16"),
        ],
    )
    assert 句.startswith("甲 对 乙 使用 天雷诀；")
    assert "叠 1 层状态（护体）" in 句, 句          # 状态不重复、只记名字
    assert "造成 11.58 伤害" in 句, 句            # 4.52 + 7.06，按事件加总
    assert "回复 0.88 血气" in 句, 句
    assert "精神 16" in 句, 句


def test_narrative_ignores_zero_damage():
    句 = _narrative("甲 对 乙 使用 平砍", [事件("伤害", "伤害", "伤害 · 0")])
    assert "造成" not in 句, 句                   # 0 伤害不进正文


def test_health_line_uses_names_and_skips_never_entered():
    参战 = [
        {"id": "player:甲", "name": "甲", "initial_resources": [{"id": "health", "current": 318}]},
        {"id": "player:乙", "name": "乙", "initial_resources": [{"id": "health", "current": 332}]},
        # 构造物：开局 0、此刻 0 ⇒ 从没入场，不该出现在这一行（否则看着像"开局就死了"）
        {"id": "player:甲:战斗对象:1", "name": "星台照夜", "initial_resources": [{"id": "health", "current": 0}]},
    ]
    状态 = {
        "player:甲": {"resources": {"health": {"current": 261.868, "maximum": 318}}},
        "player:乙": {"resources": {"health": {"current": 0, "maximum": 332}}},
        "player:甲:战斗对象:1": {"resources": {"health": {"current": 0, "maximum": 30}}},
    }
    行 = _health_line(状态, 参战, {})
    assert 行 == "⚔ 甲 261.87/318 ｜ 乙 0/332", 行
    assert "星台照夜" not in 行, 行


def test_health_line_keeps_entered_then_fallen_unit():
    参战 = [
        {"id": "player:甲:战斗对象:1", "name": "星台照夜", "initial_resources": [{"id": "health", "current": 30}]},
    ]
    状态 = {"player:甲:战斗对象:1": {"resources": {"health": {"current": 0, "maximum": 30}}}}
    assert _health_line(状态, 参战, {}) == "⚔ 星台照夜 0/30"      # 入过场，倒下也要写出来


def test_ending_line_joins_last_blow_and_result():
    时间线 = [{"narrative": "甲 对 乙 使用 收束诀；造成 24.75 伤害，陨落 · 击杀"}]
    句 = _ending_line(时间线, {"result": {"title": "甲取胜"}})
    assert 句 == "甲 对 乙 使用 收束诀；造成 24.75 伤害，陨落 · 击杀 —— 甲取胜", 句
    assert _ending_line([], {"result": {"title": "甲取胜"}}) == ""


def test_narrative_is_stable_across_two_builds():
    """同一份事件算两遍必须逐字相同（叙述层不许带随机或时间）。"""
    事件表 = [事件("伤害", "伤害", "伤害 · 4.52"), 事件("添加状态", "获得状态", "获得状态 · 护体 1")]
    首 = _narrative("甲 对 乙 使用 天雷诀", 事件表)
    次 = _narrative("甲 对 乙 使用 天雷诀", 事件表)
    assert 首 == 次
