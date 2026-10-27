"""通用商店：池货架、类别动态与灵石存入。"""

from __future__ import annotations

import asyncio

from game.core.character.contracts import CharacterCreateCommand
from game.core.trade import TradePurchaseCommand


def test_pool_shelves_are_dynamic_and_deliver_to_cultivation(services) -> None:
    user_id = "shop-pool"
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(user_id, "create-shop", "商店测试", "男", (51, 35), "")
        )
    )
    overview = asyncio.run(services.core.trade.overview(user_id))
    assert [item.category for item in overview.categories] == ["真意", "气机"]
    assert all(item.product_count > 0 for item in overview.categories)

    page = asyncio.run(services.core.trade.page(user_id, "真意"))
    assert page.total_products > 0
    product = page.products[0]
    assert product.delivery == "修行资粮"
    assert product.unit_price == 3000

    before = asyncio.run(services.core.asset.spirit_stone_balance(user_id))
    result = asyncio.run(
        services.core.trade.purchase(
            TradePurchaseCommand(user_id, "shop-buy-1", product.content_id, product.grade_id, 1)
        )
    )
    after = asyncio.run(services.core.asset.spirit_stone_balance(user_id))
    assert result.product.category == "真意"
    assert result.delivery_after >= 1
    assert before - after == result.total_price


def test_individual_shelf_can_deliver_to_inventory(services) -> None:
    from game.core.asset.contracts import InventoryAdjustment
    from game.core.character.contracts import CharacterCreateCommand
    from game.core.database.contracts import TransactionCommand

    user = "shop-individual"
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(user, "create-shop-individual", "杂货客", "男", (51, 35), "")
        )
    )
    listings = services.core.trade._load_shelf(
        "测试商店",
        0,
        {
            "类别": "基础物品",
            "编号": "200001",
            "品级": ["01"],
            "存入位置": "纳戒",
        },
        set(),
    )
    assert len(listings) == 1
    product = services.core.trade._products_for_listing(listings[0])[0]
    assert product.delivery == "纳戒"
    assert product.unit_price == 440
    plan = asyncio.run(services.core.trade._delivery_plan(user, product, 1))
    assert plan.after >= 1
