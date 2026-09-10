"""所有游戏微服务共享的正式 JSON 数据入口。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from threading import Lock
from types import MappingProxyType
from typing import Any

from .contracts import JsonDataError, JsonDataStatus, JsonEntity
from .files import JsonDataReader
from .loading import GameDataLoader, LoadedGameData


class JsonDataService:
    """启动时加载全部正式 JSON，并在进程内提供只读数据快照。"""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()
        self._load_lock = Lock()
        self._loaded: LoadedGameData | None = None

    @property
    def root(self) -> Path:
        return self._root

    def status(self) -> JsonDataStatus:
        loaded = self._loaded
        return JsonDataStatus(
            root=self._root,
            loaded=loaded is not None,
            document_count=len(loaded.catalog.documents) if loaded is not None else 0,
            content_document_count=(
                sum(document.scope == "内容" for document in loaded.catalog.documents)
                if loaded is not None
                else 0
            ),
            entity_count=loaded.entity_count if loaded is not None else 0,
            pool_count=loaded.pool_count if loaded is not None else 0,
        )

    def initialize(self) -> JsonDataStatus:
        """构建本进程唯一快照；数据更新必须通过重启服务生效。"""

        with self._load_lock:
            if self._loaded is not None:
                raise RuntimeError("正式 JSON 已加载；数据更新必须重启服务")

            loaded = GameDataLoader(JsonDataReader(self._root)).load()
            self._loaded = loaded
            return self.status()

    def dataset(self, name: str) -> Mapping[str, Any]:
        """按读取规则声明的数据集返回文件名到不可变正文的视图。"""

        dataset_name = str(name or "").strip()
        documents = self._require_loaded().catalog.dataset(dataset_name)
        return MappingProxyType(
            {document.descriptor.data_name: document.value for document in documents}
        )

    def entity(self, section: str, entity_id: str) -> Mapping[str, Any]:
        """按类别和稳定身份取得一个不可变正式实体。"""

        section_name = str(section or "").strip()
        entity_id = str(entity_id or "").strip()
        loaded = self._require_loaded()
        values = loaded.entities.get(section_name)
        if values is None:
            raise JsonDataError(f"未知实体类别：{section_name or '<空>'}")
        value = values.get(entity_id)
        if value is None:
            raise JsonDataError(f"实体不存在：{section_name} {entity_id or '<空>'}")
        return value

    def entities(self, section: str) -> Mapping[str, Mapping[str, Any]]:
        """取得一个类别的身份去重不可变实体索引。"""

        section_name = str(section or "").strip()
        loaded = self._require_loaded()
        values = loaded.entities.get(section_name)
        if values is None:
            raise JsonDataError(f"未知实体类别：{section_name or '<空>'}")
        return values

    def entity_record(self, section: str, entity_id: str) -> JsonEntity:
        """取得实体类别、编号类别、源文件和不可变正文。"""

        section_name = str(section or "").strip()
        entity_id = str(entity_id or "").strip()
        records = self._require_loaded().entity_records.get(section_name)
        if records is None:
            raise JsonDataError(f"未知实体类别：{section_name or '<空>'}")
        record = records.get(entity_id)
        if record is None:
            raise JsonDataError(f"实体不存在：{section_name} {entity_id or '<空>'}")
        return record

    def numbered_entities(self) -> tuple[JsonEntity, ...]:
        """返回全部正式编号实体，不包含命名实体、资源池和运行时对象。"""

        loaded = self._require_loaded()
        values = [
            record
            for records in loaded.entity_records.values()
            for record in records.values()
            if record.number_category
        ]
        return tuple(sorted(values, key=lambda item: (item.entity_id, item.section)))

    def entity_fields(
        self,
        section: str,
        fields: Sequence[str],
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        """取得一个类别的指定实体字段，不复制完整实体正文。"""

        section_name = str(section or "").strip()
        field_names = _field_names(fields)
        loaded = self._require_loaded()
        values = loaded.entities.get(section_name)
        if values is None:
            raise JsonDataError(f"未知实体类别：{section_name or '<空>'}")
        return tuple(
            (entity_id, _select_fields(value, field_names))
            for entity_id, value in values.items()
        )

    def all_members(self, section: str) -> tuple[str, ...]:
        """返回一个实体类别的全池稳定身份，不需要额外全池 JSON。"""

        return self._require_loaded().all_members(section)

    def number_category_members(self, number_category: str) -> tuple[str, ...]:
        """返回一个编号类别的全部稳定身份，用于实体大类中的虚拟子池。"""

        return self._require_loaded().members_by_number_category(number_category)

    def pool_members(
        self,
        file_ids: Sequence[str],
        section: str,
        *,
        deduplicate: bool = True,
    ) -> tuple[str, ...]:
        """展开资源池，只返回稳定身份，不暴露实体正文。"""

        values = self._require_loaded().resolve_pool(
            tuple(file_ids),
            section,
            deduplicate=deduplicate,
        )
        return tuple(entity_id for entity_id, _ in values)

    def pool_fields(
        self,
        file_ids: Sequence[str],
        section: str,
        fields: Sequence[str],
        *,
        deduplicate: bool = True,
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        """展开资源池，并仅复制调用方明确请求的实体字段。"""

        field_names = _field_names(fields)
        values = self._require_loaded().resolve_pool(
            tuple(file_ids),
            section,
            deduplicate=deduplicate,
        )
        return tuple(
            (entity_id, _select_fields(value, field_names))
            for entity_id, value in values
        )

    def document_paths(self) -> tuple[str, ...]:
        return tuple(
            document.relative_path
            for document in self._require_loaded().catalog.documents
        )

    def pools(self) -> Mapping[str, str]:
        """返回资源池文件到实体类别的只读索引，供审查和管理工具使用。"""

        loaded = self._require_loaded()
        return MappingProxyType(
            {file_id: pool.section for file_id, pool in loaded.pool_definitions.items()}
        )

    def _require_loaded(self) -> LoadedGameData:
        if self._loaded is None:
            raise RuntimeError("JSON 数据微服务尚未加载")
        return self._loaded


def _field_names(fields: Sequence[str]) -> tuple[str, ...]:
    field_names = tuple(str(field or "").strip() for field in fields)
    if not field_names or any(not field for field in field_names):
        raise JsonDataError("实体字段不能为空")
    if len(field_names) != len(set(field_names)):
        raise JsonDataError("实体字段不能重复")
    return field_names


def _select_fields(
    value: Mapping[str, Any],
    fields: Sequence[str],
) -> Mapping[str, Any]:
    missing = tuple(field for field in fields if field not in value)
    if missing:
        raise JsonDataError("实体缺少请求字段：" + "、".join(missing))
    return MappingProxyType({field: value[field] for field in fields})


def materialize(value: Any) -> Any:
    """把不可变 JSON 视图转换为领域服务自己的可变运行值。"""

    if isinstance(value, Mapping):
        return {str(key): materialize(raw) for key, raw in value.items()}
    if isinstance(value, tuple):
        return [materialize(item) for item in value]
    return value


__all__ = ["JsonDataService", "materialize"]
