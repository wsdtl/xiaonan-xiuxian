"""正式 JSON 数据服务的最小契约测试。"""

from pathlib import Path

import pytest

from game.core.data import JsonDataError, JsonDataService


DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(scope="module")
def data_service() -> JsonDataService:
    service = JsonDataService(DATA_ROOT)
    service.initialize()
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


def test_legacy_compatibility_names_are_absent() -> None:
    json_files = DATA_ROOT.rglob("*.json")
    assert all("兼容名" not in path.read_text(encoding="utf-8") for path in json_files)


def test_term_binding_uses_explicit_slots() -> None:
    from game.core.combat.build_terms import bind_term_slots

    bound = bind_term_slots(
        {
            "词条": {
                "计量": {"正式槽位": {"名称": "正式名称", "上限": 9}},
                "状态": {},
                "规则": {},
                "判定": {},
            },
            "节点": {"能力": "修改机制计量", "计量槽位": "正式槽位"},
        }
    )
    assert bound["节点"]["计量"] == "正式槽位"
    assert bound["节点"]["最高值"] == 9
