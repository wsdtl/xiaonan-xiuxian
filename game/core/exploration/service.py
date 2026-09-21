"""预计算、按时解封并原子结算普通探险。"""

from __future__ import annotations

import hashlib
import math
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from game.core.activity import (
    ActivityFacts,
    ActivityLifecycle,
    ActivityLifecycleService,
)
from game.core.asset import AssetService, InventoryAdjustment
from game.core.character import CharacterService
from game.core.combat import (
    CombatantResult,
    CombatantSpec,
    CombatFieldSpec,
    CombatFormationSpec,
    CombatGroupSpec,
    CombatMedicineSpec,
    CombatRequest,
    CombatResult,
    CombatService,
)
from game.core.companion import CompanionService
from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping,
    materialize,
    nonnegative_int,
    positive_int,
)
from game.core.database import (
    DatabaseService,
    SettlementTransactionPlan,
    StateAddress,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)
from game.core.enemy import EnemyInstance, EnemyService
from game.core.formation import FormationService
from game.core.injury import PLAYER_KEY, InjuryService, companion_subject
from game.core.innate_treasure import (
    InnateTreasureActivation,
    InnateTreasureService,
)
from game.core.location import LocationService
from game.core.medicine import MedicineService, RecoveryMedicineStack
from game.core.player_state import (
    PlayerStateService,
    StateTransitionCommand,
)
from game.core.world import LocationQuery, WorldService

from .contracts import (
    ExplorationCharacterSummary,
    ExplorationConflictError,
    ExplorationLeaderRequiredError,
    ExplorationNotFinishedError,
    ExplorationProgress,
    ExplorationSettlement,
    ExplorationStartCommand,
    ExplorationStarted,
    ExplorationStateError,
    ExplorationStatus,
    ExplorationUserSummary,
)
from game.core.data import strict_text

SESSION_STATE = "exploration_session"
BATTLE_STATE = "exploration_battle"
LATEST_STATE = "exploration_latest"
SETTLEMENT_STATE = "exploration_settlement"
LATEST_KEY = "main"


class ExplorationService:
    """拥有普通探险会话及逐场结果的唯一核心边界。"""

    state_types = frozenset(
        {SESSION_STATE, BATTLE_STATE, LATEST_STATE, SETTLEMENT_STATE}
    )

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        world: WorldService,
        location: LocationService,
        character: CharacterService,
        companion: CompanionService,
        asset: AssetService,
        player_state: PlayerStateService,
        enemy: EnemyService,
        formation: FormationService,
        combat: CombatService,
        activity: ActivityLifecycleService,
        innate_treasure: InnateTreasureService,
        medicine: MedicineService | None = None,
        injury: InjuryService | None = None,
    ) -> None:
        self._data = data
        self._database = database
        self._world = world
        self._location = location
        self._character = character
        self._companion = companion
        self._asset = asset
        self._player_state = player_state
        self._enemy = enemy
        self._formation = formation
        self._combat = combat
        self._activity = activity
        self._innate_treasure = innate_treasure
        self._medicine = medicine
        self._injury = injury
        self._initialized = False
        self._rules: Mapping[str, object] = {}
        self._maximum_participants = 0
        self._state_id = ""

    def initialize(self) -> ExplorationStatus:
        if self._initialized:
            raise RuntimeError("探险核心已经初始化")
        if self._medicine is None or not self._medicine.status().initialized:
            raise RuntimeError("丹药核心必须先于探险核心启动")
        if self._injury is None or not self._injury.status().initialized:
            raise RuntimeError("长期伤势核心必须先于探险核心启动")
        if not self._activity.status().initialized:
            raise RuntimeError("异步玩法生命周期核心必须先于探险核心启动")
        if not self._innate_treasure.status().initialized:
            raise RuntimeError("先天灵宝核心必须先于探险核心启动")
        rules = self._data.dataset("玩法规则").get("探险")
        self._rules = _mapping(rules, "玩法/探险/规则/探险.json")
        seconds = _positive_int(self._rules.get("每场秒数"), "探险.每场秒数")
        maximum = _positive_int(self._rules.get("最多场数"), "探险.最多场数")
        duration = _positive_int(self._rules.get("持续秒数"), "探险.持续秒数")
        if seconds * maximum != duration:
            raise JsonDataError("探险持续秒数必须等于每场秒数乘最多场数")
        self._maximum_participants = _positive_int(
            self._rules.get("参与用户上限"), "探险.参与用户上限"
        )
        self._state_id = _text(self._rules.get("行为状态"), "探险.行为状态")
        if self._player_state.state_type(self._state_id) != "行为":
            raise JsonDataError("探险.行为状态必须引用行为状态")
        _positive_int(self._rules.get("战斗行动上限"), "探险.战斗行动上限")
        # 同行道侣按「并肩」进正式参战名单，且允许没有道侣（「可无」）。声明写在数据里，
        # 判定在编组处；这里把它读死，免得数据说一套、实现做另一套。
        # 注意数据装载后已被冻结（数组是元组、对象是只读映射），要按结构比而不是按字面比。
        companion_rule = self._rules.get("同行道侣")
        if not (
            isinstance(companion_rule, Sequence)
            and len(companion_rule) == 1
            and isinstance(companion_rule[0], Mapping)
            and dict(companion_rule[0]) == {"方式": "并肩", "要求": "可无"}
        ):
            raise JsonDataError("探险同行道侣必须是并肩且可无")
        self._initialized = True
        return self.status()

    def status(self) -> ExplorationStatus:
        return ExplorationStatus(
            self._initialized,
            int(self._rules.get("每场秒数", 0)),
            int(self._rules.get("最多场数", 0)),
            int(self._rules.get("战斗行动上限", 0)),
        )

    async def start(self, command: ExplorationStartCommand) -> ExplorationStarted:
        self._require_initialized()
        owner = _user_id(command.owner_user_id)
        participants = _participants(
            owner, command.participant_user_ids, self._maximum_participants
        )
        replay = await self._start_replay(owner, command.request_id)
        if replay is not None:
            return replay
        seed = (
            command.seed
            if command.seed is not None
            else _stable_seed(owner, command.request_id)
        )
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError("探险种子必须是整数")
        started_at = _utc(command.started_at)
        session_id = hashlib.sha256(
            f"{owner}\0{command.request_id}".encode()
        ).hexdigest()[:24]

        locations = [await self._location.current(user_id) for user_id in participants]
        if (
            len({(value.space_type, value.space_id, value.xy) for value in locations})
            != 1
        ):
            raise ExplorationConflictError("同行修士必须位于同一空间和坐标")
        if locations[0].space_type != "地表":
            raise ExplorationConflictError("宗门洞天内不能进行普通探险")
        location = self._world.locate(LocationQuery(xy=locations[0].xy))
        if not location.location_key or "探险" not in location.available_functions:
            raise ExplorationConflictError("当前位置不能进行普通探险")
        if len(location.enemy_multiplier) != 2:
            raise ExplorationStateError("地点缺少单次遭遇敌人倍率")

        formation_plan = await self._formation.activation_plan(owner, position=0)
        formation_spec = (
            CombatFormationSpec(
                formation_id=formation_plan.prepared.formation_id,
                grade=formation_plan.prepared.grade_name,
                position=formation_plan.profile.position,
                materials={
                    key: float(value)
                    for key, value in formation_plan.prepared.materials
                },
            )
            if formation_plan is not None
            else None
        )

        transition_plans = []
        combatants: list[CombatantSpec] = []
        medicines: dict[str, tuple[RecoveryMedicineStack, ...]] = {}
        character_names: dict[str, str] = {}
        battle_medicine_operations: list[StateMutation] = []
        injury_states = {}
        combatant_realms: dict[str, str] = {}
        player_group_members: dict[str, list[str]] = {}
        treasure_snapshots: dict[str, dict[str, object] | None] = {}
        medicine_ratios: dict[str, float] = {}
        public_profiles = {
            value.user_id: value
            for value in await self._character.public_profiles(participants)
        }
        for user_id in participants:
            guard = await self._player_state.authorize(
                user_id, "空闲或托管且可行动"
            )
            if not guard.allowed:
                name = public_profiles.get(user_id)
                raise ExplorationConflictError(
                    f"{name.name if name else '有同行修士'}无法开始探险：{guard.reason}"
                )
            transition_plans.append(
                await self._player_state.plan_transition(
                    StateTransitionCommand(
                        user_id=user_id,
                        request_id=command.request_id,
                        state_type="行为",
                        target_state_id=self._state_id,
                        context={
                            "探险编号": session_id,
                            "发起者": owner,
                            "参与人数": len(participants),
                        },
                    )
                )
            )
            profile = await self._character.profile(user_id)
            active_treasure = await self._innate_treasure.active(user_id)
            treasure_snapshots[user_id] = (
                {
                    "编号": active_treasure.treasure_id,
                    "名称": active_treasure.name,
                    "权柄": active_treasure.authority,
                    "节点": active_treasure.effect.node,
                    "能力": active_treasure.effect.ability,
                    "数值": dict(active_treasure.effect.values),
                }
                if active_treasure is not None
                else None
            )
            medicine_ratios[user_id] = (
                float(active_treasure.effect.values["比例"])
                if active_treasure is not None
                and active_treasure.effect.node == "恢复丹生效"
                and active_treasure.effect.ability == "提高恢复量"
                else 0.0
            )
            player = await self._character.combatant(user_id)
            player_injuries = await self._injury.state(user_id, PLAYER_KEY)
            if profile.prepared_battle_medicine is not None:
                definition = self._medicine.battle(
                    profile.prepared_battle_medicine.medicine_id,
                    profile.prepared_battle_medicine.grade_id,
                )
                player = replace(
                    player,
                    prepared_statuses=(self._medicine.prepared_status(definition),),
                )
                battle_medicine_operations.append(
                    (
                        await self._character.plan_battle_medicine(
                            user_id, medicine=None
                        )
                    ).operation
                )
            player = replace(
                player,
                group_id=f"玩家编组:{user_id}",
                group_role="主战者",
                prepared_statuses=(
                    *player.prepared_statuses,
                    *self._injury.prepared_statuses(player_injuries),
                ),
            )
            injury_states[player.id] = player_injuries
            combatant_realms[player.id] = profile.realm_id
            character_names[user_id] = player.name
            combatants.append(player)
            player_group_members[user_id] = [player.id]
            companion = await self._companion.combatant(user_id)
            if companion is not None:
                current_companion = await self._companion.active_instance(user_id)
                companion_injuries = await self._injury.state(
                    user_id, companion_subject(current_companion.instance.companion_id)
                )
                prepared = current_companion.instance.prepared_battle_medicine
                if prepared is not None:
                    definition = self._medicine.battle(
                        prepared.medicine_id,
                        prepared.grade_id,
                    )
                    companion = replace(
                        companion,
                        prepared_statuses=(self._medicine.prepared_status(definition),),
                    )
                    battle_medicine_operations.extend(
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
                injury_states[companion.id] = companion_injuries
                combatant_realms[companion.id] = current_companion.instance.realm_id
                combatants.append(companion)
                player_group_members[user_id].append(companion.id)
            medicines[user_id] = await self._medicine.recovery_stacks(user_id)

        initial_unit_count = len(combatants)
        ally_groups = tuple(
            CombatGroupSpec(
                group_id=f"玩家编组:{user_id}",
                member_ids=tuple(player_group_members[user_id]),
                primary_ids=tuple(player_group_members[user_id]),
            )
            for user_id in participants
        )
        source = random.Random(seed)
        virtual_inventory = {
            user_id: {
                _owner_stack_key(user_id, stack.stack_key): stack.quantity
                for stack in stacks
            }
            for user_id, stacks in medicines.items()
        }
        medicine_definitions = _medicine_definitions(medicines, medicine_ratios)
        user_results = {
            user_id: {
                "人物": character_names[user_id],
                "角色": {},
                "消耗": Counter(),
                "掉落": Counter(),
                "灵石": 0,
                "灵宝快照": treasure_snapshots[user_id],
                "先天灵宝": None,
            }
            for user_id in participants
        }
        for combatant in combatants:
            user_results[combatant.owner_id]["角色"][combatant.id] = {
                "名称": combatant.name,
                "道侣": combatant.id.startswith("companion:"),
                "主体": injury_states[combatant.id].subject_key,
                "伤势": self._injury.serialize(injury_states[combatant.id]),
                "伤势版本": injury_states[combatant.id].version,
                "伤势变化": [],
                "剩余伤势": [
                    dict(value)
                    for value in self._injury.summary(
                        injury_states[combatant.id]
                    ).entries
                ],
                "血气": _initial_resource(combatant, "血气"),
                "精神": _initial_resource(combatant, "精神"),
                "存活": _initial_resource(combatant, "血气") > 0,
                "武器经验": 0,
            }
        current = {value.id: value for value in combatants}
        battle_values: list[dict[str, object]] = []
        defeated_total = 0
        for battle_index in range(1, self.status().maximum_battles + 1):
            living = [value for value in current.values() if (value.health or 0) > 0]
            if not living:
                break
            enemy_groups = self._enemy.generate_groups(
                pool_names=location.enemy_pool,
                group_count=len(ally_groups),
                unit_count_range=location.enemy_multiplier,
                seed=source.getrandbits(64),
                instance_prefix=f"{session_id}:{battle_index}",
            )
            enemies = tuple(item for group in enemy_groups for item in group.combatants)
            enemy_group_specs = tuple(
                CombatGroupSpec(
                    group_id=group.group_id,
                    member_ids=tuple(item.combatant.id for item in group.combatants),
                    primary_ids=group.primary_ids,
                )
                for group in enemy_groups
            )
            left = _attach_inventory(
                living,
                virtual_inventory,
                self._medicine.auto_medicine_threshold,
            )
            result = await self._combat.execute(
                CombatRequest(
                    left_team=tuple(left),
                    right_team=tuple(value.combatant for value in enemies),
                    seed=source.getrandbits(64),
                    action_limit=self.status().action_limit,
                    medicine_definitions=_carried_medicine_definitions(
                        medicine_definitions, left
                    ),
                    medicine_selection_strategy=self._medicine.selection_strategy,
                    field=CombatFieldSpec(
                        environment_id=location.environment_id,
                        scene=location.location_name or location.terrain,
                        origin="地表",
                        xy=location.xy,
                        altitude=location.altitude,
                        terrain=location.terrain,
                    ),
                    left_formation=formation_spec if battle_index == 1 else None,
                    left_groups=_living_groups(
                        ally_groups, {value.id for value in living}
                    ),
                    right_groups=enemy_group_specs,
                )
            )
            enemy_by_id = {value.combatant.id: value for value in enemies}
            defeated = [
                enemy_by_id[value.id]
                for value in result.right_results
                if value.id in enemy_by_id and not value.alive
            ]
            living_by_id = {value.id: value for value in living}
            formal_left_by_id = {
                value.id: value
                for value in result.left_results
                if value.id in living_by_id
            }
            if formal_left_by_id.keys() != living_by_id.keys():
                raise ExplorationStateError("战斗结果缺少我方正式参战者")
            formal_left_results = tuple(
                formal_left_by_id[combatant_id] for combatant_id in living_by_id
            )
            defeated_total += len(defeated)
            living_users = {
                value.owner_id
                for value in formal_left_results
                if value.alive and value.owner_id
            }
            allocations = _allocate_rewards(defeated, living_users)
            for user_id, allocation in allocations.items():
                user_results[user_id]["灵石"] += allocation["灵石"]
                user_results[user_id]["掉落"].update(allocation["掉落"])
            weapon_experience = sum(
                value.reward.weapon_experience for value in defeated
            )
            for before in living:
                user_results[before.owner_id]["角色"].setdefault(
                    before.id,
                    {
                        "名称": before.name,
                        "道侣": before.id.startswith("companion:"),
                        "武器经验": 0,
                    },
                )["武器经验"] += weapon_experience
            current = {}
            for value in formal_left_results:
                before = living_by_id[value.id]
                evolution = self._injury.evolve(
                    injury_states[value.id],
                    realm_id=combatant_realms[value.id],
                    combatant_result=value,
                    events=result.events,
                    enemy_ids=tuple(enemy_by_id),
                    battle_id=f"{session_id}:{battle_index:02d}",
                )
                injury_states[value.id] = evolution.state
                current[value.id] = replace(
                    before,
                    health=value.health,
                    spirit=value.spirit,
                    shield=0,
                    statuses=(),
                    prepared_statuses=self._injury.prepared_statuses(evolution.state),
                    cooldowns={},
                    inventory={},
                    skill_cursor=0,
                )
                record = user_results[value.owner_id]["角色"].setdefault(
                    value.id,
                    {
                        "名称": value.name,
                        "道侣": value.id.startswith("companion:"),
                        "主体": evolution.state.subject_key,
                        "武器经验": 0,
                    },
                )
                record["血气"] = value.health
                record["精神"] = value.spirit
                record["存活"] = value.alive
                record["伤势"] = self._injury.serialize(evolution.state)
                record["伤势版本"] = evolution.state.version
                record.setdefault("伤势变化", []).extend(
                    [
                        {
                            "编号": change.injury_id,
                            "名称": change.name,
                            "原层数": change.before_stacks,
                            "现层数": change.after_stacks,
                            "类别": change.category,
                        }
                        for change in evolution.changes
                    ]
                )
                record["剩余伤势"] = [
                    dict(item) for item in self._injury.summary(evolution.state).entries
                ]
                user_results[value.owner_id]["消耗"].update(value.consumed_items)
            for user_id in participants:
                owner_results = [
                    value for value in formal_left_results if value.owner_id == user_id
                ]
                if owner_results:
                    virtual_inventory[user_id] = dict(owner_results[0].inventory)
            battle_values.append(
                _battle_value(
                    session_id,
                    battle_index,
                    location.enemy_multiplier,
                    result,
                    defeated,
                    allocations,
                    formal_left_results,
                    len(enemies),
                    enemy_group_specs,
                )
            )

        battle_count = len(battle_values)
        ends_at = started_at + timedelta(
            seconds=battle_count * self.status().seconds_per_battle
        )
        for user_id in participants:
            _apply_treasure_reward(
                user_results[user_id],
                self._data,
                self._asset,
            )
        normalized_results = _normalize_user_results(user_results, current)
        consumptions = _consumption_adjustments(medicines, virtual_inventory)
        inventory_plans = {
            user_id: await self._asset.plan_inventory_changes(
                user_id,
                tuple(
                    InventoryAdjustment(item_id, grade_id, -quantity)
                    for item_id, grade_id, quantity in consumptions[user_id]
                ),
            )
            for user_id in participants
        }
        session_value = {
            "开始请求": command.request_id,
            "发起者": owner,
            "参与用户": list(participants),
            "地点": location.location_name,
            "坐标": list(location.xy),
            "初始正式单位数": initial_unit_count,
            "场数": battle_count,
            "每场秒数": self.status().seconds_per_battle,
            "开始时间": started_at.isoformat(),
            "结束时间": ends_at.isoformat(),
            "种子": seed,
            "战败敌人": defeated_total,
            "用户结果": normalized_results,
            "首战阵法": (
                {
                    "阵藏条目": formation_plan.prepared.reserve_key,
                    "阵法编号": formation_plan.prepared.formation_id,
                    "名称": formation_plan.prepared.name,
                    "品级": formation_plan.prepared.grade_id,
                }
                if formation_plan is not None
                else None
            ),
        }
        operations: list[StateMutation] = [
            StateMutation(owner, SESSION_STATE, session_id, session_value, 0)
        ]
        operations.extend(plan.mutation for plan in transition_plans)
        operations.extend(battle_medicine_operations)
        operations.extend(
            operation
            for user_id in participants
            for operation in inventory_plans[user_id].operations
        )
        if formation_plan is not None:
            operations.append(formation_plan.operation)
        for user_id in participants:
            previous = await self._database.get(
                StateAddress(user_id, LATEST_STATE, LATEST_KEY)
            )
            operations.append(
                StateMutation(
                    user_id,
                    LATEST_STATE,
                    LATEST_KEY,
                    {"发起者": owner, "探险编号": session_id},
                    previous.version if previous else 0,
                )
            )
        operations.extend(
            StateMutation(
                owner,
                BATTLE_STATE,
                f"{session_id}:{index:02d}",
                value,
                0,
            )
            for index, value in enumerate(battle_values, start=1)
        )
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id=owner,
                    request_id=command.request_id,
                    business_type="普通探险开始",
                    operations=tuple(operations),
                    payload={"探险编号": session_id, "参与用户": list(participants)},
                )
            )
        except StateConflictError as exc:
            raise ExplorationConflictError(str(exc)) from exc
        return ExplorationStarted(
            session_id,
            location.location_name,
            len(participants),
            initial_unit_count,
            battle_count,
            started_at,
            ends_at,
            receipt.replayed,
        )

    async def progress(
        self, user_id: str, *, now: datetime | None = None
    ) -> ExplorationProgress:
        owner, session_id, session = await self._session_for(user_id)
        current = _utc(now)
        started = _parse_time(session.get("开始时间"), "探险.开始时间")
        ends = _parse_time(session.get("结束时间"), "探险.结束时间")
        seconds = _positive_int(session.get("每场秒数"), "探险.每场秒数")
        total = _nonnegative_int(session.get("场数"), "探险.场数")
        elapsed = max(0, int((current - started).total_seconds()))
        unlocked = min(total, elapsed // seconds)
        if current >= ends:
            unlocked = total
        battles = await self._battles(owner, session_id, unlocked)
        return ExplorationProgress(
            session_id=session_id,
            location_name=_text(session.get("地点"), "探险.地点"),
            unlocked_battles=unlocked,
            total_battles=total,
            remaining_seconds=max(0, math.ceil((ends - current).total_seconds())),
            ended=current >= ends,
            surviving_allies=(
                _nonnegative_int(battles[-1].get("我方存活"), "战斗.我方存活")
                if battles
                else _positive_int(session.get("初始正式单位数"), "初始正式单位数")
            ),
            defeated_enemies=sum(
                _nonnegative_int(value.get("战败敌人"), "战斗.战败敌人")
                for value in battles
            ),
            spirit_stones=sum(
                _nonnegative_int(value.get("分配灵石"), "战斗.分配灵石")
                for value in battles
            ),
            item_quantity=sum(
                _nonnegative_int(value.get("分配物品"), "战斗.分配物品")
                for value in battles
            ),
            can_settle=_user_id(user_id) == owner,
        )

    async def lifecycle(
        self, user_id: str, *, now: datetime | None = None
    ) -> ActivityLifecycle:
        """从持久化会话恢复统一生命周期视图。"""

        owner, session_id, session = await self._session_for(user_id)
        settlement = await self._database.get(
            StateAddress(owner, SETTLEMENT_STATE, session_id)
        )
        return self._activity.view(
            ActivityFacts(
                activity_type="探险",
                activity_id=session_id,
                owner_id=owner,
                participant_user_ids=_texts(session.get("参与用户"), "探险.参与用户"),
                settlement_user_ids=(owner,),
                phase="settled" if settlement is not None else "running",
                started_at=_parse_time(session.get("开始时间"), "探险.开始时间"),
                ends_at=_parse_time(session.get("结束时间"), "探险.结束时间"),
                completed_at=(
                    _parse_time(settlement.value.get("结算时间"), "探险.结算时间")
                    if settlement is not None
                    else None
                ),
            ),
            user_id,
            now=_utc(now),
        )

    async def settle(
        self,
        user_id: str,
        request_id: str,
        *,
        now: datetime | None = None,
    ) -> ExplorationSettlement:
        owner, session_id, session = await self._session_for(user_id)
        existing = await self._database.get(
            StateAddress(owner, SETTLEMENT_STATE, session_id)
        )
        if existing is not None:
            return self._settlement(session_id, existing.value, replayed=True)
        if _user_id(user_id) != owner:
            raise ExplorationLeaderRequiredError("本次探险由领队统一结算")
        settled_at = _utc(now)
        ends_at = _parse_time(session.get("结束时间"), "探险.结束时间")
        if settled_at < ends_at:
            raise ExplorationNotFinishedError("探险尚未结束")
        user_values = _mapping(session.get("用户结果"), "探险.用户结果")
        participants = _texts(session.get("参与用户"), "探险.参与用户")
        result_operations: list[StateMutation] = []
        reward_operations: list[StateMutation] = []
        release_operations: list[StateMutation] = []
        summaries: list[dict[str, object]] = []
        for participant in participants:
            value = _mapping(user_values.get(participant), f"用户结果.{participant}")
            characters = _sequence(value.get("角色"), f"用户结果.{participant}.角色")
            player = next(
                _mapping(raw, "角色")
                for raw in characters
                if not bool(_mapping(raw, "角色").get("道侣"))
            )
            player_plan = await self._character.plan_battle_settlement(
                participant,
                health=_number(player.get("血气"), "人物.血气"),
                spirit=_number(player.get("精神"), "人物.精神"),
                spirit_stones_delta=_nonnegative_int(value.get("灵石"), "用户.灵石"),
                weapon_experience=_nonnegative_int(
                    player.get("武器经验"), "人物.武器经验"
                ),
            )
            result_operations.extend(player_plan.operations)
            player_injury = self._injury.restore(
                _mapping(player.get("伤势"), "人物.伤势"),
                user_id=participant,
                subject_key=_text(player.get("主体"), "人物.伤势主体"),
                version=_nonnegative_int(player.get("伤势版本"), "人物.伤势版本"),
            )
            if player_injury.entries or player_injury.version:
                result_operations.append(
                    self._injury.settlement_mutation(player_injury)
                )
            companion = next(
                (
                    _mapping(raw, "角色")
                    for raw in characters
                    if bool(_mapping(raw, "角色").get("道侣"))
                ),
                None,
            )
            if companion is not None:
                companion_plan = await self._companion.plan_battle_settlement(
                    participant,
                    health=_number(companion.get("血气"), "道侣.血气"),
                    spirit=_number(companion.get("精神"), "道侣.精神"),
                    weapon_experience=_nonnegative_int(
                        companion.get("武器经验"), "道侣.武器经验"
                    ),
                )
                result_operations.append(companion_plan.operation)
                companion_injury = self._injury.restore(
                    _mapping(companion.get("伤势"), "道侣.伤势"),
                    user_id=participant,
                    subject_key=_text(companion.get("主体"), "道侣.伤势主体"),
                    version=_nonnegative_int(
                        companion.get("伤势版本"), "道侣.伤势版本"
                    ),
                )
                if companion_injury.entries or companion_injury.version:
                    result_operations.append(
                        self._injury.settlement_mutation(companion_injury)
                    )
            drops = tuple(
                InventoryAdjustment(
                    _text(raw.get("编号"), "掉落.编号"),
                    _text(raw.get("品级"), "掉落.品级"),
                    _positive_int(raw.get("数量"), "掉落.数量"),
                )
                for raw in (
                    _mapping(item, "掉落[]")
                    for item in _sequence(
                        value.get("掉落"), "用户.掉落", allow_empty=True
                    )
                )
            )
            if drops:
                reward_operations.extend(
                    (
                        await self._asset.plan_inventory_changes(participant, drops)
                    ).operations
                )
            release_operations.append(
                (await self._player_state.plan_finish_behavior(participant)).mutation
            )
            summaries.append(materialize(value))
        settlement_value = {
            "地点": session["地点"],
            "场数": session["场数"],
            "战败敌人": session["战败敌人"],
            "参与用户": list(participants),
            "用户结果": summaries,
            "结算时间": settled_at.isoformat(),
        }
        plan = SettlementTransactionPlan(
            result_operations=tuple(result_operations),
            reward_operations=tuple(reward_operations),
            release_operations=tuple(release_operations),
            record_operations=(
                StateMutation(owner, SETTLEMENT_STATE, session_id, settlement_value, 0),
            ),
        )
        try:
            receipt = await self._database.commit(
                plan.command(
                    user_id=owner,
                    request_id=request_id,
                    business_type="普通探险结算",
                    payload={"探险编号": session_id},
                )
            )
        except StateConflictError as exc:
            raise ExplorationConflictError(str(exc)) from exc
        return self._settlement(
            session_id, settlement_value, replayed=receipt.replayed
        )

    async def latest_settlement(self, user_id: str) -> ExplorationSettlement | None:
        owner, session_id = await self._latest(user_id)
        snapshot = await self._database.get(
            StateAddress(owner, SETTLEMENT_STATE, session_id)
        )
        return (
            None
            if snapshot is None
            else self._settlement(session_id, snapshot.value, replayed=True)
        )

    async def _start_replay(
        self, owner: str, request_id: str
    ) -> ExplorationStarted | None:
        latest = await self._database.get(StateAddress(owner, LATEST_STATE, LATEST_KEY))
        if latest is None:
            return None
        value = _mapping(latest.value, "最近探险")
        if _text(value.get("发起者"), "最近探险.发起者") != owner:
            return None
        session_id = _text(value.get("探险编号"), "最近探险.探险编号")
        session = await self._database.get(
            StateAddress(owner, SESSION_STATE, session_id)
        )
        if session is None or session.value.get("开始请求") != request_id:
            return None
        raw = session.value
        return ExplorationStarted(
            session_id,
            _text(raw.get("地点"), "探险.地点"),
            len(_texts(raw.get("参与用户"), "探险.参与用户")),
            _positive_int(raw.get("初始正式单位数"), "初始正式单位数"),
            _nonnegative_int(raw.get("场数"), "探险.场数"),
            _parse_time(raw.get("开始时间"), "探险.开始时间"),
            _parse_time(raw.get("结束时间"), "探险.结束时间"),
            True,
        )

    async def _session_for(self, user_id: str) -> tuple[str, str, Mapping[str, object]]:
        owner, session_id = await self._latest(user_id)
        snapshot = await self._database.get(
            StateAddress(owner, SESSION_STATE, session_id)
        )
        if snapshot is None:
            raise ExplorationStateError("探险会话不存在")
        return owner, session_id, snapshot.value

    async def _latest(self, user_id: str) -> tuple[str, str]:
        snapshot = await self._database.get(
            StateAddress(_user_id(user_id), LATEST_STATE, LATEST_KEY)
        )
        if snapshot is None:
            raise ExplorationStateError("当前没有可查看的探险")
        value = _mapping(snapshot.value, "最近探险")
        return (
            _text(value.get("发起者"), "最近探险.发起者"),
            _text(value.get("探险编号"), "最近探险.探险编号"),
        )

    async def _battles(
        self, owner: str, session_id: str, count: int
    ) -> tuple[Mapping[str, object], ...]:
        snapshots = await self._database.get_many(
            tuple(
                StateAddress(owner, BATTLE_STATE, f"{session_id}:{index:02d}")
                for index in range(1, count + 1)
            )
        )
        if len(snapshots) != count:
            raise ExplorationStateError("探险逐场记录不完整")
        return tuple(snapshot.value for snapshot in snapshots)

    def _settlement(
        self,
        session_id: str,
        value: Mapping[str, object],
        *,
        replayed: bool,
    ) -> ExplorationSettlement:
        users = tuple(
            _user_summary(_mapping(raw, "结算.用户结果[]"))
            for raw in _sequence(value.get("用户结果"), "结算.用户结果")
        )
        return ExplorationSettlement(
            session_id,
            _text(value.get("地点"), "结算.地点"),
            _nonnegative_int(value.get("场数"), "结算.场数"),
            _nonnegative_int(value.get("战败敌人"), "结算.战败敌人"),
            len(users),
            sum(user.spirit_stones for user in users),
            sum(quantity for user in users for _, _, quantity in user.drops),
            users,
            _parse_time(value.get("结算时间"), "结算.结算时间"),
            replayed,
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("探险核心尚未初始化")


def _attach_inventory(
    combatants: Sequence[CombatantSpec],
    inventory: Mapping[str, Mapping[str, int]],
    threshold: float,
) -> list[CombatantSpec]:
    seen: set[str] = set()
    result: list[CombatantSpec] = []
    for value in combatants:
        owner = value.inventory_owner_id
        current = inventory.get(owner, {}) if owner not in seen else {}
        seen.add(owner)
        result.append(
            replace(
                value,
                inventory=current,
                medicine_threshold=threshold,
                statuses=(),
                prepared_statuses=value.prepared_statuses,
                cooldowns={},
                shield=0,
                skill_cursor=0,
            )
        )
    return result


def _medicine_definitions(
    values: Mapping[str, tuple[RecoveryMedicineStack, ...]],
    recovery_ratios: Mapping[str, float],
) -> tuple[CombatMedicineSpec, ...]:
    result: dict[str, CombatMedicineSpec] = {}
    for user_id, stacks in values.items():
        for stack in stacks:
            owner_stack_key = _owner_stack_key(user_id, stack.stack_key)
            definition = CombatMedicineSpec(
                owner_stack_key,
                stack.medicine_id,
                stack.grade_id,
                stack.resource,
                stack.recovery_percent * (1 + recovery_ratios.get(user_id, 0.0)),
                stack.grade_order,
            )
            previous = result.get(owner_stack_key)
            if previous is not None and previous != definition:
                raise ExplorationStateError("相同丹药堆叠键对应了不同恢复定义")
            result[owner_stack_key] = definition
    return tuple(result.values())


def _carried_medicine_definitions(
    definitions: Sequence[CombatMedicineSpec],
    combatants: Sequence[CombatantSpec],
) -> tuple[CombatMedicineSpec, ...]:
    carried = {
        stack_key
        for combatant in combatants
        for stack_key, quantity in combatant.inventory.items()
        if quantity > 0
    }
    return tuple(value for value in definitions if value.stack_key in carried)


def _allocate_rewards(
    defeated: Sequence[EnemyInstance], living_users: set[str]
) -> dict[str, dict[str, object]]:
    result = {user_id: {"灵石": 0, "掉落": Counter()} for user_id in living_users}
    if not living_users:
        return result
    count = len(living_users)
    for enemy in defeated:
        stone_share = enemy.reward.spirit_stones // count
        for user_id in living_users:
            result[user_id]["灵石"] += stone_share
        for drop in enemy.reward.drops:
            share = drop.quantity // count
            if share < 1:
                continue
            for user_id in living_users:
                result[user_id]["掉落"][(drop.item_id, drop.grade_id)] += share
    return result


def _living_groups(
    groups: Sequence[CombatGroupSpec], living_ids: set[str]
) -> tuple[CombatGroupSpec, ...]:
    """每场战斗的编组契约只保留本场仍存活的我方参战者。

    同一场探险可能连打多场，上一场倒下的角色不会进入下一场；编组契约若还带着他们，
    战斗核心会判「编组引用未知参战者」而整单失败。整组阵亡的编组直接去掉。
    """

    alive_groups: list[CombatGroupSpec] = []
    for group in groups:
        members = tuple(value for value in group.member_ids if value in living_ids)
        if not members:
            continue
        primaries = tuple(value for value in group.primary_ids if value in living_ids)
        alive_groups.append(
            CombatGroupSpec(
                group_id=group.group_id,
                member_ids=members,
                primary_ids=primaries or members,
            )
        )
    return tuple(alive_groups)


def _battle_value(
    session_id: str,
    index: int,
    unit_count_range: tuple[int, int],
    result: CombatResult,
    defeated: Sequence[EnemyInstance],
    allocations: Mapping[str, Mapping[str, object]],
    formal_left_results: Sequence[CombatantResult],
    formal_enemy_count: int,
    enemy_groups: Sequence[CombatGroupSpec] = (),
) -> dict[str, object]:
    return {
        "探险编号": session_id,
        "场次": index,
        "敌方编组人数范围": list(unit_count_range),
        "敌人数": formal_enemy_count,
        "敌方编组": [
            {
                "编号": group.group_id,
                "成员": list(group.member_ids),
                "主战者": list(group.primary_ids),
            }
            for group in enemy_groups
        ],
        "行动数": result.actions,
        "结果": result.winner_side or "未分胜负",
        "我方存活": sum(value.alive for value in formal_left_results),
        "战败敌人": len(defeated),
        "分配灵石": sum(int(value["灵石"]) for value in allocations.values()),
        "分配物品": sum(
            int(quantity)
            for value in allocations.values()
            for quantity in value["掉落"].values()
        ),
        "我方": [_combatant_result(value) for value in result.left_results],
        "敌方": [_combatant_result(value) for value in result.right_results],
        "事件": [
            {
                "回合": event.turn,
                "类型": event.kind,
                "来源": event.source,
                "目标": event.target,
                "文本": event.text,
                "数值": event.amount,
                "记录": materialize(event.values),
                "标签": list(event.tags),
                "能力": event.ability,
                "来源编号": event.source_id,
                "目标编号": event.target_id,
            }
            for event in result.events
        ],
        "阵法": [
            {
                "编号": formation.formation_id,
                "名称": formation.name,
                "品级": formation.grade,
                "方位": formation.position,
                "承载": formation.capacity,
                "剩余承载": formation.remaining_capacity,
                "冲击": formation.impact,
                "节点": formation.nodes,
                "轮转": formation.rotations,
                "崩解": formation.collapsed,
            }
            for formation in result.formations
        ],
    }


def _combatant_result(value: CombatantResult) -> dict[str, object]:
    return {
        "编号": value.id,
        "名称": value.name,
        "编组": value.group_id,
        "编组身份": value.group_role,
        "血气": value.health,
        "精神": value.spirit,
        "存活": value.alive,
        "消耗": dict(value.consumed_items),
    }


def _initial_resource(value: CombatantSpec, resource: str) -> float:
    current = value.health if resource == "血气" else value.spirit
    if current is not None:
        return float(current)
    return float(value.attributes.get(f"{resource}上限", 0))


def _normalize_user_results(
    values: Mapping[str, Mapping[str, object]],
    current: Mapping[str, CombatantSpec],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for user_id, raw in values.items():
        characters = raw["角色"]
        for combatant_id, record in characters.items():
            if "血气" not in record:
                combatant = current.get(combatant_id)
                record["血气"] = float(combatant.health or 0) if combatant else 0
                record["精神"] = float(combatant.spirit or 0) if combatant else 0
                record["存活"] = bool(combatant and (combatant.health or 0) > 0)
        result[user_id] = {
            "用户编号": user_id,
            "人物": raw["人物"],
            "角色": list(characters.values()),
            "消耗": _stack_rows(raw["消耗"]),
            "掉落": _drop_rows(raw["掉落"]),
            "灵石": int(raw["灵石"]),
            "先天灵宝": raw.get("先天灵宝"),
        }
    return result


def _apply_treasure_reward(
    raw: Mapping[str, object], data: JsonDataService, asset: AssetService
) -> None:
    if not isinstance(raw, dict):
        raise ExplorationStateError("探险用户预计算结果必须可写")
    snapshot_value = raw.get("灵宝快照")
    if snapshot_value is None:
        return
    snapshot = _mapping(snapshot_value, "探险.灵宝快照")
    node = _text(snapshot.get("节点"), "探险.灵宝快照.节点")
    ability = _text(snapshot.get("能力"), "探险.灵宝快照.能力")
    values = _mapping(snapshot.get("数值"), "探险.灵宝快照.数值")
    summary = ""
    drops = raw.get("掉落")
    if not isinstance(drops, Counter):
        raise ExplorationStateError("探险预计算掉落必须是计数器")
    if node == "探险奖励分配" and ability == "最低品战利品升品":
        candidates = sorted(
            (
                (item_id, grade_id)
                for (item_id, grade_id), quantity in drops.items()
                if quantity > 0 and asset.grade(grade_id).order < asset.grade("05").order
            ),
            key=lambda key: (asset.grade(key[1]).order, key[0]),
        )
        if candidates:
            item_id, grade_id = candidates[0]
            next_grade_id = f"{int(grade_id) + 1:02d}"
            drops[(item_id, grade_id)] -= 1
            drops[(item_id, next_grade_id)] += int(values["数量"])
            item_name = str(data.entity("基础物品", item_id).get("名称") or item_id)
            summary = (
                f"{asset.grade(grade_id).name}{item_name} × 1升为"
                f"{asset.grade(next_grade_id).name}品"
            )
    elif node == "探险奖励分配" and ability == "增加兽宝":
        candidates = sorted(
            (
                (item_id, grade_id)
                for (item_id, grade_id), quantity in drops.items()
                if quantity > 0
                and data.entity_record("基础物品", item_id).number_category == "兽宝"
            ),
            key=lambda key: (asset.grade(key[1]).order, key[0]),
        )
        if candidates:
            item_id, grade_id = candidates[0]
            quantity = int(values["数量"])
            drops[(item_id, grade_id)] += quantity
            item_name = str(data.entity("基础物品", item_id).get("名称") or item_id)
            summary = f"额外获得{asset.grade(grade_id).name}{item_name} × {quantity}"
    elif node == "恢复丹生效" and ability == "提高恢复量" and raw.get("消耗"):
        summary = f"自动恢复丹恢复量提高{float(values['比例']):.0%}"
    if summary:
        raw["先天灵宝"] = {
            "编号": _text(snapshot.get("编号"), "探险.灵宝快照.编号"),
            "名称": _text(snapshot.get("名称"), "探险.灵宝快照.名称"),
            "权柄": _text(snapshot.get("权柄"), "探险.灵宝快照.权柄"),
            "结果": summary,
        }


def _consumption_adjustments(
    medicines: Mapping[str, tuple[RecoveryMedicineStack, ...]],
    remaining: Mapping[str, Mapping[str, int]],
) -> dict[str, tuple[tuple[str, str, int], ...]]:
    result: dict[str, tuple[tuple[str, str, int], ...]] = {}
    for user_id, stacks in medicines.items():
        consumed = []
        for stack in stacks:
            quantity = stack.quantity - int(
                remaining[user_id].get(
                    _owner_stack_key(user_id, stack.stack_key), 0
                )
            )
            if quantity > 0:
                consumed.append((stack.medicine_id, stack.grade_id, quantity))
        result[user_id] = tuple(consumed)
    return result


def _stack_rows(values: Counter[str]) -> list[dict[str, object]]:
    normalized: Counter[str] = Counter()
    for stack_key, quantity in values.items():
        normalized[_base_stack_key(stack_key)] += quantity
    result = []
    for stack_key, quantity in sorted(normalized.items()):
        item_id, grade_id = stack_key.rsplit(":", 1)
        result.append({"编号": item_id, "品级": grade_id, "数量": quantity})
    return result


def _owner_stack_key(user_id: str, stack_key: str) -> str:
    return f"{stack_key}|{user_id}"


def _base_stack_key(stack_key: str) -> str:
    return stack_key.split("|", 1)[0]


def _drop_rows(values: Counter[tuple[str, str]]) -> list[dict[str, object]]:
    return [
        {"编号": item_id, "品级": grade_id, "数量": quantity}
        for (item_id, grade_id), quantity in sorted(values.items())
        if quantity > 0
    ]


def _user_summary(value: Mapping[str, object]) -> ExplorationUserSummary:
    characters = tuple(
        ExplorationCharacterSummary(
            _text(raw.get("名称"), "角色.名称"),
            bool(raw.get("道侣")),
            float(_number(raw.get("血气"), "角色.血气")),
            float(_number(raw.get("精神"), "角色.精神")),
            bool(raw.get("存活")),
            _nonnegative_int(raw.get("武器经验"), "角色.武器经验"),
            tuple(
                (
                    _text(change.get("名称"), "角色.伤势变化.名称"),
                    _nonnegative_int(change.get("原层数"), "角色.伤势变化.原层数"),
                    _nonnegative_int(change.get("现层数"), "角色.伤势变化.现层数"),
                )
                for change in (
                    _mapping(item, "角色.伤势变化[]")
                    for item in _sequence(
                        raw.get("伤势变化", ()), "角色.伤势变化", allow_empty=True
                    )
                )
            ),
            tuple(
                (
                    _text(injury.get("名称"), "角色.剩余伤势.名称"),
                    _positive_int(injury.get("层数"), "角色.剩余伤势.层数"),
                )
                for injury in (
                    _mapping(item, "角色.剩余伤势[]")
                    for item in _sequence(
                        raw.get("剩余伤势", ()), "角色.剩余伤势", allow_empty=True
                    )
                )
            ),
        )
        for raw in (
            _mapping(item, "角色[]")
            for item in _sequence(value.get("角色"), "用户.角色")
        )
    )
    return ExplorationUserSummary(
        _text(value.get("用户编号"), "用户.用户编号"),
        _text(value.get("人物"), "用户.人物"),
        characters,
        tuple(
            _item_tuple(item)
            for item in _sequence(value.get("消耗"), "用户.消耗", allow_empty=True)
        ),
        tuple(
            _item_tuple(item)
            for item in _sequence(value.get("掉落"), "用户.掉落", allow_empty=True)
        ),
        _nonnegative_int(value.get("灵石"), "用户.灵石"),
        _payload_activation(value.get("先天灵宝")),
    )


def _payload_activation(value: object) -> InnateTreasureActivation | None:
    if value is None:
        return None
    raw = _mapping(value, "探险结算.先天灵宝")
    return InnateTreasureActivation(
        _text(raw.get("编号"), "探险结算.先天灵宝.编号"),
        _text(raw.get("名称"), "探险结算.先天灵宝.名称"),
        _text(raw.get("权柄"), "探险结算.先天灵宝.权柄"),
        _text(raw.get("结果"), "探险结算.先天灵宝.结果"),
    )


def _item_tuple(value: object) -> tuple[str, str, int]:
    raw = _mapping(value, "基础物品")
    return (
        _text(raw.get("编号"), "物品.编号"),
        _text(raw.get("品级"), "物品.品级"),
        _positive_int(raw.get("数量"), "物品.数量"),
    )


def _participants(owner: str, values: tuple[str, ...], maximum: int) -> tuple[str, ...]:
    normalized = tuple(_user_id(value) for value in values) or (owner,)
    if normalized[0] != owner:
        raise ValueError("发起者必须位于参与用户首位")
    if len(normalized) != len(set(normalized)):
        raise ValueError("参与用户不能重复")
    if len(normalized) > maximum:
        raise ValueError(f"一次探险最多{maximum}名用户")
    return normalized


def _stable_seed(user_id: str, request_id: str) -> int:
    return int.from_bytes(
        hashlib.sha256(f"{user_id}\0{request_id}".encode()).digest()[:8], "big"
    )


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return value.astimezone(timezone.utc)


def _parse_time(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, label))
    except ValueError as exc:
        raise ExplorationStateError(f"{label}不是合法时间") from exc
    if parsed.tzinfo is None:
        raise ExplorationStateError(f"{label}必须包含时区")
    return parsed.astimezone(timezone.utc)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    return mapping(value, label, error=ExplorationStateError)


def _sequence(
    value: object, label: str, *, allow_empty: bool = False
) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ExplorationStateError(f"{label}必须是数组")
    result = tuple(value)
    if not result and not allow_empty:
        raise ExplorationStateError(f"{label}不能为空")
    return result


def _texts(value: object, label: str) -> tuple[str, ...]:
    return tuple(_text(item, f"{label}[]") for item in _sequence(value, label))


def _text(value: object, label: str) -> str:
    return strict_text(value, label, error=ExplorationStateError)


def _user_id(value: object) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError("user_id不能为空")
    return result


def _positive_int(value: object, label: str) -> int:
    return positive_int(value, label, error=ExplorationStateError)


def _nonnegative_int(value: object, label: str) -> int:
    return nonnegative_int(value, label, error=ExplorationStateError)


def _number(value: object, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExplorationStateError(f"{label}必须是数值")
    return value


__all__ = [
    "BATTLE_STATE",
    "LATEST_STATE",
    "SESSION_STATE",
    "SETTLEMENT_STATE",
    "ExplorationService",
]
