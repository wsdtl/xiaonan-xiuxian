"""人物面板的共享渲染：人物与查看自己共用同一份。"""

from __future__ import annotations

from message import DocumentBuilder, DocumentMessage, M

from game.features.chakan_juese import CharacterOverviewResult

#: 资源名 -> 上限属性。展示层只决定“怎么画”，资源集合仍以 CharacterProfile.resources 为准。
_RESOURCE_MAX_ATTRIBUTE = {
    "血气": "血气上限",
    "神魂": "神魂上限",
    "精神": "精神上限",
    "护盾": "护盾上限",
}
_RESOURCE_ORDER = ("血气", "神魂", "精神", "护盾")
_RESOURCE_TONE = {"血气": "health", "神魂": "spirit", "精神": "spirit", "护盾": "spirit"}
_RESOURCE_CAPS = frozenset(_RESOURCE_MAX_ATTRIBUTE.values())


def _resource_fields(
    builder: DocumentBuilder,
    resources: tuple[tuple[str, int | float], ...],
    attributes: dict[str, int | float],
) -> None:
    """按 CharacterProfile.resources 逐个画资源，避免只认血气和精神。"""

    values = dict(resources)
    ordered = [name for name in _RESOURCE_ORDER if name in values]
    ordered.extend(name for name, _value in resources if name not in ordered)
    for name in ordered:
        value = values[name]
        cap_name = _RESOURCE_MAX_ATTRIBUTE.get(name, "")
        cap = attributes.get(cap_name, 0) if cap_name else 0
        if cap > 0:
            builder.field(
                name,
                M.progress(
                    value,
                    cap,
                    tone=_RESOURCE_TONE.get(name, "spirit"),
                    display="value",
                ),
            )
        else:
            builder.field(name, _display_number(value))




def overview_error() -> DocumentMessage:
    return (
        M.document()
        .section("提示", icon="game.pin_doc")
        .line(
            M.status("读取失败", tone="danger"), " 人物状态暂时无法读取，请稍后再试。"
        )
        .build()
    )


def overview(
    result: CharacterOverviewResult,
    unit: str,
    dna: str = "",
    bloodlines: tuple[str, ...] = (),
) -> DocumentMessage:
    character = result.character
    attributes = dict(character.attributes)
    builder = (
        M.document()

        .section("身份", icon="game.role")
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
        .section("根性", icon="game.leaf")
        .row(
            *(
                (element, M.text(_display_number(value), tone=_element_tone(element)))
                for element, value in character.five_elements.items()
            )
        )
        .section("状态", icon="game.seed")
        .row(
            *(
                (label, M.status(value, tone=_state_tone(value)))
                for label, value in result.states
            )
        )
        .section("位置", icon="game.pin")
        .field("地点", result.location_name or "野外")
        .row(("区域", result.region), ("地形", result.terrain))
        .row(
            ("坐标", f"{result.xy[0]}, {result.xy[1]}"),
            ("海拔", f"{result.altitude}{unit}"),
        )
        .section("资源", icon="game.gem")
    )
    _resource_fields(builder, character.resources, attributes)
    # 血脉：DNA 与命中的血脉。没取到就不显示这一段（不许出现空栏目）。
    if dna:
        builder.section("血脉", icon="game.dna")
        builder.row(("DNA", dna))
        if bool(getattr(unit, "lifespan_full", False)):
            # 寿元将尽：血脉失效，加成不再生效（补救的路是传位）。
            builder.row(("血脉", "寿元将尽·血脉失效"))
    # 意境：六条路各自记阶、道行共享；一条都没点过就整段不显示（不许出现空栏目）。
    if character.yijing:
        builder.section("意境", icon="game.swirl")
        builder.row(("意境", "、".join(item.display for item in character.yijing)))
        builder.row(("道行", character.yijing[0].daoxing))
        behind = [item for item in character.yijing if item.missing]
        if behind:
            builder.line(
                "道行不足：" + "、".join(f"{item.display} 还差 {item.missing}" for item in behind)
            )
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
        builder.section("属性", icon="game.swords")
        _append_pairs(builder, primary_pairs)
    secondary = tuple(
        item
        for item in character.attributes
        if item[0] not in primary
        and item[0] not in _RESOURCE_CAPS
        and item[1] != baselines.get(item[0], 0)
        and not (item[0] == "连击伤害" and attributes.get("连击率", 0) == 0)
    )
    if secondary:
        builder.section("加成", icon="game.spark")
        _append_pairs(builder, secondary)
    if result.injuries:
        builder.section("伤势", icon="game.blood_drop")
        for index, (name, stacks) in enumerate(result.injuries, start=1):
            builder.item(index, f"{name} × {stacks}")
    else:
        builder.inline_section("伤势", M.status("无", tone="positive"), icon="game.blood_drop")
    builder.section("槽位", icon="game.hex").row(
        *(
            (category, f"{equipped}/{total}")
            for category, equipped, total in result.cultivation_usage
        )
    )
    for content in character.equipped_content:
        builder.field(
            f"{content.category}{content.slot}",
            M.text(content.grade_name or "")
            + (M.command(content.name, f"查看 {content.name}"),),
        )
    if result.innate_treasure is None:
        builder.inline_section(
            "灵宝", M.status("未执掌", tone="muted"), icon="game.amulet"
        )
    else:
        builder.section("灵宝", icon="game.amulet").field(
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
    builder.section("本命武器", icon="game.dagger")
    builder.field("名称", weapon.name)
    builder.row(("器阶", weapon.stage), ("等级", weapon.level))
    builder.row(("攻击", _display_number(weapon.attack)), ("经验", weapon.experience))
    builder.field("器律", f"{len(weapon.equipped_laws)}/{weapon.open_law_slots}")
    for law in weapon.equipped_laws:
        builder.item(law.slot, M.command(law.name, f"查看 {law.name}"))
    builder.section("物资", icon="game.bag").row(
        ("种类", character.inventory.stack_count),
        ("总数", character.inventory.total_quantity),
    )
    # 用药联动：物资下面只留一枚无边框分支按钮，标签显示当前态，只填入。
    builder.line(
        M.command(
            "自动用药：开启" if character.automatic_medicine else "自动用药：关闭",
            "人药 开|人药 关|侣药 开|侣药 关",
        )
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



__all__ = ["overview", "overview_error"]
