"""面向其他游戏服务的只读物品查询索引。"""

from __future__ import annotations

from collections import defaultdict
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService

from .contracts import (
    ItemCatalogStatus,
    ItemDetail,
    ItemNameAmbiguousError,
    ItemNotFoundError,
    ItemSummary,
)

ITEM_SECTION = "物品"
_ENTITY_FIELDS = {
    "丹方": ("炼制难度", "炉法", "成丹"),
    "人物状态": ("可转入", "附近公开"),
    "伤势": ("来源类别", "匹配状态", "战斗状态", "叠加", "治疗"),
    "先天灵宝": ("权柄", "规则介入"),
    "功法": ("属性构成", "能力"),
    "器律": ("属性构成", "器阶", "铸法", "兽引", "能力"),
    "境界": ("等级下限", "等级上限", "下一境界"),
    "战场环境": ("阶段",),
    "机制": ("节点",),
    "气机": ("属性构成", "能力"),
    "炼丹师": ("称号", "炉名", "丹道传承", "开放丹方"),
    "炼器工匠": ("称号", "炉名", "工艺流派", "开放器律"),
    "物品": ("使用效果", "强度"),
    "真意": ("属性构成", "能力"),
    "道侣": ("性别", "身份", "结交", "等级", "资质范围", "本命武器"),
    "阵师": ("称号", "阵台", "阵道传承", "开放阵法"),
    "阵法": ("宏观监测", "阵法核心", "品级"),
}


class ItemCatalogService:
    """启动时从 JSON 快照建立正式编号实体的编号和名称索引。"""

    def __init__(self, data: JsonDataService) -> None:
        self._data = data
        self._initialized = False
        self._items: dict[str, ItemDetail] = {}
        self._entities: dict[str, ItemDetail] = {}
        self._names: dict[str, tuple[ItemSummary, ...]] = {}
        self._entity_names: dict[str, tuple[ItemSummary, ...]] = {}
        self._categories: dict[str, tuple[ItemSummary, ...]] = {}

    def initialize(self) -> ItemCatalogStatus:
        if self._initialized:
            raise RuntimeError("物品查询微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于物品查询微服务启动")

        by_name: dict[str, list[ItemSummary]] = defaultdict(list)
        by_category: dict[str, list[ItemSummary]] = defaultdict(list)
        entity_by_name: dict[str, list[ItemSummary]] = defaultdict(list)
        for record in self._data.numbered_entities():
            item_id = record.entity_id
            value = record.value
            name = _required_text(value.get("名称"), f"{record.section} {item_id}.名称")
            description = str(value.get("说明") or "").strip()
            category = record.number_category
            section = record.section
            selected = _ENTITY_FIELDS.get(section, ())
            detail = ItemDetail(
                item_id=item_id,
                category=category,
                name=name,
                description=description,
                fields=MappingProxyType(
                    {
                        str(key): raw
                        for key in selected
                        if key in value and key not in {"编号", "名称", "说明"}
                        for raw in (value[key],)
                    }
                ),
                section=section,
            )
            if item_id in self._entities:
                raise JsonDataError(f"正式编号重复：{item_id}")
            self._entities[item_id] = detail
            summary = ItemSummary(item_id, category, name, section)
            entity_by_name[_normalize(name)].append(summary)
            if section == ITEM_SECTION:
                self._items[item_id] = detail
                by_name[_normalize(name)].append(summary)
                by_category[category].append(summary)

        self._names = {
            key: tuple(sorted(values, key=lambda item: item.item_id))
            for key, values in by_name.items()
        }
        self._entity_names = {
            key: tuple(sorted(values, key=lambda item: (item.section, item.item_id)))
            for key, values in entity_by_name.items()
        }
        self._categories = {
            key: tuple(sorted(values, key=lambda item: item.item_id))
            for key, values in by_category.items()
        }
        self._initialized = True
        return self.status()

    def status(self) -> ItemCatalogStatus:
        return ItemCatalogStatus(
            initialized=self._initialized,
            item_count=len(self._items),
            category_counts=MappingProxyType(
                {category: len(items) for category, items in sorted(self._categories.items())}
            ),
        )

    def get(self, item_id: str) -> ItemDetail:
        self._require_initialized()
        key = str(item_id or "").strip()
        detail = self._items.get(key)
        if detail is None:
            raise ItemNotFoundError(f"未找到物品编号：{key or '<空>'}")
        return detail

    def find_by_name(self, name: str) -> tuple[ItemSummary, ...]:
        self._require_initialized()
        return self._names.get(_normalize(name), ())

    def inspect(self, identifier: str) -> ItemDetail:
        self._require_initialized()
        query = str(identifier or "").strip()
        if not query:
            raise ItemNotFoundError("物品编号或名称不能为空")
        if query in self._items:
            return self._items[query]
        candidates = self.find_by_name(query)
        if not candidates:
            raise ItemNotFoundError(f"未找到物品：{query}")
        if len(candidates) > 1:
            raise ItemNameAmbiguousError(query, candidates)
        return self._items[candidates[0].item_id]

    def inspect_entity(self, identifier: str) -> ItemDetail:
        """按正式编号或名称查看任意编号实体。"""

        self._require_initialized()
        query = " ".join(str(identifier or "").split())
        if not query:
            raise ItemNotFoundError("编号或名称不能为空")
        if query in self._entities:
            return self._entities[query]
        candidates = self.find_entities_by_name(query)
        if not candidates:
            raise ItemNotFoundError(f"未找到编号或名称：{query}")
        if len(candidates) > 1:
            raise ItemNameAmbiguousError(query, candidates)
        return self._entities[candidates[0].item_id]

    def find_entities_by_name(self, name: str) -> tuple[ItemSummary, ...]:
        self._require_initialized()
        return self._entity_names.get(_normalize(name), ())

    def category(self, category: str) -> tuple[ItemSummary, ...]:
        self._require_initialized()
        return self._categories.get(str(category or "").strip(), ())

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("物品查询微服务尚未初始化")


def _normalize(value: object) -> str:
    return "".join(str(value or "").split()).casefold()


def _required_text(value: object, path: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise JsonDataError(f"{path}必须是非空文本")
    return text


__all__ = ["ITEM_SECTION", "ItemCatalogService"]
