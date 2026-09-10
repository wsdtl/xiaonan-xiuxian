"""由 JSON 字段规则驱动的通用能力树校验器。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


class RuleSchemaError(ValueError):
    """原子能力定义或能力树不符合声明规则。"""


class RuleSchemaValidator:
    """只理解 DSL 语法，不理解任何具体战斗能力。"""

    _CATEGORIES = frozenset({"装配", "引用", "组合", "触发", "数值", "目标", "条件", "效果"})
    _FIELD_TYPES = frozenset(
        {
            "字符串",
            "数字",
            "整数",
            "布尔",
            "字符串数组",
            "对象",
            "能力",
            "能力数组",
            "数值或能力",
            "属性引用",
            "资源引用",
            "事件引用",
            "机制引用",
            "属性数值表",
            "属性构成",
            "任意",
            "任意数组",
        }
    )
    _FIELD_KEYS = frozenset(
        {
            "类型",
            "必填",
            "默认",
            "选项",
            "最小",
            "最大",
            "最少项",
            "最多项",
            "唯一",
            "允许空",
            "允许类别",
            "允许能力",
            "允许执行器",
            "字段",
            "目标类别",
            "目标执行器",
        }
    )

    def __init__(
        self,
        *,
        abilities: Mapping[str, Any],
        executor_categories: Mapping[str, frozenset[str]],
        attributes: Mapping[str, Any],
        resources: Mapping[str, Any],
        events: Iterable[str],
        mechanisms: Mapping[str, Any],
    ) -> None:
        self.abilities = abilities
        self.executor_categories = executor_categories
        self.attributes = attributes
        self.resources = resources
        self.events = frozenset(str(value) for value in events)
        self.mechanisms = mechanisms

    def validate_definitions(self, path: str = "rules/战斗/原子能力.json -> 原子能力") -> None:
        if not self.abilities:
            raise RuleSchemaError(f"{path}：不能为空")
        for ability_name, raw_definition in self.abilities.items():
            ability_path = f"{path}.{ability_name}"
            definition = self._object(raw_definition, ability_path)
            unknown = set(definition) - {"类别", "执行器", "说明", "字段", "约束"}
            if unknown:
                self._unknown_fields(ability_path, unknown)
            category = self._nonempty_string(definition.get("类别"), f"{ability_path}.类别")
            if category not in self._CATEGORIES:
                raise RuleSchemaError(f"{ability_path}.类别：未知类别 {category}")
            executor = self._nonempty_string(definition.get("执行器"), f"{ability_path}.执行器")
            accepted = self.executor_categories.get(executor)
            if accepted is None:
                raise RuleSchemaError(f"{ability_path}.执行器：战斗核心没有执行器 {executor}")
            if category not in accepted:
                raise RuleSchemaError(
                    f"{ability_path}.执行器：{executor} 不能用于 {category} 类能力"
                )
            if "说明" in definition:
                self._nonempty_string(definition.get("说明"), f"{ability_path}.说明")
            fields = self._object(definition.get("字段", {}), f"{ability_path}.字段")
            for field_name, raw_spec in fields.items():
                self._validate_field_spec(raw_spec, f"{ability_path}.字段.{field_name}")
            constraints = definition.get("约束", [])
            if not isinstance(constraints, list):
                raise RuleSchemaError(f"{ability_path}.约束：必须是数组")
            for index, constraint in enumerate(constraints):
                self._validate_constraint_spec(
                    constraint,
                    f"{ability_path}.约束[{index}]",
                    fields,
                )

        for ability_name, raw_definition in self.abilities.items():
            fields = dict(raw_definition).get("字段", {})
            for field_name, raw_spec in fields.items():
                self._validate_field_links(
                    raw_spec,
                    f"{path}.{ability_name}.字段.{field_name}",
                )

    def validate_mechanisms(self, path: str = "战斗机制") -> None:
        if not self.mechanisms:
            raise RuleSchemaError(f"{path}：不能为空")
        for mechanism_id, node in self.mechanisms.items():
            self.validate_node(node, f"{path}.{mechanism_id}")
        self._validate_reference_cycles(path)

    def validate_node(
        self,
        raw_node: Any,
        path: str,
        *,
        allowed_categories: Iterable[str] | None = None,
        allowed_abilities: Iterable[str] | None = None,
        allowed_executors: Iterable[str] | None = None,
    ) -> str:
        node = self._object(raw_node, path)
        ability_name = self._nonempty_string(node.get("能力"), f"{path}.能力")
        definition = self.abilities.get(ability_name)
        if definition is None:
            raise RuleSchemaError(f"{path}.能力：未知原子能力 {ability_name}")
        category = str(definition["类别"])
        executor = str(definition["执行器"])
        self._allow_value(category, allowed_categories, f"{path}.能力", "类别")
        self._allow_value(ability_name, allowed_abilities, f"{path}.能力", "能力")
        self._allow_value(executor, allowed_executors, f"{path}.能力", "执行器")

        fields = dict(definition.get("字段") or {})
        unknown = set(node) - {"能力"} - set(fields)
        if unknown:
            self._unknown_fields(path, unknown)
        for field_name, raw_spec in fields.items():
            spec = dict(raw_spec)
            field_path = f"{path}.{field_name}"
            if field_name not in node:
                if spec.get("必填") and "默认" not in spec:
                    raise RuleSchemaError(f"{field_path}：缺少字段")
                continue
            self._validate_field(node[field_name], spec, field_path)
        self._validate_constraints(node, definition.get("约束") or (), path)
        return executor

    def executor_of(self, raw_node: Any, path: str = "能力节点") -> str:
        node = self._object(raw_node, path)
        ability_name = self._nonempty_string(node.get("能力"), f"{path}.能力")
        definition = self.abilities.get(ability_name)
        if definition is None:
            raise RuleSchemaError(f"{path}.能力：未知原子能力 {ability_name}")
        return str(definition["执行器"])

    def category_of(self, raw_node: Any, path: str = "能力节点") -> str:
        node = self._object(raw_node, path)
        ability_name = self._nonempty_string(node.get("能力"), f"{path}.能力")
        definition = self.abilities.get(ability_name)
        if definition is None:
            raise RuleSchemaError(f"{path}.能力：未知原子能力 {ability_name}")
        return str(definition["类别"])

    def _validate_field(self, value: Any, spec: Mapping[str, Any], path: str) -> None:
        field_type = str(spec["类型"])
        if field_type == "字符串":
            result = self._string(value, path, allow_empty=bool(spec.get("允许空", False)))
            self._choice(result, spec, path)
        elif field_type == "数字":
            self._number(value, path, spec)
        elif field_type == "整数":
            self._integer(value, path, spec)
        elif field_type == "布尔":
            if not isinstance(value, bool):
                raise RuleSchemaError(f"{path}：必须是布尔值")
        elif field_type == "字符串数组":
            values = self._list(value, path, spec)
            result = [self._nonempty_string(item, f"{path}[{index}]") for index, item in enumerate(values)]
            if spec.get("唯一", True) and len(result) != len(set(result)):
                raise RuleSchemaError(f"{path}：不能重复")
            for index, item in enumerate(result):
                self._choice(item, spec, f"{path}[{index}]")
        elif field_type == "对象":
            fields = self._object(spec.get("字段", {}), f"{path} 的字段规则")
            self._validate_object(value, fields, path)
        elif field_type == "能力":
            self.validate_node(
                value,
                path,
                allowed_categories=spec.get("允许类别"),
                allowed_abilities=spec.get("允许能力"),
                allowed_executors=spec.get("允许执行器"),
            )
        elif field_type == "能力数组":
            values = self._list(value, path, spec)
            for index, child in enumerate(values):
                self.validate_node(
                    child,
                    f"{path}[{index}]",
                    allowed_categories=spec.get("允许类别"),
                    allowed_abilities=spec.get("允许能力"),
                    allowed_executors=spec.get("允许执行器"),
                )
        elif field_type == "数值或能力":
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
        elif field_type in {"属性引用", "资源引用", "事件引用", "机制引用"}:
            reference = self._nonempty_string(value, path)
            self._validate_reference(field_type, reference, spec, path)
        elif field_type == "属性数值表":
            values = self._object(value, path)
            self._item_count(values, spec, path)
            for attribute, amount in values.items():
                if attribute not in self.attributes:
                    raise RuleSchemaError(f"{path}.{attribute}：未知战斗属性")
                self._number(amount, f"{path}.{attribute}", {})
        elif field_type == "属性构成":
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
        elif field_type == "任意":
            return
        elif field_type == "任意数组":
            self._list(value, path, spec)
        else:
            raise RuleSchemaError(f"{path}：规则使用了未知字段类型 {field_type}")

    def _validate_object(self, value: Any, fields: Mapping[str, Any], path: str) -> None:
        result = self._object(value, path)
        unknown = set(result) - set(fields)
        if unknown:
            self._unknown_fields(path, unknown)
        for field_name, raw_spec in fields.items():
            spec = dict(raw_spec)
            field_path = f"{path}.{field_name}"
            if field_name not in result:
                if spec.get("必填") and "默认" not in spec:
                    raise RuleSchemaError(f"{field_path}：缺少字段")
                continue
            self._validate_field(result[field_name], spec, field_path)

    def _validate_reference(
        self,
        field_type: str,
        reference: str,
        spec: Mapping[str, Any],
        path: str,
    ) -> None:
        sources = {
            "属性引用": self.attributes,
            "资源引用": self.resources,
            "事件引用": self.events,
            "机制引用": self.mechanisms,
        }
        if reference not in sources[field_type]:
            raise RuleSchemaError(f"{path}：未知{field_type.removesuffix('引用')} {reference}")
        if field_type != "机制引用":
            self._choice(reference, spec, path)
            return
        target_path = f"战斗机制 -> {reference}.节点"
        target = self._object(self.mechanisms[reference], target_path)
        target_category = self.category_of(target, target_path)
        target_executor = self.executor_of(target, target_path)
        self._allow_value(target_category, spec.get("目标类别"), path, "机制类别")
        self._allow_value(target_executor, spec.get("目标执行器"), path, "机制执行器")

    def _validate_constraints(
        self,
        node: Mapping[str, Any],
        constraints: Iterable[Any],
        path: str,
    ) -> None:
        for index, raw_constraint in enumerate(constraints):
            constraint = dict(raw_constraint)
            if not self._condition_matches(node, constraint.get("当")):
                continue
            for field_name in constraint.get("必填", []):
                if field_name not in node:
                    raise RuleSchemaError(f"{path}.{field_name}：当前条件下必须填写")
            count_rule = constraint.get("数组执行器数量")
            if count_rule is not None:
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

    @staticmethod
    def _condition_matches(node: Mapping[str, Any], raw_condition: Any) -> bool:
        if not raw_condition:
            return True
        condition = dict(raw_condition)
        field_name = str(condition.get("字段") or "")
        present = field_name in node
        if "存在" in condition and present != bool(condition["存在"]):
            return False
        if not present:
            return False
        if "等于" in condition and node[field_name] != condition["等于"]:
            return False
        return "属于" not in condition or node[field_name] in condition["属于"]

    def _validate_field_spec(self, raw_spec: Any, path: str) -> None:
        spec = self._object(raw_spec, path)
        unknown = set(spec) - self._FIELD_KEYS
        if unknown:
            self._unknown_fields(path, unknown)
        field_type = self._nonempty_string(spec.get("类型"), f"{path}.类型")
        if field_type not in self._FIELD_TYPES:
            raise RuleSchemaError(f"{path}.类型：未知字段类型 {field_type}")
        for key in ("必填", "唯一", "允许空"):
            if key in spec and not isinstance(spec[key], bool):
                raise RuleSchemaError(f"{path}.{key}：必须是布尔值")
        for key in ("最小", "最大"):
            if key in spec and (isinstance(spec[key], bool) or not isinstance(spec[key], int | float)):
                raise RuleSchemaError(f"{path}.{key}：必须是数字")
        for key in ("最少项", "最多项"):
            if key in spec and (isinstance(spec[key], bool) or not isinstance(spec[key], int) or spec[key] < 0):
                raise RuleSchemaError(f"{path}.{key}：必须是非负整数")
        if "最小" in spec and "最大" in spec and float(spec["最小"]) > float(spec["最大"]):
            raise RuleSchemaError(f"{path}：最小值不能大于最大值")
        if "最少项" in spec and "最多项" in spec and int(spec["最少项"]) > int(spec["最多项"]):
            raise RuleSchemaError(f"{path}：最少项不能大于最多项")
        for key in ("选项", "允许类别", "允许能力", "允许执行器", "目标类别", "目标执行器"):
            if key in spec:
                values = spec[key]
                if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
                    raise RuleSchemaError(f"{path}.{key}：必须是非空字符串数组")
        if field_type == "对象":
            fields = self._object(spec.get("字段"), f"{path}.字段")
            for field_name, child_spec in fields.items():
                self._validate_field_spec(child_spec, f"{path}.字段.{field_name}")
        elif "字段" in spec:
            raise RuleSchemaError(f"{path}.字段：只有对象类型可以声明子字段")
        if "默认" in spec:
            self._validate_field(spec["默认"], spec, f"{path}.默认")

    def _validate_field_links(self, raw_spec: Any, path: str) -> None:
        spec = dict(raw_spec)
        for category in spec.get("允许类别", []):
            if category not in self._CATEGORIES:
                raise RuleSchemaError(f"{path}.允许类别：未知类别 {category}")
        for ability in spec.get("允许能力", []):
            if ability not in self.abilities:
                raise RuleSchemaError(f"{path}.允许能力：未知原子能力 {ability}")
        for executor in (*spec.get("允许执行器", []), *spec.get("目标执行器", [])):
            if executor not in self.executor_categories:
                raise RuleSchemaError(f"{path}：未知执行器 {executor}")
        for category in spec.get("目标类别", []):
            if category not in self._CATEGORIES:
                raise RuleSchemaError(f"{path}.目标类别：未知类别 {category}")
        for field_name, child_spec in dict(spec.get("字段") or {}).items():
            self._validate_field_links(child_spec, f"{path}.字段.{field_name}")

    def _validate_constraint_spec(
        self,
        raw_constraint: Any,
        path: str,
        fields: Mapping[str, Any],
    ) -> None:
        constraint = self._object(raw_constraint, path)
        unknown = set(constraint) - {"当", "必填", "数组执行器数量"}
        if unknown:
            self._unknown_fields(path, unknown)
        condition = self._object(constraint.get("当", {}), f"{path}.当")
        condition_unknown = set(condition) - {"字段", "存在", "等于", "属于"}
        if condition_unknown:
            self._unknown_fields(f"{path}.当", condition_unknown)
        if condition:
            field_name = self._nonempty_string(condition.get("字段"), f"{path}.当.字段")
            if field_name not in fields:
                raise RuleSchemaError(f"{path}.当.字段：未知字段 {field_name}")
            if "存在" in condition and not isinstance(condition["存在"], bool):
                raise RuleSchemaError(f"{path}.当.存在：必须是布尔值")
            if "属于" in condition and not isinstance(condition["属于"], list):
                raise RuleSchemaError(f"{path}.当.属于：必须是数组")
        required = constraint.get("必填", [])
        if not isinstance(required, list) or any(value not in fields for value in required):
            raise RuleSchemaError(f"{path}.必填：必须引用已声明字段")
        count_rule = constraint.get("数组执行器数量")
        if count_rule is not None:
            value = self._object(count_rule, f"{path}.数组执行器数量")
            if set(value) - {"字段", "执行器", "最少", "最多"}:
                self._unknown_fields(
                    f"{path}.数组执行器数量",
                    set(value) - {"字段", "执行器", "最少", "最多"},
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

    def _validate_reference_cycles(self, path: str) -> None:
        graph = {
            str(mechanism_id): set(self._mechanism_references(node))
            for mechanism_id, node in self.mechanisms.items()
        }
        visiting: list[str] = []
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                start = visiting.index(name)
                chain = " -> ".join((*visiting[start:], name))
                raise RuleSchemaError(f"{path}：机制引用形成循环 {chain}")
            visiting.append(name)
            for child in graph.get(name, ()):
                visit(child)
            visiting.pop()
            visited.add(name)

        for mechanism_id in graph:
            visit(mechanism_id)

    def _mechanism_references(self, raw_node: Any) -> Iterable[str]:
        node = dict(raw_node)
        ability_name = str(node.get("能力") or "")
        definition = dict(self.abilities.get(ability_name) or {})
        for field_name, raw_spec in dict(definition.get("字段") or {}).items():
            if field_name not in node:
                continue
            spec = dict(raw_spec)
            field_type = spec.get("类型")
            value = node[field_name]
            if field_type == "机制引用":
                if isinstance(value, Mapping):
                    yield str(value.get("编号") or "")
                else:
                    yield str(value)
            elif field_type == "能力":
                yield from self._mechanism_references(value)
            elif field_type == "能力数组":
                for child in value:
                    yield from self._mechanism_references(child)
            elif field_type == "数值或能力" and isinstance(value, Mapping):
                yield from self._mechanism_references(value)
            elif field_type == "对象":
                yield from self._object_mechanism_references(value, dict(spec.get("字段") or {}))

    def _object_mechanism_references(
        self,
        raw_value: Any,
        fields: Mapping[str, Any],
    ) -> Iterable[str]:
        value = dict(raw_value)
        for field_name, raw_spec in fields.items():
            if field_name not in value:
                continue
            spec = dict(raw_spec)
            field_type = spec.get("类型")
            child = value[field_name]
            if field_type == "机制引用":
                yield str(child)
            elif field_type == "能力":
                yield from self._mechanism_references(child)
            elif field_type == "能力数组":
                for node in child:
                    yield from self._mechanism_references(node)
            elif field_type == "对象":
                yield from self._object_mechanism_references(child, dict(spec.get("字段") or {}))

    @staticmethod
    def _allow_value(value: str, allowed: Iterable[str] | None, path: str, label: str) -> None:
        if allowed is not None and value not in {str(item) for item in allowed}:
            raise RuleSchemaError(f"{path}：{label} {value} 不在当前节点允许范围内")

    @staticmethod
    def _choice(value: Any, spec: Mapping[str, Any], path: str) -> None:
        choices = spec.get("选项")
        if choices is not None and value not in choices:
            raise RuleSchemaError(f"{path}：可选值为 " + "、".join(str(item) for item in choices))

    @staticmethod
    def _list(value: Any, path: str, spec: Mapping[str, Any]) -> list[Any]:
        if not isinstance(value, list):
            raise RuleSchemaError(f"{path}：必须是数组")
        RuleSchemaValidator._item_count(value, spec, path)
        return value

    @staticmethod
    def _item_count(value: Any, spec: Mapping[str, Any], path: str) -> None:
        count = len(value)
        if "最少项" in spec and count < int(spec["最少项"]):
            raise RuleSchemaError(f"{path}：至少需要 {spec['最少项']} 项")
        if "最多项" in spec and count > int(spec["最多项"]):
            raise RuleSchemaError(f"{path}：最多允许 {spec['最多项']} 项")

    @staticmethod
    def _object(value: Any, path: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise RuleSchemaError(f"{path}：必须是对象")
        return value

    @staticmethod
    def _string(value: Any, path: str, *, allow_empty: bool) -> str:
        if not isinstance(value, str) or (not allow_empty and not value.strip()):
            raise RuleSchemaError(f"{path}：必须是非空字符串" if not allow_empty else f"{path}：必须是字符串")
        return value.strip()

    @staticmethod
    def _nonempty_string(value: Any, path: str) -> str:
        return RuleSchemaValidator._string(value, path, allow_empty=False)

    @staticmethod
    def _number(value: Any, path: str, spec: Mapping[str, Any]) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise RuleSchemaError(f"{path}：必须是数字")
        result = float(value)
        if "最小" in spec and result < float(spec["最小"]):
            raise RuleSchemaError(f"{path}：不能小于 {spec['最小']}")
        if "最大" in spec and result > float(spec["最大"]):
            raise RuleSchemaError(f"{path}：不能大于 {spec['最大']}")
        RuleSchemaValidator._choice(value, spec, path)
        return result

    @staticmethod
    def _integer(value: Any, path: str, spec: Mapping[str, Any]) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuleSchemaError(f"{path}：必须是整数")
        RuleSchemaValidator._number(value, path, spec)
        return value

    @staticmethod
    def _unknown_fields(path: str, values: Iterable[str]) -> None:
        raise RuleSchemaError(f"{path}：规则不认识字段 " + "、".join(sorted(str(value) for value in values)))
