"""角色命令回复构造。"""

from __future__ import annotations

from game.features.chakan_juese import CharacterOverviewResult
from game.features.chuangjian_renwu import CreateCharacterResult
from message import M


def invalid_create_format():
    return (
        M.document()
        .section("创建人物")
        .line("格式：创建人物 姓名 性别（男或女）")
        .build()
    )


def create_error(message: str):
    return M.document().section("创建人物").line(message).build()


def character_exists():
    return (
        M.document()
        .section("创建人物")
        .line("你已经创建过人物，不能重复创建。")
        .build()
    )


def created(result: CreateCharacterResult):
    builder = (
        M.document()
        .header("人物创建完成")
        .section("身份")
        .row(("姓名", result.name), ("性别", result.gender))
        .row(("境界", result.realm_name), ("等级", 1))
        .section("出生地")
        .field("地点", M.command(result.location_name, "位置"))
        .row(("区域", result.region), ("地形", result.terrain))
        .row(
            ("坐标", f"{result.xy[0]}, {result.xy[1]}"),
            ("海拔", f"{result.altitude}米"),
        )
        .section("初始物资")
    )
    for index, (item_name, grade, quantity) in enumerate(result.initial_items, start=1):
        builder.item(
            index,
            M.command(item_name, f"查看 {item_name}"),
            f" · {grade} × {quantity}",
        )
    return builder.build()


def overview_error():
    return (
        M.document()
        .section("人物", icon="notice")
        .line("人物状态暂时无法读取，请稍后再试。")
        .build()
    )


def overview(result: CharacterOverviewResult):
    character = result.character
    resources = dict(character.resources)
    attributes = dict(character.attributes)
    builder = (
        M.document()
        .header(character.name)
        .section("身份", icon="status")
        .row(("性别", character.gender), ("身份", character.character_type))
        .row(("境界", character.realm_name), ("等级", character.level))
        .row(("经验", character.experience), ("灵石", character.spirit_stones))
        .field("宗门贡献", character.sect_contribution)
        .section("五行根性", icon="status")
        .row(*((element, _display_number(value)) for element, value in character.five_elements.items()))
        .section("当前状态", icon="status")
        .row(*result.states)
        .section("所在之地", icon="map")
        .field("地点", result.location_name or "野外")
        .row(("区域", result.region), ("地形", result.terrain))
        .row(
            ("坐标", f"{result.xy[0]}, {result.xy[1]}"),
            ("海拔", f"{result.altitude}米"),
        )
        .section("当前资源", icon="status")
        .row(
            (
                "血气",
                _current_and_maximum(resources, attributes, "血气"),
            ),
            (
                "精神",
                _current_and_maximum(resources, attributes, "精神"),
            ),
        )
    )
    if shield := resources.get("护盾", 0):
        builder.field("护盾", _display_number(shield))
    primary_names = (
        "攻击",
        "防御",
        "速度",
        "命中率",
        "闪避率",
        "暴击率",
        "暴击伤害",
    )
    primary = set(primary_names)
    builder.section("战斗属性", icon="skill")
    _append_pairs(
        builder,
        tuple((name, attributes[name]) for name in primary_names if name in attributes),
    )
    secondary = tuple(
        item
        for item in character.attributes
        if item[0] not in primary
        and item[0] not in {"血气上限", "精神上限"}
        and item[1] != 0
        and not (item[0] == "连击伤害" and attributes.get("连击率", 0) == 0)
    )
    if secondary:
        builder.section("其他加成", icon="status")
        _append_pairs(builder, secondary)
    if result.injuries:
        builder.section("长期伤势", icon="status")
        for index, (name, stacks) in enumerate(result.injuries, start=1):
            builder.item(index, f"{name} × {stacks}")
    else:
        builder.inline_section("伤势", "无", icon="status")
    builder.section("修行槽位", icon="skill").row(
        *(
            (category, f"{equipped}/{total}")
            for category, equipped, total in result.cultivation_usage
        )
    )
    for content in character.equipped_content:
        builder.field(
            f"{content.category}{content.slot}",
            M.text(f"{content.grade_name} · " if content.grade_name else "")
            + (M.command(content.name, f"查看 {content.content_id}"),),
        )
    if result.innate_treasure is None:
        builder.inline_section("先天灵宝", "未执掌", icon="item")
    else:
        builder.section("先天灵宝", icon="item").field(
            "槽位",
            f"{result.innate_treasure_usage[0]}/{result.innate_treasure_usage[1]}",
        )
        builder.line(
            M.command(
                result.innate_treasure.name,
                f"查看 {result.innate_treasure.treasure_id}",
            ),
            ": ",
            result.innate_treasure.authority,
        )
    weapon = character.weapon
    builder.section("本命武器", icon="weapon")
    builder.field("名称", weapon.name)
    builder.row(("器阶", weapon.stage), ("等级", weapon.level))
    builder.row(("攻击", _display_number(weapon.attack)), ("经验", weapon.experience))
    builder.field("器律", f"{len(weapon.equipped_laws)}/{weapon.open_law_slots}")
    for law in weapon.equipped_laws:
        builder.item(law.slot, M.command(law.name, f"查看 {law.content_id}"))
    builder.section("随身物资", icon="inventory").row(
        ("种类", character.inventory.stack_count),
        ("总数", character.inventory.total_quantity),
        ("自动用药", "开启" if character.automatic_medicine else "关闭"),
    )
    return builder.build()


def _append_pairs(builder, values: tuple[tuple[str, int | float], ...]) -> None:
    for index in range(0, len(values), 2):
        builder.row(
            *(
                (name, _display_stat(name, value))
                for name, value in values[index : index + 2]
            )
        )


def _display_number(value: float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _display_stat(name: str, value: float) -> str:
    rendered = _display_number(value)
    if name in {"命中率", "闪避率", "暴击率", "暴击伤害", "连击伤害"}:
        return rendered + "%"
    return rendered


def _current_and_maximum(
    resources: dict[str, int | float],
    attributes: dict[str, int | float],
    name: str,
) -> str:
    current = _display_number(resources.get(name, 0))
    maximum = _display_number(attributes.get(f"{name}上限", 0))
    return f"{current}/{maximum}"


__all__ = [
    "character_exists",
    "create_error",
    "created",
    "invalid_create_format",
    "overview",
    "overview_error",
]
