"""查看实体的玩法编排：编号实体按编号或名称查，命名实体池（敌人）另认名字。"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from types import MappingProxyType

from game.core.asset import AssetService, AssetStateError, ItemRefError, parse_item_ref
from game.core.character import CharacterService
from game.core.data import JsonDataError, JsonDataService
from game.core.combat import CombatService, render_body, render_listeners
from game.core.formation import FormationService
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
    GradePreview,
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
        formation: FormationService,
    ) -> None:
        self._catalog = catalog
        self._data = data
        self._combat = combat
        self._asset = asset
        self._character = character
        self._formation = formation
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
        if not self._formation.status().initialized:
            raise RuntimeError("阵法核心必须先于查看实体玩法启动")
        self._initialized = True

    def _grade_aliases(self) -> Mapping[str, str]:
        aliases: dict[str, str] = {}
        for grade in self._asset.grades():
            aliases[grade.name] = grade.grade_id
            aliases[grade.name[:1]] = grade.grade_id
            aliases[grade.grade_id] = grade.grade_id
        return aliases

    def _parse_query(self, query: str) -> tuple[str, str]:
        """拆出「物品名 + 显式品级编号」；没写品级返回空串。"""

        try:
            ref = parse_item_ref(query, grades=self._grade_aliases())
        except ItemRefError:
            return query, ""
        return ref.item, ref.grade

    async def inspect(self, query: str, user_id: str = "") -> ItemInspectionResult:
        if not self._initialized:
            raise RuntimeError("查看实体玩法微服务尚未初始化")
        normalized = " ".join(str(query or "").split())
        item_query, grade_token = self._parse_query(normalized)
        try:
            detail = self._catalog.inspect_entity(item_query)
        except ItemNameAmbiguousError as exc:
            return ItemInspectionResult(item_query, candidates=exc.candidates)
        except ItemNotFoundError:
            return ItemInspectionResult(item_query)
        requested = None
        if grade_token:
            requested = self._asset.grade(grade_token)
        held = await self._held_grades(user_id, detail.item_id)
        previews = await self._grade_previews(detail, requested, held, user_id)
        rendered = (
            *self._breakthrough_realm_lines(detail),
            *_rendered_lines(detail, self._combat.rule_layer()),
        )
        if detail.section == "血脉" and detail.fields.get("能觉醒"):
            rendered = (*rendered, *self._awakening_lines())
        if detail.section == "意境":
            rendered = (*rendered, *self._yijing_listener_lines(detail))
        use_location, use_purposes = self._use_profile(detail)
        return ItemInspectionResult(
            item_query,
            detail=detail,
            related_details=self._related_details(detail),
            # 突破丹把「从哪到哪」写在正文最前——境界名与来源都由这一层从数据取。
            rendered=rendered,
            held_grades=held,
            grade_previews=previews,
            use_location=use_location,
            use_purposes=use_purposes,
        )

    async def _grade_previews(
        self,
        detail: ItemDetail,
        requested: object | None,
        held: tuple[HeldGrade, ...],
        user_id: str,
    ) -> tuple[GradePreview, ...]:
        """丹药/构筑/阵法按品级算一份展示快照。"""

        if detail.section not in _GRADE_SECTIONS:
            return ()
        if detail.section == "阵法":
            grades = tuple(self._asset.grades())
            quantities = await self._formation_quantities(user_id, detail.item_id)
        else:
            if detail.fields.get("无品级"):
                # 特殊丹无品级：仍走一份展示快照，但回复层不印品级行。
                grades = (self._asset.grade("01"),)
            elif requested is not None:
                grades = (requested,)
            elif held:
                grades = tuple(self._asset.grade(value.grade_id) for value in held)
            else:
                grades = (self._asset.grade("01"),)
            quantities = {value.grade_id: value.quantity for value in held}
        previews: list[GradePreview] = []
        for grade in grades:
            multiplier = float(grade.ability_multiplier)
            fields = _scale_fields(detail.fields, multiplier)
            scaled = replace(detail, fields=MappingProxyType(fields))
            rendered = (
                *self._breakthrough_realm_lines(scaled),
                *_rendered_lines(scaled, self._combat.rule_layer()),
            )
            extra: tuple[str, ...] = ()
            if detail.section == "阵法":
                try:
                    assessment = self._formation.assess(
                        detail.item_id, grade.name, ()
                    )
                except Exception:  # noqa: BLE001 - 预览失败不挡详情
                    assessment = None
                if assessment is not None:
                    extra = (
                        f"承载：{_clean_number(assessment.capacity)}",
                        f"冲击：{_clean_number(assessment.impact)}",
                        f"节点：{assessment.nodes}",
                        f"传导：{_clean_number(assessment.transmission)}",
                    )
                    detection = assessment.detection
                    if detection is not None:
                        extra += (
                            f"检测：{detection.field} {detection.relation}"
                            f"（{_clean_number(float(detection.coefficient) * multiplier)}）",
                        )
            previews.append(
                GradePreview(
                    grade.grade_id,
                    grade.name,
                    multiplier,
                    quantities.get(grade.grade_id, 0),
                    fields,
                    rendered,
                    extra,
                )
            )
        return tuple(previews)

    def _yijing_listener_lines(self, detail: ItemDetail) -> tuple[str, ...]:
        """意境七到九阶的质变监听：按原子能力渲染器出完整条件与数值。"""

        tiers = detail.fields.get("质变监听")
        if not isinstance(tiers, Mapping):
            return ()
        lines: list[str] = []
        for tier in ("7", "8", "9"):
            node = tiers.get(tier)
            if not isinstance(node, Mapping):
                continue
            rendered, _unknown = render_listeners(
                {"监听": [node]}, self._combat.rule_layer()
            )
            if rendered:
                if lines:
                    lines.append(" ")
                lines.append(f"{tier}阶效果：")
                lines.extend(rendered)
        return tuple(lines)

    def _awakening_lines(self) -> tuple[str, ...]:
        """血脉觉醒档：按气血百分比给倍率，档位来自战斗规则数据集。"""

        dataset = self._data.dataset("血脉规则")
        rules = dataset.get("血脉") if isinstance(dataset, Mapping) else None
        rows = rules.get("觉醒档") if isinstance(rules, Mapping) else None
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            return ()
        lines: list[str] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            low = row.get("下限")
            high = row.get("上限")
            multiplier = _clean_number(row.get("倍率"))
            if low is not None and high is not None:
                label = f"气血 {low}%~{high}%"
            elif low is not None:
                label = f"气血 ≥{low}%"
            else:
                label = f"气血 <{high}%"
            lines.append(f"{label}：×{multiplier}")
        return tuple(lines)

    def _use_profile(self, detail: ItemDetail) -> tuple[str, tuple[str, ...]]:
        """特殊丹药的使用地点与用途名；普通丹药没有地点门槛。"""

        if detail.section != "丹药" or not detail.fields.get("无品级"):
            return "", ()
        effect = detail.fields.get("使用效果")
        if not isinstance(effect, Mapping):
            return "", ()
        kind = str(effect.get("类型") or "").strip()
        if not kind:
            return "", ()
        dataset = self._data.dataset("使用规则")
        if "使用" in dataset:
            document = dataset.get("使用")
        elif len(dataset) == 1:
            document = next(iter(dataset.values()))
        else:
            document = dataset
        rows = document.get("使用方式") if isinstance(document, Mapping) else None
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            return "", ()
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            if str(row.get("效果") or "").strip() != kind:
                continue
            location = str(row.get("地点") or "").strip()
            purposes: list[str] = []
            actions = row.get("帮助")
            if isinstance(actions, Sequence) and not isinstance(actions, (str, bytes)):
                for action in actions:
                    if not isinstance(action, Mapping):
                        continue
                    command = str(action.get("命令") or "").strip()
                    if command.startswith("帮助 "):
                        name = command.removeprefix("帮助 ").strip()
                        if name and name not in purposes:
                            purposes.append(name)
            return location, tuple(purposes or [kind])
        return "", ()

    async def _formation_quantities(
        self, user_id: str, formation_id: str
    ) -> dict[str, int]:
        if not str(user_id or "").strip():
            return {}
        try:
            entries = await self._asset.formation_entries(user_id)
        except AssetStateError:
            return {}
        counts: dict[str, int] = {}
        for entry in entries:
            if entry.content_id != formation_id or not entry.grade_id:
                continue
            counts[entry.grade_id] = counts.get(entry.grade_id, 0) + int(entry.quantity)
        return counts

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

    def id_alias_table(self) -> Mapping[str, str]:
        """**全库**「名称 → 编号」表（不限定节）。

        与 id_aliases 的区别只在一处：范围。id_aliases 由调用方给节名（各组件各有各的范围），
        这一口给的是"全部编号实体"，给 help 这种"给机器看、越全越好"的视图用。
        """

        aliases: dict[str, str] = {}
        for entity in self._data.numbered_entities():
            name = str(entity.value.get("名称") or "").strip()
            if name:
                aliases.setdefault(name, entity.entity_id)
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
                str(race.get("名称") or ""),
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

        只认「6 位数字且确实在目录里」的值——名字式引用（器阶、卡池来源、属性名一类）不是带
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
                name = target.get("名称")
            if name is None:
                inner = getattr(target, "value", None)
                name = inner.get("名称") if isinstance(inner, Mapping) else None
            found.append(BaikeReference(path, text, str(name or text)))

        visit("", value)
        return tuple(found)

    def _catalog_entries(self) -> tuple[BaikeEntry, ...]:
        """全部带编号的条目：数据索引（种族已在内），按编号排序。"""

        rows = [
            BaikeEntry(
                str(entity.entity_id),
                str(entity.value.get("名称") or entity.entity_id),
                str(entity.section),
            )
            for entity in self._data.numbered_entities()
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
        fields = {
            str(key): value for key, value in entry.items() if key != "编号"
        }
        stage = self._enemy_stage(entry)
        if stage:
            fields["境界"] = stage
        return ItemDetail(
            item_id=number,
            category="敌人",
            name=name,
            description=str(entry.get("说明") or "").strip(),
            fields=MappingProxyType(fields),
            section="敌人",
        )

    def _enemy_stage(self, entry: Mapping[str, object]) -> str:
        """按敌人等级区间匹配角色规则里的阶梯名；跨阶写「A~B」。"""

        rules = self._data.dataset("角色规则").get("敌方修士")
        tiers = rules.get("阶梯") if isinstance(rules, Mapping) else None
        level = entry.get("等级")
        if not isinstance(tiers, Sequence) or isinstance(tiers, (str, bytes)):
            return ""
        if not isinstance(level, Sequence) or isinstance(level, (str, bytes)) or len(level) != 2:
            return ""
        low, high = int(level[0]), int(level[1])
        names: list[str] = []
        for tier in tiers:
            if not isinstance(tier, Mapping):
                continue
            span = tier.get("等级范围")
            if not isinstance(span, Sequence) or isinstance(span, (str, bytes)) or len(span) != 2:
                continue
            if max(low, int(span[0])) <= min(high, int(span[1])):
                name = str(tier.get("阶梯") or "").strip()
                if name:
                    names.append(name)
        return " ~ ".join(names)

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

    def related_details(self, detail: ItemDetail) -> tuple[ItemDetail, ...]:
        """公开的详情引用解析：敌人页也要用同一份构筑/卡名。"""

        return self._related_details(detail)

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
        # 境界链是单向的（每个境界只写「下一境界」），要显示「从哪一段突破过来」得反查一次：
        # 扫全库找出 `下一境界` 指向已解析境界的那一条，一并放进 related 供渲染层用。
        for one in tuple(resolved):
            previous_id = self._previous_realm_id(one.item_id)
            if previous_id and previous_id not in seen:
                seen.add(previous_id)
                try:
                    resolved.append(self._catalog.inspect_entity(previous_id))
                except ItemNotFoundError:
                    continue
        return tuple(resolved)

    def _breakthrough_realm_lines(self, detail: ItemDetail) -> tuple[str, ...]:
        """突破丹：把「从哪个境界到哪个」写在正文最前面。

        境界链单向（每个境界只写「下一境界」），来源得反查；名称一律从目录取，不写死。
        """

        effect = detail.fields.get("使用效果")
        if not isinstance(effect, Mapping):
            return ()
        if str(effect.get("类型") or "") != "境界突破":
            return ()
        target_id = str(effect.get("目标境界") or "").strip()
        if not target_id:
            return ()
        target = self._entity_name(target_id)
        source = self._entity_name(self._previous_realm_id(target_id))
        if not (source and target):
            return ()
        return (f"境界突破：{source} → {target}",)

    def _entity_name(self, entity_id: str) -> str:
        """编号实体的显示名；查不到就给空串（渲染层据此决定印不印那一行）。"""

        if not entity_id:
            return ""
        try:
            return str(self._catalog.inspect_entity(entity_id).name)
        except (ItemNotFoundError, ItemNameAmbiguousError):
            return ""

    def _previous_realm_id(self, realm_id: str) -> str:
        """反查 `下一境界` 指向 `realm_id` 的那一条境界（数据驱动，不写死编号）。"""

        for record in self._data.numbered_entities():
            if str(record.section) != "境界":
                continue
            if str(record.value.get("下一境界") or "") == realm_id:
                return str(record.entity_id)
        return ""


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
_ABILITY_TREE_SECTIONS = frozenset(
    {"功法", "真意", "气机", "器律", "丹药", "战场环境", "血脉"}
)


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


_GRADE_SECTIONS = frozenset(
    {"丹药", "功法", "真意", "气机", "器律", "阵法"}
)
_SCALE_KEYS = frozenset(
    {
        "数值",
        "属性",
        "永久属性",
        "威力倍率",
        "恢复百分比",
        "保留血气",
        "保留神魂",
        "护盾比例",
        "治疗比例",
    }
)


def _clean_number(value: object) -> str:
    number = round(float(value), 4)
    return str(int(number)) if number == int(number) else f"{number:g}"


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(raw) for key, raw in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_plain(raw) for raw in value]
    return value


def _scale_fields(fields: Mapping[str, object], multiplier: float) -> dict[str, object]:
    value = _plain(fields)
    assert isinstance(value, dict)
    _scale_node(value, multiplier)
    return value


def _scale_node(value: object, multiplier: float) -> None:
    """只放大展示用数值；层数、持续时间、冷却、概率与次数一律不动。"""

    if isinstance(value, dict):
        for key, raw in list(value.items()):
            if key in _SCALE_KEYS:
                if isinstance(raw, bool):
                    continue
                if isinstance(raw, (int, float)):
                    value[key] = round(float(raw) * multiplier, 4)
                elif isinstance(raw, dict):
                    for name, number in list(raw.items()):
                        if isinstance(number, (int, float)) and not isinstance(number, bool):
                            raw[name] = round(float(number) * multiplier, 4)
                elif isinstance(raw, list):
                    value[key] = [
                        round(float(item) * multiplier, 4)
                        if isinstance(item, (int, float)) and not isinstance(item, bool)
                        else item
                        for item in raw
                    ]
            else:
                _scale_node(raw, multiplier)
    elif isinstance(value, list):
        for raw in value:
            _scale_node(raw, multiplier)


__all__ = ["ItemInspectionFeature"]
