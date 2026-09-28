"""宗门战核心：管理战书生命周期并调用统一多人战斗核心。"""

from __future__ import annotations

from game.core.combat import (
    CombatantResult,
    CombatantSpec,
    CombatFieldSpec,
    CombatFormationSpec,
    CombatGroupSpec,
    CombatMedicineSpec,
    CombatReportSpec,
    CombatRequest,
    CombatService,
)

from collections.abc import Sequence, Mapping
from game.core.database import (
    DatabaseMutation,
    SharedEntityRecord,
    DatabaseService,
    SettlementTransactionPlan,
    SharedEntityMutation,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)

from game.core.sect import SectMember, SectService

from game.core.injury import InjuryState, PLAYER_KEY, InjuryService, companion_subject

import hashlib
import math
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from uuid import uuid4

from game.core.activity import (
    ActivityFacts,
    ActivityLifecycle,
    ActivityLifecycleService,
)
from game.core.asset import AssetService, InventoryAdjustment
from game.core.character import CharacterService
from game.core.companion import CompanionService
from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping as _mapping,
    materialize,
    nonnegative_int as _nonnegative,
    nonnegative_int as _stored_nonnegative,
    positive_int,
    positive_int as _positive,
    strict_text as _text,
)
from game.core.location import LocationService
from game.core.medicine import MedicineService, RecoveryMedicineStack
from game.core.player_state import PlayerStateService, StateTransitionCommand
from game.core.sect_assets import SectAssetEntry, SectAssetService
from game.core.world import LocationQuery, WorldService

from .contracts import SectWarError, SectWarHistoryPage, SectWarStatus, SectWarView

ENTITY_TYPE = "宗门战"
STATE_TYPE = "sect_war"
_TERMINAL = frozenset({"已结算", "已拒绝", "已撤回", "已过期", "已取消"})


class SectWarService:
    state_types = frozenset({STATE_TYPE})

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        sect: SectService,
        sect_assets: SectAssetService,
        asset: AssetService,
        world: WorldService,
        location: LocationService,
        character: CharacterService,
        companion: CompanionService,
        player_state: PlayerStateService,
        medicine: MedicineService,
        combat: CombatService,
        activity: ActivityLifecycleService,
        injury: InjuryService,
    ) -> None:
        self._data = data
        self._db = database
        self._sect = sect
        self._assets = sect_assets
        self._asset = asset
        self._world = world
        self._location = location
        self._character = character
        self._companion = companion
        self._state = player_state
        self._medicine = medicine
        self._combat = combat
        self._activity = activity
        self._injury = injury
        self._initialized = False
        self._seconds = 0
        self._maximum = 0
        self._actions = 0
        self._challenge_seconds = 0
        self._history_page_size = 0
        self._behavior = ""
        self._win_ratio = Decimal(0)
        self._draw_ratio = Decimal(0)

    def initialize(self) -> SectWarStatus:
        if self._initialized:
            raise RuntimeError("宗门战核心已经初始化")
        if not self._activity.status().initialized:
            raise RuntimeError("异步玩法生命周期核心必须先于宗门战核心启动")
        if not self._injury.status().initialized:
            raise RuntimeError("长期伤势核心必须先于宗门战核心启动")
        rule = _mapping(self._data.dataset("宗门规则").get("宗门战"), "宗门战.json")
        battle = _mapping(rule.get("战斗"), "宗门战.战斗")
        participants = _mapping(rule.get("参战"), "宗门战.参战")
        wager = _mapping(rule.get("押注"), "宗门战.押注")
        challenge = _mapping(rule.get("约战"), "宗门战.约战")
        history = _mapping(rule.get("记录"), "宗门战.记录")
        self._challenge_seconds = _positive(
            challenge.get("有效秒数"), "宗门战.约战.有效秒数"
        )
        self._seconds = _positive(battle.get("结算秒数"), "宗门战.战斗.结算秒数")
        self._actions = _positive(
            battle.get("战斗行动上限"), "宗门战.战斗.战斗行动上限"
        )
        if (
            _nonnegative(battle.get("每宗阵法上限"), "宗门战.战斗.每宗阵法上限") != 1
            or battle.get("阵法来源") != "宗门万珍殿"
        ):
            raise JsonDataError("宗门战必须允许每宗从万珍殿使用至多一座阵法")
        self._maximum = _positive(participants.get("玩家上限"), "宗门战.参战.玩家上限")
        self._history_page_size = _positive(
            history.get("每页数量"), "宗门战.记录.每页数量"
        )
        self._win_ratio = _ratio(wager.get("胜方比例"), "宗门战.押注.胜方比例")
        self._draw_ratio = _ratio(wager.get("平局返还比例"), "宗门战.押注.平局返还比例")
        loss_ratio = _ratio(wager.get("损耗比例"), "宗门战.押注.损耗比例")
        if self._win_ratio + loss_ratio != 1 or self._draw_ratio + loss_ratio != 1:
            raise JsonDataError("宗门战押注返还比例与损耗比例必须相加为1")
        self._behavior = _text(
            _mapping(rule.get("状态"), "宗门战.状态").get("行为"),
            "宗门战.状态.行为",
        )
        if self._state.state_type(self._behavior) != "行为":
            raise JsonDataError("宗门战状态必须引用行为状态")
        self._initialized = True
        return self.status()

    def status(self) -> SectWarStatus:
        return SectWarStatus(self._initialized, self._seconds, self._maximum)

    async def challenge(
        self, user_id: str, target_name: str, wager: int, request_id: str
    ) -> SectWarView:
        member = await self._member_officer(user_id)
        normalized_wager = _request_positive(wager, "押注")
        target = await self._db.get_shared_entity_by_name("宗门", target_name.strip())
        if target is None or target.entity_id == member.sect_id:
            raise SectWarError("target_invalid")
        # 战书列表整份读一次（每次三十几毫秒，见 `_current_record`）：先用它结过期战书，
        # 再用同一份挑「有没有在打的」——原先这三步各读一遍。
        records = await self._db.list_shared_entities(ENTITY_TYPE)
        if await self._expire_for_sects((member.sect_id, target.entity_id), user_id, records):
            records = await self._db.list_shared_entities(ENTITY_TYPE)
        if self._has_active(records, member.sect_id) or self._has_active(
            records, target.entity_id
        ):
            raise SectWarError("active_exists")
        location = await self._location.current(user_id)
        if location.space_type != "地表":
            raise SectWarError("surface_required")
        war_id = uuid4().hex[:20]
        now = _now()
        value = {
            "名称": f"宗门战-{war_id}",
            "宗门战编号": war_id,
            "状态": "待应战",
            "甲方": member.sect_id,
            "乙方": target.entity_id,
            "坐标": list(location.xy),
            "押注": normalized_wager,
            "甲方押注": normalized_wager,
            "乙方押注": 0,
            "甲方锁定": False,
            "乙方锁定": False,
            "创建时间": now.isoformat(),
            "过期时间": (now + timedelta(seconds=self._challenge_seconds)).isoformat(),
            "开始时间": "",
            "结束时间": "",
            "完成时间": "",
            "胜方": "",
            "战报编号": "",
        }
        await self._commit(
            user_id,
            request_id,
            "发起宗门战",
            (
                await self._assets.plan_spirit_stone_change(
                    member.sect_id, -normalized_wager
                ),
                SharedEntityMutation(ENTITY_TYPE, war_id, value, 0),
            ),
            {"宗门战编号": war_id, "甲方": member.sect_id, "乙方": target.entity_id},
        )
        return await self._view(value)

    async def accept(self, user_id: str, request_id: str) -> SectWarView:
        member = await self._member_officer(user_id)
        record = await self._current_record(member.sect_id, user_id)
        value = dict(record.value)
        if value.get("状态") != "待应战" or value.get("乙方") != member.sect_id:
            raise SectWarError("cannot_accept")
        wager = _stored_nonnegative(value.get("押注"), "宗门战.押注")
        value["状态"] = "备战"
        value["乙方押注"] = wager
        await self._commit(
            user_id,
            request_id,
            "接受宗门战",
            (
                await self._assets.plan_spirit_stone_change(member.sect_id, -wager),
                SharedEntityMutation(
                    ENTITY_TYPE, record.entity_id, value, record.version
                ),
            ),
            {"宗门战编号": record.entity_id, "宗门编号": member.sect_id},
        )
        return await self._view(value)

    async def reject(self, user_id: str, request_id: str) -> SectWarView:
        member = await self._member_officer(user_id)
        record = await self._current_record(member.sect_id, user_id)
        value = record.value
        if value.get("状态") != "待应战" or value.get("乙方") != member.sect_id:
            raise SectWarError("cannot_reject")
        return await self._terminate(
            user_id, request_id, record, "已拒绝", "拒绝宗门战"
        )

    async def withdraw(self, user_id: str, request_id: str) -> SectWarView:
        member = await self._member_officer(user_id)
        record = await self._current_record(member.sect_id, user_id)
        value = record.value
        if value.get("状态") != "待应战" or value.get("甲方") != member.sect_id:
            raise SectWarError("cannot_withdraw")
        return await self._terminate(
            user_id, request_id, record, "已撤回", "撤回宗门战"
        )

    async def cancel(self, user_id: str, request_id: str) -> SectWarView:
        member = await self._member_officer(user_id)
        record = await self._current_record(member.sect_id, user_id)
        if record.value.get("状态") not in {"备战", "已锁定"}:
            raise SectWarError("cannot_cancel")
        return await self._terminate(
            user_id, request_id, record, "已取消", "取消宗门战"
        )

    async def lock(
        self, user_id: str, request_id: str, formation_entry: str = ""
    ) -> SectWarView:
        member = await self._member_officer(user_id)
        record = await self._current_record(member.sect_id, user_id)
        value = dict(record.value)
        side = _side(value, member.sect_id)
        if not side or value.get("状态") not in {"备战", "已锁定"}:
            raise SectWarError("cannot_lock")
        if value.get(f"{side}锁定"):
            raise SectWarError("already_locked")
        follow = await self._sect.follow(member.sect_id)
        sect = await self._sect.sect(member.sect_id)
        if (
            follow is None
            or sect is None
            or follow.leader_user_id != sect.leader_user_id
        ):
            raise SectWarError("follow_required")
        if len(follow.member_user_ids) > self._maximum:
            raise SectWarError("participant_limit")
        locations = [
            await self._location.current(uid) for uid in follow.member_user_ids
        ]
        xy = _stored_xy(value.get("坐标"))
        if any(
            location.space_type != "地表" or location.xy != xy for location in locations
        ):
            raise SectWarError("location_mismatch")
        formation_key = str(formation_entry or "").strip()
        formation = (
            await self._formation_entry(member.sect_id, formation_key)
            if formation_key
            else None
        )
        value[f"{side}锁定"] = True
        value[f"{side}成员"] = list(follow.member_user_ids)
        value[f"{side}阵法条目"] = formation.entry_key if formation else ""
        value[f"{side}阵法名称"] = formation.name if formation else ""
        if value.get("甲方锁定") and value.get("乙方锁定"):
            value["状态"] = "已锁定"
        state_plans = []
        for participant in follow.member_user_ids:
            state_plans.append(
                await self._state.plan_transition(
                    StateTransitionCommand(
                        participant,
                        request_id,
                        "行为",
                        self._behavior,
                        {"宗门战编号": record.entity_id, "宗门编号": member.sect_id},
                    )
                )
            )
        await self._commit(
            user_id,
            request_id,
            "锁定宗门战阵容",
            (
                SharedEntityMutation(
                    ENTITY_TYPE, record.entity_id, value, record.version
                ),
            )
            + tuple(plan.mutation for plan in state_plans),
            {"宗门战编号": record.entity_id, "宗门编号": member.sect_id},
        )
        return await self._view(value)

    async def unlock(self, user_id: str, request_id: str) -> SectWarView:
        member = await self._member_officer(user_id)
        record = await self._current_record(member.sect_id, user_id)
        value = dict(record.value)
        side = _side(value, member.sect_id)
        if not side or value.get("状态") not in {"备战", "已锁定"}:
            raise SectWarError("cannot_unlock")
        if not value.get(f"{side}锁定"):
            raise SectWarError("not_locked")
        participants = _stored_texts(value.get(f"{side}成员", ()), f"{side}成员")
        value["状态"] = "备战"
        value[f"{side}锁定"] = False
        value.pop(f"{side}成员", None)
        value.pop(f"{side}阵法条目", None)
        value.pop(f"{side}阵法名称", None)
        operations: list[object] = [
            SharedEntityMutation(ENTITY_TYPE, record.entity_id, value, record.version)
        ]
        operations.extend(await self._release_operations(participants))
        await self._commit(
            user_id,
            request_id,
            "解除宗门战阵容",
            tuple(operations),
            {"宗门战编号": record.entity_id, "宗门编号": member.sect_id},
        )
        return await self._view(value)

    async def start(self, user_id: str, request_id: str) -> SectWarView:
        member = await self._member_officer(user_id)
        record = await self._current_record(member.sect_id, user_id)
        value = dict(record.value)
        if value.get("状态") != "已锁定":
            raise SectWarError("both_not_locked")
        left_ids = _stored_texts(value.get("甲方成员"), "甲方成员")
        right_ids = _stored_texts(value.get("乙方成员"), "乙方成员")
        location = self._world.locate(LocationQuery(xy=_stored_xy(value.get("坐标"))))
        (
            left,
            left_medicines,
            left_battle_medicine,
            left_injuries,
        ) = await self._combatants(left_ids)
        (
            right,
            right_medicines,
            right_battle_medicine,
            right_injuries,
        ) = await self._combatants(right_ids)
        medicine_stacks = {**left_medicines, **right_medicines}
        inventory = {
            owner: {stack.stack_key: stack.quantity for stack in stacks}
            for owner, stacks in medicine_stacks.items()
        }
        left = _attach_inventory(
            left, inventory, self._medicine.auto_medicine_threshold
        )
        right = _attach_inventory(
            right, inventory, self._medicine.auto_medicine_threshold
        )
        left_formation, left_formation_operation = await self._formation_spec(
            str(value.get("甲方")), str(value.get("甲方阵法条目") or ""), 0
        )
        right_formation, right_formation_operation = await self._formation_spec(
            str(value.get("乙方")), str(value.get("乙方阵法条目") or ""), 0
        )
        result = await self._combat.execute(
            CombatRequest(
                left_team=left,
                right_team=right,
                seed=_seed(record.entity_id),
                action_limit=self._actions,
                medicine_definitions=_medicine_definitions(medicine_stacks),
                medicine_selection_strategy=self._medicine.selection_strategy,
                # 只存战报，不存展示包：展示包由战报页面按需重建（`game/cmd/通用/战报`）。
                # 展示包比战报还大（一次 15 人对 15 人实测几十兆字符），而它每一步都能从
                # 战报现算——存两份等于把同一件事存两遍。
                report=CombatReportSpec(
                    scene=location.location_name or location.terrain,
                ),
                field=CombatFieldSpec(
                    environment_id=location.environment_id,
                    scene=location.location_name or location.terrain,
                    origin="地表",
                    xy=location.xy,
                    altitude=location.altitude,
                    terrain=location.terrain,
                ),
                left_formation=left_formation,
                right_formation=right_formation,
                left_groups=_combat_groups(left_ids, left),
                right_groups=_combat_groups(right_ids, right),
            )
        )
        injury_results = {}
        left_enemy_ids = tuple(item.id for item in result.right_results)
        right_enemy_ids = tuple(item.id for item in result.left_results)
        for item in result.left_results:
            if item.id not in left_injuries:
                # **战斗构造物不是参战者**：它们的单位编号形如 `xxx:战斗对象:n`，
                # 战斗里由效果现造，开战前那份 `injuries` 里自然没有它们（只有人物与道侣），
                # 长期伤势也就无从结算。战报里照旧有它们（那是 `report` 层的事），这里只结算"人"。
                continue
            state, realm_id = left_injuries[item.id]
            injury_results[item.id] = self._injury.evolve(
                state,
                realm_id=realm_id,
                combatant_result=item,
                events=result.events,
                enemy_ids=left_enemy_ids,
                battle_id=record.entity_id,
            )
        for item in result.right_results:
            if item.id not in right_injuries:
                continue
            state, realm_id = right_injuries[item.id]
            injury_results[item.id] = self._injury.evolve(
                state,
                realm_id=realm_id,
                combatant_result=item,
                events=result.events,
                enemy_ids=right_enemy_ids,
                battle_id=record.entity_id,
            )
        consumptions = _consumptions(result.left_results + result.right_results)
        definitions = {
            stack.stack_key: stack
            for stacks in medicine_stacks.values()
            for stack in stacks
        }
        inventory_operations: list[StateMutation] = []
        for owner, used in consumptions.items():
            plan = await self._asset.plan_inventory_changes(
                owner,
                tuple(
                    InventoryAdjustment(
                        definitions[stack_key].medicine_id,
                        definitions[stack_key].grade_id,
                        -quantity,
                    )
                    for stack_key, quantity in sorted(used.items())
                ),
            )
            inventory_operations.extend(plan.operations)
        now = _now()
        value.update(
            {
                "状态": "战斗中",
                "开始时间": now.isoformat(),
                "结束时间": (now + timedelta(seconds=self._seconds)).isoformat(),
                "胜方": result.winner_side or "平局",
                "甲方存活": sum(item.alive for item in result.left_results),
                "乙方存活": sum(item.alive for item in result.right_results),
                "战报编号": record.entity_id,
                "战报": materialize(result.report or {}),
            }
        )
        value["战果"] = {
            item.id: {
                "用户编号": item.owner_id,
                "道侣": item.id.startswith("companion:"),
                "血气": item.health,
                "精神": item.spirit,
                "伤势主体": injury_results[item.id].state.subject_key,
                "伤势": self._injury.serialize(injury_results[item.id].state),
                "伤势版本": injury_results[item.id].state.version,
                "伤势变化": [
                    {
                        "编号": change.injury_id,
                        "名称": change.name,
                        "原层数": change.before_stacks,
                        "现层数": change.after_stacks,
                        "类别": change.category,
                    }
                    for change in injury_results[item.id].changes
                ],
            }
            # **只收参战者**：战斗构造物（单位编号形如 `xxx:战斗对象:n`）是战斗中由效果现造的，
            # 开战前那份 `injuries` 里没有它们、也就没有长期伤势可写；战报本身照旧记着它们
            # （那是 `report` 层的事）。不收它们，`开始宗门战` 就不会再因构造物 KeyError 崩。
            for item in (*result.left_results, *result.right_results)
            if item.id in injury_results
        }
        operations: list[object] = [
            SharedEntityMutation(ENTITY_TYPE, record.entity_id, value, record.version)
        ]
        operations.extend(left_battle_medicine)
        operations.extend(right_battle_medicine)
        operations.extend(inventory_operations)
        if left_formation_operation is not None:
            operations.append(left_formation_operation)
        if right_formation_operation is not None:
            operations.append(right_formation_operation)
        await self._commit(
            user_id,
            request_id,
            "开始宗门战",
            tuple(operations),
            {"宗门战编号": record.entity_id, "战报编号": record.entity_id},
        )
        return await self._view(value)

    async def current(self, user_id: str, request_id: str = "") -> SectWarView:
        member = await self._member(user_id)
        record = await self._current_record(member.sect_id, user_id)
        if record.value.get("状态") == "战斗中" and _now() >= _time(
            record.value.get("结束时间")
        ):
            return await self._settle(
                user_id,
                request_id or f"sect-war-settle:{record.entity_id}",
                record,
            )
        return await self._view(record.value)

    async def lifecycle(
        self, user_id: str, *, now: datetime | None = None
    ) -> ActivityLifecycle:
        """从宗门战书恢复统一生命周期视图，不触发自动结算。"""

        member = await self._member(user_id)
        record = await self._current_record(member.sect_id, user_id)
        value = record.value
        status = _text(value.get("状态"), "宗门战.状态")
        if status == "战斗中":
            phase = "running"
        elif status == "已结算":
            phase = "settled"
        elif status in _TERMINAL:
            phase = "terminated"
        else:
            phase = "pending"
        participants = _all_participants(value)
        return self._activity.view(
            ActivityFacts(
                activity_type="宗门战",
                activity_id=record.entity_id,
                owner_id=_text(value.get("甲方"), "宗门战.甲方"),
                participant_user_ids=participants,
                settlement_user_ids=participants,
                phase=phase,
                started_at=(
                    _time(value.get("开始时间")) if value.get("开始时间") else None
                ),
                ends_at=(
                    _time(value.get("结束时间")) if value.get("结束时间") else None
                ),
                completed_at=(
                    _time(value.get("完成时间")) if value.get("完成时间") else None
                ),
            ),
            user_id,
            now=now or _now(),
        )

    async def history(self, user_id: str, page: int = 1) -> SectWarHistoryPage:
        member = await self._member(user_id)
        normalized_page = _request_positive(page, "页码")
        records = [
            record
            for record in await self._db.list_shared_entities(ENTITY_TYPE)
            if member.sect_id in (record.value.get("甲方"), record.value.get("乙方"))
            and record.value.get("状态") in _TERMINAL
        ]
        records.sort(key=lambda item: item.updated_at, reverse=True)
        page_count = max(1, math.ceil(len(records) / self._history_page_size))
        current_page = min(normalized_page, page_count)
        start = (current_page - 1) * self._history_page_size
        entries = tuple(
            [
                await self._view(record.value)
                for record in records[start : start + self._history_page_size]
            ]
        )
        return SectWarHistoryPage(current_page, page_count, len(records), entries)

    async def view(self, user_id: str, war_id: str) -> SectWarView:
        member = await self._member(user_id)
        record = await self._record(war_id)
        if member.sect_id not in (record.value.get("甲方"), record.value.get("乙方")):
            raise SectWarError("not_participant")
        return await self._view(record.value)

    async def _settle(self, user_id: str, request_id: str, record: SharedEntityRecord) -> SectWarView:
        value = dict(record.value)
        if value.get("状态") != "战斗中":
            return await self._view(value)
        if _now() < _time(value.get("结束时间")):
            raise SectWarError("not_ended")
        result_rows = _mapping(value.get("战果"), "宗门战.战果")
        result_operations: list[object] = []
        reward_operations: list[object] = []
        for raw in result_rows.values():
            item = _mapping(raw, "宗门战.战果[]")
            owner = _text(item.get("用户编号"), "战果.用户编号")
            if bool(item.get("道侣")):
                result_operations.append(
                    (
                        await self._companion.plan_battle_settlement(
                            owner,
                            health=float(item.get("血气") or 0),
                            spirit=float(item.get("精神") or 0),
                        )
                    ).operation
                )
            else:
                result_operations.extend(
                    (
                        await self._character.plan_battle_settlement(
                            owner,
                            health=float(item.get("血气") or 0),
                            spirit=float(item.get("精神") or 0),
                        )
                    ).operations
                )
            injuries = self._injury.restore(
                _mapping(item.get("伤势"), "战果.伤势"),
                user_id=owner,
                subject_key=_text(item.get("伤势主体"), "战果.伤势主体"),
                version=_stored_nonnegative(item.get("伤势版本"), "战果.伤势版本"),
            )
            if injuries.entries or injuries.version:
                result_operations.append(self._injury.settlement_mutation(injuries))
        winner = str(value.get("胜方") or "平局")
        wager = _stored_nonnegative(value.get("押注"), "宗门战.押注")
        if winner == "left":
            reward_operations.append(
                await self._assets.plan_spirit_stone_change(
                    str(value["甲方"]), _payout(wager * 2, self._win_ratio)
                )
            )
        elif winner == "right":
            reward_operations.append(
                await self._assets.plan_spirit_stone_change(
                    str(value["乙方"]), _payout(wager * 2, self._win_ratio)
                )
            )
        else:
            refund = _payout(wager, self._draw_ratio)
            reward_operations.extend(
                (
                    await self._assets.plan_spirit_stone_change(
                        str(value["甲方"]), refund
                    ),
                    await self._assets.plan_spirit_stone_change(
                        str(value["乙方"]), refund
                    ),
                )
            )
        value["状态"] = "已结算"
        value["完成时间"] = _now().isoformat()
        release_operations = await self._release_operations(_all_participants(value))
        plan = SettlementTransactionPlan(
            result_operations=tuple(result_operations),
            reward_operations=tuple(reward_operations),
            release_operations=tuple(release_operations),
            record_operations=(
                SharedEntityMutation(
                    ENTITY_TYPE, record.entity_id, value, record.version
                ),
            ),
        )
        await self._commit(
            user_id,
            request_id,
            "结算宗门战",
            plan.command(
                user_id=user_id,
                request_id=request_id,
                business_type="结算宗门战",
                payload={"宗门战编号": record.entity_id, "胜方": winner},
            ).operations,
            {"宗门战编号": record.entity_id, "胜方": winner},
        )
        return await self._view(value)

    async def _terminate(
        self, user_id: str, request_id: str, record: SharedEntityRecord, status: str, business: str
    ) -> SectWarView:
        value = dict(record.value)
        operations: list[object] = []
        attacker_wager = _stored_nonnegative(value.get("甲方押注", 0), "甲方押注")
        defender_wager = _stored_nonnegative(value.get("乙方押注", 0), "乙方押注")
        if attacker_wager:
            operations.append(
                await self._assets.plan_spirit_stone_change(
                    str(value["甲方"]), attacker_wager
                )
            )
        if defender_wager:
            operations.append(
                await self._assets.plan_spirit_stone_change(
                    str(value["乙方"]), defender_wager
                )
            )
        value["状态"] = status
        value["完成时间"] = _now().isoformat()
        operations.insert(
            0,
            SharedEntityMutation(ENTITY_TYPE, record.entity_id, value, record.version),
        )
        operations.extend(await self._release_operations(_all_participants(value)))
        await self._commit(
            user_id,
            request_id,
            business,
            tuple(operations),
            {"宗门战编号": record.entity_id, "状态": status},
        )
        return await self._view(value)

    async def _expire_for_sects(
        self,
        sect_ids: tuple[str, ...],
        user_id: str,
        records: Sequence = (),
    ) -> bool:
        """把过期的战书结算掉；`records` 是调用方**刚读过**的全量记录，省掉一次整份读取。

        返回「有没有真的结掉过期战书」——有的话调用方手里那份记录已经旧了，必须重读。
        """

        changed = False
        for record in records or await self._db.list_shared_entities(ENTITY_TYPE):
            if not set(sect_ids).intersection(
                (record.value.get("甲方"), record.value.get("乙方"))
            ) or not _expired(record.value):
                continue
            try:
                await self._terminate(
                    user_id,
                    f"sect-war-expire:{record.entity_id}",
                    record,
                    "已过期",
                    "宗门战过期退款",
                )
            except StateConflictError:
                continue
            changed = True
        return changed

    async def _current_record(self, sect_id: str, user_id: str) -> SharedEntityRecord:
        # 战书列表是**共享实体**，一条记录里带着整份战报（15 对 15 实测 600 KB 上下）：
        # 读一次要三十几毫秒。原先「先结算过期战书、再挑当前战书」各读一遍，同一次命令里
        # 把同一份列表整份读了两遍——这里读一次，两边共用。
        records = await self._db.list_shared_entities(ENTITY_TYPE)
        if await self._expire_for_sects((sect_id,), user_id, records):
            # 刚结掉一条过期战书：手里那份已经旧了，重读一次（与从前一样准）。
            records = await self._db.list_shared_entities(ENTITY_TYPE)
        active = [
            record
            for record in records
            if sect_id in (record.value.get("甲方"), record.value.get("乙方"))
            and record.value.get("状态") not in _TERMINAL
        ]
        if not active:
            raise SectWarError("no_active")
        active.sort(key=lambda item: item.updated_at, reverse=True)
        return active[0]

    @staticmethod
    def _has_active(records: Sequence, sect_id: str) -> bool:
        """这份战书列表里有没有这个宗门还没了结的一战。"""

        return any(
            sect_id in (record.value.get("甲方"), record.value.get("乙方"))
            and record.value.get("状态") not in _TERMINAL
            for record in records
        )

    async def _formation_entry(self, sect_id: str, entry_key: str) -> SectAssetEntry:
        sect = await self._sect.sect(sect_id)
        if sect is None:
            raise SectWarError("sect_changed")
        vault = await self._assets.wanzhen(sect.leader_user_id)
        entry = next(
            (item for item in vault.entries if item.entry_key == entry_key), None
        )
        if entry is None or entry.category != "阵法":
            raise SectWarError("formation_missing")
        return entry

    async def _formation_spec(self, sect_id: str, entry_key: str, position: int) -> tuple[CombatFormationSpec | None, dict[str, float] | None]:
        if not entry_key:
            return None, None
        plan = await self._assets.plan_formation_consumption(sect_id, entry_key)
        entry = plan.entry
        return (
            CombatFormationSpec(
                entry.content_id,
                entry.grade_name,
                position,
                {key: float(value) for key, value in entry.materials},
            ),
            plan.operation,
        )

    async def _combatants(self, user_ids: tuple[str, ...]) -> tuple[tuple[CombatantSpec, ...], dict[str, tuple[RecoveryMedicineStack, ...]], tuple[StateMutation, ...], dict[str, tuple[InjuryState, str]]]:
        combatants: list[CombatantSpec] = []
        medicines: dict[str, tuple[RecoveryMedicineStack, ...]] = {}
        battle_operations: list[StateMutation] = []
        injuries = {}
        for user_id in user_ids:
            profile = await self._character.profile(user_id)
            # 把刚读到的人物事实交给它，省掉同一次命令里第二次整份状态读取。
            character = await self._character.combatant(user_id, profile=profile)
            character_injuries = await self._injury.state(user_id, PLAYER_KEY)
            if profile.prepared_battle_medicine is not None:
                definition = self._medicine.battle(
                    profile.prepared_battle_medicine.medicine_id,
                    profile.prepared_battle_medicine.grade_id,
                )
                character = replace(
                    character,
                    prepared_statuses=(self._medicine.prepared_status(definition),),
                )
                battle_operations.append(
                    (
                        await self._character.plan_battle_medicine(
                            user_id, medicine=None
                        )
                    ).operation
                )
            character = replace(
                character,
                group_id=f"玩家编组:{user_id}",
                group_role="主战者",
                prepared_statuses=(
                    *character.prepared_statuses,
                    *self._injury.prepared_statuses(character_injuries),
                ),
            )
            injuries[character.id] = (character_injuries, profile.realm_id)
            combatants.append(character)
            companion = await self._companion.combatant(user_id)
            if companion is not None:
                instance = await self._companion.active_instance(user_id)
                companion_injuries = await self._injury.state(
                    user_id, companion_subject(instance.instance.companion_id)
                )
                prepared = instance.instance.prepared_battle_medicine
                if prepared is not None:
                    definition = self._medicine.battle(
                        prepared.medicine_id, prepared.grade_id
                    )
                    companion = replace(
                        companion,
                        prepared_statuses=(self._medicine.prepared_status(definition),),
                    )
                    battle_operations.extend(
                        (
                            await self._companion.plan_battle_medicine(
                                user_id, medicine=None
                            )
                        ).operations
                    )
                companion = replace(
                    companion,
                    group_id=f"玩家编组:{user_id}",
                    group_role="主战者",
                    prepared_statuses=(
                        *companion.prepared_statuses,
                        *self._injury.prepared_statuses(companion_injuries),
                    ),
                )
                injuries[companion.id] = (
                    companion_injuries,
                    instance.instance.realm_id,
                )
                combatants.append(companion)
            medicines[user_id] = await self._medicine.recovery_stacks(user_id)
        return tuple(combatants), medicines, tuple(battle_operations), injuries

    async def _release_operations(
        self, participants: Sequence[str]
    ) -> list[StateMutation]:
        # 一次读齐（`current_many` 一条连接读完），再把刚读到的那份交给规划口——
        # 原先按人读一次、`plan_finish_behavior` 与 `plan_transition` 各自又读一次，
        # 一场 15 对 15 的结算要为 30 个人读 90 次状态行。
        unique = tuple(dict.fromkeys(participants))
        snapshots = {
            value.user_id: value for value in await self._state.current_many(unique)
        }
        operations = []
        for participant in unique:
            snapshot = snapshots.get(participant)
            if snapshot is None or snapshot.states["行为"].state_id != self._behavior:
                continue
            plan = await self._state.plan_finish_behavior(
                participant, expected_version=snapshot.version, snapshot=snapshot
            )
            operations.append(plan.mutation)
        return operations

    async def _member(self, user_id: str) -> SectMember:
        member = await self._sect.membership(user_id)
        if member is None:
            raise SectWarError("not_member")
        return member

    async def _member_officer(self, user_id: str) -> SectMember:
        member = await self._member(user_id)
        if not self._sect.is_officer(member.role):
            raise SectWarError("officer_required")
        return member

    async def report(self, war_id: str) -> tuple[Mapping[str, object], int] | None:
        """按宗门战编号取**存下来的战报与它的版本**（公开读口，战报页面用）。

        宗门战记录是共享实体，按编号就能取，不需要问「谁发起的」——所以战报页面的分享
        地址可以只用编号。版本是记录自己的修订号：页面那边**按版本决定要不要重算画面**，
        这样永远不会拿到比存档旧的画面（第 119 轮）。

        没打过、还没结算或编号不存在时返回 `None`，由调用方决定怎么对外说（页面回 404）。
        """

        record = await self._db.get_shared_entity(ENTITY_TYPE, str(war_id or "").strip())
        if record is None:
            return None
        value = record.value.get("战报") if isinstance(record.value, Mapping) else None
        if not isinstance(value, Mapping) or not value:
            return None
        return value, int(record.version)

    async def _record(self, war_id: str) -> SharedEntityRecord:
        record = await self._db.get_shared_entity(
            ENTITY_TYPE, str(war_id or "").strip()
        )
        if record is None:
            raise SectWarError("not_found")
        return record

    async def _view(self, raw: Mapping[str, object]) -> SectWarView:
        attacker = await self._sect.sect(str(raw.get("甲方")))
        defender = await self._sect.sect(str(raw.get("乙方")))
        return SectWarView(
            str(raw.get("宗门战编号")),
            str(raw.get("甲方")),
            str(raw.get("乙方")),
            attacker.name if attacker else "",
            defender.name if defender else "",
            str(raw.get("状态")),
            int(raw.get("押注") or 0),
            len(raw.get("甲方成员", [])),
            len(raw.get("乙方成员", [])),
            _time(raw.get("结束时间")) if raw.get("结束时间") else None,
            str(raw.get("胜方") or ""),
            bool(raw.get("甲方锁定")),
            bool(raw.get("乙方锁定")),
            str(raw.get("甲方阵法名称") or ""),
            str(raw.get("乙方阵法名称") or ""),
            str(raw.get("战报编号") or ""),
        )

    async def _commit(self, user_id: str, request_id: str, business: str, operations: Sequence[DatabaseMutation], payload: Mapping[str, object]) -> None:
        await self._db.commit(
            TransactionCommand(
                user_id, request_id, business, tuple(operations), payload
            )
        )


def _attach_inventory(combatants: Sequence[CombatantSpec], inventory: Mapping[str, Mapping[str, int]], threshold: float) -> tuple[CombatantSpec, ...]:
    seen: set[str] = set()
    result = []
    for combatant in combatants:
        owner = combatant.inventory_owner_id
        current = inventory.get(owner, {}) if owner not in seen else {}
        seen.add(owner)
        result.append(
            replace(
                combatant,
                inventory=current,
                medicine_threshold=threshold,
                statuses=(),
                cooldowns={},
                shield=0,
                skill_cursor=0,
            )
        )
    return tuple(result)


def _medicine_definitions(values: Mapping[str, Sequence[RecoveryMedicineStack]]) -> tuple[CombatMedicineSpec, ...]:
    definitions = {}
    for stacks in values.values():
        for stack in stacks:
            definitions[stack.stack_key] = CombatMedicineSpec(
                stack.stack_key,
                stack.medicine_id,
                stack.grade_id,
                stack.resource,
                stack.recovery_percent,
                stack.grade_order,
            )
    return tuple(definitions.values())


def _consumptions(results: Sequence[CombatantResult]) -> dict[str, Counter[str]]:
    values: dict[str, Counter[str]] = {}
    for result in results:
        if result.inventory_owner_id:
            values.setdefault(result.inventory_owner_id, Counter()).update(
                result.consumed_items
            )
    return values


def _all_participants(value: Mapping[str, object]) -> tuple[str, ...]:
    return _stored_texts(value.get("甲方成员", ()), "甲方成员") + _stored_texts(
        value.get("乙方成员", ()), "乙方成员"
    )


def _combat_groups(user_ids: tuple[str, ...], combatants: Sequence[CombatantSpec]) -> tuple[CombatGroupSpec, ...]:
    by_owner: dict[str, list[str]] = {str(user_id): [] for user_id in user_ids}
    for value in combatants:
        if value.owner_id in by_owner:
            by_owner[value.owner_id].append(value.id)
    return tuple(
        CombatGroupSpec(
            group_id=f"玩家编组:{user_id}",
            member_ids=tuple(member_ids),
            primary_ids=tuple(member_ids),
        )
        for user_id, member_ids in by_owner.items()
        if member_ids
    )


def _side(value: Mapping[str, object], sect_id: str) -> str:
    if value.get("甲方") == sect_id:
        return "甲方"
    if value.get("乙方") == sect_id:
        return "乙方"
    return ""


def _expired(value: Mapping[str, object]) -> bool:
    return (
        value.get("状态") == "待应战"
        and bool(value.get("过期时间"))
        and _now() >= _time(value.get("过期时间"))
    )


def _request_positive(value: int, label: str) -> int:
    return positive_int(value, label, error=SectWarError)


def _stored_texts(value: int, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是数组")
    return tuple(_text(item, f"{label}[]") for item in value)


def _stored_xy(value: int) -> tuple[int, int]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 2
    ):
        raise JsonDataError("宗门战坐标必须是xy")
    x, y = value
    if (
        isinstance(x, bool)
        or isinstance(y, bool)
        or not isinstance(x, int)
        or not isinstance(y, int)
    ):
        raise JsonDataError("宗门战坐标必须是整数xy")
    return x, y


def _ratio(value: int, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise JsonDataError(f"{label}必须是0至1之间的小数") from exc
    if result < 0 or result > 1:
        raise JsonDataError(f"{label}必须是0至1之间的小数")
    return result


def _payout(amount: int, ratio: Decimal) -> int:
    return int((Decimal(amount) * ratio).to_integral_value(rounding=ROUND_FLOOR))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _time(value: int) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise JsonDataError("宗门战时间不是合法ISO时间") from exc
    if parsed.tzinfo is None:
        raise JsonDataError("宗门战时间必须包含时区")
    return parsed.astimezone(timezone.utc)


def _seed(value: int) -> int:
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big")


__all__ = ["ENTITY_TYPE", "STATE_TYPE", "SectWarService"]
