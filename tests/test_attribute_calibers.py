"""属性口径：每种属性怎么被读必须写在数据里，且基准与口径相符。

这条契约是「加成的基准是 100、减免的基准是 0」这件事的唯一落点。它防的是一类
**静默改机制**的改动：把 `伤害减免` 的基准也从 0 补成 100，「没减免」就变成「减 100%」，
1967 场里 1950 场战报会变——而且不报错。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from game.core.combat.foundation import (
    ATTRIBUTE_CALIBERS,
    _validate_attribute_definitions,
)
from game.core.combat.models import Fighter, attribute_ratio

DATA = Path(__file__).resolve().parents[1] / "data"
DEFINITIONS = json.loads(
    (DATA / "战斗" / "定义" / "属性.json").read_text(encoding="utf-8")
)


def _fighter(attributes: dict[str, float] | None = None) -> Fighter:
    return Fighter(
        id="测试", name="测试", attributes=dict(attributes or {}), health=100, spirit=100
    )


def test_every_attribute_declares_a_known_caliber() -> None:
    for name, definition in DEFINITIONS.items():
        assert definition.get("口径") in ATTRIBUTE_CALIBERS, name


def test_bonus_caliber_uses_a_100_base_and_reduction_uses_0() -> None:
    for name, definition in DEFINITIONS.items():
        caliber = definition["口径"]
        if caliber == "加成":
            assert definition["默认值"] == 100, name
        if caliber in {"减免", "比率"}:
            assert definition["默认值"] == 0, name


def test_validator_rejects_a_caliber_that_contradicts_its_base() -> None:
    broken = {
        "伤害减免": {
            "默认值": 100,
            "单位": "%",
            "最小单位": 1,
            "最低值": 0,
            "最高值": 400,
            "显示": "百分比",
            "口径": "减免",
            "说明": "故意写错基准",
        }
    }
    with pytest.raises(ValueError, match="基准必须是 0"):
        _validate_attribute_definitions(broken)


def test_validator_rejects_an_unregistered_caliber() -> None:
    broken = {
        "攻击": {
            "默认值": 0,
            "单位": "点",
            "最小单位": 1,
            "最低值": 0,
            "最高值": 10,
            "显示": "数值",
            "口径": "随便写的",
            "说明": "口径没登记",
        }
    }
    with pytest.raises(ValueError, match="口径未登记"):
        _validate_attribute_definitions(broken)


def test_unset_bonus_attribute_reads_as_one() -> None:
    """没写这个属性的参战者读到的必须是「不增不减」，不是 0。"""

    fighter = _fighter()
    assert attribute_ratio(fighter, "伤害加成", DEFINITIONS) == 1.0
    assert attribute_ratio(fighter, "技能威力", DEFINITIONS) == 1.0
    assert attribute_ratio(fighter, "治疗效果", DEFINITIONS) == 1.0
    assert attribute_ratio(fighter, "伤害减免", DEFINITIONS) == 0.0
    assert attribute_ratio(fighter, "暴击伤害", DEFINITIONS) == 1.5


def test_bonus_is_relative_to_the_declared_base() -> None:
    """数据写的都是「加在基准上的差值」：120 是 +20%，20 是 −80%。"""

    assert attribute_ratio(_fighter({"伤害加成": 120}), "伤害加成", DEFINITIONS) == 1.2
    assert attribute_ratio(_fighter({"伤害加成": 20}), "伤害加成", DEFINITIONS) == 0.2


def test_call_site_default_still_wins_when_given() -> None:
    """命中率的基准是**伤害规则里的基础命中率**，不是属性自己的默认值。"""

    fighter = _fighter()
    assert attribute_ratio(fighter, "命中率", DEFINITIONS, 0.95) == pytest.approx(0.95)
    assert attribute_ratio(fighter, "命中率", DEFINITIONS) == 1.0


def test_all_engine_read_attributes_are_declared() -> None:
    """引擎真正读到的百分比属性都得在定义里，避免「读了个没登记的名字，静默取 0」。"""

    读取的 = {
        "命中率", "闪避率", "暴击率", "抗暴率", "暴击伤害", "暴击伤害减免",
        "格挡率", "破格率", "格挡减伤", "比例穿透", "伤害加成", "伤害减免",
        "普通攻击威力", "技能威力", "治疗加成", "受疗加成", "护盾加成", "受盾加成",
        "治疗效果", "护盾强度", "吸血率", "反伤率", "连击率", "连击伤害",
        "反击率", "控制命中率", "控制抵抗率", "韧性", "冷却缩减", "精神消耗修正",
    }
    assert 读取的 <= set(DEFINITIONS)
