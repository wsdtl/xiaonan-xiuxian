"""纳戒大类、小类和分页编排。"""

from __future__ import annotations

from math import ceil

from game.core.asset import (
    AssetCategory,
    AssetEntry,
    AssetService,
    AssetSnapshot,
    AssetSortRules,
    AssetStateError,
)

from .contracts import (
    NajieCategorySummary,
    NajieCategoryView,
    NajieEntry,
    NajieHome,
    NajiePage,
    NajieQueryError,
    NajieStateError,
    NajieSubcategorySummary,
)


class NajieFeature:
    """只组合资产视图，不拥有任何资产写权限。"""

    def __init__(self, assets: AssetService) -> None:
        self._assets = assets
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("纳戒玩法微服务已经初始化")
        if not self._assets.status().initialized:
            raise RuntimeError("玩家资产核心微服务必须先于纳戒玩法启动")
        self._initialized = True

    async def home(self, user_id: str) -> NajieHome:
        snapshot = await self._snapshot(user_id)
        return NajieHome(
            tuple(
                _category_summary(snapshot, category)
                for category in snapshot.categories
            )
        )

    async def category(self, user_id: str, category_name: str) -> NajieCategoryView:
        snapshot = await self._snapshot(user_id)
        category = _category(snapshot, category_name)
        return NajieCategoryView(_category_summary(snapshot, category))

    async def page(
        self,
        user_id: str,
        category_name: str,
        subcategory_name: str,
        page: int = 1,
    ) -> NajiePage:
        snapshot = await self._snapshot(user_id)
        category = _category(snapshot, category_name)
        if subcategory_name not in {
            subcategory.name for subcategory in category.subcategories
        }:
            available = "、".join(
                subcategory.name for subcategory in category.subcategories
            )
            raise NajieQueryError(
                f"{category.name}中没有“{subcategory_name or '<空>'}”。"
                f"可选分项：{available}"
            )
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise NajieQueryError("纳戒页码必须是正整数")
        entries = _sorted_entries(
            tuple(
                entry
                for entry in snapshot.entries
                if entry.category == category.name
                and entry.subcategory == subcategory_name
            ),
            snapshot.sort_rules,
        )
        total_pages = max(1, ceil(len(entries) / snapshot.page_limit))
        if page > total_pages:
            raise NajieQueryError(
                f"{subcategory_name}没有第{page}页，共{total_pages}页"
            )
        offset = (page - 1) * snapshot.page_limit
        page_entries = entries[offset : offset + snapshot.page_limit]
        return NajiePage(
            category=category.name,
            subcategory=subcategory_name,
            icon=category.icon,
            page=page,
            total_pages=total_pages,
            entry_count=len(entries),
            total_quantity=sum(entry.quantity for entry in entries),
            start_index=offset + 1 if page_entries else 0,
            end_index=offset + len(page_entries),
            entries=tuple(_entry_view(entry) for entry in page_entries),
        )

    async def _snapshot(self, user_id: str) -> AssetSnapshot:
        if not self._initialized:
            raise RuntimeError("纳戒玩法微服务尚未初始化")
        try:
            return await self._assets.snapshot(user_id)
        except AssetStateError as exc:
            raise NajieStateError(str(exc)) from exc


def _category(snapshot: AssetSnapshot, name: str) -> AssetCategory:
    normalized = str(name or "").strip()
    try:
        return next(
            category for category in snapshot.categories if category.name == normalized
        )
    except StopIteration as exc:
        available = "、".join(category.name for category in snapshot.categories)
        raise NajieQueryError(
            f"纳戒中没有“{normalized or '<空>'}”这一类。可选大类：{available}"
        ) from exc


def _category_summary(
    snapshot: AssetSnapshot, category: AssetCategory
) -> NajieCategorySummary:
    entries = tuple(
        entry for entry in snapshot.entries if entry.category == category.name
    )
    subcategories = tuple(
        NajieSubcategorySummary(
            subcategory.name,
            sum(entry.subcategory == subcategory.name for entry in entries),
            sum(
                entry.quantity
                for entry in entries
                if entry.subcategory == subcategory.name
            ),
        )
        for subcategory in category.subcategories
    )
    return NajieCategorySummary(
        category.name,
        category.icon,
        len(entries),
        sum(entry.quantity for entry in entries),
        subcategories,
    )


def _sorted_entries(
    entries: tuple[AssetEntry, ...], rules: AssetSortRules
) -> tuple[AssetEntry, ...]:
    if entries and entries[0].category == "阵藏" and entries[0].grade_id == "05":
        return tuple(
            sorted(
                entries,
                key=lambda entry: (entry.updated_at, entry.instance_key),
                reverse=rules.holy_formation_newest_first,
            )
        )

    ordered = sorted(entries, key=lambda entry: entry.instance_key)
    ordered.sort(
        key=lambda entry: entry.content_id,
        reverse=rules.content_id_descending,
    )
    ordered.sort(
        key=lambda entry: int(entry.grade_id or 0),
        reverse=rules.grade_descending,
    )
    if rules.equipped_first:
        ordered.sort(key=lambda entry: bool(entry.equipped_slots), reverse=True)
    return tuple(ordered)


def _entry_view(entry: AssetEntry) -> NajieEntry:
    return NajieEntry(
        category=entry.category,
        content_id=entry.content_id,
        name=entry.name,
        grade_id=entry.grade_id,
        grade_name=entry.grade_name,
        quantity=entry.quantity,
        equipped_slots=entry.equipped_slots,
        material_total=entry.material_total,
    )


__all__ = ["NajieFeature"]
