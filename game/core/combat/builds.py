"""四类构筑来源各自的契约。

功法、真意、气机、器律是四个不同的设计方向：功法走完整战斗循环，真意只承载
被动规律，气机只提供固定属性倾向，器律锻在本命武器孔位上。它们不共享同一套
形状，所以校验也必须分开，不能互相借用字段。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from game.core.data import JsonDataService, materialize

from .foundation import rule_validator
from .schema import RuleSchemaValidator

BUILD_CONTRACT_DATASET = "战斗规则"
BUILD_CONTRACT_NAME = "构筑契约"
BUILD_SECTIONS = ("功法", "真意", "气机", "器律")
_ELEMENT_KEYS = frozenset({"木", "火", "土", "金", "水", "无相"})


class BuildContractError(ValueError):
    """构筑数据不符合它所属那一类的契约。"""


def load_build_contracts(data: JsonDataService) -> dict[str, Mapping[str, Any]]:
    rules = materialize(data.dataset(BUILD_CONTRACT_DATASET))
    raw = rules.get(BUILD_CONTRACT_NAME)
    if not isinstance(raw, Mapping):
        raise BuildContractError(
            f"战斗规则缺少{BUILD_CONTRACT_NAME}；构筑必须按四个方向分别声明"
        )
    declared = set(str(key) for key in raw)
    if declared != set(BUILD_SECTIONS):
        raise BuildContractError(
            "构筑契约必须正好声明功法、真意、气机、器律："
            + "、".join(sorted(declared))
        )
    contracts: dict[str, Mapping[str, Any]] = {}
    for section in BUILD_SECTIONS:
        contract = raw[section]
        if not isinstance(contract, Mapping):
            raise BuildContractError(f"构筑契约.{section}必须是对象")
        contracts[section] = contract
    return contracts


def validate_builds(
    data: JsonDataService,
    contracts: Mapping[str, Mapping[str, Any]] | None = None,
    validator: RuleSchemaValidator | None = None,
) -> dict[str, int]:
    """逐类校验构筑实体，返回每类通过的实体数。"""

    if contracts is None:
        contracts = load_build_contracts(data)
    if validator is None:
        validator = rule_validator(materialize(data.dataset("战斗定义")))
    counts: dict[str, int] = {}
    weights: dict[int, str] = {}
    for section in BUILD_SECTIONS:
        contract = contracts[section]
        entities = data.entities(section)
        if not entities:
            raise BuildContractError(f"{section}不能为空")
        for content_id, raw in entities.items():
            _validate_build(
                section,
                contract,
                str(content_id),
                materialize(raw),
                validator,
                weights,
            )
        counts[section] = len(entities)
    return counts


def _validate_build(
    section: str,
    contract: Mapping[str, Any],
    content_id: str,
    value: Any,
    validator: RuleSchemaValidator,
    weights: dict[int, str],
) -> None:
    path = f"{section}[{content_id}]"
    if not isinstance(value, Mapping):
        raise BuildContractError(f"{path}必须是对象")
    prefix = str(contract.get("编号前缀") or "")
    if not content_id.startswith(prefix):
        raise BuildContractError(f"{path}编号必须以{prefix}开头")
    expected = tuple(str(field) for field in contract.get("字段") or ())
    actual = set(str(key) for key in value)
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        unknown = sorted(actual - set(expected))
        details = []
        if missing:
            details.append("缺少 " + "、".join(missing))
        if unknown:
            details.append("多出 " + "、".join(unknown))
        raise BuildContractError(f"{path}字段不符合{section}契约：{'；'.join(details)}")
    for field in ("名称", "说明"):
        if not str(value.get(field) or "").strip():
            raise BuildContractError(f"{path}.{field}不能为空")
    if section == "器律":
        for field in ("器阶", "铸法"):
            if not str(value.get(field) or "").strip():
                raise BuildContractError(f"{path}.{field}不能为空")
        beast = value.get("兽引")
        if not isinstance(beast, list) or not beast or any(
            not isinstance(item, str) or not item.strip() for item in beast
        ):
            raise BuildContractError(f"{path}.兽引必须是非空字符串数组")
    else:
        _validate_weight(section, contract, path, value, weights)

    composition = value.get("属性构成")
    if not isinstance(composition, Mapping) or not composition:
        raise BuildContractError(f"{path}.属性构成必须是非空对象")
    if not set(str(key) for key in composition) <= _ELEMENT_KEYS:
        raise BuildContractError(f"{path}.属性构成包含未登记五行")
    total = sum(float(amount) for amount in composition.values())
    if abs(total - 100.0) > 1e-6:
        raise BuildContractError(f"{path}.属性构成必须合计 100，当前 {total:g}")

    abilities = value.get("能力")
    if not isinstance(abilities, list) or not abilities:
        raise BuildContractError(f"{path}.能力必须是非空数组")
    allowed_roots = tuple(str(item) for item in contract.get("根能力") or ())
    fixed = contract.get("能力数量")
    if fixed is not None and len(abilities) != int(fixed):
        raise BuildContractError(f"{path}的{section}必须正好有{int(fixed)}项根能力")
    minimum = int(contract.get("最少能力") or 1)
    if len(abilities) < minimum:
        raise BuildContractError(f"{path}.能力不得少于{minimum}项")
    roots: list[str] = []
    for index, node in enumerate(abilities):
        node_path = f"{path}.能力[{index}]"
        if not isinstance(node, Mapping):
            raise BuildContractError(f"{node_path}必须是对象")
        root = str(node.get("能力") or "")
        roots.append(root)
        if root not in allowed_roots:
            raise BuildContractError(
                f"{node_path}的根能力是{root or '<空>'}，"
                f"{section}只允许 {'、'.join(allowed_roots)}"
            )
        validator.validate_node(node, node_path)
        _validate_event_binding(node, node_path)
    if bool(contract.get("要求主动技能")) and "主动技能" not in roots:
        raise BuildContractError(f"{path}必须至少有一项主动技能")


def _validate_weight(
    section: str,
    contract: Mapping[str, Any],
    path: str,
    value: Mapping[str, Any],
    weights: dict[int, str],
) -> None:
    weight = value.get("权重")
    if isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0:
        raise BuildContractError(f"{path}.权重必须是正整数")
    if not bool(contract.get("参与权重唯一")):
        return
    owner = weights.get(weight)
    if owner is not None:
        raise BuildContractError(f"{path}.权重与{owner}重复：{weight}")
    weights[weight] = path


def _validate_event_binding(
    value: Any, path: str, *, damage_event: bool = False
) -> None:
    """转移伤害只能在伤害事件监听里执行；构筑不能再绕过这条约束。"""

    if isinstance(value, Mapping):
        ability = str(value.get("能力") or "")
        current = damage_event
        if ability == "监听事件":
            current = str(value.get("事件") or "") in {"造成伤害前", "受到致命伤害"}
        if ability == "转移伤害" and not current:
            raise BuildContractError(f"{path}.转移伤害只能在伤害事件监听中执行")
        for key, child in value.items():
            _validate_event_binding(child, f"{path}.{key}", damage_event=current)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_event_binding(child, f"{path}[{index}]", damage_event=damage_event)


__all__ = [
    "BUILD_CONTRACT_DATASET",
    "BUILD_CONTRACT_NAME",
    "BUILD_SECTIONS",
    "BuildContractError",
    "load_build_contracts",
    "validate_builds",
]
