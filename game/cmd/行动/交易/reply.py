"""地点交易命令回复构造。"""

from __future__ import annotations

from ...actions import CommandAction, message_actions
from ...presentation import format_lines, linked_name_line

from typing import Sequence

from game.features.jiaoyi import TradeFeature, TradeOverview, TradePage, TradePurchaseResult

from message import DocumentMessage, Action, M

from ...presentation import sentence


def overview(feature: TradeFeature, value: TradeOverview) -> DocumentMessage:
    builder = (
        M.document()

        .section(feature.copy("总览", "货架"), icon="game.bag")
        .field(
            feature.copy("总览", "货币"),
            M.text(value.spirit_stones, tone="cultivation"),
        )
    )
    for category in value.categories:
        builder.line(
            M.command(category.category, f"交易 {category.category}"),
            f" · {category.product_count}项",
        )
    return builder.small(feature.copy("总览", "说明")).build()


def page(feature: TradeFeature, value: TradePage) -> DocumentMessage:
    builder = (
        M.document()

        .section(
            feature.copy("列表", "页码", {"当前页": value.page, "总页数": value.total_pages}),
            icon="game.bag",
        )
        .field("商品", M.text(value.total_products, tone="emphasis"))
    )
    for index, product in enumerate(value.products, start=(value.page - 1) * 50 + 1):
        # 卡面全中文、不印编号；名字只作显示，点它出「查看 | 购买」两条分支。
        # 两条分支的参数尾巴不一样（购买还要品级），所以各自写全（branches.py 认可这种写法）。
        builder.item(
            index,
            M.command(
                M.text(f"{product.grade_name}{product.name}"),
                f"查看 {product.name} | 购买 {product.grade_name}{product.name}",
                submit=False,
            ),
            f" · {product.unit_price}灵石",
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


def purchased(feature: TradeFeature, value: TradePurchaseResult) -> DocumentMessage:
    return (
        M.document()
        .section(feature.copy("购买", "标题"), icon="game.bag")
        .line(M.status("购买完成", tone="positive"))
        .line(
            *linked_name_line(
                feature.copy(
                    "购买",
                    "所得",
                    {
                        "品级": value.product.grade_name,
                        "名称": "\u0000",
                        "数量": value.quantity,
                    },
                ),
                value.product.name,
            )
        )
        .row(
            (feature.copy("购买", "花费"), M.text(value.total_price, tone="warning")),
            ("剩余灵石", M.text(value.spirit_stones_after, tone="cultivation")),
        )
        .field(
            feature.copy("购买", "余量", {"存入位置": value.product.delivery}),
            value.delivery_after,
        )
        .build()
    )


def error(
    feature: TradeFeature,
    message: str,
    actions: Sequence[CommandAction] = (),
    *,
    command: str,
) -> DocumentMessage:
    builder = M.document().section(feature.copy("错误", "标题"), icon="game.pin_doc")
    builder.line(M.status(feature.copy("错误", command), tone="danger"))
    format_lines(builder, sentence(message))
    hint = feature.copy("错误", "格式")
    # 正文已经是这句格式文案时别再补一遍：同一句话印两遍就是零信息。
    if hint not in sentence(message):
        builder.small(hint)
    if actions:
        builder.actions(message_actions(actions))
    return builder.build()


__all__ = ["error", "overview", "page", "purchased"]
