"""查看实体的玩法编排：编号实体按编号或名称查，命名实体池（敌人）另认名字。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from types import MappingProxyType

from game.core.asset import AssetService, AssetStateError
from game.core.character import CharacterService
from game.core.data import JsonDataError, JsonDataService
from game.core.combat import CombatService, render_body, render_listeners
from game.core.item_catalog import (
    ItemCatalogService,
    ItemDetail,
    ItemNameAmbiguousError,
    ItemNotFoundError,
)

from .contracts import (
    BaikeCatalog,
    BaikeDetail,
    BaikeEntry,
    BaikePrefixRow,
    BaikeReference,
    HeldGrade,
    ItemInspectionResult,
)


#: 种族在登记表里的编号前缀（唯一不由数据索引提供的一类）。
_RACE_PREFIX = "55"


class ItemInspectionFeature:
    """把实体查询结果交给命令层，不携带命令或消息协议依赖。"""

    def __init__(
        self,
        catalog: ItemCatalogService,
        combat: CombatService,
        asset: AssetService,
        data: JsonDataService,
        character: CharacterService,
    ) -> None:
        self._catalog = catalog
        self._data = data
        self._combat = combat
        self._asset = asset
        self._character = character
        self._initialized = False
        self._enemy_ids: frozenset[str] | None = None
        self._mask_text: str | None = None

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("查看实体玩法微服务已经初始化")
        if not self._catalog.status().initialized:
            raise RuntimeError("实体查询微服务必须先于查看实体玩法启动")
        if not self._combat.status().initialized:
            raise RuntimeError("战斗核心必须先于查看实体玩法启动")
        if not self._character.status().initialized:
            raise RuntimeError("角色核心必须先于查看实体玩法启动")
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

    def id_aliases(self, sections: Sequence[str]) -> Mapping[str, str]:
        """「中文名 / 品级名 → 编号」的别名表。

        `sections` 是调用方要认的实体节——**范围由调用方定**（帮助那条给机器读的 `help` 命令
        只在自己列的那几节里认名称）；本口只负责把事实取出来。品级照资产核心的品级表来，
        连它的首字一起认（「黄」→ 01），不硬编码。
        """

        aliases: dict[str, str] = {}
        for section in sections:
            try:
                table = self._data.entities(section)
            except Exception:  # noqa: BLE001 - 这一节不存在就跳过（与调用方原来的口径一致）
                continue
            for content_id, value in table.items():
                name = str(value.get("名称") or "").strip()
                if name and name not in aliases:
                    aliases[name] = str(content_id)
        for grade in self._asset.grades():
            grade_name = str(getattr(grade, "name", "") or "").strip()
            grade_id = str(getattr(grade, "grade_id", "") or "").strip()
            if not grade_name or not grade_id:
                continue
            for token in (grade_name, grade_name[:1]):
                aliases.setdefault(token, grade_id)
        return MappingProxyType(aliases)

    def is_race(self, entity_id: str) -> bool:
        """这个编号是不是种族（前缀 55）——百科页用它决定缺号时回哪一句。"""

        return str(entity_id or "").strip().startswith(_RACE_PREFIX)

    def catalog(self) -> BaikeCatalog:
        """百科总表：全部带编号的条目（编号实体 + 角色核心的种族）与登记表前缀计数。"""

        entries = self._catalog_entries()
        return BaikeCatalog(entries, self._prefix_rows(entries))

    def detail(self, entity_id: str) -> BaikeDetail | None:
        """单条详情。种族走角色核心的登记表（前缀 55），其余走编号实体索引。"""

        identifier = str(entity_id or "").strip()
        if not identifier:
            return None
        if identifier.startswith(_RACE_PREFIX):
            race = self._character.races().get(identifier) or self._find_race(identifier)
            if race is None:
                return None
            return BaikeDetail(
                identifier,
                str(race.get("种族") or ""),
                "种族",
                "",
                race,
                self.references(identifier, race),
            )
        record = next(
            (item for item in self._data.numbered_entities() if item.entity_id == identifier),
            None,
        )
        if record is None:
            return None
        return BaikeDetail(
            identifier,
            str(record.value.get("名称") or identifier),
            str(record.section),
            str(record.number_category),
            record.value,
            self.references(identifier, record.value),
        )

    def references(self, entity_id: str, value: object) -> tuple[BaikeReference, ...]:
        """实体字段里指向别的实体的**编号式**引用。

        只认「6 位数字且确实在目录里」的值——名字式引用（铸法、卡池来源、属性名一类）不是带
        编号的实体，链不过去，页面上也不假装能点。这一段原先写在百科页里（命令层自己 walk
        数据结构），现在归到玩法：它是业务判断，不是渲染。
        """

        catalog: dict[str, object] = {
            item.entity_id: item for item in self._data.numbered_entities()
        }
        for race in self._character.races().values():
            number = str(race.get("编号") or "")
            if number:
                catalog.setdefault(number, race)
        found: list[BaikeReference] = []
        seen: set[str] = set()

        def visit(path: str, node: object) -> None:
            if isinstance(node, Mapping):
                for key, child in node.items():
                    visit((path + "." + str(key)) if path else str(key), child)
                return
            if isinstance(node, (list, tuple)):
                for child in node:
                    visit(path, child)
                return
            text = str(node or "").strip()
            if len(text) != 6 or not text.isdigit() or text == entity_id or text in seen:
                return
            target = catalog.get(text)
            if target is None:
                return
            seen.add(text)
            name = None
            if isinstance(target, Mapping):
                name = target.get("种族")
            if name is None:
                inner = getattr(target, "value", None)
                name = inner.get("名称") if isinstance(inner, Mapping) else None
            found.append(BaikeReference(path, text, str(name or text)))

        visit("", value)
        return tuple(found)

    def _catalog_entries(self) -> tuple[BaikeEntry, ...]:
        """全部带编号的条目：数据索引 + 角色核心的种族，按编号排序。"""

        rows = [
            BaikeEntry(
                str(entity.entity_id),
                str(entity.value.get("名称") or entity.entity_id),
                str(entity.section),
            )
            for entity in self._data.numbered_entities()
        ]
        rows += [
            BaikeEntry(str(race.get("编号") or ""), str(race.get("种族") or ""), "种族")
            for race in self._character.races().values()
        ]
        return tuple(sorted((row for row in rows if row.entity_id), key=lambda row: row.entity_id))

    def _prefix_rows(self, entries: Sequence[BaikeEntry]) -> tuple[BaikePrefixRow, ...]:
        """登记表里的前缀各数一数有多少条。

        只走登记表自己那一层键，不做遍历：正式 JSON 的结构由 `game.core.data` 建索引。
        """

        document = self._data.dataset("基础定义").get("编号") or {}
        registry = document.get("编号前缀") or () if isinstance(document, Mapping) else ()
        counted: dict[str, int] = {}
        for entry in entries:
            key = entry.entity_id[:2]
            counted[key] = counted.get(key, 0) + 1
        return tuple(
            BaikePrefixRow(
                str(row.get("前缀") or ""),
                str(row.get("主体") or ""),
                str(row.get("类别") or ""),
                counted.get(str(row.get("前缀") or ""), 0),
            )
            for row in registry
            if isinstance(row, Mapping)
        )

    def _find_race(self, entity_id: str) -> Mapping | None:
        """种族登记表按名字索引，详情按编号取，所以要按编号再找一遍。"""

        for race in self._character.races().values():
            if str(race.get("编号") or "") == entity_id:
                return race
        return None

    def mask_text(self) -> str:
        """敌人条目页的遮罩词：配置里没有的答案（种族／性别／器律）不假装知道。"""

        if self._mask_text is None:
            root = self._data.dataset("敌人展示").get("文本")
            value = str(root.get("遮罩") or "").strip()
            if not value:
                raise JsonDataError("敌人展示缺少文本.json")
            self._mask_text = value
        return self._mask_text


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
