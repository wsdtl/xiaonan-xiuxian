"""正式 JSON 数据服务的最小契约测试。"""

from pathlib import Path

import pytest

from game.core.combat import expand_build_section
from game.core.data import JsonDataError, JsonDataService


DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="module")
def data_service() -> JsonDataService:
    service = JsonDataService(DATA_ROOT)
    service.initialize(expand=expand_build_section)
    return service


def test_data_snapshot_has_expected_shape(data_service: JsonDataService) -> None:
    status = data_service.status()
    assert status.loaded
    assert status.document_count > 0
    assert status.entity_count > 0
    assert status.pool_count > 0


def test_numbered_entities_are_unique_and_resolvable(
    data_service: JsonDataService,
) -> None:
    records = data_service.numbered_entities()
    keys = [(record.section, record.entity_id) for record in records]
    assert len(keys) == len(set(keys))
    for record in records[:25]:
        assert data_service.entity(record.section, record.entity_id) == record.value


def test_pool_expansion_is_stable_and_deduplicated(
    data_service: JsonDataService,
) -> None:
    records = data_service.numbered_entities()
    record = next(record for record in records if record.source_file)
    members = data_service.pool_members((record.source_file,), record.section)
    assert members
    assert len(members) == len(set(members))


def test_pool_index_has_declared_sections(data_service: JsonDataService) -> None:
    pools = data_service.pools()
    assert pools
    assert all(file_id and section for file_id, section in pools.items())


def test_snapshot_is_read_only(data_service: JsonDataService) -> None:
    record = data_service.numbered_entities()[0]
    value = data_service.entity(record.section, record.entity_id)
    with pytest.raises(TypeError):
        value["__test_mutation__"] = True  # type: ignore[index]


def test_unknown_entity_is_rejected(data_service: JsonDataService) -> None:
    with pytest.raises(JsonDataError):
        data_service.entity("不存在的类别", "000000")


def test_obsolete_names_are_absent() -> None:
    json_files = DATA_ROOT.rglob("*.json")
    assert all("兼容名" not in path.read_text(encoding="utf-8") for path in json_files)
    assert all("归脉" not in path.read_text(encoding="utf-8") for path in json_files)


def test_herbs_carry_their_own_meridian(data_service: JsonDataService) -> None:
    """归脉映射退役后，本脉落在灵植实体自己身上。"""

    herbs = [
        item_id
        for item_id in data_service.entities("基础物品")
        if data_service.entity_record("基础物品", item_id).number_category == "灵植"
    ]
    assert herbs
    allowed = {"青华", "丹离", "坤载", "太白", "玄冥"}
    for item_id in herbs:
        value = data_service.entity("基础物品", item_id)
        assert value.get("本脉") in allowed, (item_id, value.get("本脉"))


def test_recipes_and_laws_use_explicit_materials(data_service: JsonDataService) -> None:
    """丹药与器律都写显式材料，不再回查炉法/难度/铸法/兽引。"""

    for medicine_id, value in data_service.entities("丹药").items():
        assert value.get("材料"), medicine_id
        assert "炉法" not in value and "炼制难度" not in value, medicine_id
    for law_id, value in data_service.entities("器律").items():
        assert value.get("材料"), law_id
        assert "铸法" not in value and "兽引" not in value, law_id


def test_builds_carry_their_own_combat_text() -> None:
    """构筑必须自带完整能力树：不许按编号回查中间层，也不留词条表。"""

    patterns = (
        "战斗/内容/功法/*.json",
        "战斗/内容/真意/*.json",
        "战斗/内容/气机/*.json",
        "物品/内容/器律/*.json",
    )
    files = [path for pattern in patterns for path in DATA_ROOT.glob(pattern)]
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "引用战斗机制" not in text, path
        assert "引用被动机制" not in text, path
        assert '"词条"' not in text, path


def test_four_build_contracts_are_satisfied() -> None:
    """功法、真意、气机、器律各按自己的形状通过启动契约。"""

    from game.core.combat.builds import validate_builds
    from game.core.data import JsonDataService

    service = JsonDataService(DATA_ROOT)
    service.initialize(expand=expand_build_section)
    counts = validate_builds(service)
    assert set(counts) == {"功法", "真意", "气机", "器律"}
    assert all(value > 0 for value in counts.values())
