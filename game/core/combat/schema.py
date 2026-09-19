"""战斗字段契约的校验适配。

通用的契约语法校验在 `game.core.data.schema`，本模块只提供战斗领域的部分：

- **领域字段类型**：`能力`、`能力数组`、`数值或能力`、三类引用、`属性数值表`、
  `属性构成`；
- **领域引用表**：属性、资源、事件；
- **数组执行器数量**：限制同一字段里某一执行器可以出现几次。

构筑不再按编号回查中间层：功法、真意、气机、器律各自携带完整能力树，
它们的形状契约在 `game.core.combat.builds`。

错误信息保留完整配置路径，数据作者可据此定位到具体文件与键。
"""

from __future__ import annotations


from collections.abc import Iterable, Mapping
from typing import Any

from game.core.data import DefinitionSchemaValidator, SchemaError

class RuleSchemaError(SchemaError):
    """原子能力定义或能力树不符合声明规则。

    保留本领域专用的异常类型名：错误信息里会带上类名，改动它会改变既有
    诊断输出，也会影响捕获该类型的调用方。
    """

#: 原子能力定义的顶层键；`字段` 与 `约束` 由基类处理。
_ENTRY_KEYS = frozenset({"类别", "执行器", "说明", "字段", "约束"})
_CATEGORIES = frozenset({"装配", "引用", "组合", "触发", "数值", "目标", "条件", "效果"})
#: 引用类字段类型；引用表由构造参数给出。
_REFERENCE_TYPES = ("属性引用", "资源引用", "事件引用")
#: 领域扩展的字段类型。
_DOMAIN_TYPES = frozenset(
    {
        "能力",
        "能力数组",
        "数值或能力",
        *_REFERENCE_TYPES,
        "属性数值表",
        "属性构成",
    }
)
#: 领域扩展的字段规格键。
_DOMAIN_KEYS = frozenset({"允许类别", "允许能力", "允许执行器", "目标类别", "目标执行器"})
#: 声明为"非空字符串数组"的领域规格键。
_DOMAIN_LIST_KEYS = ("允许类别", "允许能力", "允许执行器", "目标类别", "目标执行器")


class RuleSchemaValidator(DefinitionSchemaValidator):
    """按 `战斗定义/原子能力.json` 的字段契约校验原子能力与能力树。"""

    entry_keys = _ENTRY_KEYS

    @classmethod
    def _error(cls, message: str) -> RuleSchemaError:
        """战斗领域用自己的异常类型抛出，保持既有诊断输出与捕获类型。"""

        return RuleSchemaError(message)

    def __init__(
        self,
        *,
        abilities: Mapping[str, Any],
        executor_categories: Mapping[str, frozenset[str]],
        attributes: Mapping[str, Any],
        resources: Mapping[str, Any],
        events: Iterable[str],
    ) -> None:
        super().__init__(
            {
                "属性引用": attributes,
                "资源引用": resources,
                "事件引用": frozenset(str(value) for value in events),
            }
        )
        self.abilities = abilities
        self.executor_categories = executor_categories
        self.attributes = attributes
        self.resources = resources
        self.events = frozenset(str(value) for value in events)

    # ------------------------------------------------------------------ 领域扩展

    @property
    def ability_types(self) -> frozenset[str]:
        return _DOMAIN_TYPES

    @property
    def domain_field_keys(self) -> frozenset[str]:
        return _DOMAIN_KEYS

    @property
    def domain_list_keys(self) -> tuple[str, ...]:
        return _DOMAIN_LIST_KEYS

    @property
    def domain_constraint_keys(self) -> frozenset[str]:
        return frozenset({"数组执行器数量"})

    def collect_unknown_field_type(
        self,
        value: Any,
        spec: Mapping[str, Any],
        path: str,
    ) -> bool:
        """处理战斗领域字段类型；返回 False 表示该类型不属于本领域。"""

        field_type = str(spec["类型"])
        if field_type == "能力":
            self.validate_node(
                value,
                path,
                allowed_categories=spec.get("允许类别"),
                allowed_abilities=spec.get("允许能力"),
                allowed_executors=spec.get("允许执行器"),
            )
            return True
        if field_type == "能力数组":
            for index, child in enumerate(self._list(value, path, spec)):
                self.validate_node(
                    child,
                    f"{path}[{index}]",
                    allowed_categories=spec.get("允许类别"),
                    allowed_abilities=spec.get("允许能力"),
                    allowed_executors=spec.get("允许执行器"),
                )
            return True
        if field_type == "数值或能力":
            if isinstance(value, bool):
                raise RuleSchemaError(f"{path}：不能是布尔值")
            if isinstance(value, int | float):
                self._number(value, path, spec)
            else:
                self.validate_node(
                    value,
                    path,
                    allowed_categories=spec.get("允许类别", ["数值"]),
                    allowed_abilities=spec.get("允许能力"),
                    allowed_executors=spec.get("允许执行器"),
                )
            return True
        if field_type in _REFERENCE_TYPES:
            self._validate_reference(field_type, value, spec, path)
            return True
        if field_type == "属性数值表":
            values = self._object(value, path)
            self.item_count(values, spec, path)
            for attribute, amount in values.items():
                if attribute not in self.attributes:
                    raise RuleSchemaError(f"{path}.{attribute}：未知战斗属性")
                self._number(amount, f"{path}.{attribute}", {})
            return True
        if field_type == "属性构成":
            values = self._object(value, path)
            allowed = {"木", "火", "土", "金", "水", "无相"}
            if not values or len(values) > 3 or not set(values) <= allowed:
                raise RuleSchemaError(f"{path}：属性构成必须包含1至3种正式属性")
            total = 0.0
            for attribute, amount in values.items():
                self._number(amount, f"{path}.{attribute}", {"最小": 0})
                total += float(amount)
            if abs(total - 100.0) > 1e-6:
                raise RuleSchemaError(f"{path}：属性构成总和必须为100")
            return True
        return False

    def validate_domain_field_links(self, spec: Mapping[str, Any], path: str) -> None:
        """校验字段规格里的类别、执行器、原子能力引用是否成立。"""

        for category in spec.get("允许类别", []):
            if category not in _CATEGORIES:
                raise RuleSchemaError(f"{path}.允许类别：未知类别 {category}")
        for ability in spec.get("允许能力", []):
            if ability not in self.abilities:
                raise RuleSchemaError(f"{path}.允许能力：未知原子能力 {ability}")
        for executor in (*spec.get("允许执行器", []), *spec.get("目标执行器", [])):
            if executor not in self.executor_categories:
                raise RuleSchemaError(f"{path}：未知执行器 {executor}")
        for category in spec.get("目标类别", []):
            if category not in _CATEGORIES:
                raise RuleSchemaError(f"{path}.目标类别：未知类别 {category}")

    def validate_definition(self, definition: Mapping[str, Any], path: str) -> None:
        """校验类别与执行器：执行器必须存在且能用于该类别。"""

        category = self._nonempty_string(definition.get("类别"), f"{path}.类别")
        if category not in _CATEGORIES:
            raise RuleSchemaError(f"{path}.类别：未知类别 {category}")
        executor = self._nonempty_string(definition.get("执行器"), f"{path}.执行器")
        accepted = self.executor_categories.get(executor)
        if accepted is None:
            raise RuleSchemaError(f"{path}.执行器：战斗核心没有执行器 {executor}")
        if category not in accepted:
            raise RuleSchemaError(f"{path}.执行器：{executor} 不能用于 {category} 类能力")

    # ------------------------------------------------------------------ 公开入口

    def validate_definitions(self, path: str = "rules/战斗/原子能力.json -> 原子能力") -> None:
        super().validate_definitions(self.abilities, path)

    def validate_node(
        self,
        raw_node: Any,
        path: str,
        *,
        allowed_categories: Iterable[str] | None = None,
        allowed_abilities: Iterable[str] | None = None,
        allowed_executors: Iterable[str] | None = None,
    ) -> None:
        """校验一个能力节点：必须引用已声明原子能力，且字段满足其契约。

        卡里可以只写「模板 + 参数」，但模板引用在**装载期**就已展开
        （见 `service._expand_build_entities`），所以这里拿到的一定是完整的树。
        """

        node = self._object(raw_node, path)
        ability_name = self._nonempty_string(node.get("能力"), f"{path}.能力")
        if ability_name not in self.abilities:
            raise RuleSchemaError(f"{path}.能力：未知原子能力 {ability_name}")
        definition = dict(self.abilities[ability_name])
        category = self._nonempty_string(definition.get("类别"), f"{path}.类别")
        executor = self._nonempty_string(definition.get("执行器"), f"{path}.执行器")
        self.allow_value(category, allowed_categories, path, "能力类别")
        self.allow_value(executor, allowed_executors, path, "能力执行器")
        self.allow_value(ability_name, allowed_abilities, path, "原子能力")
        # `能力` 是节点的结构键，排在其它字段之前校验，使其错误信息优先出现。
        fields = dict(self._object(definition.get("字段", {}), f"{path} 的字段规则"))
        fields["能力"] = {"类型": "字符串", "必填": True}
        self.validate_object(node, fields, path)
        self.validate_constraints(node, definition.get("约束", []), path)

    def category_of(self, node: Mapping[str, Any], path: str) -> str:
        ability_name = str(node.get("能力") or "")
        return str(dict(self.abilities.get(ability_name) or {}).get("类别") or "")

    def executor_of(self, node: Mapping[str, Any], path: str) -> str:
        ability_name = str(node.get("能力") or "")
        return str(dict(self.abilities.get(ability_name) or {}).get("执行器") or "")

    def validate_constraint_spec(
        self,
        raw_constraint: Any,
        path: str,
        fields: Mapping[str, Any],
    ) -> None:
        """在通用约束之上补充「数组执行器数量」。"""

        super().validate_constraint_spec(raw_constraint, path, fields)
        constraint = dict(raw_constraint)
        count_rule = constraint.get("数组执行器数量")
        if count_rule is None:
            return
        value = self._object(count_rule, f"{path}.数组执行器数量")
        if set(value) - {"字段", "执行器", "最少", "最多"}:
            self._unknown_fields(
                f"{path}.数组执行器数量", set(value) - {"字段", "执行器", "最少", "最多"}
            )
        field_name = self._nonempty_string(value.get("字段"), f"{path}.数组执行器数量.字段")
        if field_name not in fields or fields[field_name].get("类型") != "能力数组":
            raise RuleSchemaError(f"{path}.数组执行器数量.字段：必须引用能力数组")
        executor = self._nonempty_string(value.get("执行器"), f"{path}.数组执行器数量.执行器")
        if executor not in self.executor_categories:
            raise RuleSchemaError(f"{path}.数组执行器数量.执行器：未知执行器 {executor}")
        minimum = value.get("最少", 0)
        maximum = value.get("最多", 2**31 - 1)
        if (
            isinstance(minimum, bool)
            or isinstance(maximum, bool)
            or not isinstance(minimum, int)
            or not isinstance(maximum, int)
            or minimum < 0
            or maximum < minimum
        ):
            raise RuleSchemaError(f"{path}.数组执行器数量：数量边界必须是递增的非负整数")

    def validate_constraints(
        self,
        node: Mapping[str, Any],
        constraints: Iterable[Any],
        path: str,
    ) -> None:
        """通用条件必填 + 战斗的「数组执行器数量」。"""

        super().validate_constraints(node, constraints, path)
        for raw_constraint in constraints:
            constraint = dict(raw_constraint)
            if not self._condition_matches(node, constraint.get("当")):
                continue
            count_rule = constraint.get("数组执行器数量")
            if count_rule is None:
                continue
            count_spec = dict(count_rule)
            field_name = str(count_spec["字段"])
            executor = str(count_spec["执行器"])
            values = node.get(field_name) or []
            count = sum(
                self.executor_of(value, f"{path}.{field_name}") == executor
                for value in values
            )
            minimum = int(count_spec.get("最少", 0))
            maximum = int(count_spec.get("最多", 2**31 - 1))
            if not minimum <= count <= maximum:
                raise RuleSchemaError(
                    f"{path}.{field_name}：执行器 {executor} 的数量必须在 {minimum} 至 {maximum} 之间"
                )

    # ------------------------------------------------------------------ 引用

    def _validate_reference(
        self,
        field_type: str,
        value: Any,
        spec: Mapping[str, Any],
        path: str,
    ) -> None:
        reference = self._nonempty_string(value, path)
        if not self.resolve_reference(field_type, reference):
            raise RuleSchemaError(
                f"{path}：未知{self.reference_label(field_type)} {reference}"
            )
        self._choice(reference, spec, path)


__all__ = ["RuleSchemaError", "RuleSchemaValidator"]
