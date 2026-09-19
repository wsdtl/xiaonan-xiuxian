"""正式 JSON 的实体、资源池与世界索引。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from .contracts import JsonDataError, JsonEntity
from .files import (
    ENTITY_ID_POOL,
    NAMED_ENTITY,
    NAMED_ENTITY_POOL,
    NUMBERED_ENTITY_LIST,
    NUMBERED_ENTITY_POOL,
    OBJECT,
    OBJECT_LIST,
    SOURCE_POOL,
    JsonDataCatalog,
    JsonDataReader,
    JsonDocument,
)


@dataclass(frozen=True)
class PoolDefinition:
    section: str
    entity_ids: tuple[str, ...] = ()
    source_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoadedGameData:
    catalog: JsonDataCatalog
    entities: Mapping[str, Mapping[str, Any]]
    entity_records: Mapping[str, Mapping[str, JsonEntity]]
    number_category_members: Mapping[str, tuple[str, ...]]
    pool_definitions: Mapping[str, PoolDefinition]

    @property
    def entity_count(self) -> int:
        return sum(len(values) for values in self.entities.values())

    @property
    def pool_count(self) -> int:
        return len(self.pool_definitions)

    def resolve_pool(
        self,
        file_ids: Sequence[str],
        section: str,
        *,
        deduplicate: bool,
    ) -> tuple[tuple[str, Mapping[str, Any]], ...]:
        """递归展开直接编号池、源文件池和实体源文件。"""

        section_name = str(section or "").strip()
        if section_name not in self.entities:
            raise JsonDataError(f"不支持的资源池集合：{section_name or '<空>'}")
        result: list[tuple[str, Mapping[str, Any]]] = []
        for file_id in file_ids:
            result.extend(self._resolve_pool_file(str(file_id), section_name, ()))
        if not result:
            joined = "、".join(str(value) for value in file_ids) or "<空>"
            raise JsonDataError(f"资源池为空：{joined} -> {section_name}")
        result.sort(key=lambda entry: entry[0])
        if not deduplicate:
            return tuple(result)
        unique: list[tuple[str, Mapping[str, Any]]] = []
        seen: set[str] = set()
        for entity_id, value in result:
            if entity_id in seen:
                continue
            seen.add(entity_id)
            unique.append((entity_id, value))
        return tuple(unique)

    def all_members(self, section: str) -> tuple[str, ...]:
        section_name = str(section or "").strip()
        values = self.entities.get(section_name)
        if values is None:
            raise JsonDataError(f"未知实体类别：{section_name or '<空>'}")
        return tuple(sorted(values))

    def members_by_number_category(self, number_category: str) -> tuple[str, ...]:
        category = str(number_category or "").strip()
        values = self.number_category_members.get(category)
        if values is None:
            raise JsonDataError(f"未知编号类别：{category or '<空>'}")
        return values

    def _resolve_pool_file(
        self,
        file_id: str,
        section: str,
        stack: tuple[str, ...],
    ) -> list[tuple[str, Mapping[str, Any]]]:
        document = self.catalog.content_file(file_id)
        canonical = document.file_id
        pool = self.pool_definitions.get(canonical)
        if pool is None:
            raise JsonDataError(f"内容文件不是资源池：{document.relative_path}")
        if pool.section != section:
            raise JsonDataError(
                f"资源池集合不匹配：{document.relative_path} 是 {pool.section}，不是 {section}"
            )
        cycle_key = canonical.casefold()
        stack_keys = tuple(value.casefold() for value in stack)
        if cycle_key in stack_keys:
            chain = " -> ".join((*stack, canonical))
            raise JsonDataError(f"资源池形成循环引用：{chain}")
        entities = self.entities[section]
        result: list[tuple[str, Mapping[str, Any]]] = []
        for entity_id in pool.entity_ids:
            value = entities.get(entity_id)
            if value is None:
                raise JsonDataError(
                    f"资源池引用不存在的{section}：{document.relative_path} -> {entity_id}"
                )
            result.append((entity_id, value))
        next_stack = (*stack, canonical)
        for source_file in pool.source_files:
            result.extend(self._resolve_pool_file(source_file, section, next_stack))
        return result


class GameDataLoader:
    """注册四类正式 JSON，并建立可验证的运行期只读索引。"""

    def __init__(self, reader: JsonDataReader) -> None:
        self.reader = reader

    def load(self, expand: "Callable[[str, Mapping[str, Any]], Any] | None" = None) -> LoadedGameData:
        """读取并建立运行期只读索引。

        `expand` 是**装载期后处理钩子**：逐段落对实体索引做一次改写，发生在快照
        冻结**之前**。构筑模板引用必须在这里展开成完整的树，否则「快照里的原始形态」
        与「某处展开后的形态」会并存，同一个实体出现两种样子，读取方各拿一种。
        """

        catalog = self.reader.load_catalog()
        entities, records, pools = _index_content(catalog)
        if expand is not None:
            # 一个段落有**两份索引**：`entities`（按类别取实体）与 `records`
            # （`JsonEntity`，带来源与编号类别）。两者的 `value` 原本指向同一个对象，
            # 所以展开必须**同时改写两份**——只改前者会让 `numbered_entities()` 这条
            # 读取路径继续看到未展开的引用（实测：查看页把模板引用渲染成
            # `〈未支持：〉`，而战斗语料一条都测不出来，因为战斗走的是 `entities`）。
            for section in tuple(entities):
                expanded = expand(section, entities[section])
                if expanded is entities[section]:
                    continue
                # 钩子返回的是普通字典（展开要构造新映射）。**必须逐个实体重新裹回只读**：
                # `MappingProxyType(dict(...))` 只冻结外层映射，内层实体仍是普通字典，
                # 快照的只读承诺就破了（`test_snapshot_is_read_only` 会抓到）。
                frozen = {
                    entity_id: MappingProxyType(dict(value))
                    for entity_id, value in expanded.items()
                }
                entities[section] = MappingProxyType(frozen)
                records[section] = {
                    entity_id: (
                        replace(record, value=frozen[entity_id])
                        if record.value is not frozen[entity_id]
                        else record
                    )
                    for entity_id, record in records[section].items()
                }
        _validate_number_prefixes(catalog)
        loaded = LoadedGameData(
            catalog=catalog,
            entities=MappingProxyType(
                {
                    section: MappingProxyType(values)
                    for section, values in entities.items()
                }
            ),
            entity_records=MappingProxyType(
                {
                    section: MappingProxyType(values)
                    for section, values in records.items()
                }
            ),
            number_category_members=MappingProxyType(
                _index_number_category_members(records)
            ),
            pool_definitions=MappingProxyType(pools),
        )
        _validate_all_pools(loaded)
        _validate_pool_references(loaded)
        return loaded


def _index_content(
    catalog: JsonDataCatalog,
) -> tuple[
    dict[str, dict[str, Mapping[str, Any]]],
    dict[str, dict[str, JsonEntity]],
    dict[str, PoolDefinition],
]:
    sections = {
        document.descriptor.section
        for document in catalog.documents
        if document.descriptor.section
    }
    entities: dict[str, dict[str, Mapping[str, Any]]] = {
        section: {} for section in sorted(sections)
    }
    sources: dict[str, dict[str, str]] = {section: {} for section in entities}
    records: dict[str, dict[str, JsonEntity]] = {section: {} for section in entities}
    pools: dict[str, PoolDefinition] = {}
    for document in catalog.documents:
        descriptor = document.descriptor
        _validate_document_shape(document)
        if not descriptor.section:
            continue
        if descriptor.shape in {ENTITY_ID_POOL, SOURCE_POOL}:
            pools[document.file_id] = _reference_pool(document, descriptor.section)
            continue
        entries = _document_entries(document)
        if descriptor.source_pool:
            pools[document.file_id] = PoolDefinition(
                section=descriptor.section,
                entity_ids=tuple(entity_id for entity_id, _ in entries),
            )
        values = entities.get(descriptor.section)
        if values is None:
            continue
        for entity_id, value in entries:
            previous = values.get(entity_id)
            if previous is None:
                values[entity_id] = value
                sources[descriptor.section][entity_id] = document.relative_path
                records[descriptor.section][entity_id] = JsonEntity(
                    entity_id=entity_id,
                    section=descriptor.section,
                    number_category=descriptor.number_category,
                    source_file=document.file_id,
                    directory_owner=descriptor.directory_owner,
                    # 快照承诺只读，而 `entity_records[..].value` 是**另一条**读取路径
                    # （`numbered_entities()`、`实体查询`）。原先这里放普通字典，
                    # 于是同一个实体从 `entities` 拿是只读、从 `records` 拿是可写——
                    # 迁移后把功能测试的读取路径从前者换到后者才暴露出来。
                    value=MappingProxyType(dict(value)),
                )
                continue
            if _entity_signature(previous) != _entity_signature(value):
                raise JsonDataError(
                    f"实体身份冲突：{descriptor.section} {entity_id} 同时定义于 "
                    f"{sources[descriptor.section][entity_id]} 与 {document.relative_path}"
                )
    return entities, records, pools


def _index_number_category_members(
    records: Mapping[str, Mapping[str, JsonEntity]],
) -> dict[str, tuple[str, ...]]:
    members: dict[str, set[str]] = {}
    for values in records.values():
        for entity_id, record in values.items():
            if record.number_category:
                members.setdefault(record.number_category, set()).add(entity_id)
    return {
        category: tuple(sorted(entity_ids))
        for category, entity_ids in sorted(members.items())
    }


def _document_entries(
    document: JsonDocument,
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    descriptor = document.descriptor
    value = document.value
    section = descriptor.section
    if descriptor.shape in {NUMBERED_ENTITY_LIST, NUMBERED_ENTITY_POOL}:
        return _numbered_entries(value, document, section)
    if descriptor.shape == NAMED_ENTITY_POOL:
        return _named_collection_entries(value, document, section)
    if descriptor.shape == NAMED_ENTITY:
        if not isinstance(value, Mapping):
            raise JsonDataError(f"命名内容文件根值必须是对象：{document.relative_path}")
        entity_id = document.file_id
        declared_name = value.get("名称")
        if declared_name is not None and str(declared_name).strip() != entity_id:
            raise JsonDataError(
                f"命名内容身份必须使用文件名：{document.relative_path} -> {declared_name}"
            )
        return ((entity_id, value),)
    raise JsonDataError(f"内容文档形态不受支持：{document.relative_path}")


def _numbered_entries(
    value: Any,
    document: JsonDocument,
    section: str,
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    if not _is_array(value):
        raise JsonDataError(
            f"编号内容文件根值必须是数组：{document.relative_path} -> {section}"
        )
    result: list[tuple[str, Mapping[str, Any]]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise JsonDataError(
                f"内容对象必须是字典：{document.relative_path} -> {section}[{index}]"
            )
        entity_id = str(raw.get("编号") or "").strip()
        if not entity_id:
            raise JsonDataError(
                f"内容对象缺少编号：{document.relative_path} -> {section}[{index}]"
            )
        if entity_id in seen:
            raise JsonDataError(
                f"内容文件存在重复编号：{document.relative_path} -> {entity_id}"
            )
        seen.add(entity_id)
        result.append((entity_id, raw))
    if not result:
        raise JsonDataError(f"编号内容文件不能为空：{document.relative_path}")
    return tuple(result)


def _named_collection_entries(
    value: Any,
    document: JsonDocument,
    section: str,
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    if not isinstance(value, Mapping) or not value:
        raise JsonDataError(
            f"命名内容集合必须是非空对象：{document.relative_path} -> {section}"
        )
    result = []
    for entity_id, raw in value.items():
        if not isinstance(raw, Mapping):
            raise JsonDataError(
                f"命名内容对象必须是字典：{document.relative_path} -> {section}.{entity_id}"
            )
        result.append((str(entity_id), raw))
    return tuple(result)


def _reference_pool(document: JsonDocument, section: str) -> PoolDefinition:
    value = document.value
    if not _is_array(value) or not value:
        raise JsonDataError(f"引用池必须是非空字符串数组：{document.relative_path}")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise JsonDataError(f"引用池包含无效成员：{document.relative_path}")
    references = tuple(item.strip() for item in value)
    if len(references) != len(set(references)):
        raise JsonDataError(f"引用池包含重复成员：{document.relative_path}")
    if document.descriptor.shape == ENTITY_ID_POOL:
        if not all(_looks_like_entity_id(item) for item in references):
            raise JsonDataError(f"编号池只能保存六位实体编号：{document.relative_path}")
        return PoolDefinition(section=section, entity_ids=references)
    if any(_looks_like_entity_id(item) for item in references):
        raise JsonDataError(f"源池只能保存源文件名：{document.relative_path}")
    return PoolDefinition(section=section, source_files=references)


def _validate_document_shape(document: JsonDocument) -> None:
    shape = document.descriptor.shape
    value = document.value
    if shape == OBJECT and not isinstance(value, Mapping):
        raise JsonDataError(f"对象文档根值必须是对象：{document.relative_path}")
    if shape == OBJECT_LIST and (
        not _is_array(value) or any(not isinstance(item, Mapping) for item in value)
    ):
        raise JsonDataError(f"字典列表文档根值必须是字典数组：{document.relative_path}")
    if shape == NAMED_ENTITY and not isinstance(value, Mapping):
        raise JsonDataError(f"命名实体文档根值必须是对象：{document.relative_path}")


def _validate_all_pools(loaded: LoadedGameData) -> None:
    for file_id, pool in loaded.pool_definitions.items():
        loaded.resolve_pool((file_id,), pool.section, deduplicate=False)


def _validate_pool_references(loaded: LoadedGameData) -> None:
    expected_sections = loaded.catalog.read_rules.pool_reference_sections
    for document in loaded.catalog.documents:
        if document.descriptor.dataset == "读取定义":
            continue
        for key, reference in _iter_pool_references(document.value):
            expected = expected_sections.get(key)
            if expected is None:
                raise JsonDataError(
                    f"未登记的资源池引用字段：{document.relative_path} -> {key}"
                )
            target = loaded.catalog.content_file(reference)
            pool = loaded.pool_definitions.get(target.file_id)
            if pool is None or pool.section != expected:
                actual = pool.section if pool is not None else "非资源池"
                raise JsonDataError(
                    f"资源池引用类别错误：{document.relative_path} -> {key}={reference} "
                    f"应为{expected}，实际为{actual}"
                )


def _validate_number_prefixes(
    catalog: JsonDataCatalog,
) -> None:
    number_definition_path = catalog.read_rules.number_definition_path
    number_definition = catalog.read(number_definition_path)
    if not isinstance(number_definition, Mapping):
        raise JsonDataError(f"编号定义没有加载：{number_definition_path}")
    rule = number_definition.get("编号规则")
    prefix_rows = number_definition.get("编号前缀")
    if not isinstance(rule, Mapping) or not _is_array(prefix_rows):
        raise JsonDataError("基础/定义/编号.json 缺少编号规则或编号前缀")
    digits = int(rule.get("位数") or 0)
    prefix_digits = int(rule.get("前缀位数") or 0)
    allowed: dict[str, set[str]] = {}
    for row in prefix_rows:
        if not isinstance(row, Mapping):
            raise JsonDataError("基础/定义/编号.json.编号前缀必须是字典数组")
        prefix = str(row.get("前缀") or "")
        category = str(row.get("类别") or "")
        if not prefix or not category:
            raise JsonDataError("基础/定义/编号.json.编号前缀缺少前缀或类别")
        allowed.setdefault(category, set()).add(prefix)
    for document in catalog.documents:
        descriptor = document.descriptor
        if descriptor.shape not in {NUMBERED_ENTITY_LIST, NUMBERED_ENTITY_POOL}:
            continue
        category = descriptor.number_category
        prefixes = allowed.get(category, set())
        if not prefixes:
            raise JsonDataError(f"基础/定义/编号.json 没有登记{category}编号前缀")
        for entity_id, _ in _numbered_entries(
            document.value,
            document,
            descriptor.section,
        ):
            if len(entity_id) != digits or not entity_id.isdigit():
                raise JsonDataError(
                    f"{descriptor.section}编号不符合{digits}位数字规则：{entity_id}"
                )
            if entity_id[:prefix_digits] not in prefixes:
                raise JsonDataError(
                    f"{descriptor.section}编号前缀不属于{category}：{entity_id}"
                )


def _iter_pool_references(value: Any) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []

    def visit(current: Any) -> None:
        if isinstance(current, Mapping):
            for raw_key, raw_value in current.items():
                key = str(raw_key)
                if key.endswith("池"):
                    if isinstance(raw_value, str):
                        result.append((key, raw_value))
                    elif _is_array(raw_value) and all(
                        isinstance(item, str) for item in raw_value
                    ):
                        result.extend((key, item) for item in raw_value)
                    else:
                        raise JsonDataError(
                            f"资源池引用必须是文件名或文件名数组：{key}"
                        )
                visit(raw_value)
        elif _is_array(current):
            for item in current:
                visit(item)

    visit(value)
    return tuple(result)


def _looks_like_entity_id(value: str) -> bool:
    return len(value) == 6 and value.isdigit()


def _entity_signature(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): raw for key, raw in value.items()}


def _is_array(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes)
