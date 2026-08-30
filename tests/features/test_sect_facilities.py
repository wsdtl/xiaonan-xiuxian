from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal

import pytest

import game.app as game_app
from game.config import GameConfig, GameDatabaseConfig
from game.core.asset import CultivationAcquisition, InventoryAdjustment
from game.core.database import StateAddress, TransactionCommand
from game.core.gathering import GatheringStartCommand
from game.core.sect_assets import SectAssetError
from game.core.sect_facilities import SectFacilityError
from game.features.chuangjian_renwu import CreateCharacterRequest
from game.features.zongmen import SectFeatureError
from game.features.zongmen_shengchan import SectProductionFeatureError
from game.features.zongmen_sheshi import SectFacilityFeatureError


def _run(awaitable):
    return asyncio.run(awaitable)


@pytest.fixture
def services(tmp_path, monkeypatch):
    monkeypatch.setattr(
        game_app,
        "game_config",
        GameConfig(
            GameDatabaseConfig(
                tmp_path / "game.db",
                tmp_path / "runtime.db",
                5000,
            )
        ),
    )
    value = game_app.build_game_services()
    yield value
    value.core.database.close()


def _create_sect(services) -> None:
    create = services.features.chuangjian_renwu
    _run(create.create(CreateCharacterRequest("qq-1", "create-1", "林远", "男")))
    _run(create.create(CreateCharacterRequest("qq-2", "create-2", "白川", "男")))
    sect = services.features.zongmen
    _run(sect.create("qq-1", "sect-create", "青云宗"))
    _run(sect.invite("qq-1", "白川", "sect-invite"))
    _run(sect.accept("qq-2", "sect-accept"))
    _run(services.features.zongmen_shanmen.enter("qq-1", "gate-enter-1"))
    _run(services.features.zongmen_shanmen.enter("qq-2", "gate-enter-2"))


def _commit(services, user_id: str, request_id: str, operations) -> None:
    _run(
        services.core.database.commit(
            TransactionCommand(user_id, request_id, "测试准备", tuple(operations), {})
        )
    )


def _seed_facility_resources(services) -> None:
    data = services.core.data
    items = tuple(
        InventoryAdjustment(content_id, "05", 15_000)
        for content_id in data.entities("物品")
        if data.entity_record("物品", content_id).number_category
        in {"灵植", "灵矿", "兽宝"}
    )
    inventory = _run(services.core.asset.plan_inventory_changes("qq-1", items))
    stones = _run(
        services.core.character.plan_spirit_stone_change("qq-1", delta=30_000_000)
    )
    _commit(
        services,
        "qq-1",
        "prepare-facility-resources",
        (*inventory.operations, stones.operation),
    )
    _run(
        services.features.zongmen_lingcang.donate_stones(
            "qq-1", "facility-stones", 30_000_000
        )
    )


def test_lingcang_and_wanzhen_transfer_real_personal_assets(services) -> None:
    _create_sect(services)
    data = services.core.data
    herb_id = next(
        content_id
        for content_id in data.entities("物品")
        if data.entity_record("物品", content_id).number_category == "灵植"
    )
    herb_plan = _run(
        services.core.asset.plan_inventory_changes(
            "qq-1", (InventoryAdjustment(herb_id, "01", 3),)
        )
    )
    stones_before = _run(services.core.character.profile("qq-1")).spirit_stones
    stone_plan = _run(
        services.core.character.plan_spirit_stone_change("qq-1", delta=100)
    )
    _commit(
        services,
        "qq-1",
        "prepare-lingcang",
        (*herb_plan.operations, stone_plan.operation),
    )

    _run(
        services.features.zongmen_lingcang.donate_material(
            "qq-1", "donate-herb", "灵植", herb_id, "01", 2
        )
    )
    _run(services.features.zongmen_lingcang.donate_stones("qq-1", "donate-stones", 40))
    lingcang = _run(services.features.zongmen_lingcang.page("qq-1", "灵植"))
    assert lingcang.spirit_stones == 40
    assert [(value.content_id, value.quantity) for value in lingcang.entries] == [
        (herb_id, 2)
    ]
    assert _run(services.core.asset.inventory_stacks("qq-1", herb_id))[0].quantity == 1
    assert (
        _run(services.core.character.profile("qq-1")).spirit_stones
        == stones_before + 60
    )

    medicine_id = next(
        content_id
        for content_id in data.entities("物品")
        if data.entity_record("物品", content_id).number_category == "丹药"
    )
    medicine_plan = _run(
        services.core.asset.plan_inventory_changes(
            "qq-1", (InventoryAdjustment(medicine_id, "01", 1),)
        )
    )
    _commit(services, "qq-1", "prepare-wanzhen", medicine_plan.operations)
    donated = _run(
        services.features.zongmen_wanzhen.donate(
            "qq-1", "donate-medicine", "丹药", medicine_id, "01", 1
        )
    )
    granted = _run(
        services.features.zongmen_wanzhen.grant(
            "qq-1", "grant-medicine", "白川", donated.entry.entry_key, 1
        )
    )
    assert granted.target_name == "白川"
    assert (
        _run(services.core.asset.inventory_stacks("qq-2", medicine_id))[0].quantity >= 1
    )

    with pytest.raises(SectFeatureError, match="storage_not_empty"):
        _run(services.features.zongmen.disband("qq-1", "sect-disband"))


def test_contribution_is_personal_and_sect_level_uses_current_members(services) -> None:
    _create_sect(services)
    assert _run(services.core.character.profile("qq-1")).sect_contribution == 0

    stones = _run(
        services.core.character.plan_spirit_stone_change("qq-1", delta=50_000)
    )
    _commit(services, "qq-1", "prepare-contribution-stones", (stones.operation,))
    _run(
        services.features.zongmen_lingcang.donate_stones(
            "qq-1", "contribution-stones", 50_000
        )
    )
    member = _run(services.core.sect.membership("qq-1"))
    assert member is not None
    progress = _run(services.core.sect_progress.snapshot(member.sect_id))
    assert progress.level == 2
    assert progress.total_contribution == 500

    herb_id = next(
        content_id
        for content_id in services.core.data.entities("物品")
        if services.core.data.entity_record("物品", content_id).number_category
        == "灵植"
    )
    herb = services.core.data.entity("物品", herb_id)
    grade = services.core.asset.grade("03")
    expected = int(
        (
            Decimal(str(herb["参考价"])) * grade.price_multiplier / Decimal(100)
        ).to_integral_value(rounding=ROUND_FLOOR)
    )
    inventory = _run(
        services.core.asset.plan_inventory_changes(
            "qq-2", (InventoryAdjustment(herb_id, "03", 1),)
        )
    )
    _commit(services, "qq-2", "prepare-contribution-herb", inventory.operations)
    _run(
        services.features.zongmen_lingcang.donate_material(
            "qq-2", "contribution-herb", "灵植", herb_id, "03", 1
        )
    )
    assert _run(services.core.character.profile("qq-2")).sect_contribution == expected
    assert (
        _run(services.core.sect_progress.snapshot(member.sect_id)).total_contribution
        == 500 + expected
    )

    _run(services.features.zongmen.kick("qq-1", "白川", "kick-contributor"))
    assert _run(services.core.character.profile("qq-2")).sect_contribution == expected
    assert (
        _run(services.core.sect_progress.snapshot(member.sect_id)).total_contribution
        == 500
    )


def test_failed_material_donation_changes_no_asset_or_contribution(services) -> None:
    _create_sect(services)
    herb_id = next(
        content_id
        for content_id in services.core.data.entities("物品")
        if services.core.data.entity_record("物品", content_id).number_category
        == "灵植"
    )
    inventory = _run(
        services.core.asset.plan_inventory_changes(
            "qq-1", (InventoryAdjustment(herb_id, "01", 1),)
        )
    )
    _commit(services, "qq-1", "prepare-failed-donation", inventory.operations)

    with pytest.raises(SectAssetError):
        _run(
            services.core.sect_assets.donate_material(
                "qq-1", "failed-donation", "灵植", herb_id, "01", 2
            )
        )

    assert _run(services.core.character.profile("qq-1")).sect_contribution == 0
    assert _run(services.core.asset.inventory_stacks("qq-1", herb_id))[0].quantity == 1
    assert _run(services.core.sect_assets.lingcang("qq-1")).entries == ()


def test_resource_multipliers_reach_production_and_gathering_snapshots(
    services,
) -> None:
    _create_sect(services)
    _seed_facility_resources(services)
    member = _run(services.core.sect.membership("qq-1"))
    assert member is not None
    progress = _run(services.core.sect_progress.snapshot(member.sect_id))
    assert progress.production_multiplier > 1
    assert progress.gathering_multiplier > 1

    production = services.core.sect_production
    facility = next(
        value for value in production.status().facilities if value.kind == "灵脉"
    )
    started_at = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    _run(production.collect("灵脉", "qq-1", "production-start", now=started_at))
    expected_outputs, expected_stones = production._roll(
        facility,
        member.sect_id,
        0,
        facility.catch_up_limit,
        progress.production_multiplier,
    )
    _, base_stones = production._roll(
        facility, member.sect_id, 0, facility.catch_up_limit, 1.0
    )
    produced = _run(
        production.collect(
            "灵脉",
            "qq-1",
            "production-collect",
            now=started_at
            + timedelta(seconds=facility.period_seconds * facility.catch_up_limit),
        )
    )
    assert produced.outputs == expected_outputs
    assert produced.spirit_stones == expected_stones
    assert produced.spirit_stones > base_stones

    _run(services.features.zongmen_shanmen.leave("qq-1", "gate-leave-gathering"))
    gathering_started = _run(
        services.core.gathering.start(
            GatheringStartCommand(
                "采药",
                "qq-1",
                "sect-gathering",
                ("qq-1",),
                seed=19,
                started_at=started_at,
            )
        )
    )
    session = _run(
        services.core.database.get(
            StateAddress("qq-1", "gathering_session", gathering_started.session_id)
        )
    )
    assert session is not None
    assert (
        session.value["用户结果"]["qq-1"]["宗门采集倍率"]
        == progress.gathering_multiplier
    )


def test_production_start_and_collect_actions_match_the_real_commands(services) -> None:
    _create_sect(services)
    feature = services.features.zongmen_shengchan

    unopened = _run(feature.view("灵脉", "qq-1"))
    assert [(action.label, action.command) for action in feature.actions(unopened)] == [
        ("开启", "灵脉 开启")
    ]
    assert feature.actions(_run(feature.view("灵脉", "qq-2"))) == ()

    started = _run(feature.start("灵脉", "qq-1", "start-lingmai"))
    assert started.newly_started is True
    assert feature.actions(started.view) == ()
    assert started.view.last_settled_at is not None
    mature = _run(
        services.core.sect_production.view(
            "灵脉",
            "qq-1",
            now=started.view.last_settled_at
            + timedelta(seconds=started.view.facility.period_seconds),
        )
    )
    assert [(action.label, action.command) for action in feature.actions(mature)] == [
        ("收取", "灵脉 收取")
    ]
    with pytest.raises(SectProductionFeatureError, match="已经开启"):
        _run(feature.start("灵脉", "qq-1", "start-lingmai-again"))

    with pytest.raises(SectProductionFeatureError, match="请先发送：灵田 开启"):
        _run(feature.collect("灵田", "qq-1", "collect-unopened-field"))


def test_cangjing_uses_highest_grade_and_invalidates_borrowing_after_kick(
    services,
) -> None:
    _create_sect(services)
    technique_id = next(iter(services.core.data.entities("功法")))
    low = _run(
        services.core.asset.plan_cultivation_acquisitions(
            "qq-1", (CultivationAcquisition("功法", technique_id, "01"),)
        )
    )
    high = _run(
        services.core.asset.plan_cultivation_acquisitions(
            "qq-2", (CultivationAcquisition("功法", technique_id, "03"),)
        )
    )
    _commit(services, "qq-1", "prepare-technique-low", low.operations)
    _commit(services, "qq-2", "prepare-technique-high", high.operations)

    page = _run(services.features.zongmen_cangjing.page("qq-2"))
    technique = next(
        value for value in page.entries if value.content_id == technique_id
    )
    assert technique.grade_id == "03"
    _run(
        services.features.zongmen_cangjing.borrow(
            "qq-2", "borrow-technique", technique_id, 1
        )
    )
    equipped = _run(services.core.character.profile("qq-2")).equipped_content
    assert any(
        value.category == "功法"
        and value.content_id == technique_id
        and value.grade == "03"
        for value in equipped
    )

    _run(services.features.zongmen.kick("qq-1", "白川", "sect-kick"))
    equipped_after = _run(services.core.character.profile("qq-2")).equipped_content
    assert all(value.content_id != technique_id for value in equipped_after)


def test_sect_facility_roles_follow_officer_rules(services) -> None:
    _create_sect(services)
    facilities = services.features.zongmen_sheshi

    with pytest.raises(SectFacilityFeatureError, match="不能调用宗门灵藏材料"):
        _run(facilities.page("炼丹", "qq-2", "宗门"))
    with pytest.raises(SectFacilityError, match="不能炼制圣品"):
        services.core.sect_facilities.authorize("弟子", "个人纳戒", "圣品")

    _run(services.features.zongmen.appoint_elder("qq-1", "白川", "appoint-elder"))
    page = _run(facilities.page("炼丹", "qq-2", "宗门"))
    assert page.role == "长老"
    assert page.material_source == "宗门灵藏"

    _run(services.features.zongmen.remove_elder("qq-1", "白川", "remove-elder"))
    with pytest.raises(SectFacilityFeatureError, match="不能调用宗门灵藏材料"):
        _run(facilities.page("炼丹", "qq-2", "宗门"))


def test_sect_alchemy_keeps_personal_and_sect_outputs_separate(services) -> None:
    _create_sect(services)
    _seed_facility_resources(services)
    facilities = services.features.zongmen_sheshi

    page = _run(facilities.page("炼丹", "qq-1", "个人", "恢复丹"))
    recipe = next(entry for entry in page.entries if entry.available)
    preview = _run(facilities.preview("炼丹", "qq-1", "个人", recipe.content_id))
    before = _run(
        services.core.asset.inventory_stacks(
            "qq-1", preview.assessment.recipe.medicine_id
        )
    )
    result = _run(
        facilities.craft("炼丹", "qq-1", "personal-alchemy", "个人", recipe.content_id)
    )
    after = _run(
        services.core.asset.inventory_stacks(
            "qq-1", preview.assessment.recipe.medicine_id
        )
    )
    assert result.destination == "纳戒"
    assert (
        sum(value.quantity for value in after)
        == sum(value.quantity for value in before) + 1
    )

    sect_preview = _run(facilities.preview("炼丹", "qq-1", "个人", recipe.content_id))
    materials = (
        (sect_preview.assessment.beast_material, "兽宝"),
        *((value, "灵植") for value in sect_preview.assessment.herb_materials),
    )
    for index, (material, category) in enumerate(materials):
        assert material is not None
        _run(
            services.features.zongmen_lingcang.donate_material(
                "qq-1",
                f"sect-material-{index}",
                category,
                material.item_id,
                material.grade_id,
                material.quantity,
            )
        )
    member = _run(services.core.sect.membership("qq-1"))
    assert member is not None
    progress = _run(services.core.sect_progress.snapshot(member.sect_id))
    discounted = _run(facilities.preview("炼丹", "qq-1", "宗门", recipe.content_id))
    assert discounted.spirit_stone_cost == max(
        1, int(sect_preview.spirit_stone_cost * progress.facility_cost_multiplier)
    )
    stones_before = _run(services.core.sect_assets.lingcang("qq-1")).spirit_stones
    sect_result = _run(
        facilities.craft("炼丹", "qq-1", "sect-alchemy", "宗门", recipe.content_id)
    )
    vault = _run(services.core.sect_assets.wanzhen("qq-1"))
    assert sect_result.destination == "万珍殿"
    assert any(
        entry.category == "丹药"
        and entry.content_id == sect_preview.assessment.recipe.medicine_id
        for entry in vault.entries
    )
    assert (
        sect_result.spirit_stones_after == stones_before - sect_result.spirit_stone_cost
    )


def test_sect_forging_keeps_personal_and_sect_outputs_separate(services) -> None:
    _create_sect(services)
    _seed_facility_resources(services)
    facilities = services.features.zongmen_sheshi

    page = _run(facilities.page("炼器", "qq-1", "个人", "灵器"))
    law = next(entry for entry in page.entries if entry.available)
    personal = _run(
        facilities.craft("炼器", "qq-1", "personal-forging", "个人", law.content_id)
    )
    assert personal.destination == "器藏"
    assert (
        _run(services.core.asset.law_reserve_stack("qq-1", law.content_id)).quantity
        == 1
    )

    preview = _run(facilities.preview("炼器", "qq-1", "个人", law.content_id))
    materials = (
        *((material, "兽宝") for material in preview.assessment.beast_materials),
        *((material, "灵矿") for material in preview.assessment.mineral_materials),
    )
    for index, (material, category) in enumerate(materials):
        _run(
            services.features.zongmen_lingcang.donate_material(
                "qq-1",
                f"forging-material-{index}",
                category,
                material.item_id,
                material.grade_id,
                material.quantity,
            )
        )
    sect = _run(
        facilities.craft("炼器", "qq-1", "sect-forging", "宗门", law.content_id)
    )
    vault = _run(services.core.sect_assets.wanzhen("qq-1"))
    assert sect.destination == "万珍殿"
    assert any(
        entry.category == "器律" and entry.content_id == law.content_id
        for entry in vault.entries
    )


def test_sacred_sect_formations_are_stored_as_independent_instances(services) -> None:
    _create_sect(services)
    _seed_facility_resources(services)
    facilities = services.features.zongmen_sheshi

    formation = _run(facilities.page("炼阵", "qq-1", "个人")).entries[0]
    preview = _run(
        facilities.preview("炼阵", "qq-1", "个人", formation.content_id, "圣")
    )
    for index, material in enumerate(preview.assessment.materials):
        _run(
            services.features.zongmen_lingcang.donate_material(
                "qq-1",
                f"sacred-material-{index}",
                material.category,
                material.item_id,
                material.grade_id,
                material.quantity * 2,
            )
        )

    first = _run(
        facilities.craft(
            "炼阵", "qq-1", "sacred-formation-1", "宗门", formation.content_id, "圣"
        )
    )
    second = _run(
        facilities.craft(
            "炼阵", "qq-1", "sacred-formation-2", "宗门", formation.content_id, "圣"
        )
    )
    entries = tuple(
        entry
        for entry in _run(services.core.sect_assets.wanzhen("qq-1")).entries
        if entry.category == "阵法"
        and entry.content_id == formation.content_id
        and entry.grade_id == "05"
    )
    assert first.destination == second.destination == "万珍殿"
    assert len(entries) == 2
    assert all(entry.quantity == 1 for entry in entries)
    assert len({entry.entry_key for entry in entries}) == 2
    assert all(entry.materials for entry in entries)
