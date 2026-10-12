"""查看正式编号实体的玩法编排。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from types import MappingProxyType

from game.core.asset import AssetService, AssetStateError
from game.core.data import JsonDataService
from game.core.combat import CombatService, render_body, render_listeners
from game.core.item_catalog import (
    ItemCatalogService,
    ItemDetail,
    ItemNameAmbiguousError,
    ItemNotFoundError,
)

from .contracts import HeldGrade, ItemInspectionResult


class ItemInspectionFeature:
    """把实体查询结果交给命令层，不携带命令或消息协议依赖。"""

    def __init__(
        self,
        catalog: ItemCatalogService,
        combat: CombatService,
        asset: AssetService,
        data: JsonDataService,
    ) -> None:
        self._catalog = catalog
        self._data = data
        self._combat = combat
        self._asset = asset
        self._initialized = False
        self._enemy_ids: frozenset[str] | None = None

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("查看实体玩法微服务已经初始化")
        if not self._catalog.status().initialized:
            raise RuntimeError("实体查询微服务必须先于查看实体玩法启动")
        if not self._combat.status().initialized:
            raise RuntimeError("战斗核心必须先于查看实体玩法启动")
        self._initialized = True

    async def inspect(self, query: str, user_id: str = "") -> ItemInspectionResult:
        if not self._initialized:
            raise RuntimeError("查看实体玩法微服务尚未初始化")
        normalized = " ".join(str(query or "").split())
        try:
            detail = self._catalog.inspect_entity(normalized)
            return ItemInspectionResult(
                normalized,
                detail=detail,
                related_details=self._related_details(detail),
                rendered=_rendered_lines(detail, self._combat.rule_layer()),
                held_grades=await self._held_grades(user_id, detail.item_id),
            )
        except ItemNameAmbiguousError as exc:
            return ItemInspectionResult(normalized, candidates=exc.candidates)
        except ItemNotFoundError:
            return ItemInspectionResult(normalized)

    def enemy_identifiers(self) -> frozenset[str]:
        """敌人能被查的所有写法：编号与名字。"""

        """判据：显示用中文、隐式受理 id —— 所以两种写法都必须认。"""
        if self._enemy_ids is None:
            rows = self._data.entity_fields("敌人", ["编号", "名称"])
            found: set[str] = set()
            for key, value in rows:
                # 池成员键是编号；名字取定义里的「名称」，缺了才退回键。
                display = str(value.get("名称") or key)
                found.add(display)
                number = str(value.get("编号") or "")
                if number:
                    found.add(number)
            self._enemy_ids = frozenset(found)
        return self._enemy_ids

    def inspect_enemy(self, identifier: str) -> ItemDetail | None:
        """按敌人编号造一个可渲染的实体详情。"""

        if not self._initialized:
            raise RuntimeError("查看实体玩法微服务尚未初始化")
        wanted = str(identifier or "").strip()
        by_id = {
            str(value["编号"]): str(value.get("名称") or key)
            for key, value in self._data.entity_fields("敌人", ["编号", "名称"])
        }
        if wanted in by_id:
            number, name = wanted, by_id[wanted]
        else:
            by_name = {value: key for key, value in by_id.items()}
            number, name = by_name.get(wanted, ""), wanted
        if not number:
            return None
        entry = self._data.entity("敌人", number)
        return ItemDetail(
            item_id=number,
            category="敌人",
            name=name,
            description=str(entry.get("说明") or "").strip(),
            fields=MappingProxyType(
                {str(key): value for key, value in entry.items() if key != "编号"}
            ),
            section="敌人",
        )

    async def _held_grades(self, user_id: str, content_id: str) -> tuple[HeldGrade, ...]:
        """执行者持有该编号的品级。没创建人物、没持有，都按「未持有」处理。

        查看是公开查询：实体本身没有品级，能显示的唯一品级事实就是「我手里那份是哪一品」。
        """

        normalized = str(user_id or "").strip()
        if not normalized:
            return ()
        try:
            snapshot = await self._asset.snapshot(normalized)
        except (ValueError, AssetStateError):
            return ()
        found: dict[str, HeldGrade] = {}
        for entry in snapshot.entries:
            if entry.content_id != content_id or not entry.grade_id:
                continue
            previous = found.get(entry.grade_id)
            grade = self._asset.grade(entry.grade_id)
            found[entry.grade_id] = HeldGrade(
                grade.grade_id,
                grade.name,
                float(grade.ability_multiplier),
                entry.quantity + (previous.quantity if previous else 0),
            )
        return tuple(sorted(found.values(), key=lambda item: item.multiplier))

    def _related_details(self, detail: ItemDetail) -> tuple[ItemDetail, ...]:
        """解析详情实际引用的编号实体，供玩家页显示名称和真实效果。"""

        pending = list(_entity_references(detail.fields))
        resolved: list[ItemDetail] = []
        seen: set[str] = {detail.item_id}
        while pending:
            entity_id = pending.pop(0)
            if entity_id in seen:
                continue
            seen.add(entity_id)
            try:
                related = self._catalog.inspect_entity(entity_id)
            except ItemNotFoundError:
                continue
            resolved.append(related)
            pending.extend(_entity_references(related.fields))
        return tuple(resolved)


def _entity_references(value: object) -> Iterator[str]:
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _entity_references(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from _entity_references(child)
    elif isinstance(value, str) and value.isdigit() and len(value) == 6:
        yield value


#: 正文由能力树现算的领域。构筑四类、丹药、战场环境走 `render_body`；
#: 伤势的战斗状态走 `render_listeners`。其余领域没有能力树，正文在命令层成形。
_ABILITY_TREE_SECTIONS = frozenset({"功法", "真意", "气机", "器律", "丹药", "战场环境"})


def _rendered_lines(detail: ItemDetail, rule_layer: Mapping[str, object]) -> tuple[str, ...]:
    """按领域把能力树渲染成规则正文。

    放在玩法层而不是命令层：渲染器是战斗核心的公共能力，而命令层不得导入核心服务。
    命令层只决定这些行**显示在哪**，不决定它们**怎么写**。登记表从战斗核心的公共读口取
    ——锁定技的句子由它成句，缺了就只会印「缺少登记表」。
    """

    section = detail.section
    if section in _ABILITY_TREE_SECTIONS:
        return tuple(render_body(detail.fields, rule_layer)[0])
    if section == "伤势":
        state = detail.fields.get("战斗状态")
        if isinstance(state, Mapping):
            return tuple(render_listeners(state, rule_layer)[0])
    return ()


__all__ = ["ItemInspectionFeature"]
