"""角色命令回复构造。"""

from __future__ import annotations

from message import DocumentMessage, M

from game.features.chuangjian_renwu import CreateCharacterResult

from ...character_overview import overview, overview_error


def invalid_create_format() -> DocumentMessage:
    return (
        M.document()
        .section("创建")
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
        .section("创建", icon="game.pin_doc")
        .line(M.status("创建失败", tone="danger"), " ", message)
        .build()
    )


def character_exists() -> DocumentMessage:
    return (
        M.document()
        .section("创建")
        .line(M.status("已有角色", tone="warning"), " 不能重复创建人物。")
        .build()
    )


def created(
    result: CreateCharacterResult, unit: str
) -> DocumentMessage:
    builder = (
        M.document()

        .inline_section("创建", M.status("成功", tone="positive"), icon="game.success")
        .section("身份", icon="game.role")
        .row(("姓名", M.text(result.name, tone="emphasis")), ("性别", result.gender))
        .row(("种族", result.race or "人族"), ("境界", result.realm_name), ("等级", 1))
        .section("出生地", icon="game.pin")
        .field("地点", M.command(result.location_name, "位置"))
        .row(("区域", result.region), ("地形", result.terrain))
        .row(
            ("坐标", f"{result.xy[0]}, {result.xy[1]}"),
            ("海拔", f"{result.altitude}{unit}"),
        )
        .section("初始物资", icon="game.bag")
    )
    for index, (item_name, grade, quantity) in enumerate(result.initial_items, start=1):
        builder.item(
            index,
            M.command(f"{grade}{item_name}", f"查看 {item_name}"),
            f" × {quantity}",
        )
    return builder.build()



__all__ = [
    "character_exists",
    "create_error",
    "created",
    "invalid_create_format",
    "overview",
    "overview_error",
]
