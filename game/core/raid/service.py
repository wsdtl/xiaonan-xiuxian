"""按讨伐定义生成首领、辅助和属从编组。"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from game.core.activity import (
    ActivityFacts,
    ActivityLifecycle,
    ActivityLifecycleService,
)
from game.core.asset import AssetService, InventoryAdjustment
from game.core.character import CharacterService
from game.core.combat import CombatGroupSpec, CombatRequest, CombatService
from game.core.companion import CompanionService
from game.core.data import JsonDataError, JsonDataService, materialize, nonempty_text, positive_int
from game.core.database import (
    DatabaseService,
    SettlementTransactionPlan,
    StateAddress,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)
from game.core.enemy import EnemyGroup, EnemyService
from game.core.location import LocationService
from game.core.player_state import PlayerStateService, StateTransitionCommand
from game.core.world import LocationQuery, WorldService

from .contracts import (
    RaidDefinition,
    RaidError,
    RaidGroupResult,
    RaidLeaderRequiredError,
    RaidNotFinishedError,
    RaidProgress,
    RaidSettlement,
    RaidStartCommand,
    RaidStarted,
)

SESSION_STATE = "raid_session"
SETTLEMENT_STATE = "raid_settlement"
LATEST_STATE = "raid_latest"


class RaidService:
    """读取讨伐专属敌方来源并组装公共战斗请求。"""

    state_types = frozenset({SESSION_STATE, SETTLEMENT_STATE, LATEST_STATE})

    def __init__(
        self,
        data: JsonDataService,
        enemy: EnemyService,
        database: DatabaseService | None = None,
        world: WorldService | None = None,
        location: LocationService | None = None,
        character: CharacterService | None = None,
        companion: CompanionService | None = None,
        player_state: PlayerStateService | None = None,
        combat: CombatService | None = None,
        activity: ActivityLifecycleService | None = None,
        asset: AssetService | None = None,
    ) -> None:
        self._data = data
        self._enemy = enemy
        self._database = database
        self._world = world
        self._location = location
        self._character = character
        self._companion = companion
        self._player_state = player_state
        self._combat = combat
        self._activity = activity
        self._asset = asset
        self._initialized = False
        self._rules: Mapping[str, object] = {}
        self._state_id = ""

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("讨伐核心已经初始化")
        if not self._enemy.status().initialized:
            raise RuntimeError("敌人核心必须先于讨伐核心启动")
        rules = self._data.dataset("玩法规则").get("讨伐")
        if not isinstance(rules, Mapping):
            raise JsonDataError("讨伐/规则/讨伐.json 必须是对象")
        self._rules = dict(rules)
        self._state_id = _text(self._rules.get("行为状态"), "讨伐.行为状态")
        self._initialized = True

    def definition(self, raid_id: str) -> RaidDefinition:
        self._require_initialized()
        raw = materialize(self._data.entity("讨伐", raid_id))
        if not isinstance(raw, dict):
            raise JsonDataError(f"讨伐定义必须是对象：{raid_id}")
        return RaidDefinition(
            raid_id=str(raid_id),
            boss_pool=_pool_names(raw.get("首领池"), f"{raid_id}.首领池"),
            support_pool=_pool_names(raw.get("辅助池"), f"{raid_id}.辅助池"),
            subordinate_pool=_pool_names(raw.get("属从池"), f"{raid_id}.属从池"),
            reward_pool=_pool_names(raw.get("奖励池"), f"{raid_id}.奖励池"),
            boss_tier=_text(raw.get("首领阶梯"), f"{raid_id}.首领阶梯"),
            support_tier=_text(raw.get("辅助阶梯"), f"{raid_id}.辅助阶梯"),
            subordinate_tier=_text(raw.get("属从阶梯"), f"{raid_id}.属从阶梯"),
            boss_unit_count=_unit_range(raw.get("首领人数"), f"{raid_id}.首领人数", (1, 1)),
            support_unit_count=_unit_range(raw.get("辅助人数"), f"{raid_id}.辅助人数", (0, 1)),
            subordinate_unit_count=_unit_range(raw.get("属从人数"), f"{raid_id}.属从人数", (2, 3)),
        )

    def generate(
        self,
        definition: RaidDefinition,
        *,
        ally_group_count: int,
        seed: int,
        instance_prefix: str,
    ) -> RaidGroupResult:
        self._require_initialized()
        if ally_group_count < 1:
            raise ValueError("讨伐至少需要一个我方编组")
        source = random.Random(seed)
        boss_group_id = f"{instance_prefix}:首领编组"
        boss = self._enemy.generate_category(
            section="讨伐首领",
            pool_names=definition.boss_pool,
            count=source.randint(*definition.boss_unit_count),
            seed=source.getrandbits(64),
            instance_prefix=boss_group_id,
            required_tier=definition.boss_tier,
        )
        boss = tuple(
            replace(
                value,
                combatant=replace(
                    value.combatant,
                    group_id=boss_group_id,
                    group_role="主战者",
                ),
            )
            for value in boss
        )
        support_count = source.randint(*definition.support_unit_count)
        if support_count:
            support = self._enemy.generate_category(
                section="讨伐辅助",
                pool_names=definition.support_pool,
                count=support_count,
                seed=source.getrandbits(64),
                instance_prefix=f"{boss_group_id}:辅助",
                required_tier=definition.support_tier,
            )
            boss = (*boss, *tuple(
                replace(
                    value,
                    combatant=replace(
                        value.combatant,
                        group_id=boss_group_id,
                        group_role="辅助",
                    ),
                )
                for value in support
            ))
        boss_result = EnemyGroup(
            group_id=boss_group_id,
            combatants=tuple(boss),
            primary_ids=tuple(value.combatant.id for value in boss if value.combatant.group_role == "主战者"),
        )
        subordinates: list[EnemyGroup] = []
        for index in range(2, ally_group_count + 1):
            group_id = f"{instance_prefix}:属从编组{index:02d}"
            members = self._enemy.generate_category(
                section="讨伐属从",
                pool_names=definition.subordinate_pool,
                count=source.randint(*definition.subordinate_unit_count),
                seed=source.getrandbits(64),
                instance_prefix=group_id,
                required_tier=definition.subordinate_tier,
            )
            grouped = tuple(
                replace(
                    value,
                    combatant=replace(
                        value.combatant,
                        group_id=group_id,
                        group_role="主战者",
                    ),
                )
                for value in members
            )
            subordinates.append(
                EnemyGroup(
                    group_id=group_id,
                    combatants=grouped,
                    primary_ids=tuple(value.combatant.id for value in grouped),
                )
            )
        return RaidGroupResult(boss_result, tuple(subordinates))

    async def start(self, command: RaidStartCommand) -> RaidStarted:
        self._require_runtime()
        owner = _text(command.owner_user_id, "讨伐发起者")
        participants = _users(command.participant_user_ids)
        if participants[0] != owner:
            raise RaidError("讨伐发起者必须是第一名参与者")
        replay = await self._database.get(StateAddress(owner, SESSION_STATE, _session_id(owner, command.request_id)))
        if replay is not None:
            return _started(replay.value, replayed=True)
        locations = [await self._location.current(user_id) for user_id in participants]
        if len({(item.space_type, item.space_id, item.xy) for item in locations}) != 1:
            raise RaidError("同行修士必须处于同一位置")
        current = locations[0]
        if current.space_type != "地表":
            raise RaidError("洞天内不能进行讨伐")
        location = self._world.locate(LocationQuery(xy=current.xy))
        if not location.location_key or "讨伐" not in location.available_functions:
            raise RaidError("当前地点没有开放讨伐")
        raid_id = f"{_text(location.location_key, '地点编号')}讨伐"
        if len(participants) > 15:
            raise RaidError("讨伐参与用户不能超过15人")
        definition = self.definition(raid_id)
        seed = command.seed if command.seed is not None else _seed(owner, command.request_id)
        started_at = _time(command.started_at or datetime.now(UTC))
        session_id = _session_id(owner, command.request_id)
        transition_operations = []
        allies = []
        ally_groups = []
        user_character_ids: dict[str, list[str]] = {}
        public_profiles = {
            value.user_id: value
            for value in await self._character.public_profiles(participants)
        }
        for user_id in participants:
            guard = await self._player_state.authorize(
                user_id, "自主空闲且可行动"
            )
            if not guard.allowed:
                name = public_profiles.get(user_id)
                raise RaidError(
                    f"{name.name if name else '有同行修士'}无法参加讨伐：{guard.reason}"
                )
            transition_operations.append(
                (await self._player_state.plan_transition(StateTransitionCommand(
                    user_id=user_id,
                    request_id=command.request_id,
                    state_type="行为",
                    target_state_id=self._state_id,
                    context={"讨伐编号": session_id, "发起者": owner},
                ))).mutation
            )
            player = replace(await self._character.combatant(user_id), group_id=f"玩家编组:{user_id}")
            members = [player.id]
            allies.append(player)
            companion = await self._companion.combatant(user_id)
            if companion is not None:
                companion = replace(companion, group_id=f"玩家编组:{user_id}")
                allies.append(companion)
                members.append(companion.id)
            user_character_ids[user_id] = members
            ally_groups.append(CombatGroupSpec(f"玩家编组:{user_id}", tuple(members), tuple(members)))
        groups = self.generate(
            definition,
            ally_group_count=len(ally_groups),
            seed=seed,
            instance_prefix=session_id,
        )
        enemies = tuple(member.combatant for group in groups.groups for member in group.combatants)
        enemy_groups = tuple(
            CombatGroupSpec(group.group_id, tuple(item.combatant.id for item in group.combatants), group.primary_ids)
            for group in groups.groups
        )
        result = await self._combat.execute(CombatRequest(
            left_team=tuple(allies),
            right_team=enemies,
            seed=seed,
            action_limit=_positive_int(self._rules.get("战斗行动上限", 2400), "讨伐.战斗行动上限"),
            left_groups=tuple(ally_groups),
            right_groups=enemy_groups,
        ))
        enemy_instances = {
            item.combatant.id: item
            for group in groups.groups
            for item in group.combatants
        }
        defeated = tuple(
            enemy_instances[item.id]
            for item in result.right_results
            if not item.alive and item.id in enemy_instances
        )
        boss_defeated = all(
            not next(item for item in result.right_results if item.id == boss_id).alive
            for boss_id in groups.boss_group.primary_ids
        )
        bonus = self._boss_reward(definition, seed) if boss_defeated else None
        rewards = _raid_rewards(defeated, result.left_results, participants, bonus)
        weapon_experience = sum(item.reward.weapon_experience for item in defeated)
        session = {
            "讨伐会话编号": session_id,
            "发起请求": command.request_id,
            "发起者": owner,
            "参与用户": list(participants),
            "地点": location.location_name,
            "讨伐编号": raid_id,
            "开始时间": started_at.isoformat(),
            "结束时间": (started_at + timedelta(seconds=_positive_int(self._rules.get("持续秒数", 120), "讨伐.持续秒数"))).isoformat(),
            "用户角色": user_character_ids,
            "编组数量": len(groups.groups),
            "战果": {item.id: {"用户编号": item.owner_id, "道侣": item.id.startswith("companion:"), "血气": item.health, "精神": item.spirit, "武器经验": weapon_experience} for item in result.left_results},
            "奖励": rewards,
            "战败敌人": len(defeated),
            "胜负": result.winner_side or "平局",
            "首领血条": {"总段数": 3, "已破": 3 if not any(item.alive for item in result.right_results if item.group_id.endswith("首领编组")) else 0},
            "战报": materialize(result.report or {}),
        }
        operations = [StateMutation(owner, SESSION_STATE, session_id, session, 0), *transition_operations]
        for user_id in participants:
            latest = await self._database.get(StateAddress(user_id, LATEST_STATE, "main"))
            operations.append(StateMutation(user_id, LATEST_STATE, "main", {"发起者": owner, "讨伐编号": session_id}, latest.version if latest else 0))
        try:
            receipt = await self._database.commit(TransactionCommand(owner, command.request_id, "讨伐开始", tuple(operations), {"讨伐编号": session_id}))
        except StateConflictError as exc:
            raise RaidError(str(exc)) from exc
        return _started(session, replayed=receipt.replayed)

    async def progress(self, user_id: str, *, now: datetime | None = None) -> RaidProgress:
        owner, session_id, session = await self._session_for(user_id)
        current = _time(now or datetime.now(UTC))
        started = _time(session["开始时间"])
        ends = _time(session["结束时间"])
        phases = int(session["首领血条"].get("总段数", 3))
        duration = max(1.0, (ends - started).total_seconds())
        phase = min(phases, max(1, int((current - started).total_seconds() / (duration / phases)) + 1))
        return RaidProgress(session_id, str(session["地点"]), max(0, math.ceil((ends - current).total_seconds())), current >= ends, phase, phases, owner == user_id)

    async def lifecycle(self, user_id: str, *, now: datetime | None = None) -> ActivityLifecycle:
        owner, session_id, session = await self._session_for(user_id)
        settlement = await self._database.get(StateAddress(owner, SETTLEMENT_STATE, session_id))
        return self._activity.view(ActivityFacts("讨伐", session_id, owner, _users(session["参与用户"]), (owner,), "settled" if settlement else "running", _time(session["开始时间"]), _time(session["结束时间"]), _time(settlement.value["结算时间"]) if settlement else None), user_id, now=now)

    async def settle(self, user_id: str, request_id: str, *, now: datetime | None = None) -> RaidSettlement:
        owner, session_id, session = await self._session_for(user_id)
        existing = await self._database.get(StateAddress(owner, SETTLEMENT_STATE, session_id))
        if existing is not None:
            return _settlement(existing.value, replayed=True)
        if user_id != owner:
            raise RaidLeaderRequiredError("本次讨伐由发起者统一结算")
        settled_at = _time(now or datetime.now(UTC))
        if settled_at < _time(session["结束时间"]):
            raise RaidNotFinishedError("讨伐尚未结束")
        result_ops = []
        release_ops = []
        for participant in _users(session["参与用户"]):
            for raw_id in session["用户角色"][participant]:
                row = session["战果"].get(raw_id)
                if not row:
                    continue
                if row.get("道侣"):
                    result_ops.append((await self._companion.plan_battle_settlement(participant, health=float(row["血气"]), spirit=float(row["精神"]), weapon_experience=int(row.get("武器经验", 0)))).operation)
                else:
                    result_ops.extend((await self._character.plan_battle_settlement(participant, health=float(row["血气"]), spirit=float(row["精神"]), weapon_experience=int(row.get("武器经验", 0)))).operations)
            release_ops.append((await self._player_state.plan_finish_behavior(participant)).mutation)
        reward_ops = []
        for participant, reward in session["奖励"].items():
            stones = int(reward.get("灵石", 0) or 0)
            if stones:
                reward_ops.append(await self._asset.plan_spirit_stone_change(participant, stones))
            adjustments = tuple(InventoryAdjustment(item_id, grade_id, quantity) for item_id, grade_id, quantity in reward.get("基础物品", []))
            if adjustments:
                reward_ops.extend((await self._asset.plan_inventory_changes(participant, adjustments)).operations)
        value = {"讨伐编号": session_id, "地点": session["地点"], "参与用户": session["参与用户"], "战败敌人": session["战败敌人"], "胜负": session.get("胜负", "平局"), "结算时间": settled_at.isoformat()}
        plan = SettlementTransactionPlan(tuple(result_ops), tuple(reward_ops), tuple(release_ops), (StateMutation(owner, SETTLEMENT_STATE, session_id, value, 0),))
        try:
            receipt = await self._database.commit(plan.command(user_id=owner, request_id=request_id, business_type="讨伐结算", payload={"讨伐编号": session_id}))
        except StateConflictError as exc:
            raise RaidError(str(exc)) from exc
        return _settlement(value, replayed=receipt.replayed)

    async def _session_for(self, user_id: str) -> tuple[str, str, Mapping[str, object]]:
        latest = await self._database.get(StateAddress(_text(user_id, "查看用户"), LATEST_STATE, "main"))
        if latest is None:
            raise RaidError("当前没有可查看的讨伐")
        owner = _text(latest.value.get("发起者"), "最近讨伐.发起者")
        session_id = _text(latest.value.get("讨伐编号"), "最近讨伐.讨伐编号")
        snapshot = await self._database.get(StateAddress(owner, SESSION_STATE, session_id))
        if snapshot is None:
            raise RaidError("讨伐会话不存在")
        return owner, session_id, snapshot.value

    def _require_runtime(self) -> None:
        if not all((self._database, self._world, self._location, self._character, self._companion, self._player_state, self._combat, self._activity, self._asset)):
            raise RuntimeError("讨伐核心运行依赖尚未装配")
        self._require_initialized()

    def _boss_reward(self, definition: RaidDefinition, seed: int) -> tuple[str, str, int]:
        candidates = self._data.pool_members(definition.reward_pool, "基础物品")
        item_id = random.Random(seed ^ 0xA5A5A5A5).choice(candidates)
        grade_id = self._asset.draw_drop_grade(seed=seed ^ 0x5A5A5A5A).grade_id
        return item_id, grade_id, 1

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("讨伐核心尚未初始化")


__all__ = ["RaidService"]


def _pool_names(value, path: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise JsonDataError(f"{path}必须是非空文件名列表")
    result = tuple(str(item).strip() for item in value)
    if any(not item for item in result):
        raise JsonDataError(f"{path}不能包含空文件名")
    return result


def _unit_range(value, path: str, default: tuple[int, int]) -> tuple[int, int]:
    if value is None:
        return default
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise JsonDataError(f"{path}必须是两个整数")
    low, high = (int(item) for item in value)
    if low < 0 or high < low:
        raise JsonDataError(f"{path}范围无效")
    return low, high


def _text(value: object, label: str) -> str:
    return nonempty_text(value, label, error=RaidError)


def _users(values: object) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or not values:
        raise RaidError("讨伐至少需要一名参与者")
    result = tuple(_text(value, "参与用户") for value in values)
    if len(set(result)) != len(result):
        raise RaidError("参与用户不能重复")
    return result


def _time(value: object) -> datetime:
    if isinstance(value, datetime):
        current = value
    else:
        current = datetime.fromisoformat(str(value))
    if current.tzinfo is None or current.utcoffset() is None:
        raise RaidError("时间必须包含时区")
    return current.astimezone(UTC)


def _seed(owner: str, request_id: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{owner}\0{request_id}".encode()).digest()[:8], "big")


def _session_id(owner: str, request_id: str) -> str:
    return hashlib.sha256(f"{owner}\0{request_id}".encode()).hexdigest()[:24]


def _positive_int(value: object, label: str) -> int:
    return positive_int(value, label, error=RaidError)


def _started(value: Mapping[str, object], *, replayed: bool) -> RaidStarted:
    return RaidStarted(
        str(value.get("讨伐会话编号") or value.get("讨伐编号") or ""),
        str(value.get("地点") or ""),
        len(_users(value.get("参与用户"))),
        int(value.get("编组数量", 1) or 1),
        _time(value.get("开始时间")),
        _time(value.get("结束时间")),
        replayed,
    )


def _settlement(value: Mapping[str, object], *, replayed: bool) -> RaidSettlement:
    return RaidSettlement(
        str(value.get("讨伐编号") or value.get("地点") or ""),
        str(value.get("地点") or ""),
        str(value.get("胜负") or ""),
        len(_users(value.get("参与用户"))),
        int(value.get("战败敌人", 0) or 0),
        _time(value.get("结算时间")),
        replayed,
    )


def _raid_rewards(
    defeated: tuple[object, ...],
    results: object,
    participants: tuple[str, ...],
    bonus: tuple[str, str, int] | None,
) -> dict[str, dict[str, object]]:
    living = {
        str(value.owner_id)
        for value in results
        if getattr(value, "alive", False) and value.owner_id
    }
    recipients = tuple(user_id for user_id in participants if user_id in living)
    stones = sum(item.reward.spirit_stones for item in defeated)
    drops: dict[tuple[str, str], int] = {}
    for item in defeated:
        for drop in item.reward.drops:
            key = (drop.item_id, drop.grade_id)
            drops[key] = drops.get(key, 0) + drop.quantity
    if bonus is not None:
        item_id, grade_id, quantity = bonus
        drops[(item_id, grade_id)] = drops.get((item_id, grade_id), 0) + quantity
    rewards = {user_id: {"灵石": 0, "基础物品": []} for user_id in participants}
    if not recipients:
        return rewards
    for user_id in recipients:
        rewards[user_id]["灵石"] = stones // len(recipients)
    for (item_id, grade_id), quantity in drops.items():
        share = quantity // len(recipients)
        if share:
            for user_id in recipients:
                rewards[user_id]["基础物品"].append([item_id, grade_id, share])
    return rewards
