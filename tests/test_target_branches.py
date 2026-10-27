from __future__ import annotations

import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from game.core.combat.mechanics import AbilityRuntime
from game.core.combat.models import RuleNode

DATA = Path(__file__).resolve().parents[1] / "data"


def _walk(value):
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            yield node
            stack.extend(item for item in node.values() if isinstance(item, (dict, list)))
        elif isinstance(node, list):
            stack.extend(node)


def test_every_support_effect_has_explicit_target_or_branch() -> None:
    missing = []
    for path in DATA.rglob("*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for node in _walk(document):
            ability = node.get("能力")
            if not isinstance(ability, str) or ability not in {"恢复资源", "添加护盾", "复活"}:
                continue
            if "目标" not in node and "目标分支" not in node:
                missing.append(str(path))
    assert not missing


def test_directional_effects_use_target_branches() -> None:
    abilities = json.loads(
        (DATA / "战斗/定义/原子能力.json").read_text(encoding="utf-8")
    )
    effect_abilities = {
        name
        for name, definition in abilities.items()
        if isinstance(definition, dict) and definition.get("类别") == "效果"
    }
    aoe = {"全体", "任意", "友方全体"}
    missing = []
    for path in DATA.rglob("*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for node in _walk(document):
            ability = node.get("能力")
            if not isinstance(ability, str) or ability not in effect_abilities:
                continue
            target = node.get("目标")
            is_aoe = (
                isinstance(target, dict)
                and (
                    target.get("选择全部") is True
                    or target.get("范围") in aoe
                )
            )
            if is_aoe:
                assert "目标分支" not in node
                continue
            if "目标分支" not in node:
                missing.append(str(path))
    assert not missing


def test_target_branch_data_is_well_formed() -> None:
    seen = 0
    for path in DATA.rglob("*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for node in _walk(document):
            raw = node.get("目标分支")
            if not isinstance(raw, dict) or "分支" not in raw:
                continue
            seen += 1
            assert isinstance(raw, dict), path
            assert raw.get("方式") in {"顺序", "权重", "随机"}, path
            branches = raw.get("分支")
            assert isinstance(branches, list) and branches, path
            for branch in branches:
                assert isinstance(branch, dict), path
                assert float(branch.get("强度", 100)) > 0, path
                target = branch.get("目标")
                assert isinstance(target, dict), path
                assert target.get("选择全部") is not True, path
                assert target.get("范围") not in {"全体", "任意"}, path
    assert seen >= 7


class _FakeRuntime(AbilityRuntime):
    def __init__(self) -> None:
        pass

    def _conditions_allow(self, context, source, target, conditions, event_amount, event_values, tags):
        return bool(conditions and conditions[0])

    def _select_targets(self, context, source, target, value):
        return [] if value.get("范围") == "empty" else [SimpleNamespace(id="target")]


def _branch(target: dict, *, condition: bool | None = None, strength: int = 100, weight: int = 1):
    value = {"目标": target, "强度": strength, "权重": weight}
    if condition is not None:
        value["条件"] = [condition]
    return value


def test_branch_order_and_fallback() -> None:
    runtime = _FakeRuntime()
    context = SimpleNamespace(rng=random.Random(1))
    effect = {
        "目标分支": {
            "方式": "顺序",
            "分支": [
                _branch({"范围": "empty"}, condition=True),
                _branch({"范围": "其他己方"}, condition=True, strength=120),
            ],
        }
    }
    chosen = runtime._choose_target_branch(context, None, None, effect, 0.0, {}, ())
    assert chosen is not None
    assert chosen[0]["强度"] == 120
    assert chosen[1]["排除召唤物"] is True


def test_branch_strength_reaches_effect_and_preselects_target() -> None:
    runtime = _FakeRuntime()
    seen = []

    class Catalog:
        @staticmethod
        def parse_node(value):
            return RuleNode("测试", "测试", "效果", value)

    def handler(context, source, target, effect, multiplier):
        seen.append((multiplier, context.target_override, effect["目标"]))
        return True

    runtime.catalog = Catalog()
    runtime._ability_handlers = {"测试": handler}
    context = SimpleNamespace(
        rng=random.Random(1),
        ability_depth=0,
        ability_handler_cache={},
        event_count=0,
        last_result={},
        effect_history=[],
        target_override=None,
        current_element_composition={"无相": 100},
        fighter_order={},
        action_progress={},
    )
    effect = {
        "能力": "测试",
        "目标分支": {
            "方式": "顺序",
            "分支": [
                {
                    "目标": {"范围": "其他己方", "数量": 1},
                    "强度": 120,
                }
            ],
        },
    }
    source = SimpleNamespace(id="source")
    target = SimpleNamespace(id="target")
    assert runtime._execute_mechanism(context, source, target, effect) is True
    assert seen
    multiplier, override, selected = seen[0]
    assert multiplier == 1.2
    assert override is not None and override[1][0].id == "target"
    assert selected is override[0]


def test_branch_weighted_and_aoe_rejection() -> None:
    runtime = _FakeRuntime()
    context = SimpleNamespace(rng=random.Random(7))
    effect = {
        "目标分支": {
            "方式": "权重",
            "分支": [
                _branch({"范围": "其他己方"}, weight=1),
                _branch({"范围": "其他己方"}, weight=3),
            ],
        }
    }
    chosen = runtime._choose_target_branch(context, None, None, effect, 0.0, {}, ())
    assert chosen is not None

    with pytest.raises(ValueError):
        runtime._choose_target_branch(
            context,
            None,
            None,
            {
                "目标分支": {
                    "方式": "顺序",
                    "分支": [_branch({"范围": "全体", "选择全部": True})],
                }
            },
            0.0,
            {},
            (),
        )
