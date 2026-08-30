from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from game.app import build_game_services
from game.config import GameConfig, GameDatabaseConfig
from game.core.database import TransactionCommand
from game.core.location import LocationMoveCommand
from game.core.trade import TradeError, TradePurchaseCommand
from game.core.world import LocationQuery
from game.features.chuangjian_renwu import CreateCharacterRequest


def _run(awaitable):
    return asyncio.run(awaitable)


def test_trade_purchase_and_cultivation_equip_share_one_consumable_reserve(
    tmp_path: Path, monkeypatch
) -> None:
    import game.app as game_app

    monkeypatch.setattr(
        game_app,
        "game_config",
        GameConfig(
            GameDatabaseConfig(tmp_path / "game.db", tmp_path / "runtime.db", 5000)
        ),
    )
    root = Path(__file__).resolve().parents[2]
    services = build_game_services(data_dir=root / "data")
    create = services.features.chuangjian_renwu
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))
    current = _run(services.core.location.current("qq-1"))
    destination = services.core.world.locate(LocationQuery(location_name="青岚城"))
    _run(
        services.core.location.move(
            LocationMoveCommand(
                "qq-1", "move-1", current.xy, destination.xy
            )
        )
    )

    overview = _run(services.core.trade.overview("qq-1"))
    page = _run(services.core.trade.page("qq-1", "真意"))
    product = next(value for value in page.products if value.grade_id == "01")
    with pytest.raises(TradeError, match="未知物品品级"):
        _run(
            services.core.trade.purchase(
                TradePurchaseCommand("qq-1", "bad-grade", product.content_id, "不存在", 1)
            )
        )
    with pytest.raises(TradeError, match="灵石"):
        _run(
            services.core.trade.purchase(
                TradePurchaseCommand(
                    "qq-1", "purchase-too-much", product.content_id, product.grade_id, 50
                )
            )
        )
    assert (
        _run(
            services.core.asset.cultivation_reserve_stack(
                "qq-1", "真意", product.content_id, product.grade_id
            )
        )
        is None
    )
    assert _run(services.core.character.profile("qq-1")).spirit_stones == 10000

    command = TradePurchaseCommand(
        "qq-1", "purchase-1", product.content_id, product.grade_id, 2
    )
    purchase = _run(
        services.core.trade.purchase(command)
    )
    replay = _run(services.core.trade.purchase(command))

    assert overview.location_name == "青岚城"
    assert purchase.reserve_after == 2
    assert purchase.spirit_stones_after == 10000 - product.unit_price * 2
    assert replay.replayed is True
    assert replay.reserve_after == purchase.reserve_after
    assert replay.spirit_stones_after == purchase.spirit_stones_after
    equip = _run(
        services.core.character.plan_equip(
            "qq-1",
            category="真意",
            content_id=product.content_id,
            grade_id=product.grade_id,
            slot=1,
        )
    )
    assert equip.reserve_operation is not None
    _run(
        services.core.database.commit(
            TransactionCommand(
                "qq-1",
                "equip-1",
                "测试人物装配",
                (equip.reserve_operation, equip.operation),
                {},
            )
        )
    )
    reserve = _run(
        services.core.asset.cultivation_reserve_stack(
            "qq-1", "真意", product.content_id, product.grade_id
        )
    )
    profile = _run(services.core.character.profile("qq-1"))

    assert reserve is not None and reserve.quantity == 1
    assert any(
        value.category == "真意" and value.content_id == product.content_id
        for value in profile.equipped_content
    )
    services.core.database.close()
