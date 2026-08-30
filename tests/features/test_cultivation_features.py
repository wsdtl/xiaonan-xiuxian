from __future__ import annotations

import asyncio
import random
from pathlib import Path

import pytest

from game.core.asset import AssetService, CultivationAcquisition, InventoryAdjustment
from game.core.character import CharacterService
from game.core.companion import CompanionService
from game.core.data import JsonDataService
from game.core.database import (
    DatabaseService,
    StateAddress,
    StateMutation,
    TransactionCommand,
)
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.core.item_catalog import ItemCatalogService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.pool import PoolService
from game.core.world import WorldService
from game.features.chuangjian_renwu import (
    CreateCharacterFeature,
    CreateCharacterRequest,
)
from game.features.daolv_peiyang import CompanionCultivationFeature
from game.features.renwu_peiyang import (
    CharacterBreakthroughRequest,
    CharacterCultivationFeature,
    CharacterCultivationFeatureError,
    CharacterEquipRequest,
    CharacterLawRequest,
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
    assets = AssetService(data, database)
    assets.initialize()
    forging = ForgingService(data, database, assets, world, location, innate_treasure_service(data, database))
    forging.initialize()
    items = ItemCatalogService(data)
    items.initialize()
    companion = CompanionService(data, database, growth, forging)
    companion.initialize()
    character = CharacterService(
        data, database, player_state, location, assets, growth, forging
    )
    character.initialize()
    create = CreateCharacterFeature(data, world, character)
    create.initialize()
    character_feature = CharacterCultivationFeature(
        data,
        character,
        assets,
        items,
        growth,
        forging,
        database,
        innate_treasure_service(data, database),
    )
    character_feature.initialize()
    companion_feature = CompanionCultivationFeature(
        data, companion, assets, items, growth, forging, database
    )
    companion_feature.initialize()
    return (
        data,
        database,
        assets,
        growth,
        companion,
        character,
        create,
        character_feature,
        companion_feature,
    )


def test_character_breakthrough_consumes_medicine_and_settles_saved_experience(
    tmp_path: Path,
) -> None:
    (
        _,
        database,
        assets,
        growth,
        _,
        character,
        create,
        feature,
        _,
    ) = _services(tmp_path)
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))
    snapshot = _run(database.get(StateAddress("qq-1", "character", "main")))
    assert snapshot is not None
    state = dict(snapshot.value)
    state["等级"] = 5
    state["经验"] = growth.experience_required(5)
    grant = _run(
        assets.plan_inventory_changes("qq-1", (InventoryAdjustment("140001", "01", 1),))
    )
    _run(
        database.commit(
            TransactionCommand(
                "qq-1",
                "prepare-breakthrough",
                "测试准备",
                (StateMutation("qq-1", "character", "main", state, snapshot.version),)
                + grant.operations,
                {},
            )
        )
    )

    result = _run(
        feature.breakthrough(
            CharacterBreakthroughRequest("qq-1", "breakthrough-1", "聚气丹")
        )
    )

    assert result.profile.realm_id == "510002"
    assert result.profile.level == 6
    assert _run(assets.inventory_stacks("qq-1", "140001")) == ()
    current = _run(database.get(StateAddress("qq-1", "character", "main")))
    assert current is not None
    assert [dict(value) for value in current.value["突破记录"]] == [
        {"目标境界": "510002", "突破丹": "140001", "补正来源丹药": None}
    ]
    assert character.status().initialized


def test_companion_growth_keeps_fixed_build_and_weapon_growth_independent(
    tmp_path: Path,
) -> None:
    (
        data,
        database,
        _,
        growth,
        companion,
        _,
        _,
        _,
        feature,
    ) = _services(tmp_path)
    definition = next(
        value
        for value in (
            companion.definition(companion_id)
            for companion_id in sorted(data.entities("道侣"))
        )
        if value.gender == "女"
    )
    _run(
        database.commit(
            TransactionCommand(
                "qq-1",
                "prepare-relation",
                "测试准备",
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
    invitation = _run(
        companion.plan_invitation(
            "qq-1",
            definition.companion_id,
            player_gender="男",
            occurred_at="2026-08-17T00:00:00+00:00",
            random_source=random.Random(7),
        )
    )
    _run(
        database.commit(
            TransactionCommand(
                "qq-1", "invite-1", "道侣邀约", invitation.operations, {}
            )
        )
    )
    before = _run(feature.inspect("qq-1"))
    required = growth.experience_required(before.instance.level)
    growth_plan = _run(companion.plan_growth("qq-1", experience=required))
    _run(
        database.commit(
            TransactionCommand(
                "qq-1", "companion-growth-1", "道侣成长", growth_plan.operations, {}
            )
        )
    )
    after = _run(feature.inspect("qq-1"))

    assert after.instance.level == before.instance.level + 1
    assert after.instance.cultivation == before.instance.cultivation
    assert after.instance.weapon_level == before.instance.weapon_level
    assert after.instance.weapon_experience == before.instance.weapon_experience


def test_character_equip_and_law_forging_use_shared_reserves(tmp_path: Path) -> None:
    (
        data,
        database,
        assets,
        _,
        _,
        character,
        create,
        feature,
        _,
    ) = _services(tmp_path)
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))
    (first_technique_id, _), (second_technique_id, second_technique) = tuple(
        data.entities("功法").items()
    )[:2]
    law_id, law = next(
        (law_id, value)
        for law_id, value in data.entities("器律").items()
        if value.get("器阶") == "灵器"
    )
    weapon = _run(database.get(StateAddress("qq-1", "weapon", "main")))
    assert weapon is not None
    weapon_value = dict(weapon.value)
    weapon_value.update({"等级": 21, "器阶": "灵器"})
    _run(
        database.commit(
            TransactionCommand(
                "qq-1",
                "prepare-reserves",
                "测试准备",
                (
                    StateMutation(
                        "qq-1",
                        "cultivation_library",
                        first_technique_id,
                        {"编号": first_technique_id, "品级": "01"},
                        0,
                    ),
                    StateMutation(
                        "qq-1",
                        "cultivation_library",
                        second_technique_id,
                        {"编号": second_technique_id, "品级": "01"},
                        0,
                    ),
                    StateMutation(
                        "qq-1",
                        "law_reserve",
                        law_id,
                        {"编号": law_id, "数量": 1},
                        0,
                    ),
                    StateMutation(
                        "qq-1", "weapon", "main", weapon_value, weapon.version
                    ),
                ),
                {},
            )
        )
    )

    _run(
        feature.equip(
            CharacterEquipRequest(
                "qq-1", "equip-1", "功法", first_technique_id, "01", 1
            )
        )
    )
    equipped = _run(
        feature.equip(
            CharacterEquipRequest(
                "qq-1", "equip-2", "功法", second_technique_id, "01", 1
            )
        )
    )
    acquisition = _run(
        assets.plan_cultivation_acquisitions(
            "qq-1",
            (CultivationAcquisition("功法", second_technique_id, "02"),),
        )
    )
    sync = _run(
        character.plan_technique_grade_sync(
            "qq-1", ((second_technique_id, "02"),)
        )
    )
    assert acquisition.results[0].outcome == "升品"
    assert sync.updated_slots == 1 and sync.operation is not None
    _run(
        database.commit(
            TransactionCommand(
                "qq-1",
                "upgrade-technique",
                "测试功法升品",
                acquisition.operations + (sync.operation,),
                {},
            )
        )
    )
    forged = _run(feature.forge_law(CharacterLawRequest("qq-1", "forge-1", law_id, 1)))

    assert equipped.content_name == second_technique["名称"]
    assert forged.law_name == law["名称"]
    assert forged.profile.equipped_content[0].content_id == second_technique_id
    assert forged.profile.equipped_content[0].grade == "02"
    assert forged.profile.weapon.equipped_laws[0].content_id == law_id
    assert (
        _run(
            database.get(
                StateAddress("qq-1", "cultivation_library", first_technique_id)
            )
        )
        is not None
    )
    assert (
        _run(
            database.get(
                StateAddress("qq-1", "cultivation_library", second_technique_id)
            )
        )
        is not None
    )
    upgraded = _run(
        database.get(
            StateAddress("qq-1", "cultivation_library", second_technique_id)
        )
    )
    assert upgraded is not None and upgraded.value["品级"] == "02"
    assert _run(database.get(StateAddress("qq-1", "law_reserve", law_id))) is None


def test_character_cannot_equip_one_technique_in_two_slots(tmp_path: Path) -> None:
    (
        data,
        database,
        assets,
        _,
        _,
        _,
        create,
        feature,
        _,
    ) = _services(tmp_path)
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))
    technique = data.entity("功法", "400265")
    acquisition = _run(
        assets.plan_cultivation_acquisitions(
            "qq-1", (CultivationAcquisition("功法", "400265", "02"),)
        )
    )
    _run(
        database.commit(
            TransactionCommand(
                "qq-1",
                "gain-technique",
                "测试取得功法",
                acquisition.operations,
                {},
            )
        )
    )
    _run(
        feature.equip(
            CharacterEquipRequest("qq-1", "equip-1", "功法", "400265", "02", 1)
        )
    )

    with pytest.raises(CharacterCultivationFeatureError, match="已装配在1号槽"):
        _run(
            feature.equip(
                CharacterEquipRequest(
                    "qq-1", "equip-2", "功法", technique["名称"], "02", 2
                )
            )
        )

    profile = _run(feature.inspect("qq-1")).profile
    assert [(entry.slot, entry.content_id) for entry in profile.equipped_content] == [
        (1, "400265")
    ]
