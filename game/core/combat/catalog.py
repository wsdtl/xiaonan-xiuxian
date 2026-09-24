"""战报 JSON 的只读内存目录。"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
#: `_derived` 的「没缓存」哨兵：缓存里可能合法地存 `None`。
_MISSING = object()

_UI_TEXT_FIELDS = {
    "brand_suffix": "品牌后缀",
    "settlement_label": "结算标题",
    "archive_kicker": "归档眉题",
    "archive_title": "归档标题",
    "more_summary": "更多结算",
    "segment_label": "片段标题",
    "segment_select_label": "选择片段",
    "previous_segment_label": "上一片段",
    "next_segment_label": "下一片段",
    "participant_panel_title": "参战者面板",
    "comparison_title": "状态对比",
    "comparison_empty": "状态无变化",
    "empty_timeline": "空时间线",
    "empty_filter": "空筛选",
    "empty_participants": "空参战者",
    "loading_events": "读取全部事件",
    "loading_participants": "读取参战者",
    "loading_comparison": "读取状态对比",
    "switching_segment": "切换片段中",
    "switched_segment": "切换片段完成",
    "segment_load_failed": "片段读取失败",
    "events_loading": "全部事件读取中",
    "participants_loading": "参战者读取中",
    "unsupported_detail": "明细协议不支持",
    "participant_fallback": "参战者默认名称",
    "versus_label": "对阵分隔",
    "additional_team_template": "多方参战",
}


@dataclass(frozen=True, slots=True)
class BattleReportCatalog:
    """校验一次战报配置，后续标准化和展示只查询这个目录。"""

    raw: Mapping[str, Any]
    #: 属性定义（`属性.json`）。战报的 `属性摘要` 只列「与基准不同」的属性，
    #: 而基准是每个属性自己的事（加成类 100、减免类 0），所以要把定义一起带进来，
    #: 不能把「不等于 0」写死。
    attributes: Mapping[str, Mapping[str, Any]] = dataclass_field(default_factory=dict)
    #: 记录事实名单的缓存（见 `recorded_facts`）：它每条事件都要查一次。
    _record_cache: frozenset[str] | None = dataclass_field(
        default=None, init=False, repr=False, compare=False
    )
    #: 派生量缓存（见 `_derived`）：`标准化` / `展示` 下的名单与定义都是**只读** `raw`
    #: 上的纯函数，而一份战报构建会把同一份名单取上千次——15 对 15 的 `events` 视图
    #: 实测 `内部明细` 取 4707 次、`伤害事实` 取 4001 次，每次都从原始配置重算一遍
    #: frozenset。与 `recorded_facts` 同一手法：算一次就存住。
    #: 缓存里只放**不可变值**（frozenset / tuple / `raw` 自己的子对象）。
    _derived_cache: dict[str, Any] = dataclass_field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def _derived(self, key: str, compute: Callable[[], Any]) -> Any:
        """取一个从只读 `raw` 上算出来的派生量；同一次装载里只算一次。"""

        cache = self._derived_cache
        value = cache.get(key, _MISSING)
        if value is _MISSING:
            value = compute()
            cache[key] = value
        return value

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        attributes: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> BattleReportCatalog:
        raw = deepcopy(dict(value))
        catalog = cls(raw, dict(attributes or {}))
        catalog._validate()
        return catalog

    def attribute_baseline(self, key: str) -> float:
        """这个属性的基准值（不增不减的那个值）；未登记时按 0。"""

        return float(dict(self.attributes.get(key) or {}).get("默认值", 0.0))

    def attribute_caliber(self, key: str) -> str:
        """这个属性的口径（`数值` / `加成` / `倍率` / `概率` / `减免` / `比率`）。"""

        return str(dict(self.attributes.get(key) or {}).get("口径") or "")

    @property
    def report_schema(self) -> str:
        return str(self.protocol["战报"])

    @property
    def presentation_schema(self) -> str:
        return str(self.protocol["展示"])

    @property
    def presentation_version(self) -> int:
        return int(self.protocol["展示版本"])

    @property
    def game_name(self) -> str:
        return str(self.raw["游戏名称"])

    @property
    def protocol(self) -> Mapping[str, Any]:
        return self._derived("protocol", lambda: _mapping(self.raw, "协议"))

    @property
    def visual(self) -> Mapping[str, Any]:
        return self._derived("visual", lambda: _mapping(self.raw, "视觉"))

    @property
    def normalization(self) -> Mapping[str, Any]:
        return self._derived("normalization", lambda: _mapping(self.raw, "标准化"))

    @property
    def presentation(self) -> Mapping[str, Any]:
        return self._derived("presentation", lambda: _mapping(self.raw, "展示"))

    @property
    def system(self) -> Mapping[str, Any]:
        value = _mapping(self.visual, "系统")
        return {"name": value["名称"], "color": value["颜色"]}

    @property
    def foreground(self) -> str:
        return str(self.visual["前景色"])

    @property
    def participant_colors(self) -> tuple[str, ...]:
        return tuple(str(value) for value in _sequence(self.visual, "参战者颜色"))

    @property
    def resources(self) -> Mapping[str, Mapping[str, Any]]:
        return {
            str(resource_id): {
                "label": definition["名称"],
                "color": definition["颜色"],
                "tone": definition["色调"],
                "presentation": definition["呈现"],
            }
            for resource_id, definition in _mapping(self.visual, "资源").items()
        }

    @property
    def category_definitions(self) -> tuple[Mapping[str, Any], ...]:
        return self._derived(
            "category_definitions",
            lambda: tuple(
                {
                    "id": definition["标识"],
                    "label": definition["名称"],
                    "color": definition["颜色"],
                    "tone": definition["色调"],
                    "priority": int(definition["优先级"]),
                }
                for value in _sequence(self.normalization, "分类")
                for definition in (_mapping_value(value, "标准化.分类"),)
            ),
        )

    @property
    def ui(self) -> dict[str, Any]:
        interface = _mapping(self.presentation, "界面")
        text = _mapping(interface, "文案")
        return {
            "text": {
                field: str(text[source])
                for field, source in _UI_TEXT_FIELDS.items()
            },
            "modes": _options(interface, "模式"),
            "filters": [
                {"id": value["id"], "label": value["label"]}
                for value in self.category_definitions
            ],
            "snapshots": _options(interface, "快照"),
            "defaults": {
                "mode": str(interface["默认模式"]),
                "filter": str(interface["默认筛选"]),
                "snapshot": str(interface["默认快照"]),
            },
        }

    @property
    def compact_hidden_kinds(self) -> frozenset[str]:
        return self._derived(
            "compact_hidden_kinds", lambda: _strings(self.normalization, "紧凑隐藏类型")
        )

    @property
    def internal_details(self) -> frozenset[str]:
        """不该进战报的明细标签：引擎的记账字段与内部编号。

        `事件` 只是把类型名抄一遍，`来源 / 承受者 / 行动者 / 目标ID / 对象ID` 是
        `L1`、`L1:战斗对象:1` 这样的内部编号，`原始数值 / 当前数值` 多数时候是 0，
        `状态定义` 是整个状态对象。它们并排印在事件行上时，一句「青云剑修 命中 霜岭客」
        后面跟着七个记账字段——**玩家要看的是战斗，不是引擎的账本**。
        """

        return self._derived(
            "internal_details", lambda: _strings(self.normalization, "内部明细")
        )

    @property
    def compact_facts(self) -> dict[str, tuple[tuple[str, ...], ...]]:
        """简要模式每行带出哪些事实：`事件类型 -> ((标签,), (前, 后), …)`。

        一个条目是「取哪个明细标签」；写两个标签表示要把「前 → 后」连起来。
        `_compact_text` 按序取第一个有值的，拼成 `类型名 · 事实`。
        """

        return self._derived(
            "compact_facts",
            lambda: {
                str(kind): tuple(
                    (str(entry),)
                    if isinstance(entry, str)
                    else tuple(str(name) for name in entry)
                    for entry in entries
                )
                for kind, entries in _mapping(self.normalization, "紧凑事实")[
                    "类型"
                ].items()
            },
        )

    @property
    def system_kinds(self) -> frozenset[str]:
        return self._derived(
            "system_kinds", lambda: _strings(self.normalization, "系统类型")
        )

    @property
    def percent_details(self) -> frozenset[str]:
        return self._derived(
            "percent_details", lambda: _strings(self.normalization, "百分比明细")
        )

    @property
    def multiplier_details(self) -> frozenset[str]:
        return self._derived(
            "multiplier_details", lambda: _strings(self.normalization, "倍率明细")
        )

    @property
    def percent_attributes(self) -> frozenset[str]:
        return self._derived(
            "percent_attributes", lambda: _strings(self.normalization, "百分比属性")
        )

    @property
    def attribute_summary(self) -> tuple[str, ...]:
        return self._derived(
            "attribute_summary",
            lambda: tuple(_strings_in_order(self.normalization, "属性摘要")),
        )

    @property
    def recorded_facts(self) -> frozenset[str]:
        """进战斗日志的事实键（`标准化.记录事实.保留`）。

        引擎在**记录那一刻**就按它筛：不在名单上的键既不进事件、也不进战报与存储。
        名单之外还有一份 `丢弃`，那是「明确想过、决定不记」的键——判据靠它对账，
        引擎不看它（`保留` 是唯一闸门）。每条事件都要查一次，所以算一次就缓存住。
        """

        cached = self._record_cache
        if cached is None:
            cached = _strings(_mapping(self.normalization, "记录事实"), "保留")
            object.__setattr__(self, "_record_cache", cached)
        return cached

    @property
    def dropped_facts(self) -> frozenset[str]:
        """明确决定**不记**的事实键（`标准化.记录事实.丢弃`）：记账字段与中间过程。"""

        return self._derived(
            "dropped_facts",
            lambda: _strings(_mapping(self.normalization, "记录事实"), "丢弃"),
        )

    @property
    def damage_facts(self) -> frozenset[str]:
        return self._derived(
            "damage_facts", lambda: _strings(self.presentation, "伤害事实")
        )

    @property
    def event_fields(self) -> frozenset[str]:
        """展示协议里一个事件**只许有**这些字段（`协议.事件字段`）。

        展示包是发给页面的载荷，字段多一个就多一份重复的重量（`logical_time` 每条事件
        抄一遍同一串时间、`subject` 抄一遍同样的能力名），而页面从来不读。判据
        （`检查战报展示`）按这份名单核实际载荷，多一个少一个都红。
        """

        return self._derived("event_fields", lambda: _strings(self.protocol, "事件字段"))

    @property
    def fact_fields(self) -> frozenset[str]:
        """展示协议里一条事实**只许有**这些字段（`协议.事实字段`）。"""

        return self._derived("fact_fields", lambda: _strings(self.protocol, "事实字段"))

    @property
    def participant_fields(self) -> frozenset[str]:
        """快照里的参战者记录**只许有**这些字段（`协议.参战者字段`）：只留会变的那一半。"""

        return self._derived(
            "participant_fields", lambda: _strings(self.protocol, "参战者字段")
        )

    @property
    def roster_fields(self) -> frozenset[str]:
        """花名册里一条档案**只许有**这些字段（`协议.花名册字段`）：不变的那一半。"""

        return self._derived(
            "roster_fields", lambda: _strings(self.protocol, "花名册字段")
        )

    def settlement_kinds(self, category: str) -> frozenset[str]:
        values = _mapping(self.normalization, "结算事件")
        return frozenset(
            str(value) for value in _sequence(values, str(category))
        )

    @property
    def view_modes(self) -> list[dict[str, Any]]:
        return _options(self.normalization, "查看模式")

    @property
    def participant_presentation(self) -> Mapping[str, Any]:
        value = _mapping(self.presentation, "参战者")
        status = _mapping(value, "状态组")
        return {
            "状态组": {
                "id": status["标识"],
                "label": status["名称"],
                "presentation": status["呈现"],
                "empty_text": status["空内容"],
            },
            "详情标题": value["详情标题"],
            "详情分组": deepcopy(dict(_mapping(value, "详情分组"))),
        }

    def normalized_category(self, kind: str) -> str:
        mapping = _mapping(self.normalization, "类型分类")
        return str(mapping.get(kind) or self.normalization["默认分类"])

    def normalized_category_definition(self, category_id: str) -> Mapping[str, Any]:
        for value in self.category_definitions:
            if value["id"] == category_id:
                return value
        raise KeyError(f"战报配置没有分类：{category_id}")

    def kind_label(self, kind: str) -> str:
        return str(_mapping(self.normalization, "类型名称").get(kind) or kind)

    def public_category(self, kind: str, normalized_category: str) -> str:
        direct = _mapping(self.presentation, "类型分类")
        return str(direct.get(kind) or normalized_category)

    def event_tone(self, category: str, kind: str) -> str:
        direct = _mapping(self.presentation, "类型色调")
        return str(
            direct.get(kind)
            or self.normalized_category_definition(category)["tone"]
            or self.presentation["默认色调"]
        )

    def dominant_tone(self, categories: Sequence[str]) -> str:
        present = set(categories)
        definitions = sorted(
            self.category_definitions,
            key=lambda value: int(value["priority"]),
            reverse=True,
        )
        for definition in definitions:
            if definition["id"] in present:
                return str(definition["tone"])
        return str(self.presentation["默认色调"])

    def resource_key(self, label: str) -> str | None:
        value = _mapping(self.presentation, "资源键").get(label)
        return str(value) if value is not None else None

    def status_tone(self, category: str) -> str:
        return str(
            _mapping(self.presentation, "状态色调").get(category)
            or self.presentation["默认状态色调"]
        )

    def result_tone(self, code: str) -> str:
        return str(
            _mapping(self.presentation, "结果色调").get(code)
            or self.presentation["默认结果色调"]
        )

    def _validate(self) -> None:
        if not self.report_schema.strip() or not self.presentation_schema.strip():
            raise ValueError("战报配置缺少协议名称")
        if self.presentation_version < 1:
            raise ValueError("战报展示版本必须是正整数")
        if not self.game_name.strip():
            raise ValueError("战报配置缺少游戏名称")
        if not _COLOR.fullmatch(self.foreground):
            raise ValueError("战报前景色必须是六位十六进制颜色")
        if not self.participant_colors:
            raise ValueError("战报至少需要一种参战者颜色")
        for color in (*self.participant_colors, str(self.system["color"])):
            if not _COLOR.fullmatch(color):
                raise ValueError(f"战报颜色不合法：{color}")
        category_ids = [str(value.get("id") or "") for value in self.category_definitions]
        if len(category_ids) != len(set(category_ids)) or not all(category_ids):
            raise ValueError("战报标准分类标识不能为空或重复")
        default_category = str(self.normalization["默认分类"])
        if default_category not in category_ids:
            raise ValueError("战报默认分类没有对应定义")
        settlement = _mapping(self.normalization, "结算事件")
        required_settlements = {
            "角色伤害",
            "战场伤害",
            "资源恢复",
            "资源消耗",
            "状态添加",
            "状态移除",
        }
        if set(settlement) != required_settlements:
            raise ValueError("战报结算事件类别不完整")
        for key in required_settlements:
            if not _strings(settlement, key):
                raise ValueError(f"战报结算事件不能为空：{key}")
        for resource_id in ("health", "spirit", "shield"):
            definition = _mapping(self.resources, resource_id)
            if not str(definition.get("label") or "").strip():
                raise ValueError(f"战报资源缺少名称：{resource_id}")
            if not _COLOR.fullmatch(str(definition.get("color") or "")):
                raise ValueError(f"战报资源颜色不合法：{resource_id}")
        ui = _mapping(self.presentation, "界面")
        for key in ("文案", "模式", "快照", "默认模式", "默认筛选", "默认快照"):
            if key not in ui:
                raise ValueError(f"战报界面配置缺少：{key}")
        missing_text = set(_UI_TEXT_FIELDS.values()) - set(_mapping(ui, "文案"))
        if missing_text:
            raise ValueError("战报界面文案不完整：" + "、".join(sorted(missing_text)))
        mode_ids = {value["id"] for value in _options(ui, "模式")}
        snapshot_ids = {value["id"] for value in _options(ui, "快照")}
        if str(ui["默认模式"]) not in mode_ids:
            raise ValueError("战报默认模式没有对应定义")
        if str(ui["默认筛选"]) not in category_ids:
            raise ValueError("战报默认筛选没有对应定义")
        if str(ui["默认快照"]) not in snapshot_ids:
            raise ValueError("战报默认快照没有对应定义")
        hidden = self.compact_hidden_kinds
        known_kinds = set(_mapping(self.normalization, "类型分类"))
        for kind, entries in self.compact_facts.items():
            # 声明的类型必须是真事件，也不能声明「本来就不会出现在简要模式」的类型：
            # 两种写错都只会安静地不生效，等于没有声明。
            if kind not in known_kinds:
                raise ValueError(f"战报紧凑事实声明了未知事件类型：{kind}")
            if kind in hidden:
                raise ValueError(f"战报紧凑事实声明了被隐藏的事件类型：{kind}")
            for entry in entries:
                if not entry or len(entry) > 2 or not all(name.strip() for name in entry):
                    raise ValueError(f"战报紧凑事实条目不合法：{kind}")
        self._validate_records()

    def _validate_records(self) -> None:
        """记录名单要自洽：保留与丢弃不重叠，屏上不显示的账也不该记。"""

        recorded = self.recorded_facts
        dropped = self.dropped_facts
        both = recorded & dropped
        if both:
            raise ValueError("战报记录事实同时写在保留与丢弃里：" + "、".join(sorted(both)))
        if not recorded:
            raise ValueError("战报记录事实的保留名单不能为空")
        shown = self.internal_details - dropped
        if shown:
            raise ValueError(
                "战报内部明细必须也在丢弃名单里（屏上不显示的账别记）："
                + "、".join(sorted(shown))
            )
        must_record = self.damage_facts | self.percent_details | self.multiplier_details
        for kind, entries in self.compact_facts.items():
            must_record |= {name for entry in entries for name in entry}
        missing = must_record - recorded
        if missing:
            raise ValueError(
                "战报要显示的事实没在记录名单里（会渲染成空）：" + "、".join(sorted(missing))
            )
        if not self.event_fields or not self.fact_fields:
            raise ValueError(
                "战报协议缺少展示字段名单（`协议.事件字段` / `协议.事实字段`）："
                "展示载荷靠它对账，缺了就没人管「多发字段」这件事了"
            )
        if not self.participant_fields or not self.roster_fields:
            raise ValueError(
                "战报协议缺少参战者字段名单（`协议.参战者字段` / `协议.花名册字段`）："
                "快照与花名册的分工靠它对账"
            )

    def validate_event_kinds(self, event_kinds: Sequence[str]) -> None:
        declared = {str(value) for value in event_kinds}
        categories = set(_mapping(self.normalization, "类型分类"))
        labels = set(_mapping(self.normalization, "类型名称"))
        missing_categories = declared - categories
        missing_labels = declared - labels
        unknown_categories = categories - declared
        unknown_labels = labels - declared
        if missing_categories or missing_labels or unknown_categories or unknown_labels:
            details = []
            if missing_categories:
                details.append("缺少分类：" + "、".join(sorted(missing_categories)))
            if missing_labels:
                details.append("缺少名称：" + "、".join(sorted(missing_labels)))
            if unknown_categories:
                details.append("废弃分类：" + "、".join(sorted(unknown_categories)))
            if unknown_labels:
                details.append("废弃名称：" + "、".join(sorted(unknown_labels)))
            raise ValueError("战报事件映射与战斗事件定义不一致；" + "；".join(details))
        settlement = _mapping(self.normalization, "结算事件")
        unknown_settlements = {
            str(kind)
            for values in settlement.values()
            for kind in values
            if str(kind) not in declared
        }
        if unknown_settlements:
            raise ValueError(
                "战报结算事件未在战斗事件中定义："
                + "、".join(sorted(unknown_settlements))
            )


def _mapping(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    return _mapping_value(value.get(key), key)


def _mapping_value(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"战报配置必须是对象：{path}")
    return value


def _sequence(value: Mapping[str, Any], key: str) -> Sequence[Any]:
    result = value.get(key)
    if not isinstance(result, list | tuple):
        raise TypeError(f"战报配置必须是数组：{key}")
    return result


def _strings(value: Mapping[str, Any], key: str) -> frozenset[str]:
    return frozenset(_strings_in_order(value, key))


def _strings_in_order(value: Mapping[str, Any], key: str) -> tuple[str, ...]:
    result = tuple(str(item) for item in _sequence(value, key))
    if any(not item.strip() for item in result):
        raise ValueError(f"战报配置不能包含空值：{key}")
    return result


def _options(value: Mapping[str, Any], key: str) -> list[dict[str, str]]:
    result = []
    for raw in _sequence(value, key):
        option = _mapping_value(raw, key)
        option_id = str(option.get("标识") or "").strip()
        label = str(option.get("名称") or "").strip()
        if not option_id or not label:
            raise ValueError(f"战报选项缺少标识或名称：{key}")
        result.append({"id": option_id, "label": label})
    if len({value["id"] for value in result}) != len(result):
        raise ValueError(f"战报选项标识重复：{key}")
    return result
