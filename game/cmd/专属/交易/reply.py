"""地点交易命令回复构造。"""

from __future__ import annotations

from game.features.jiaoyi import (
    TradeFeature,
    TradeOverview,
    TradePage,
    TradePurchaseResult,
)
from message import Action, M


def overview(feature: TradeFeature, value: TradeOverview):
    builder = (
        M.document()
        .header(feature.copy("总览", "标题", 地点=value.location_name))
        .section(feature.copy("总览", "货架"), icon="inventory")
        .field(feature.copy("总览", "货币"), value.spirit_stones)
    )
    for category in value.categories:
        builder.line(
            M.command(category.category, f"交易 {category.category}"),
            f" · {category.product_count}项",
        )
    return builder.line(feature.copy("总览", "说明")).build()


def page(feature: TradeFeature, value: TradePage):
    builder = (
        M.document()
        .header(feature.copy("列表", "标题", 地点=value.location_name, 类别=value.category))
        .section(
            feature.copy(
                "列表", "页码", 当前页=value.page, 总页数=value.total_pages
            ),
            icon="inventory",
        )
        .field("商品", value.total_products)
    )
    for index, product in enumerate(
        value.products, start=(value.page - 1) * 50 + 1
    ):
        builder.item(
            index,
            M.command(
                f"{product.grade_name}{product.name}",
                f"购买 {product.content_id} {product.grade_id}",
                submit=False,
            ),
            f" · {product.content_id} · {product.unit_price}灵石",
        )
    actions: list[Action] = []
    if value.page > 1:
        actions.append(
            Action(
                "trade.previous",
                "上一页",
                f"交易 {value.category} {value.page - 1}",
                behavior="callback",
                style="secondary",
            )
        )
    if value.page < value.total_pages:
        actions.append(
            Action(
                "trade.next",
                "下一页",
                f"交易 {value.category} {value.page + 1}",
                behavior="callback",
                style="secondary",
            )
        )
    actions.append(
        Action(
            "trade.home",
            "返回交易",
            "交易",
            behavior="callback",
            style="secondary",
        )
    )
    return builder.actions(actions).build()


def purchased(feature: TradeFeature, value: TradePurchaseResult):
    return (
        M.document()
        .section(feature.copy("购买", "标题"), icon="inventory")
        .line(
            feature.copy(
                "购买",
                "所得",
                品级=value.product.grade_name,
                名称=value.product.name,
                数量=value.quantity,
            )
        )
        .row(
            (feature.copy("购买", "花费"), value.total_price),
            ("剩余灵石", value.spirit_stones_after),
        )
        .field(feature.copy("购买", "余量"), value.reserve_after)
        .build()
    )


def error(feature: TradeFeature, message: str):
    return (
        M.document()
        .section(feature.copy("错误", "标题"), icon="notice")
        .line(message)
        .line(feature.copy("错误", "格式"))
        .build()
    )


__all__ = ["error", "overview", "page", "purchased"]
