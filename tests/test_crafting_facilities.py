"""城池炼制设施、批量材料节省与个人灵石消耗。"""

from __future__ import annotations

import asyncio

import pytest

from game.core.asset.contracts import InventoryAdjustment
from game.core.character.contracts import CharacterCreateCommand
from game.core.database.contracts import TransactionCommand


def _seed(services, user_id: str, adjustments) -> None:
    plan = asyncio.run(services.core.asset.plan_inventory_changes(user_id, adjustments))
    asyncio.run(
        services.core.database.commit(
            TransactionCommand(user_id, "seed-" + user_id, "测试发放", plan.operations, {})
        )
    )


def test_forging_facility_and_batch_saving(services) -> None:
    from game.core.forging import ForgingMaterial

    law = services.core.forging.laws("后天灵宝")[0]
    assert law.materials
    user_city = "forge-city"
    user_wild = "forge-wild"
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(user_city, "create-forge-city", "城炼", "男", (51, 55), "")
        )
    )
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(user_wild, "create-forge-wild", "野炼", "男", (15, 17), "")
        )
    )
    adjustments = []
    for raw in law.materials:
        adjustments.append(
            InventoryAdjustment(str(raw["编号"]), "01", int(raw["数量"]) * 20)
        )
    _seed(services, user_city, tuple(adjustments))
    _seed(services, user_wild, tuple(adjustments))

    city = asyncio.run(services.core.forging.preview(user_city, law.law_id, 10))
    wild = asyncio.run(services.core.forging.preview(user_wild, law.law_id, 10))
    assert city.facility is not None and city.facility.name == "天衡炉"
    assert wild.facility is None
    assert city.spirit_stone_cost == wild.spirit_stone_cost == 4800 * 10
    city_materials = sum(m.quantity for m in city.beast_materials + city.mineral_materials)
    wild_materials = sum(m.quantity for m in wild.beast_materials + wild.mineral_materials)
    assert city_materials < wild_materials
    assert city.can_forge and wild.can_forge

    before = asyncio.run(services.core.asset.spirit_stone_balance(user_city))
    result = asyncio.run(services.core.forging.forge(user_city, "forge-batch", law.law_id, 10))
    after = asyncio.run(services.core.asset.spirit_stone_balance(user_city))
    assert result.quantity_after == 10
    assert before - after == 48000


def test_alchemy_facility_is_one_time_and_batch_saving(services) -> None:
    user_city = "alchemy-city"
    user_wild = "alchemy-wild"
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(user_city, "create-alchemy-city", "城丹", "男", (51, 35), "")
        )
    )
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(user_wild, "create-alchemy-wild", "野丹", "男", (15, 17), "")
        )
    )
    adjustments = (
        InventoryAdjustment("210064", "04", 200),
        InventoryAdjustment("200001", "04", 400),
        InventoryAdjustment("220001", "04", 400),
    )
    _seed(services, user_city, adjustments)
    _seed(services, user_wild, adjustments)

    city = asyncio.run(services.core.alchemy.preview(user_city, "120033", quantity=100))
    wild = asyncio.run(services.core.alchemy.preview(user_wild, "120033", quantity=100))
    assert city.facility is not None and city.facility.name == "丹霞鼎"
    assert wild.facility is None
    assert city.spirit_stone_cost == wild.spirit_stone_cost == 300 * 100
    city_total = sum(m.quantity for m in (city.beast_material,) + city.herb_materials)
    wild_total = sum(m.quantity for m in (wild.beast_material,) + wild.herb_materials)
    assert city_total < wild_total
    assert city.can_refine and wild.can_refine

    before = asyncio.run(services.core.asset.spirit_stone_balance(user_city))
    result = asyncio.run(services.core.alchemy.refine(user_city, "alchemy-batch", "120033", quantity=100))
    after = asyncio.run(services.core.asset.spirit_stone_balance(user_city))
    assert result.quantity_after == 100
    assert before - after == 30000


def test_formation_facility_and_personal_stones(services) -> None:
    user = "formation-facility"
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(user, "create-formation-facility", "城阵", "男", (18, 53), "")
        )
    )
    _seed(services, user, (
        InventoryAdjustment("220032", "01", 2),
        InventoryAdjustment("220086", "01", 2),
        InventoryAdjustment("210001", "01", 8),
        InventoryAdjustment("220001", "01", 12),
        InventoryAdjustment("200001", "01", 12),
    ))
    preview = asyncio.run(services.core.formation.preview(user, "530001", "黄品"))
    assert preview.facility is not None and preview.facility.name == "云京台"
    assert preview.spirit_stone_cost == 500
    assert preview.can_form
    before = asyncio.run(services.core.asset.spirit_stone_balance(user))
    result = asyncio.run(
        services.core.formation.form(user, "formation-facility-1", "530001", "黄品")
    )
    after = asyncio.run(services.core.asset.spirit_stone_balance(user))
    assert result.quantity_after >= 1
    assert before - after == 500


def test_crafting_npc_mode_is_gone(services) -> None:
    data = services.core.data
    from game.core.data import JsonDataError

    for kind in ("炼器工匠", "炼丹师", "阵师"):
        with pytest.raises(JsonDataError):
            data.entities(kind)
    facilities = []
    for location in data.entities("地点").values():
        facilities.append(location.get("设施"))
        assert not ({"锻造", "炼丹", "炼阵"} & set(location.get("可用功能") or ()))
    present = [value for value in facilities if value is not None]
    assert len(present) == 6
    categories = [value["类别"] for value in present]
    assert categories.count("炼器") == 2
    assert categories.count("炼丹") == 2
    assert categories.count("炼阵") == 2


def test_catalogs_do_not_scan_inventory(services, monkeypatch) -> None:
    """目录页只读静态配方；不得为了列目录去读纳戒材料。"""

    user = "catalog-user"
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(user, "create-catalog", "目录", "男", (15, 17), "")
        )
    )

    async def fail(_user_id):
        raise AssertionError("目录不应读取纳戒材料")

    monkeypatch.setattr(services.core.alchemy, "_material_entries", fail)
    monkeypatch.setattr(services.core.forging, "_material_entries", fail)

    alchemy = asyncio.run(services.core.alchemy.list_recipes(user, "恢复丹"))
    assert alchemy.entries
    forging = asyncio.run(services.core.forging.list_laws(user, "灵器"))
    assert forging.entries
    formation = asyncio.run(services.core.formation.overview(user))
    assert formation.entries
