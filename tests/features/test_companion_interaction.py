from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest

from game.core.asset import AssetService, InventoryAdjustment
from game.core.character import CharacterService
from game.core.companion import CompanionService
from game.core.data import JsonDataService
from game.core.database import DatabaseService, TransactionCommand
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.core.item_catalog import ItemCatalogService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.pool import PoolService
from game.core.sect import SectService
from game.core.team import TeamService
from game.core.world import WorldService
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from game.features.daolv_jiejiao import (
    CompanionFarewellRequest,
    CompanionGiftRequest,
    CompanionInteractionFeature,
    CompanionInvitationRequest,
    CompanionQueryError,
)
from game.features.weizhi import PositionFeature
from message import DocumentMessage
from tests.support import innate_treasure_service


def _run(awaitable):
    return asyncio.run(awaitable)


def _services(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    pool = PoolService(data)
    pool.initialize()
    growth = GrowthService(data, pool)
    growth.initialize()
    database = DatabaseService(tmp_path / "game.db")
    database.initialize()
    world = WorldService(data)
    world.initialize()
    player_state = PlayerStateService(data, database)
    player_state.initialize()
    team = TeamService(data, database, player_state)
    team.initialize()
    sect = SectService(data, database, player_state)
    sect.initialize()
    location = LocationService(data, database, world)
    location.initialize()
    item_catalog = ItemCatalogService(data)
    item_catalog.initialize()
    asset = AssetService(data, database)
    asset.initialize()
    forging = ForgingService(data, database, asset, world, location, innate_treasure_service(data, database))
    forging.initialize()
    companion = CompanionService(data, database, growth, forging)
    companion.initialize()
    character = CharacterService(
        data, database, player_state, location, asset, growth, forging
    )
    character.initialize()
    create = CreateCharacterFeature(data, world, character)
    create.initialize()
    interaction = CompanionInteractionFeature(
        data,
        companion,
        item_catalog,
        asset,
        character,
        location,
        world,
        database,
        innate_treasure_service(data, database),
    )
    interaction.initialize()
    position = PositionFeature(
        data,
        world,
        location,
        character,
        player_state,
        companion,
        team,
        sect,
    )
    position.initialize()
    return database, companion, item_catalog, asset, create, interaction, position


def _create(create: CreateCharacterFeature, user_id: str = "qq-1") -> None:
    _run(create.create(CreateCharacterRequest(user_id, "create-1", "林远", "男")))


def _grant(
    database: DatabaseService,
    asset: AssetService,
    item_id: str,
    grade_id: str,
    quantity: int,
    request_id: str,
) -> None:
    plan = _run(
        asset.plan_inventory_changes(
            "qq-1",
            (InventoryAdjustment(item_id, grade_id, quantity),),
        )
    )
    _run(
        database.commit(
            TransactionCommand(
                "qq-1",
                request_id,
                "测试入库",
                plan.operations,
                {"物品编号": item_id},
            )
        )
    )


def _local_female(companion: CompanionService):
    local = companion.local_cultivators("溪隐台")
    summary = next(value for value in local if value.gender == "女")
    return companion.definition(summary.companion_id)


def test_gift_invite_farewell_and_position_share_one_companion_state(
    tmp_path: Path,
) -> None:
    database, companion, _, asset, create, interaction, position = _services(tmp_path)
    _create(create)
    definition = _local_female(companion)
    item_id = min(definition.favorite_item_ids)
    _grant(database, asset, item_id, "02", 20, "grant-liked")

    gift = _run(
        interaction.gift(
            CompanionGiftRequest(
                "qq-1",
                "gift-1",
                definition.companion_id,
                item_id,
                "02",
                10,
            )
        )
    )

    assert gift.accepted is True
    assert gift.view.has_relation is True
    assert str(gift.affection_gain) == "108.0"
    assert str(gift.affection_after) == "108.0"
    assert gift.first_full is True
    assert gift.reward_item is not None
    relation = _run(companion.relation("qq-1", definition.companion_id))
    assert relation.gift_totals[f"{item_id}:02"] == 10
    assert relation.first_full_at

    invitation = _run(
        interaction.invite(
            CompanionInvitationRequest(
                "qq-1",
                "invite-1",
                definition.companion_id,
            )
        )
    )
    assert invitation.first_invitation is True
    assert invitation.view.is_active is True
    assert 1 <= invitation.instance.qualification <= 1000
    current = _run(position.current("qq-1"))
    assert current.active_companion is not None
    assert current.active_companion.companion_id == definition.companion_id
    assert definition.companion_id not in {
        value.companion_id for value in current.local_cultivators
    }

    farewell = _run(
        interaction.farewell(
            CompanionFarewellRequest(
                "qq-1",
                "farewell-1",
                definition.companion_id,
            )
        )
    )
    assert farewell.definition.companion_id == definition.companion_id
    assert _run(companion.active("qq-1")) is None
    assert _run(companion.instance("qq-1", definition.companion_id)) is not None
    assert (
        _run(companion.relation("qq-1", definition.companion_id)).current_affection
        == 108
    )

    second = _run(
        interaction.gift(
            CompanionGiftRequest(
                "qq-1",
                "gift-2",
                definition.companion_id,
                item_id,
                "02",
                1,
            )
        )
    )
    assert second.first_full is False


def test_unliked_gift_is_not_consumed_and_multiple_grades_require_choice(
    tmp_path: Path,
) -> None:
    database, companion, item_catalog, asset, create, interaction, _ = _services(
        tmp_path
    )
    _create(create)
    definition = _local_female(companion)
    liked_item = min(definition.favorite_item_ids)
    unliked_item = next(
        item.item_id
        for item in item_catalog.category("灵植")
        if item.item_id not in definition.favorite_item_ids
        and item.item_id not in definition.acceptable_item_ids
    )
    _grant(database, asset, liked_item, "01", 1, "grant-yellow")
    _grant(database, asset, liked_item, "02", 1, "grant-black")

    refused = _run(
        interaction.gift(
            CompanionGiftRequest(
                "qq-1",
                "gift-refused",
                definition.companion_id,
                unliked_item,
                "",
                1,
            )
        )
    )
    assert refused.accepted is False
    assert _run(companion.relation("qq-1", definition.companion_id)).version == 0

    with pytest.raises(CompanionQueryError, match="多个品级"):
        _run(
            interaction.gift(
                CompanionGiftRequest(
                    "qq-1",
                    "gift-ambiguous",
                    definition.companion_id,
                    liked_item,
                    "",
                    1,
                )
            )
        )


def test_same_meridian_plant_is_accepted_with_lower_affection(tmp_path: Path) -> None:
    database, companion, _, asset, create, interaction, _ = _services(tmp_path)
    _create(create)
    definition = _local_female(companion)
    item_id = min(definition.acceptable_item_ids)
    _grant(database, asset, item_id, "01", 1, "grant-acceptable")

    result = _run(
        interaction.gift(
            CompanionGiftRequest(
                "qq-1",
                "gift-acceptable",
                definition.companion_id,
                item_id,
                "01",
                1,
            )
        )
    )

    assert result.accepted is True
    assert result.preference == "合意"
    assert str(result.affection_gain) == "5.0"
    assert result.view.relation.gift_totals[f"{item_id}:01"] == 1


def test_companion_command_repeats_current_location_actions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _, companion, _, _, create, interaction, position = _services(tmp_path)
    _create(create)
    definition = _local_female(companion)

    class RecordingManager:
        message: DocumentMessage | None = None

        async def send(self, message: DocumentMessage) -> None:
            self.message = message

    command_module = import_module("game.cmd.专属.道侣结交")
    monkeypatch.setattr(
        command_module,
        "current_game_services",
        lambda: SimpleNamespace(
            features=SimpleNamespace(
                daolv_jiejiao=interaction,
                weizhi=position,
            )
        ),
    )
    manager = RecordingManager()

    _run(
        command_module.inspect_companion(
            user_id="qq-1",
            message=definition.companion_id,
            manager=manager,
        )
    )

    assert manager.message is not None
    commands = tuple(action.data for action in manager.message.document.actions)
    assert commands[:2] == (
        f"交谈 {definition.companion_id}",
        f"赠予 {definition.companion_id}",
    )
    assert commands[-7:] == (
        "附近 修士",
        "开始探险",
        "开始闭关",
        "开始采药",
        "开始采矿",
        "附近",
        "地图",
    )
