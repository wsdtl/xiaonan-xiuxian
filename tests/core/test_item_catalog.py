from pathlib import Path

import pytest

from game.core.data import JsonDataService
from game.core.item_catalog import ItemCatalogService


@pytest.fixture
def catalog() -> ItemCatalogService:
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    service = ItemCatalogService(data)
    service.initialize()
    return service


def test_inspect_item_by_id_or_name_returns_one_read_only_public_definition(
    catalog: ItemCatalogService,
) -> None:
    detail = catalog.inspect("100005")

    assert catalog.inspect("小还丹") == detail
    assert detail.item_id == "100005"
    assert detail.category == "丹药"
    assert detail.name == "小还丹"
    assert detail.fields["使用效果"]["类型"] == "恢复血气"
    assert "权重" not in detail.fields
    assert "参考价" not in detail.fields
    with pytest.raises(TypeError):
        detail.fields["使用效果"]["恢复百分比"] = 99
    with pytest.raises(ValueError, match="未找到物品"):
        catalog.inspect("不存在的物品")


def test_category_indexes_cover_all_item_categories(catalog: ItemCatalogService) -> None:
    status = catalog.status()

    assert status.item_count == 941
    assert status.category_counts == {
        "丹药": 359,
        "灵植": 108,
        "灵矿": 108,
        "兽宝": 366,
    }


def test_entity_index_covers_numbered_non_item_content(catalog: ItemCatalogService) -> None:
    technique = catalog.inspect_entity("400541")
    assert technique.section == "功法"
    assert technique.category == "功法"
    assert technique.name
    assert "能力" in technique.fields

    formation = catalog.inspect_entity("530001")
    assert formation.section == "阵法"
    assert formation.fields["品级"]


def test_every_numbered_entity_is_reachable_by_id_and_name(
    catalog: ItemCatalogService,
) -> None:
    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    records = data.numbered_entities()

    assert len(records) == len({record.entity_id for record in records})
    for record in records:
        detail = catalog.inspect_entity(record.entity_id)
        assert detail.name == record.value["名称"]
        assert any(
            candidate.item_id == record.entity_id
            for candidate in catalog.find_entities_by_name(detail.name)
        )
