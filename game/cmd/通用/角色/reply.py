"""角色命令回复构造。"""

from __future__ import annotations

from message import DocumentBuilder, DocumentMessage, M

from game.features.chakan_juese import CharacterOverviewResult
from game.features.chuangjian_renwu import CreateCharacterResult


def invalid_create_format() -> DocumentMessage:
    return (
        M.document()
        .section("创建人物")
        .line(
            M.status("格式有误", tone="warning"),
            " 创建人物 姓名 性别（男或女）[种族]",
        )
        .line(M.status("提示", tone="info"), " 种族可省略，省略时用基准族人族")
        .build()
    )


def create_error(message: str) -> DocumentMessage:
    return (
        M.document()
        .section("创建人物", icon="notice")
        .line(M.status("创建失败", tone="danger"), " ", message)
        .build()
    )


def character_exists() -> DocumentMessage:
    return (
        M.document()
        .section("创建人物")
        .line(M.status("已有角色", tone="warning"), " 不能重复创建人物。")
        .build()
    )


def created(result: CreateCharacterResult) -> DocumentMessage:
    builder = (
        M.document()
        .header("人物创建完成")
        .inline_section("创建结果", M.status("成功", tone="positive"), icon="success")
        .section("身份")
        .row(("姓名", M.text(result.name, tone="emphasis")), ("性别", result.gender))
        .row(("种族", result.race or "人族"), ("境界", result.realm_name), ("等级", 1))
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


def overview_error() -> DocumentMessage:
    return (
        M.document()
        .section("人物", icon="notice")
        .line(
            M.status("读取失败", tone="danger"), " 人物状态暂时无法读取，请稍后再试。"
        )
        .build()
    )


def overview(result: CharacterOverviewResult) -> DocumentMessage:
    character = result.character
    resources = dict(character.resources)
    attributes = dict(character.attributes)
    builder = (
        M.document()
        .header(character.name)
        .section("身份", icon="status")
        .row(
            ("性别", character.gender),
            ("种族", character.race or "人族"),
            ("身份", character.character_type),
        )
        .row(("境界", character.realm_name), ("等级", character.level))
        .row(
            (
                "寿元",
                f"{character.age} / {character.lifespan} 岁"
                + ("（寿元将尽）" if character.lifespan_full else ""),
            ),
        )
        .row(
            ("经验", M.text(character.experience, tone="cultivation")),
            ("灵石", M.text(character.spirit_stones, tone="emphasis")),
            ("宗门贡献", character.sect_contribution),
        )
        .section("五行根性", icon="status")
        .row(
            *(
                (element, M.text(_display_number(value), tone=_element_tone(element)))
                for element, value in character.five_elements.items()
            )
        )
        .section("当前状态", icon="status")
        .row(
            *(
                (label, M.status(value, tone=_state_tone(value)))
                for label, value in result.states
            )
        )
        .section("所在之地", icon="map")
        .field("地点", result.location_name or "野外")
        .row(("区域", result.region), ("地形", result.terrain))
        .row(
            ("坐标", f"{result.xy[0]}, {result.xy[1]}"),
            ("海拔", f"{result.altitude}米"),
        )
        .section("当前资源", icon="status")
        .field(
            "血气",
            M.progress(
                resources.get("血气", 0),
                attributes.get("血气上限", 1),
                tone="health",
                display="value",
            ),
        )
        .field(
            "精神",
            M.progress(
                resources.get("精神", 0),
                attributes.get("精神上限", 1),
                tone="spirit",
                display="value",
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
    # 等于基准的属性没有信息：加成类的基准是 100，没装备的新人一屏全是「100」，
    # 占地方又不说明任何事。基准由角色核心从属性定义里取（默认值就是基准值）。
    # 主区这七项同样要过这一关——防御和三项概率的基准都是 0，新人身上全在。
    baselines = dict(result.attribute_baselines)
    primary_pairs = tuple(
        (name, attributes[name])
        for name in primary_names
        if name in attributes and attributes[name] != baselines.get(name, 0)
    )
    if primary_pairs:
        builder.section("战斗属性", icon="skill")
        _append_pairs(builder, primary_pairs)
    secondary = tuple(
        item
        for item in character.attributes
        if item[0] not in primary
        and item[0] not in {"血气上限", "精神上限"}
        and item[1] != baselines.get(item[0], 0)
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
        builder.inline_section("伤势", M.status("无", tone="positive"), icon="status")
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
        builder.inline_section(
            "先天灵宝", M.status("未执掌", tone="muted"), icon="item"
        )
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
        (
            "自动用药",
            M.status(
                "开启" if character.automatic_medicine else "关闭",
                tone="positive" if character.automatic_medicine else "muted",
            ),
        ),
    )
    return builder.build()


def _append_pairs(builder: DocumentBuilder, values: tuple[tuple[str, int | float], ...]) -> None:
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


def _element_tone(element: str) -> str:
    return {
        "金": "metal",
        "木": "wood",
        "水": "water",
        "火": "fire",
        "土": "earth",
        "无相": "formless",
    }.get(element, "muted")


def _state_tone(value: str) -> str:
    if any(word in value for word in ("重伤", "身死", "失败")):
        return "danger"
    if any(word in value for word in ("等待", "跟随", "托管", "进行")):
        return "warning"
    if any(word in value for word in ("休息", "空闲", "就绪", "正常")):
        return "positive"
    return "info"


__all__ = [
    "character_exists",
    "create_error",
    "created",
    "invalid_create_format",
    "overview",
    "overview_error",
]
