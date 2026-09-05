"""战斗核心公共微服务。"""

from __future__ import annotations

import asyncio
import copy
from dataclasses import replace
from typing import Any

from game.core.data import JsonDataService, materialize
from game.core.formation import FormationService

from .catalog import BattleReportCatalog
from .build_terms import bind_term_slots
from .contracts import (
    BUILD_SECTIONS,
    CombatantSpec,
    CombatFieldSpec,
    CombatFormationSpec,
    CombatRequest,
    CombatResult,
    CombatStatus,
    CombatStatusSpec,
)
from .engine import BattleEngine
from .foundation import load_battle_foundation
from .models import (
    PreparedCombatField,
    PreparedFieldStage,
    PreparedFormation,
    PreparedFormationStage,
    RuntimeCombatantSnapshot,
)
from .presentation import build_battle_report_presentation
from .report import RuntimeBattleReportParticipant, build_battle_report


class CombatService:
    """消费 JSON 数据微服务，统一提供战斗执行与战报生成。"""

    def __init__(self, data: JsonDataService, formation: FormationService) -> None:
        self._data = data
        self._formation = formation
        self._engine: BattleEngine | None = None
        self._report_catalog: BattleReportCatalog | None = None

    def initialize(self) -> CombatStatus:
        if self._engine is not None:
            raise RuntimeError("战斗核心已经初始化")
        if not self._formation.status().initialized:
            raise RuntimeError("阵法核心必须先于战斗核心启动")
        foundation = load_battle_foundation(
            self._data,
            formation_rules=self._formation.node_rules(),
        )
        report_dataset = materialize(self._data.dataset("战斗展示"))
        report_catalog = BattleReportCatalog.from_mapping(report_dataset["战报"])
        self._engine = BattleEngine(foundation)
        report_catalog.validate_event_kinds(tuple(self._engine.catalog.events))
        self._report_catalog = report_catalog
        return self.status()

    def status(self) -> CombatStatus:
        engine = self._engine
        if engine is None:
            return CombatStatus(False, 0, 0, 0, 0)
        return CombatStatus(
            initialized=True,
            mechanism_count=len(engine.catalog.mechanisms),
            ability_count=len(engine.catalog.abilities),
            event_count=len(engine.catalog.events),
            environment_count=len(engine.catalog.environments),
            formation_count=self._formation.status().formation_count,
        )

    async def execute(self, request: CombatRequest) -> CombatResult:
        """执行唯一的公共战斗请求，不阻塞异步消息驱动。"""

        return await asyncio.to_thread(self._execute_sync, request)

    def _execute_sync(self, request: CombatRequest) -> CombatResult:
        self._validate_groups(request)
        left = tuple(self._runtime_snapshot(value) for value in request.left_team)
        right = tuple(self._runtime_snapshot(value) for value in request.right_team)
        medicine_definitions = self._medicine_definitions(request)
        field = self._prepared_field(request.field)
        left_formation = self._prepared_formation(request.left_formation, side=0)
        right_formation = self._prepared_formation(request.right_formation, side=1)
        result = self._simulate_runtime_teams(
            left=left,
            right=right,
            medicine_definitions=medicine_definitions,
            medicine_selection_strategy=request.medicine_selection_strategy,
            seed=request.seed,
            action_limit=request.action_limit,
            field=field,
            formations=tuple(
                value
                for value in (left_formation, right_formation)
                if value is not None
            ),
        )
        if request.report is None:
            return result
        return self._attach_report(result, request, (*left, *right))

    def _simulate_runtime_teams(
        self,
        *,
        left: tuple[RuntimeCombatantSnapshot, ...],
        right: tuple[RuntimeCombatantSnapshot, ...],
        medicine_definitions: dict[str, Any],
        medicine_selection_strategy: str,
        seed: int,
        action_limit: int,
        field: PreparedCombatField | None = None,
        formations: tuple[PreparedFormation, ...] = (),
    ) -> CombatResult:
        """供战斗服务自身测试和基准使用的内部同步入口。"""

        return self._require_engine().simulate_teams(
            left=left,
            right=right,
            medicine_definitions=medicine_definitions,
            medicine_selection_strategy=medicine_selection_strategy,
            seed=seed,
            action_limit=action_limit,
            field=field,
            formations=formations,
        )

    def _prepared_formation(
        self, spec: CombatFormationSpec | None, *, side: int
    ) -> PreparedFormation | None:
        if spec is None:
            return None
        profile = self._formation.battle_profile(
            spec.formation_id,
            spec.grade,
            spec.materials,
            position=spec.position,
        )
        stages = tuple(
            PreparedFormationStage(
                threshold_multiplier=value.threshold_multiplier,
                cycle_multiplier=value.cycle_multiplier,
                impact_multiplier=value.impact_multiplier,
            )
            for value in profile.stages
        )
        return PreparedFormation(
            profile.formation_id,
            profile.name,
            profile.grade_name,
            side,
            profile.position,
            profile.capacity,
            profile.impact,
            profile.nodes,
            profile.transmission,
            stages,
        )

    def _prepared_field(
        self,
        spec: CombatFieldSpec | None,
    ) -> PreparedCombatField | None:
        if spec is None:
            return None
        environment_id = str(spec.environment_id or "").strip()
        try:
            raw = self._require_engine().catalog.environments[environment_id]
        except KeyError as exc:
            raise ValueError(
                f"战斗核心未登记战场环境：{environment_id or '<空>'}"
            ) from exc
        origin = str(spec.origin or "").strip()
        if origin not in {"地表", "秘境"}:
            raise ValueError(f"未知战场来源：{origin or '<空>'}")
        xy = spec.xy
        altitude = spec.altitude
        terrain = str(spec.terrain or "").strip()
        if origin == "地表":
            if xy is None or len(xy) != 2:
                raise ValueError("地表战场必须提供 xy")
            if altitude is None or not terrain:
                raise ValueError("地表战场必须提供海拔和区域地形")
            xy = (int(xy[0]), int(xy[1]))
            altitude = int(altitude)
        elif xy is not None or altitude is not None:
            raise ValueError("秘境战场不能伪造地表 xy 或海拔")
        stages = tuple(
            PreparedFieldStage(
                name=str(stage["名称"]),
                threshold=float(stage["起始承伤比例"]),
                entry_abilities=tuple(copy.deepcopy(stage["入阶能力"])),
                passive_abilities=tuple(copy.deepcopy(stage["常驻能力"])),
            )
            for stage in raw["阶段"]
        )
        return PreparedCombatField(
            environment_id=environment_id,
            name=str(raw["名称"]),
            scene=str(spec.scene or "").strip() or str(raw["名称"]),
            origin=origin,
            xy=xy,
            altitude=altitude,
            terrain=terrain,
            stages=stages,
        )

    def _runtime_snapshot(self, value: CombatantSpec) -> RuntimeCombatantSnapshot:
        techniques = []
        for index, reference in enumerate(value.build):
            section = str(reference.section or "").strip()
            content_id = str(reference.content_id or "").strip()
            if section not in BUILD_SECTIONS:
                raise ValueError(f"战斗构筑不支持实体类别：{section or '<空>'}")
            definition = bind_term_slots(
                materialize(self._data.entity(section, content_id))
            )
            definition["属性构成"] = dict(
                definition.get("属性构成") or {"无相": 100}
            )
            definition["来源类别"] = section
            definition["实例"] = (
                reference.instance_id or f"{value.id}:{section}:{index}"
            )
            definition["出生序号"] = int(reference.born_order)
            definition["威力倍率"] = float(reference.power_multiplier)
            techniques.append(definition)
        prepared_statuses = tuple(
            self._prepared_status(status) for status in value.prepared_statuses
        )
        return RuntimeCombatantSnapshot(
            id=value.id,
            name=value.name,
            attributes=copy.deepcopy(dict(value.attributes)),
            level=value.level,
            combatant_type=value.combatant_type,
            gender=value.gender,
            weapon_attack=value.weapon_attack,
            techniques=tuple(techniques),
            health=value.health,
            spirit=value.spirit,
            shield=value.shield,
            statuses=(*copy.deepcopy(value.statuses), *prepared_statuses),
            cooldowns=copy.deepcopy(dict(value.cooldowns)),
            inventory=copy.deepcopy(dict(value.inventory)),
            inventory_owner_id=value.inventory_owner_id,
            auto_medicine=value.auto_medicine,
            medicine_threshold=value.medicine_threshold,
            skill_cursor=value.skill_cursor,
            owner_id=value.owner_id,
            controller_id=value.controller_id,
            group_id=value.group_id,
            group_role=value.group_role,
            form=value.form,
            forms=copy.deepcopy(dict(value.forms)),
            tags=tuple(value.tags),
            tactic=tuple(copy.deepcopy(value.tactic)),
            battle_profile=copy.deepcopy(dict(value.battle_profile)),
            five_elements=copy.deepcopy(dict(value.five_elements)),
        )

    @staticmethod
    def _validate_groups(request: CombatRequest) -> None:
        for side, groups, members in (
            ("左方", request.left_groups, request.left_team),
            ("右方", request.right_groups, request.right_team),
        ):
            if not groups:
                continue
            known = {value.id for value in members}
            declared: set[str] = set()
            grouped: set[str] = set()
            for group in groups:
                if group.group_id in declared:
                    raise ValueError(f"{side}编组编号不能重复：{group.group_id}")
                declared.add(group.group_id)
                current = set(group.member_ids)
                if current - known:
                    raise ValueError(f"{side}编组引用未知参战者")
                for member in members:
                    if member.id in current and member.group_id and member.group_id != group.group_id:
                        raise ValueError(f"{side}参战者的编组归属与编组契约不一致")
                if current & grouped:
                    raise ValueError(f"{side}参战者不能同时属于多个编组")
                grouped.update(current)
            if grouped != known:
                raise ValueError(f"{side}编组必须覆盖全部参战者")

    def _prepared_status(self, value: CombatStatusSpec) -> dict[str, Any]:
        listeners = []
        for mechanism_id in value.mechanism_ids:
            mechanism = materialize(self._data.entity("机制", mechanism_id))
            node = copy.deepcopy(dict(mechanism["节点"]))
            if node.get("能力") != "监听事件":
                raise ValueError(f"战前状态只能装配监听型战斗机制：{mechanism_id}")
            listeners.append(node)
        record = dict(value.metadata)
        if value.mechanism_ids:
            record["战斗机制"] = list(value.mechanism_ids)
        return {
            "名称": value.name,
            "类别": value.category,
            "剩余行动": value.remaining_actions,
            "持续单位": value.duration_unit,
            "属性": dict(value.modifiers),
            "层数": value.stacks,
            "层数上限": value.maximum_stacks,
            "行动限制": list(value.action_limits),
            "标签": list(value.tags),
            "监听": listeners,
            "来源": value.source,
            "来源名称": value.source_name,
            "构筑实例": value.build_instance,
            "记录": record,
        }

    @staticmethod
    def _medicine_definitions(request: CombatRequest) -> dict[str, Any]:
        definitions = {value.stack_key: value for value in request.medicine_definitions}
        if len(definitions) != len(request.medicine_definitions):
            raise ValueError("恢复丹堆叠键不能重复")
        if definitions and request.medicine_selection_strategy != "缺口优先":
            raise ValueError("恢复丹选药策略必须由调用方明确提交为缺口优先")
        inventory_ids = {
            str(item_id)
            for combatant in (*request.left_team, *request.right_team)
            for item_id, quantity in combatant.inventory.items()
            if int(quantity) > 0
        }
        unknown = set(definitions) - inventory_ids
        if unknown:
            raise ValueError(
                "恢复丹定义未被任何参战者携带：" + "、".join(sorted(unknown))
            )
        return definitions

    def _attach_report(
        self,
        result: CombatResult,
        request: CombatRequest,
        runtime_snapshots: tuple[RuntimeCombatantSnapshot, ...],
    ) -> CombatResult:
        report_spec = request.report
        if report_spec is None:
            return result
        metadata = {value.id: value for value in report_spec.participants}
        if len(metadata) != len(report_spec.participants):
            raise ValueError("战报补充信息的参战者 ID 不能重复")
        requested = (*request.left_team, *request.right_team)
        requested_by_id = {value.id: value for value in requested}
        unknown = set(metadata) - set(requested_by_id)
        if unknown:
            raise ValueError(
                "战报补充信息引用未知参战者：" + "、".join(sorted(unknown))
            )
        runtime_by_id = {value.id: value for value in runtime_snapshots}
        participants = []
        for value in (*result.left_results, *result.right_results):
            original = requested_by_id.get(value.id)
            runtime = runtime_by_id.get(value.id)
            display = metadata.get(value.id)
            attributes = dict(value.attributes)
            participants.append(
                RuntimeBattleReportParticipant(
                    id=value.id,
                    name=value.name,
                    title=(
                        display.title
                        if display and display.title
                        else value.combatant_type
                    ),
                    attributes=attributes,
                    initial_health=(
                        value.health
                        if original is None
                        else float(
                            original.health
                            if original.health is not None
                            else attributes.get("血气上限", value.health)
                        )
                    ),
                    final_health=value.health,
                    initial_spirit=(
                        value.spirit
                        if original is None
                        else float(
                            original.spirit
                            if original.spirit is not None
                            else attributes.get("精神上限", value.spirit)
                        )
                    ),
                    final_spirit=value.spirit,
                    initial_shield=original.shield
                    if original is not None
                    else value.shield,
                    final_shield=value.shield,
                    initial_statuses=(
                        runtime.statuses
                        if runtime is not None
                        else original.statuses
                        if original is not None
                        else ()
                    ),
                    statuses=value.statuses,
                    techniques=runtime.techniques if runtime is not None else (),
                    moves=display.moves if display else (),
                    mechanisms=display.mechanisms if display else (),
                    ability_definitions=self._require_engine().catalog.abilities,
                    color=display.color if display else "",
                    extra=display.extra if display else {},
                    level=value.level,
                    combatant_type=value.combatant_type,
                )
            )
        report = build_battle_report(
            result,
            participants,
            catalog=self._require_report_catalog(),
            seed=request.seed,
            generated_at=report_spec.generated_at,
            scene=result.field.scene if result.field is not None else report_spec.scene,
            mechanism_names=self._require_engine().catalog.mechanism_names,
        )
        presentation = (
            build_battle_report_presentation(
                report,
                self._require_report_catalog(),
            )
            if report_spec.include_presentation
            else None
        )
        return replace(result, report=report, presentation=presentation)

    def _require_engine(self) -> BattleEngine:
        if self._engine is None:
            raise RuntimeError("战斗核心尚未初始化")
        return self._engine

    def _require_report_catalog(self) -> BattleReportCatalog:
        if self._report_catalog is None:
            raise RuntimeError("战斗核心尚未初始化")
        return self._report_catalog


__all__ = ["CombatService"]
