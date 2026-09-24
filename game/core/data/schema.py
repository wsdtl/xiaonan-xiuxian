"""字段契约（schema）的通用校验引擎。

项目用 JSON 里的字段契约描述正式数据允许的形状，再由各领域服务在启动时校验。
`data/战斗/定义/原子能力.json` 是现有规模最大的一份契约，本模块把它依赖的
**语法层**抽出来，使契约不再只能由单个服务私有实现：

- **通用**：原始类型、容器、数值与数组约束、选项、未知字段、字段规格自校验、
  引用表驱动、对象递归；
- **领域扩展**：领域通过 `collect_unknown_field_type`、`validate_domain_field`、
  `validate_domain_field_links`、`domain_field_keys` 和 `ability_types` 注入自己的
  类型名、规格键与引用表，基类不出现任何领域字面量。

字段契约的书写约定见 `data/schema编写规范.md`。

错误信息保留完整配置路径（例如 `战斗定义.原子能力.主动技能.字段.释放顺序.类型`），
数据作者据此可直接定位到具体文件与键。
"""

from __future__ import annotations


from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .contracts import JsonDataError

#: 数字判据的候选类型元组。
#:
#: **不要写成 `isinstance(value, int | float)`**：`int | float` 是每次求值都新建一个
#: `UnionType` 的表达式，热路径上（实测一次启动要校验 28 万个字段）纯属白做。
_NUMBER_TYPES = (int, float)


class SchemaError(JsonDataError):
    """数据不符合已声明的字段契约。

    继承 `JsonDataError`：契约违规与"数据不存在/越界"属于同一类失败，调用方
    原有的 `except JsonDataError` 仍然覆盖它。
    """


class SchemaValidator:
    """理解字段契约语法的通用校验器，不理解任何具体领域概念。"""

    @classmethod
    def _error(cls, message: str) -> SchemaError:
        """构造本领域使用的异常。

        用 `cls` 而非固定类型，子类便可用自己的异常类型（例如战斗的
        `RuleSchemaError`）抛出，错误信息里的类名与调用方的捕获类型都不变。
        """

        return SchemaError(message)

    #: 基类内置的字段类型；领域类型由 `ability_types` 追加。
    _BUILTIN_FIELD_TYPES = frozenset(
        {
            "字符串",
            "数字",
            "整数",
            "布尔",
            "字符串数组",
            "对象",
            "任意",
            "任意数组",
        }
    )
    #: 基类内置的字段规格键；领域键由 `domain_field_keys` 追加。
    _BUILTIN_FIELD_KEYS = frozenset(
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
            "字段",
        }
    )

    def __init__(self, reference_tables: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self.reference_tables: dict[str, Mapping[str, Any]] = dict(reference_tables or {})

    # ------------------------------------------------------------------ 领域扩展点

    @property
    def ability_types(self) -> frozenset[str]:
        """领域额外支持的字段类型名。"""

        return frozenset()

    @property
    def domain_field_keys(self) -> frozenset[str]:
        """领域额外支持的字段规格键。"""

        return frozenset()

    @property
    def field_types(self) -> frozenset[str]:
        return self._BUILTIN_FIELD_TYPES | self.ability_types

    @property
    def field_keys(self) -> frozenset[str]:
        return self._BUILTIN_FIELD_KEYS | self.domain_field_keys

    def collect_unknown_field_type(
        self,
        value: Any,
        spec: Mapping[str, Any],
        path: str,
    ) -> bool:
        """领域字段类型的校验入口；返回 True 表示已处理该类型。"""

        return False

    def validate_domain_field_links(self, spec: Mapping[str, Any], path: str) -> None:
        """校验领域字段规格里对领域编号的引用是否成立。"""

    # ------------------------------------------------------------------ 字段与对象

    def validate_field_spec(self, raw_spec: Any, path: str) -> None:
        """校验一条字段规格自身是否合法（不是校验数据）。"""

        spec = self._object(raw_spec, path)
        unknown = set(spec) - self.field_keys
        if unknown:
            self._unknown_fields(path, unknown)
        field_type = self._nonempty_string(spec.get("类型"), f"{path}.类型")
        if field_type not in self.field_types:
            raise self._error(f"{path}.类型：未知字段类型 {field_type}")
        for key in ("必填", "唯一", "允许空"):
            if key in spec and not isinstance(spec[key], bool):
                raise self._error(f"{path}.{key}：必须是布尔值")
        for key in ("最小", "最大"):
            if key in spec and (
                isinstance(spec[key], bool) or not isinstance(spec[key], int | float)
            ):
                raise self._error(f"{path}.{key}：必须是数字")
        for key in ("最少项", "最多项"):
            if key in spec and (
                isinstance(spec[key], bool)
                or not isinstance(spec[key], int)
                or spec[key] < 0
            ):
                raise self._error(f"{path}.{key}：必须是非负整数")
        if "最小" in spec and "最大" in spec and float(spec["最小"]) > float(spec["最大"]):
            raise self._error(f"{path}：最小值不能大于最大值")
        if "最少项" in spec and "最多项" in spec and int(spec["最少项"]) > int(spec["最多项"]):
            raise self._error(f"{path}：最少项不能大于最多项")
        for key in ("选项", *self.domain_list_keys):
            if key in spec:
                values = spec[key]
                if not isinstance(values, list) or any(
                    not isinstance(value, str) or not value for value in values
                ):
                    raise self._error(f"{path}.{key}：必须是非空字符串数组")
        if field_type == "对象":
            fields = self._object(spec.get("字段"), f"{path}.字段")
            for field_name, child_spec in fields.items():
                self.validate_field_spec(child_spec, f"{path}.字段.{field_name}")
        elif "字段" in spec:
            raise self._error(f"{path}.字段：只有对象类型可以声明子字段")
        if "默认" in spec:
            self.validate_field(spec["默认"], spec, f"{path}.默认")

    @property
    def domain_list_keys(self) -> tuple[str, ...]:
        """领域额外声明的"非空字符串数组"型规格键。"""

        return ()

    @property
    def domain_constraint_keys(self) -> frozenset[str]:
        """领域额外支持的约束键。"""

        return frozenset()

    def validate_field(self, value: Any, spec: Mapping[str, Any], path: str) -> None:
        """按一条字段规格校验数据值。"""

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
                raise self._error(f"{path}：必须是布尔值")
        elif field_type == "字符串数组":
            values = self._list(value, path, spec)
            result = [
                self._nonempty_string(item, f"{path}[{index}]")
                for index, item in enumerate(values)
            ]
            if spec.get("唯一", True) and len(result) != len(set(result)):
                raise self._error(f"{path}：不能重复")
            for index, item in enumerate(result):
                self._choice(item, spec, f"{path}[{index}]")
        elif field_type == "对象":
            fields = self._object(spec.get("字段", {}), f"{path} 的字段规则")
            self.validate_object(value, fields, path)
        elif field_type == "任意":
            return
        elif field_type == "任意数组":
            self._list(value, path, spec)
        elif not self.collect_unknown_field_type(value, spec, path):
            raise self._error(f"{path}：规则使用了未知字段类型 {field_type}")

    def validate_object(
        self,
        value: Any,
        fields: Mapping[str, Any],
        path: str,
    ) -> None:
        """校验一个对象是否满足声明的子字段规则。"""

        result = self._object(value, path)
        # 两边都是 `dict` 时直接用键视图相减：省掉 `set(result)` 与 `set(fields)` 两次
        # 建集合。实测一次启动要过 7.3 万个对象，而字段表在节点间高度重复。
        if type(result) is dict and type(fields) is dict:
            unknown = result.keys() - fields.keys()
        else:
            unknown = set(result) - set(fields)
        if unknown:
            self._unknown_fields(path, unknown)
        for field_name, raw_spec in fields.items():
            # 字段规格是**只读**的（`validate_field` 及其下游只取值、不改写），所以已经是
            # 普通字典时不必再复制一份——实测一次启动有 28 万次字段校验。
            spec = raw_spec if type(raw_spec) is dict else dict(raw_spec)
            if field_name not in result:
                if spec.get("必填") and "默认" not in spec:
                    raise self._error(f"{path}.{field_name}：缺少字段")
                continue
            self.validate_field(result[field_name], spec, f"{path}.{field_name}")

    def validate_constraints(
        self,
        node: Mapping[str, Any],
        constraints: Iterable[Any],
        path: str,
    ) -> None:
        """校验条件约束（例如某条件下必须填写的字段）。"""

        for raw_constraint in constraints:
            constraint = dict(raw_constraint)
            if not self._condition_matches(node, constraint.get("当")):
                continue
            for field_name in constraint.get("必填", []):
                if field_name not in node:
                    raise self._error(f"{path}.{field_name}：当前条件下必须填写")

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

    def validate_declared_fields(
        self,
        value: Any,
        required: Iterable[str],
        optional: Iterable[str] = (),
        path: str = "",
        *,
        detailed: Mapping[str, Any] | None = None,
        discriminator: str = "类型",
    ) -> None:
        """按「必填字段 / 可选字段」声明校验一个对象。

        这是项目里已有的轻量契约写法（见 `data/物品/基础物品/定义/使用效果.json`）：
        只声明字段集合，不声明每个字段的类型。类型与取值仍由各领域服务在读取时
        校验，本方法负责**字段集合**这一层，并让未知字段与缺必填字段显式失败。

        `detailed` 是可选的类型级补充：形如 `{字段名: 字段规格}`，同名键以它为准，
        因此字段清单与类型声明可以写在同一个契约里而不互相覆盖。

        `discriminator` 是契约条目自身的判别键（数据里也有、但不属于「字段」），
        默认 `类型`；不需要时传空串。
        """

        required_names = tuple(str(name) for name in required)
        optional_names = tuple(str(name) for name in optional)
        specs: dict[str, dict[str, Any]] = {
            name: {"类型": "任意", "必填": True} for name in required_names
        }
        specs.update({name: {"类型": "任意"} for name in optional_names if name not in specs})
        # 详细类型声明补充类型信息，但**不得取消字段清单已声明的必填性**：
        # 清单里列为必填的字段，详细规格也必须视为必填。
        for name, raw_spec in dict(detailed or {}).items():
            spec = dict(raw_spec)
            key = str(name)
            if key in required_names:
                spec["必填"] = True
            elif "必填" not in spec and key in specs:
                spec["必填"] = specs[key].get("必填", False)
            specs[key] = spec
        if discriminator:
            specs.setdefault(discriminator, {"类型": "字符串", "必填": True})
        self.validate_object(value, specs, path)

    # ------------------------------------------------------------------ 引用

    def resolve_reference(self, field_type: str, token: str) -> bool:
        """判断引用是否指向引用表里存在的项。"""

        table = self.reference_tables.get(field_type)
        if table is None:
            return False
        return token in table

    def reference_label(self, field_type: str) -> str:
        """引用类型在错误信息里的名称，默认去掉「引用」后缀。"""

        return field_type.removesuffix("引用")

    # ------------------------------------------------------------------ 基础断言

    def allow_value(self,
        value: str,
        allowed: Iterable[str] | None,
        path: str,
        label: str,
    ) -> None:
        if allowed is None:
            return
        # 允许清单几乎每次都是 `tuple`/`list`（来自字段规格），逐项 `str()` 建集合纯属白做；
        # 先按键序列分派，只有真出现非字符串项时才退回「先转字符串再比」的老路
        # （实测一次启动要过 20.9 万次，其中 `{str(item) for item in allowed}` 占大头）。
        # 清单是生成器时这一趟只判一次，之后那个集合可能不含已取出的项——所以只对
        # **序列**用这条快路，生成器等其它可迭代对象照旧。
        if (type(allowed) is tuple or type(allowed) is list) and value in allowed:
            return
        if value in {str(item) for item in allowed}:
            return
        raise self._error(f"{path}：{label} {value} 不在当前节点允许范围内")

    def _choice(self, value: Any, spec: Mapping[str, Any], path: str) -> None:
        choices = spec.get("选项")
        if choices is not None and value not in choices:
            raise self._error(f"{path}：可选值为 " + "、".join(str(item) for item in choices))

    def _list(self, value: Any, path: str, spec: Mapping[str, Any]) -> list[Any]:
        if not isinstance(value, list):
            raise self._error(f"{path}：必须是数组")
        self.item_count(value, spec, path)
        return value

    def item_count(self, value: Any, spec: Mapping[str, Any], path: str) -> None:
        count = len(value)
        if "最少项" in spec and count < int(spec["最少项"]):
            raise self._error(f"{path}：至少需要 {spec['最少项']} 项")
        if "最多项" in spec and count > int(spec["最多项"]):
            raise self._error(f"{path}：最多允许 {spec['最多项']} 项")

    def _object(self, value: Any, path: str) -> dict[str, Any]:
        """要求 `value` 是对象，并交付可变副本。

        正式 JSON 快照是不可变映射（`mappingproxy`），因此这里接受任何
        `Mapping` 而不是只认 `dict`；传入 `dict` 时返回同一对象，行为不变。

        `dict` 是绝大多数调用（快照经 `materialize` 之后树里只有 `dict`），先按具体类型
        短路，省掉每个对象一次 `Mapping` 抽象基类的实例检查。
        """

        if type(value) is dict:
            return value
        if not isinstance(value, Mapping):
            raise self._error(f"{path}：必须是对象")
        return value if isinstance(value, dict) else dict(value)

    def _string(self, value: Any, path: str, *, allow_empty: bool) -> str:
        """要求字符串并返回去掉首尾空白的那份。

        先按 `type(value) is str` 短路（正式数据里的字符串一律是真 `str`），
        `strip()` 只算一次——原先判空与返回各算一次，实测一次启动要过 37 万次。
        """

        if type(value) is not str and not isinstance(value, str):
            raise self._error(
                f"{path}：必须是非空字符串" if not allow_empty else f"{path}：必须是字符串"
            )
        result = value.strip()
        if not allow_empty and not result:
            raise self._error(f"{path}：必须是非空字符串")
        return result

    def _nonempty_string(self, value: Any, path: str) -> str:
        return self._string(value, path, allow_empty=False)

    def _string_list(self, value: Any, path: str) -> tuple[str, ...]:
        """要求一个不重复的非空字符串数组，用于契约里的字段清单声明。"""

        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise self._error(f"{path}：必须是字符串数组")
        names = tuple(str(item).strip() for item in value)
        if any(not name for name in names) or len(names) != len(set(names)):
            raise self._error(f"{path}：不能为空或重复")
        return names

    def _number(self, value: Any, path: str, spec: Mapping[str, Any]) -> float:
        if isinstance(value, bool) or not isinstance(value, _NUMBER_TYPES):
            raise self._error(f"{path}：必须是数字")
        result = float(value)
        if "最小" in spec and result < float(spec["最小"]):
            raise self._error(f"{path}：不能小于 {spec['最小']}")
        if "最大" in spec and result > float(spec["最大"]):
            raise self._error(f"{path}：不能大于 {spec['最大']}")
        self._choice(value, spec, path)
        return result

    def _integer(self, value: Any, path: str, spec: Mapping[str, Any]) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise self._error(f"{path}：必须是整数")
        self._number(value, path, spec)
        return value

    def _unknown_fields(self, path: str, values: Iterable[str]) -> None:
        raise self._error(
            f"{path}：规则不认识字段 " + "、".join(sorted(str(value) for value in values))
        )


class DefinitionSchemaValidator(SchemaValidator):
    """按「名称 -> 定义」形式的字段契约校验一组定义。

    定义的公共形状是 `{说明?, 字段, 约束?}`；`entry_keys` 声明该形式允许的顶层键，
    `validate_definition` 由领域补充自己的顶层语义（例如类别与执行器）。
    """

    #: 定义对象允许的顶层键；领域可扩展。
    entry_keys = frozenset({"说明", "字段", "约束"})

    def validate_definitions(self, definitions: Mapping[str, Any], path: str) -> None:
        """校验全部定义；空定义集视为配置缺失。"""

        if not definitions:
            raise self._error(f"{path}：不能为空")
        for name, raw_definition in definitions.items():
            entry_path = f"{path}.{name}"
            definition = self._object(raw_definition, entry_path)
            unknown = set(definition) - set(self.entry_keys)
            if unknown:
                self._unknown_fields(entry_path, unknown)
            if "说明" in definition:
                self._nonempty_string(definition.get("说明"), f"{entry_path}.说明")
            self.validate_definition(definition, entry_path)
            fields = self._object(definition.get("字段", {}), f"{entry_path}.字段")
            for field_name, raw_spec in fields.items():
                self.validate_field_spec(raw_spec, f"{entry_path}.字段.{field_name}")
            constraints = definition.get("约束", [])
            if not isinstance(constraints, list):
                raise self._error(f"{entry_path}.约束：必须是数组")
            for index, constraint in enumerate(constraints):
                self.validate_constraint_spec(
                    constraint, f"{entry_path}.约束[{index}]", fields
                )

        # 第二遍：此时全部字段规格已自校验，可以安全解析跨定义引用。
        for name, raw_definition in definitions.items():
            fields = dict(raw_definition).get("字段", {})
            for field_name, raw_spec in fields.items():
                self.validate_field_links(
                    raw_spec, f"{path}.{name}.字段.{field_name}"
                )

    def validate_definition(self, definition: Mapping[str, Any], path: str) -> None:
        """领域可覆盖：校验定义的顶层语义。"""

    def validate_field_links(self, raw_spec: Any, path: str) -> None:
        """校验字段规格里对定义名和其他编号的引用是否成立。"""

        spec = dict(raw_spec)
        self.validate_domain_field_links(spec, path)
        for field_name, child_spec in dict(spec.get("字段") or {}).items():
            self.validate_field_links(child_spec, f"{path}.字段.{field_name}")

    def validate_constraint_spec(
        self,
        raw_constraint: Any,
        path: str,
        fields: Mapping[str, Any],
    ) -> None:
        """校验一条约束自身的合法性。"""

        constraint = self._object(raw_constraint, path)
        unknown = set(constraint) - {"当", "必填"} - set(self.domain_constraint_keys)
        if unknown:
            self._unknown_fields(path, unknown)
        condition = self._object(constraint.get("当", {}), f"{path}.当")
        condition_unknown = set(condition) - {"字段", "存在", "等于", "属于"}
        if condition_unknown:
            self._unknown_fields(f"{path}.当", condition_unknown)
        if condition:
            field_name = self._nonempty_string(condition.get("字段"), f"{path}.当.字段")
            if field_name not in fields:
                raise self._error(f"{path}.当.字段：未知字段 {field_name}")
            if "存在" in condition and not isinstance(condition["存在"], bool):
                raise self._error(f"{path}.当.存在：必须是布尔值")
            if "属于" in condition and not isinstance(condition["属于"], list):
                raise self._error(f"{path}.当.属于：必须是数组")
        required = constraint.get("必填", [])
        if not isinstance(required, list) or any(value not in fields for value in required):
            raise self._error(f"{path}.必填：必须引用已声明字段")


class ContractSet:
    """一组「必填字段 / 可选字段」形式的实体字段契约。

    领域把契约写在 `data/<组件>/定义/<名称>.json`，形如：

    ```json
    [
      {
        "类别": "境界",
        "必填字段": ["编号", "名称", "等级下限", "等级上限"],
        "可选字段": ["下一境界"],
        "字段": { "等级下限": { "类型": "整数", "最小": 1 } }
      }
    ]
    ```

    `类别` 是该条契约适用的对象名（通常是实体类别），`字段` 是可选的类型级补充。
    服务在初始化时载入契约并校验自己拥有的全部实体，字段缺陷即阻止启动。
    """

    def __init__(self, entries: Mapping[str, tuple[tuple[str, ...], tuple[str, ...], Mapping[str, Any]]]) -> None:
        self._entries = dict(entries)

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(self._entries)

    def __contains__(self, category: object) -> bool:
        return str(category) in self._entries

    @classmethod
    def from_dataset(cls, document: Any, path: str) -> ContractSet:
        """从数据集文档载入。

        契约可以有两种登记方式：以「字典列表」声明时文档本身就是条目数组；
        以「对象」声明时按数据名取同名字段契约（例如 `世界/定义/*.json` 下与其他
        定义并列的字段契约）。数据集只含一份契约时自动解包。
        """

        if isinstance(document, Mapping):
            if "字段契约" in document:
                document = document["字段契约"]
            elif len(document) == 1:
                document = next(iter(document.values()))
        return cls.load(document, path)

    @classmethod
    def load(cls, document: Any, path: str) -> ContractSet:
        """从一份「字典列表」契约文档载入。

        `document` 由调用方通过 `JsonDataService.dataset()` 取得。
        """

        validator = SchemaValidator()
        if not isinstance(document, Sequence) or isinstance(document, (str, bytes)):
            raise SchemaError(f"{path} 必须是字典列表")
        entries: dict[str, tuple[tuple[str, ...], tuple[str, ...], Mapping[str, Any]]] = {}
        for index, raw in enumerate(document):
            entry = validator._object(raw, f"{path}[{index}]")
            unknown = set(entry) - {"类别", "必填字段", "可选字段", "字段", "说明"}
            if unknown:
                raise SchemaError(
                    f"{path}[{index}]：契约不认识键 "
                    + "、".join(sorted(str(value) for value in unknown))
                )
            category = validator._nonempty_string(entry.get("类别"), f"{path}[{index}].类别")
            if category in entries:
                raise SchemaError(f"{path}：契约重复声明类别 {category}")
            required = validator._string_list(
                entry.get("必填字段", []), f"{path}[{index}].必填字段"
            )
            optional = validator._string_list(
                entry.get("可选字段", []), f"{path}[{index}].可选字段"
            )
            fields = validator._object(entry.get("字段", {}), f"{path}[{index}].字段")
            for field_name, spec in fields.items():
                validator.validate_field_spec(spec, f"{path}[{index}].字段.{field_name}")
            entries[category] = (required, optional, fields)
        if not entries:
            raise SchemaError(f"{path} 不能为空")
        return cls(entries)

    def validate(
        self,
        value: Any,
        category: str,
        path: str,
        *,
        discriminator: str = "",
    ) -> None:
        """按 `category` 的契约校验一个实体。"""

        entry = self._entries.get(str(category))
        if entry is None:
            raise SchemaError(f"{path}：没有为 {category} 声明字段契约")
        required, optional, fields = entry
        SchemaValidator().validate_declared_fields(
            value,
            required,
            optional,
            path,
            detailed=fields,
            discriminator=discriminator,
        )


__all__ = [
    "ContractSet",
    "DefinitionSchemaValidator",
    "SchemaError",
    "SchemaValidator",
]
