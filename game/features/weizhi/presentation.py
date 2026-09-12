"""位置展示 JSON 到玩法内部契约的严格适配。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from string import Formatter
from types import MappingProxyType

from game.core.data import JsonDataError, positive_int as _positive_int
from game.features.presentation import require_mapping

from .contracts import PositionAction, PositionCopy


@dataclass(frozen=True)
class ButtonTemplate:
    page: str
    condition: str
    function: str
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class PositionPresentation:
    meters_per_li: int
    rounding_step: int
    same_place: str
    open_functions: frozenset[str]
    directions: Mapping[tuple[int, int], str]
    copy: PositionCopy
    buttons: tuple[ButtonTemplate, ...]


def load_position_presentation(
    dataset: Mapping[str, object],
) -> PositionPresentation:
    """把完整位置展示数据集一次转换为不可变玩法配置。"""

    _require_keys(
        dataset,
        {
            "距离与方向",
            "文本",
            "图标",
            "位置",
            "附近",
            "地点功能",
            "地形功能",
        },
        "位置展示数据集",
    )
    distance_and_direction = require_mapping(
        dataset["距离与方向"], "位置/展示/规则/距离与方向.json"
    )
    _require_keys(
        distance_and_direction,
        {"距离", "同处措辞", "方向"},
        "距离与方向",
    )
    distance = require_mapping(distance_and_direction["距离"], "距离与方向.距离")
    _require_keys(distance, {"单位", "每里米数", "约数步长"}, "距离与方向.距离")
    function_buttons = _button_templates(
        dataset["地点功能"],
        "位置/展示/按钮/地点功能.json",
        function_buttons=True,
    )
    terrain_buttons = _button_templates(
        dataset["地形功能"],
        "位置/展示/按钮/地形功能.json",
        function_buttons=True,
    )
    position_buttons = _button_templates(
        dataset["位置"],
        "位置/展示/按钮/位置.json",
        default_page="位置",
    )
    nearby_buttons = _button_templates(
        dataset["附近"],
        "位置/展示/按钮/附近.json",
    )
    buttons = function_buttons + terrain_buttons + position_buttons + nearby_buttons
    identities = tuple((item.page, item.action_id) for item in buttons)
    if len(identities) != len(set(identities)):
        raise JsonDataError("位置展示存在重复的页面按钮编号")

    return PositionPresentation(
        meters_per_li=_positive_int(distance["每里米数"], "距离与方向.距离.每里米数"),
        rounding_step=_positive_int(distance["约数步长"], "距离与方向.距离.约数步长"),
        same_place=_text(distance_and_direction["同处措辞"], "距离与方向.同处措辞"),
        open_functions=frozenset(item.function for item in function_buttons),
        directions=MappingProxyType(_direction_map(distance_and_direction["方向"])),
        copy=_position_copy(dataset["文本"], dataset["图标"]),
        buttons=buttons,
    )


def render_action(
    template: ButtonTemplate, variables: Mapping[str, object]
) -> PositionAction:
    return PositionAction(
        action_id=template.action_id,
        label=template.label.format_map(variables),
        command=template.command.format_map(variables),
        behavior=template.behavior,
        style=template.style,
    )


def _direction_map(value: object) -> dict[tuple[int, int], str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError("距离与方向.方向必须是字典列表")
    result: dict[tuple[int, int], str] = {}
    for index, raw in enumerate(value):
        row = require_mapping(raw, f"距离与方向.方向[{index}]")
        offset = row.get("偏移")
        if (
            not isinstance(offset, Sequence)
            or isinstance(offset, (str, bytes))
            or len(offset) != 2
            or any(item not in {-1, 0, 1} for item in offset)
        ):
            raise JsonDataError(f"距离与方向.方向[{index}].偏移无效")
        key = (int(offset[0]), int(offset[1]))
        if key == (0, 0) or key in result:
            raise JsonDataError("位置方向不能包含原点或重复偏移")
        result[key] = _text(row.get("名称"), f"距离与方向.方向[{index}].名称")
    expected = {(x, y) for x in (-1, 0, 1) for y in (-1, 0, 1) if (x, y) != (0, 0)}
    if set(result) != expected:
        raise JsonDataError("位置方向必须完整定义八个方向")
    return result


def _position_copy(value: object, icon_value: object) -> PositionCopy:
    root = require_mapping(value, "位置/展示/规则/文本.json")
    icons = require_mapping(icon_value, "位置/展示/规则/图标.json")
    _require_keys(
        root,
        {"格式", "位置", "附近概览", "附近修士", "附近地点", "命令"},
        "位置文本",
    )
    common = require_mapping(root["格式"], "位置文本.格式")
    current = require_mapping(root["位置"], "位置文本.位置")
    overview = require_mapping(root["附近概览"], "位置文本.附近概览")
    cultivators = require_mapping(root["附近修士"], "位置文本.附近修士")
    locations = require_mapping(root["附近地点"], "位置文本.附近地点")
    command = require_mapping(root["命令"], "位置文本.命令")
    _require_keys(
        common,
        {
            "未知地点",
            "坐标",
            "海拔",
            "修士摘要",
            "修士方位",
            "同处修士方位",
            "地点摘要",
            "地点详情",
            "状态前缀",
            "状态分隔",
            "队伍状态",
            "宗门同行领队",
            "宗门同行成员",
            "同行状态冲突",
            "功能分隔",
            "无开放功能",
        },
        "位置文本.格式",
    )
    _require_keys(
        current,
        {
            "所在之地",
            "区域",
            "地形",
            "坐标",
            "海拔",
            "本地修士",
            "同行道侣",
            "人数",
        },
        "位置文本.位置",
    )
    _require_keys(
        overview,
        {
            "标题",
            "修士",
            "本地修士",
            "来往修士",
            "附近修士",
            "山河",
            "没有地点",
            "当前位置",
            "地点",
        },
        "位置文本.附近概览",
    )
    _require_keys(
        cultivators,
        {
            "标题",
            "本地修士",
            "同行道侣",
            "来往修士",
            "洞天修士",
            "没有来往修士",
            "页次",
            "当前",
            "截断提示",
            "页码无效",
            "没有此页",
        },
        "位置文本.附近修士",
    )
    _require_keys(locations, {"标题", "山河", "没有地点"}, "位置文本.附近地点")
    _require_keys(command, {"格式错误"}, "位置文本.命令")
    _require_keys(
        icons,
        {"错误", "地点", "修士", "行止", "页次"},
        "位置图标",
    )
    return PositionCopy(
        error_icon=_text(icons.get("错误"), "位置图标.错误"),
        location_icon=_text(icons.get("地点"), "位置图标.地点"),
        cultivator_icon=_text(icons.get("修士"), "位置图标.修士"),
        navigation_icon=_text(icons.get("行止"), "位置图标.行止"),
        page_icon=_text(icons.get("页次"), "位置图标.页次"),
        unknown_location=_template(
            common.get("未知地点"), "位置文本.格式.未知地点", {"区域", "地形"}
        ),
        coordinate=_template(
            common.get("坐标"), "位置文本.格式.坐标", {"横坐标", "纵坐标"}
        ),
        altitude=_template(common.get("海拔"), "位置文本.格式.海拔", {"海拔"}),
        cultivator_summary=_template(
            common.get("修士摘要"),
            "位置文本.格式.修士摘要",
            {"境界", "等级", "性别", "状态"},
        ),
        cultivator_direction=_template(
            common.get("修士方位"),
            "位置文本.格式.修士方位",
            {"方向", "距离"},
        ),
        colocated_cultivator_direction=_template(
            common.get("同处修士方位"),
            "位置文本.格式.同处修士方位",
            {"距离"},
        ),
        location_summary=_template(
            common.get("地点摘要"),
            "位置文本.格式.地点摘要",
            {"名称", "方向", "距离"},
        ),
        location_detail=_template(
            common.get("地点详情"),
            "位置文本.格式.地点详情",
            {"区域", "地形", "功能"},
        ),
        state_prefix=_template(
            common.get("状态前缀"), "位置文本.格式.状态前缀", {"状态"}
        ),
        state_separator=_text(common.get("状态分隔"), "位置文本.格式.状态分隔"),
        team_state=_template(
            common.get("队伍状态"),
            "位置文本.格式.队伍状态",
            {"人数"},
        ),
        sect_follow_leader_state=_template(
            common.get("宗门同行领队"),
            "位置文本.格式.宗门同行领队",
            {"人数"},
        ),
        sect_follow_member_state=_text(
            common.get("宗门同行成员"), "位置文本.格式.宗门同行成员"
        ),
        fellowship_conflict_state=_text(
            common.get("同行状态冲突"), "位置文本.格式.同行状态冲突"
        ),
        function_separator=_text(common.get("功能分隔"), "位置文本.格式.功能分隔"),
        no_available_function=_text(
            common.get("无开放功能"), "位置文本.格式.无开放功能"
        ),
        current_place_section=_text(current.get("所在之地"), "位置文本.位置.所在之地"),
        region_label=_text(current.get("区域"), "位置文本.位置.区域"),
        terrain_label=_text(current.get("地形"), "位置文本.位置.地形"),
        coordinate_label=_text(current.get("坐标"), "位置文本.位置.坐标"),
        altitude_label=_text(current.get("海拔"), "位置文本.位置.海拔"),
        local_cultivators_section=_text(
            current.get("本地修士"), "位置文本.位置.本地修士"
        ),
        active_companion_section=_text(
            current.get("同行道侣"), "位置文本.位置.同行道侣"
        ),
        count_label=_text(current.get("人数"), "位置文本.位置.人数"),
        overview_title=_template(
            overview.get("标题"), "位置文本.附近概览.标题", {"地点"}
        ),
        overview_cultivators_section=_text(
            overview.get("修士"), "位置文本.附近概览.修士"
        ),
        overview_local_label=_text(
            overview.get("本地修士"), "位置文本.附近概览.本地修士"
        ),
        overview_visiting_label=_text(
            overview.get("来往修士"), "位置文本.附近概览.来往修士"
        ),
        overview_nearby_label=_text(
            overview.get("附近修士"), "位置文本.附近概览.附近修士"
        ),
        overview_locations_section=_text(
            overview.get("山河"), "位置文本.附近概览.山河"
        ),
        overview_no_locations=_text(
            overview.get("没有地点"), "位置文本.附近概览.没有地点"
        ),
        overview_current_section=_text(
            overview.get("当前位置"), "位置文本.附近概览.当前位置"
        ),
        overview_current_label=_text(overview.get("地点"), "位置文本.附近概览.地点"),
        cultivators_title=_text(cultivators.get("标题"), "位置文本.附近修士.标题"),
        cultivators_local_section=_text(
            cultivators.get("本地修士"), "位置文本.附近修士.本地修士"
        ),
        cultivators_active_section=_text(
            cultivators.get("同行道侣"), "位置文本.附近修士.同行道侣"
        ),
        cultivators_visiting_section=_text(
            cultivators.get("来往修士"), "位置文本.附近修士.来往修士"
        ),
        cultivators_inside_section=_text(
            cultivators.get("洞天修士"), "位置文本.附近修士.洞天修士"
        ),
        cultivators_empty=_text(
            cultivators.get("没有来往修士"), "位置文本.附近修士.没有来往修士"
        ),
        cultivators_page_section=_text(
            cultivators.get("页次"), "位置文本.附近修士.页次"
        ),
        cultivators_current_label=_text(
            cultivators.get("当前"), "位置文本.附近修士.当前"
        ),
        cultivators_truncated=_text(
            cultivators.get("截断提示"), "位置文本.附近修士.截断提示"
        ),
        invalid_page=_text(cultivators.get("页码无效"), "位置文本.附近修士.页码无效"),
        missing_page=_text(cultivators.get("没有此页"), "位置文本.附近修士.没有此页"),
        locations_title=_text(locations.get("标题"), "位置文本.附近地点.标题"),
        locations_section=_text(locations.get("山河"), "位置文本.附近地点.山河"),
        locations_empty=_text(locations.get("没有地点"), "位置文本.附近地点.没有地点"),
        invalid_command=_text(command.get("格式错误"), "位置文本.命令.格式错误"),
    )


def _button_templates(
    value: object,
    label: str,
    *,
    default_page: str = "",
    function_buttons: bool = False,
) -> tuple[ButtonTemplate, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是字典列表")
    result: list[ButtonTemplate] = []
    for index, raw in enumerate(value):
        row = require_mapping(raw, f"{label}[{index}]")
        allowed = {"编号", "名称", "命令", "行为", "样式"}
        if function_buttons:
            allowed.add("功能")
        elif not default_page:
            allowed.update({"页面", "条件"})
        if unknown := set(row) - allowed:
            raise JsonDataError(
                f"{label}[{index}]存在未知字段：{'、'.join(sorted(unknown))}"
            )
        page = (
            "地点功能"
            if function_buttons
            else default_page or _text(row.get("页面"), f"{label}[{index}].页面")
        )
        condition = (
            ""
            if function_buttons or default_page
            else str(row.get("条件") or "").strip()
        )
        function = (
            _text(row.get("功能"), f"{label}[{index}].功能") if function_buttons else ""
        )
        if page not in {
            "地点功能",
            "位置",
            "概览",
            "修士",
            "地点",
            "地点条目",
        }:
            raise JsonDataError(f"{label}[{index}].页面无效：{page}")
        if condition not in {"", "有上一页", "有下一页", "地表"}:
            raise JsonDataError(f"{label}[{index}].条件无效：{condition}")
        expected_fields = (
            {"页码"}
            if condition in {"有上一页", "有下一页"}
            else {"地点"}
            if page == "地点条目"
            else set()
        )
        action_id = _text(row.get("编号"), f"{label}[{index}].编号")
        action_label, label_fields = _partial_template(
            row.get("名称"), f"{label}[{index}].名称", expected_fields
        )
        action_command, command_fields = _partial_template(
            row.get("命令"), f"{label}[{index}].命令", expected_fields
        )
        if label_fields | command_fields != expected_fields:
            raise JsonDataError(
                f"{label}[{index}]模板占位符必须是："
                f"{'、'.join(sorted(expected_fields)) or '无'}"
            )
        behavior = _text(row.get("行为"), f"{label}[{index}].行为")
        style = _text(row.get("样式"), f"{label}[{index}].样式")
        if behavior not in {"callback", "send", "fill", "link"}:
            raise JsonDataError(f"{label}[{index}].行为无效：{behavior}")
        if style not in {"primary", "secondary"}:
            raise JsonDataError(f"{label}[{index}].样式无效：{style}")
        result.append(
            ButtonTemplate(
                page,
                condition,
                function,
                action_id,
                action_label,
                action_command,
                behavior,
                style,
            )
        )
    functions = tuple(item.function for item in result if item.function)
    if len(functions) != len(set(functions)):
        raise JsonDataError(f"{label}不能重复定义同一地点功能")
    return tuple(result)


def _template(value: object, label: str, fields: set[str]) -> str:
    template, found = _partial_template(value, label, fields)
    if found != fields:
        raise JsonDataError(f"{label}占位符必须是：{'、'.join(sorted(fields)) or '无'}")
    return template


def _partial_template(
    value: object, label: str, allowed_fields: set[str]
) -> tuple[str, set[str]]:
    template = _text(value, label)
    found: set[str] = set()
    try:
        for _, field_name, format_spec, conversion in Formatter().parse(template):
            if field_name is None:
                continue
            if not field_name or format_spec or conversion:
                raise ValueError
            found.add(field_name)
    except ValueError as exc:
        raise JsonDataError(f"{label}包含无效模板") from exc
    if not found <= allowed_fields:
        raise JsonDataError(
            f"{label}只能使用占位符：{'、'.join(sorted(allowed_fields)) or '无'}"
        )
    return template, found


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JsonDataError(f"{label}必须是非空字符串")
    return value.strip()


def _require_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) == expected:
        return
    missing = expected - set(value)
    unknown = set(value) - expected
    details: list[str] = []
    if missing:
        details.append(f"缺少 {'、'.join(sorted(missing))}")
    if unknown:
        details.append(f"多出 {'、'.join(sorted(unknown))}")
    raise JsonDataError(f"{label}字段不完整：{'；'.join(details)}")
