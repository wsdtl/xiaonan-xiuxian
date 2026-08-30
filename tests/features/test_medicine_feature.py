from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from game.core.asset import AssetService, InventoryAdjustment
from game.core.character import CharacterService
from game.core.companion import CompanionService
from game.core.data import JsonDataService
from game.core.database import DatabaseService, StateMutation, TransactionCommand
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.core.location import LocationService
from game.core.medicine import MedicineService
from game.core.player_state import PlayerStateService
from game.core.pool import PoolService
from game.core.world import WorldService
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from game.features.fudan import (
    AutoMedicineRequest,
    MedicineFeature,
    MedicineFeatureError,
    MedicineUseRequest,
)
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
    location = LocationService(data, database, world)
    location.initialize()
    asset = AssetService(data, database)
    asset.initialize()
    medicine = MedicineService(data, asset)
    medicine.initialize()
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
    feature = MedicineFeature(
        data,
        medicine,
        character,
        companion,
        asset,
        player_state,
        database,
        innate_treasure_service(data, database),
    )
    feature.initialize()
    return database, asset, character, companion, create, feature


def _create(create: CreateCharacterFeature) -> None:
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))


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
            "qq-1", (InventoryAdjustment(item_id, grade_id, quantity),)
        )
    )
    _run(
        database.commit(
            TransactionCommand(
                "qq-1", request_id, "测试入库", plan.operations, {"编号": item_id}
            )
        )
    )


def _invite_companion(
    database: DatabaseService, companion: CompanionService
) -> str:
    definition = next(
        value for value in companion.local_cultivators("溪隐台") if value.gender == "女"
    )
    _run(
        database.commit(
            TransactionCommand(
                "qq-1",
                "prepare-relation",
                "测试关系",
                (
                    StateMutation(
                        "qq-1",
                        "companion_relation",
                        definition.companion_id,
                        {"当前好感": 100, "赠礼累计": {}},
                        0,
                    ),
                ),
                {},
            )
        )
    )
    plan = _run(
        companion.plan_invitation(
            "qq-1",
            definition.companion_id,
            player_gender="男",
            occurred_at="2026-08-19T00:00:00+00:00",
        )
    )
    _run(
        database.commit(
            TransactionCommand("qq-1", "invite-1", "测试邀约", plan.operations, {})
        )
    )
    return definition.companion_id


def test_recovery_rejects_full_resource_without_consuming_and_replays_once(
    tmp_path: Path,
) -> None:
    database, asset, character, _, create, feature = _services(tmp_path)
    _create(create)

    with pytest.raises(MedicineFeatureError, match="血气已满"):
        _run(
            feature.use(
                MedicineUseRequest("qq-1", "full-1", "人物", "小还丹")
            )
        )
    assert _run(asset.inventory_stacks("qq-1", "100005"))[0].quantity == 3

    damage = _run(
        character.plan_battle_settlement("qq-1", health=50, spirit=100)
    )
    _run(
        database.commit(
            TransactionCommand(
                "qq-1", "damage-1", "测试受伤", damage.operations, {}
            )
        )
    )
    request = MedicineUseRequest("qq-1", "recover-1", "人物", "小还丹")
    first = _run(feature.use(request))
    replay = _run(feature.use(request))

    assert first.recovered == 15
    assert replay.replayed is True
    assert dict(_run(character.profile("qq-1")).resources)["血气"] == 65
    assert _run(asset.inventory_stacks("qq-1", "100005"))[0].quantity == 2


def test_unknown_medicine_is_reported_as_feature_error(tmp_path: Path) -> None:
    _, _, _, _, create, feature = _services(tmp_path)
    _create(create)

    with pytest.raises(MedicineFeatureError, match="未找到唯一丹药"):
        _run(
            feature.use(
                MedicineUseRequest("qq-1", "unknown-medicine", "人物", "不存在的丹药")
            )
        )


def test_character_and_companion_have_independent_settings_and_battle_medicine(
    tmp_path: Path,
) -> None:
    database, asset, character, companion, create, feature = _services(tmp_path)
    _create(create)
    companion_id = _invite_companion(database, companion)

    _run(
        feature.set_automatic(
            AutoMedicineRequest("qq-1", "character-auto-off", "人物", False)
        )
    )
    assert _run(character.profile("qq-1")).automatic_medicine is False
    assert _run(companion.instance("qq-1", companion_id)).automatic_medicine is True
    _run(
        feature.set_automatic(
            AutoMedicineRequest("qq-1", "companion-auto-off", "道侣", False)
        )
    )
    assert _run(character.profile("qq-1")).automatic_medicine is False
    assert _run(companion.instance("qq-1", companion_id)).automatic_medicine is False

    _grant(database, asset, "120001", "01", 2, "grant-battle-medicine")
    _run(
        feature.use(
            MedicineUseRequest("qq-1", "character-battle", "人物", "赤霄破军丹")
        )
    )
    _run(
        feature.use(
            MedicineUseRequest("qq-1", "companion-battle", "道侣", "赤霄破军丹")
        )
    )

    assert _run(character.profile("qq-1")).prepared_battle_medicine is not None
    assert (
        _run(companion.instance("qq-1", companion_id)).prepared_battle_medicine
        is not None
    )
    assert _run(asset.inventory_stacks("qq-1", "120001")) == ()
