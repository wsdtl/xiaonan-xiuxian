"""预计算、按整轮解封并原子结算多人闭关。"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone

from game.core.activity import (
    ActivityFacts,
    ActivityLifecycle,
    ActivityLifecycleService,
)
from game.core.asset import AssetService, CultivationAcquisition
from game.core.character import CharacterService
from game.core.companion import CompanionService
from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping,
    nonempty_text,
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
from game.core.injury import PLAYER_KEY, InjuryService, companion_subject
from game.core.innate_treasure import (
    InnateTreasureActivation,
    InnateTreasureService,
)
from game.core.location import LocationService
from game.core.player_state import PlayerStateService, StateTransitionCommand
from game.core.pool import ALLOW_REPEATS, PoolRequest, PoolService
from game.core.world import LocationQuery, WorldService

from .contracts import (
    RetreatCharacterSummary,
    RetreatConflictError,
    RetreatInsight,
    RetreatLeaderRequiredError,
    RetreatProgress,
    RetreatSettlement,
    RetreatStartCommand,
    RetreatStarted,
    RetreatStateError,
    RetreatStatus,
    RetreatUserSummary,
)
from game.core.data import boolean

SESSION_STATE = "retreat_session"
LATEST_STATE = "retreat_latest"
SETTLEMENT_STATE = "retreat_settlement"
LATEST_KEY = "main"


class RetreatService:
    """拥有闭关会话、预计算结果和最终结算的唯一核心边界。"""

    state_types = frozenset({SESSION_STATE, LATEST_STATE, SETTLEMENT_STATE})

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
        pool: PoolService,
        activity: ActivityLifecycleService,
        injury: InjuryService,
        innate_treasure: InnateTreasureService,
    ) -> None:
        self._data = data
        self._database = database
        self._world = world
        self._location = location
        self._character = character
        self._companion = companion
        self._asset = asset
        self._player_state = player_state
        self._pool = pool
        self._activity = activity
        self._injury = injury
        self._innate_treasure = innate_treasure
        self._initialized = False
        self._rules: Mapping[str, object] = {}
        self._maximum_participants = 0
        self._state_id = ""
        self._experience_base = 0
        self._experience_per_level = 0
        self._health_ratio = 0.0
        self._spirit_ratio = 0.0

    def initialize(self) -> RetreatStatus:
        if self._initialized:
            raise RuntimeError("闭关核心已经初始化")
        if not self._activity.status().initialized:
            raise RuntimeError("异步玩法生命周期核心必须先于闭关核心启动")
        if not self._injury.status().initialized:
            raise RuntimeError("长期伤势核心必须先于闭关核心启动")
        if not self._innate_treasure.status().initialized:
            raise RuntimeError("先天灵宝核心必须先于闭关核心启动")
        rules = self._data.dataset("玩法规则").get("闭关")
        self._rules = _mapping(rules, "闭关/规则/闭关.json")
        seconds = _positive_int(self._rules.get("每轮秒数"), "闭关.每轮秒数")
        maximum = _positive_int(self._rules.get("最多轮数"), "闭关.最多轮数")
        duration = _positive_int(self._rules.get("持续秒数"), "闭关.持续秒数")
        if seconds * maximum != duration:
            raise JsonDataError("闭关持续秒数必须等于每轮秒数乘最多轮数")
        self._maximum_participants = _positive_int(
            self._rules.get("参与用户上限"), "闭关.参与用户上限"
        )
        self._state_id = _text(self._rules.get("行为状态"), "闭关.行为状态")
        if self._player_state.state_type(self._state_id) != "行为":
            raise JsonDataError("闭关.行为状态必须引用行为状态")
        if self._rules.get("允许提前出关") is not True:
            raise JsonDataError("当前闭关实现要求允许提前出关")
        if self._rules.get("提前出关轮数") != "向下取整":
            raise JsonDataError("闭关提前出关轮数必须向下取整")
        growth = _mapping(self._rules.get("每轮经验"), "闭关.每轮经验")
        if growth.get("等级取值") != "开始时":
            raise JsonDataError("闭关每轮经验必须使用开始时等级")
        self._experience_base = _nonnegative_int(
            growth.get("基础"), "闭关.每轮经验.基础"
        )
        self._experience_per_level = _nonnegative_int(
            growth.get("每级"), "闭关.每轮经验.每级"
        )
        settlement = _mapping(self._rules.get("成长结算"), "闭关.成长结算")
        if settlement != {
            "人物经验": True,
            "本命武器经验": False,
            "正式参与者分别结算": True,
        }:
            raise JsonDataError("闭关成长结算必须分别增加人物经验且不增加武器经验")
        recovery = _mapping(self._rules.get("每轮恢复"), "闭关.每轮恢复")
        if recovery.get("最多恢复至上限") is not True:
            raise JsonDataError("闭关恢复必须限制在资源上限")
        self._health_ratio = _ratio(
            recovery.get("血气上限比例"), "闭关.每轮恢复.血气上限比例"
        )
        self._spirit_ratio = _ratio(
            recovery.get("精神上限比例"), "闭关.每轮恢复.精神上限比例"
        )
        insight = _mapping(self._rules.get("功法感悟"), "闭关.功法感悟")
        expected = {
            "判定对象": "玩家",
            "每轮独立判定": True,
            "候选来源": "玩家虚拟全池",
            "抽取模式": ALLOW_REPEATS,
            "品级来源": "随机奖励",
            "取得规则": "修行所得.功法取得",
        }
        if any(insight.get(key) != value for key, value in expected.items()):
            raise JsonDataError("闭关功法感悟规则与当前玩家全池契约不一致")
        _ratio(insight.get("概率"), "闭关.功法感悟.概率")
        self._initialized = True
        return self.status()

    def status(self) -> RetreatStatus:
        insight = self._rules.get("功法感悟", {})
        probability = insight.get("概率", 0) if isinstance(insight, Mapping) else 0
        return RetreatStatus(
            self._initialized,
            int(self._rules.get("每轮秒数", 0)),
            int(self._rules.get("最多轮数", 0)),
            int(self._rules.get("持续秒数", 0)),
            float(probability),
        )

    async def start(self, command: RetreatStartCommand) -> RetreatStarted:
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
            raise TypeError("闭关种子必须是整数")
        started_at = _utc(command.started_at)
        maximum_ends_at = started_at + timedelta(seconds=self.status().maximum_seconds)
        session_id = hashlib.sha256(
            f"{owner}\0{command.request_id}".encode()
        ).hexdigest()[:24]

        locations = [await self._location.current(user_id) for user_id in participants]
        if (
            len({(value.space_type, value.space_id, value.xy) for value in locations})
            != 1
        ):
            raise RetreatConflictError("同行修士必须位于同一空间和坐标")
        if locations[0].space_type != "地表":
            raise RetreatConflictError("宗门洞天内不能进行闭关")
        location = self._world.locate(LocationQuery(xy=locations[0].xy))
        if not location.location_key or "闭关" not in location.available_functions:
            raise RetreatConflictError("当前位置不能闭关")

        transitions = []
        formal_count = 0
        user_results: dict[str, dict[str, object]] = {}
        source = random.Random(seed)
        for user_id in participants:
            guard = await self._player_state.authorize(user_id, "空闲或托管")
            if not guard.allowed:
                raise RetreatConflictError(f"{user_id}无法开始闭关：{guard.reason}")
            transitions.append(
                await self._player_state.plan_transition(
                    StateTransitionCommand(
                        user_id=user_id,
                        request_id=command.request_id,
                        state_type="行为",
                        target_state_id=self._state_id,
                        context={
                            "闭关编号": session_id,
                            "发起者": owner,
                            "参与人数": len(participants),
                        },
                    )
                )
            )
            profile = await self._character.profile(user_id)
            formal_count += 1
            activation: InnateTreasureActivation | None = None
            insight_attempts = 1
            round_experience = self._round_experience(profile.level)
            treatment_multiplier = 1
            active_treasure = await self._innate_treasure.active(user_id)
            if active_treasure is not None:
                effect = active_treasure.effect
                if effect.node in {"闭关开始", "闭关疗伤"}:
                    if effect.ability == "增加每轮感悟判定":
                        added = int(effect.values["次数"])
                        insight_attempts += added
                        summary = f"每轮额外感悟判定 × {added}"
                    elif effect.ability == "提高每轮经验":
                        ratio = float(effect.values["比例"])
                        before = round_experience
                        round_experience = max(
                            before + 1, math.ceil(before * (1 + ratio))
                        )
                        summary = f"人物每轮经验 {before} → {round_experience}"
                    elif effect.ability == "增加每轮疗养进度":
                        treatment_multiplier += int(effect.values["进度"])
                        summary = f"人物每轮疗养进度 × {treatment_multiplier}"
                    else:
                        summary = ""
                    if summary:
                        activation = InnateTreasureActivation(
                            active_treasure.treasure_id,
                            active_treasure.name,
                            active_treasure.authority,
                            summary,
                        )
            result: dict[str, object] = {
                "人物": {
                    "名称": profile.name,
                    "开始等级": profile.level,
                    "每轮经验": round_experience,
                    "疗养进度倍率": treatment_multiplier,
                },
                "功法感悟": self._precompute_insights(source, insight_attempts),
                "先天灵宝": _activation_payload(activation),
            }
            active = await self._companion.active(user_id)
            if active is not None:
                instance = await self._companion.instance(user_id, active.companion_id)
                if instance is None:
                    raise RetreatStateError("同行道侣缺少实例")
                definition = self._companion.definition(active.companion_id)
                result["道侣"] = {
                    "编号": active.companion_id,
                    "名称": definition.name,
                    "开始等级": instance.level,
                    "每轮经验": self._round_experience(instance.level),
                }
                formal_count += 1
            user_results[user_id] = result

        session_value = {
            "开始请求": command.request_id,
            "发起者": owner,
            "参与用户": list(participants),
            "地点": location.location_name,
            "坐标": list(location.xy),
            "正式角色数": formal_count,
            "每轮秒数": self.status().seconds_per_round,
            "最多轮数": self.status().maximum_rounds,
            "开始时间": started_at.isoformat(),
            "最晚出关时间": maximum_ends_at.isoformat(),
            "种子": seed,
            "用户结果": user_results,
        }
        operations: list[StateMutation] = [
            StateMutation(owner, SESSION_STATE, session_id, session_value, 0),
            *(plan.mutation for plan in transitions),
        ]
        for user_id in participants:
            previous = await self._database.get(
                StateAddress(user_id, LATEST_STATE, LATEST_KEY)
            )
            operations.append(
                StateMutation(
                    user_id,
                    LATEST_STATE,
                    LATEST_KEY,
                    {"发起者": owner, "闭关编号": session_id},
                    previous.version if previous else 0,
                )
            )
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id=owner,
                    request_id=command.request_id,
                    business_type="闭关开始",
                    operations=tuple(operations),
                    payload={"闭关编号": session_id, "参与用户": list(participants)},
                )
            )
        except StateConflictError as exc:
            raise RetreatConflictError(str(exc)) from exc
        return RetreatStarted(
            session_id,
            location.location_name,
            len(participants),
            formal_count,
            self.status().maximum_rounds,
            started_at,
            maximum_ends_at,
            receipt.replayed,
        )

    async def progress(
        self, user_id: str, *, now: datetime | None = None
    ) -> RetreatProgress:
        normalized_user_id = _user_id(user_id)
        owner, session_id, session = await self._session_for(normalized_user_id)
        settlement = await self._database.get(
            StateAddress(owner, SETTLEMENT_STATE, session_id)
        )
        current = _utc(now)
        started = _parse_time(session.get("开始时间"), "闭关.开始时间")
        maximum_ends = _parse_time(session.get("最晚出关时间"), "闭关.最晚出关时间")
        if settlement is None:
            completed = self._completed_rounds(started, current)
            settled = False
            remaining = max(0, math.ceil((maximum_ends - current).total_seconds()))
        else:
            completed = _nonnegative_int(
                settlement.value.get("完成轮数"), "闭关结算.完成轮数"
            )
            settled = True
            remaining = 0
        results = _mapping(session.get("用户结果"), "闭关.用户结果")
        own = _mapping(results.get(normalized_user_id), "闭关.本人结果")
        own_insights = _insights(own.get("功法感悟"), completed)
        group_insights = sum(
            len(
                _insights(_mapping(value, "闭关.用户结果[]").get("功法感悟"), completed)
            )
            for value in results.values()
        )
        return RetreatProgress(
            session_id,
            _text(session.get("地点"), "闭关.地点"),
            len(_texts(session.get("参与用户"), "闭关.参与用户")),
            completed,
            self.status().maximum_rounds,
            remaining,
            current >= maximum_ends,
            settled,
            normalized_user_id == owner and not settled,
            group_insights,
            own_insights,
        )

    async def lifecycle(
        self, user_id: str, *, now: datetime | None = None
    ) -> ActivityLifecycle:
        """从持久化会话恢复统一生命周期视图。"""

        normalized = _user_id(user_id)
        owner, session_id, session = await self._session_for(normalized)
        settlement = await self._database.get(
            StateAddress(owner, SETTLEMENT_STATE, session_id)
        )
        return self._activity.view(
            ActivityFacts(
                activity_type="闭关",
                activity_id=session_id,
                owner_id=owner,
                participant_user_ids=_texts(session.get("参与用户"), "闭关.参与用户"),
                settlement_user_ids=(owner,),
                phase="settled" if settlement is not None else "running",
                started_at=_parse_time(session.get("开始时间"), "闭关.开始时间"),
                ends_at=_parse_time(session.get("最晚出关时间"), "闭关.最晚出关时间"),
                completed_at=(
                    _parse_time(settlement.value.get("出关时间"), "闭关.出关时间")
                    if settlement is not None
                    else None
                ),
                early_settlement=True,
            ),
            normalized,
            now=_utc(now),
        )

    async def settle(
        self,
        user_id: str,
        request_id: str,
        *,
        now: datetime | None = None,
    ) -> RetreatSettlement:
        normalized_user_id = _user_id(user_id)
        owner, session_id, session = await self._session_for(normalized_user_id)
        existing = await self._database.get(
            StateAddress(owner, SETTLEMENT_STATE, session_id)
        )
        if existing is not None:
            return self._settlement(session_id, existing.value, replayed=True)
        if normalized_user_id != owner:
            raise RetreatLeaderRequiredError("本次闭关由领队统一带领出关")
        settled_at = _utc(now)
        started_at = _parse_time(session.get("开始时间"), "闭关.开始时间")
        completed = self._completed_rounds(started_at, settled_at)
        participants = _texts(session.get("参与用户"), "闭关.参与用户")
        raw_results = _mapping(session.get("用户结果"), "闭关.用户结果")
        result_operations: list[StateMutation] = []
        reward_operations: list[StateMutation] = []
        release_operations: list[StateMutation] = []
        summaries: list[dict[str, object]] = []
        recovery_rounds = min(1.0, completed * self._health_ratio)
        spirit_rounds = min(1.0, completed * self._spirit_ratio)
        for participant in participants:
            raw = _mapping(raw_results.get(participant), f"闭关.用户结果.{participant}")
            player = _mapping(raw.get("人物"), "闭关.人物")
            player_experience = (
                _nonnegative_int(player.get("每轮经验"), "人物.每轮经验") * completed
            )
            player_plan = await self._character.plan_retreat_settlement(
                participant,
                experience=player_experience,
                health_recovery_ratio=recovery_rounds,
                spirit_recovery_ratio=spirit_rounds,
            )
            result_operations.append(player_plan.operation)
            player_treatment = await self._injury.plan_treatment(
                participant,
                PLAYER_KEY,
                completed
                * _positive_int(
                    player.get("疗养进度倍率"), "人物.疗养进度倍率"
                ),
            )
            if player_treatment.mutation is not None:
                result_operations.append(player_treatment.mutation)
            characters = [
                {
                    "名称": _text(player.get("名称"), "闭关.人物.名称"),
                    "道侣": False,
                    "经验": player_plan.experience_gained,
                    "原等级": player_plan.level_before,
                    "现等级": player_plan.level_after,
                    "血气": player_plan.health,
                    "精神": player_plan.spirit,
                    "疗伤": _injury_changes(player_treatment.changes),
                    "剩余伤势": [
                        dict(value)
                        for value in self._injury.summary(
                            player_treatment.state
                        ).entries
                    ],
                }
            ]
            companion = raw.get("道侣")
            if companion is not None:
                companion_value = _mapping(companion, "闭关.道侣")
                companion_experience = (
                    _nonnegative_int(companion_value.get("每轮经验"), "道侣.每轮经验")
                    * completed
                )
                companion_plan = await self._companion.plan_retreat_settlement(
                    participant,
                    companion_id=_text(companion_value.get("编号"), "闭关.道侣.编号"),
                    experience=companion_experience,
                    health_recovery_ratio=recovery_rounds,
                    spirit_recovery_ratio=spirit_rounds,
                )
                result_operations.append(companion_plan.operation)
                companion_treatment = await self._injury.plan_treatment(
                    participant,
                    companion_subject(companion_plan.companion_id),
                    completed,
                )
                if companion_treatment.mutation is not None:
                    result_operations.append(companion_treatment.mutation)
                characters.append(
                    {
                        "名称": _text(companion_value.get("名称"), "闭关.道侣.名称"),
                        "道侣": True,
                        "经验": companion_plan.experience_gained,
                        "原等级": companion_plan.level_before,
                        "现等级": companion_plan.level_after,
                        "血气": companion_plan.health,
                        "精神": companion_plan.spirit,
                        "疗伤": _injury_changes(companion_treatment.changes),
                        "剩余伤势": [
                            dict(value)
                            for value in self._injury.summary(
                                companion_treatment.state
                            ).entries
                        ],
                    }
                )
            unlocked = _insights(raw.get("功法感悟"), completed)
            acquisition_plan = await self._asset.plan_cultivation_acquisitions(
                participant,
                tuple(
                    CultivationAcquisition("功法", value.content_id, value.grade_id)
                    for value in unlocked
                ),
            )
            reward_operations.extend(acquisition_plan.operations)
            technique_sync = await self._character.plan_technique_grade_sync(
                participant,
                tuple(
                    (result.content_id, result.grade.grade_id)
                    for result in acquisition_plan.results
                    if result.outcome == "升品"
                ),
            )
            if technique_sync.operation is not None:
                reward_operations.append(technique_sync.operation)
            insights = [
                {
                    "轮次": source.round_number,
                    "编号": result.content_id,
                    "品级": result.grade.grade_id,
                    "结果": result.outcome,
                }
                for source, result in zip(
                    unlocked, acquisition_plan.results, strict=True
                )
            ]
            release_operations.append(
                (await self._player_state.plan_finish_behavior(participant)).mutation
            )
            summaries.append(
                {
                    "用户": participant,
                    "人物": _text(player.get("名称"), "闭关.人物.名称"),
                    "角色": characters,
                    "功法感悟": insights,
                    "先天灵宝": raw.get("先天灵宝"),
                }
            )
        settlement_value = {
            "地点": session["地点"],
            "完成轮数": completed,
            "最多轮数": self.status().maximum_rounds,
            "参与用户": list(participants),
            "用户结果": summaries,
            "出关时间": settled_at.isoformat(),
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
                    business_type="闭关出关",
                    payload={"闭关编号": session_id, "完成轮数": completed},
                )
            )
        except StateConflictError as exc:
            raise RetreatConflictError(str(exc)) from exc
        return self._settlement(
            session_id, settlement_value, replayed=receipt.replayed
        )

    def _precompute_insights(
        self, source: random.Random, attempts_per_round: int = 1
    ) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for round_number in range(1, self.status().maximum_rounds + 1):
            for _ in range(attempts_per_round):
                if source.random() >= self.status().insight_probability:
                    continue
                content = self._pool.draw(
                    PoolRequest(
                        section="功法",
                        count=1,
                        mode=ALLOW_REPEATS,
                        full_pool=True,
                        seed=source.getrandbits(64),
                    )
                ).entity_ids[0]
                grade = self._asset.draw_drop_grade(seed=source.getrandbits(64))
                result.append(
                    {"轮次": round_number, "编号": content, "品级": grade.grade_id}
                )
        return result

    def _round_experience(self, level: int) -> int:
        return self._experience_base + level * self._experience_per_level

    def _completed_rounds(self, started_at: datetime, current: datetime) -> int:
        elapsed = max(0, int((current - started_at).total_seconds()))
        return min(
            self.status().maximum_rounds, elapsed // self.status().seconds_per_round
        )

    async def _start_replay(self, owner: str, request_id: str) -> RetreatStarted | None:
        latest = await self._database.get(StateAddress(owner, LATEST_STATE, LATEST_KEY))
        if latest is None:
            return None
        value = _mapping(latest.value, "最近闭关")
        if _text(value.get("发起者"), "最近闭关.发起者") != owner:
            return None
        session_id = _text(value.get("闭关编号"), "最近闭关.闭关编号")
        session = await self._database.get(
            StateAddress(owner, SESSION_STATE, session_id)
        )
        if session is None or session.value.get("开始请求") != request_id:
            return None
        raw = session.value
        return RetreatStarted(
            session_id,
            _text(raw.get("地点"), "闭关.地点"),
            len(_texts(raw.get("参与用户"), "闭关.参与用户")),
            _positive_int(raw.get("正式角色数"), "闭关.正式角色数"),
            _positive_int(raw.get("最多轮数"), "闭关.最多轮数"),
            _parse_time(raw.get("开始时间"), "闭关.开始时间"),
            _parse_time(raw.get("最晚出关时间"), "闭关.最晚出关时间"),
            True,
        )

    async def _session_for(self, user_id: str) -> tuple[str, str, Mapping[str, object]]:
        latest = await self._database.get(
            StateAddress(_user_id(user_id), LATEST_STATE, LATEST_KEY)
        )
        if latest is None:
            raise RetreatStateError("当前没有可查看的闭关")
        value = _mapping(latest.value, "最近闭关")
        owner = _text(value.get("发起者"), "最近闭关.发起者")
        session_id = _text(value.get("闭关编号"), "最近闭关.闭关编号")
        session = await self._database.get(
            StateAddress(owner, SESSION_STATE, session_id)
        )
        if session is None:
            raise RetreatStateError("闭关会话不存在")
        return owner, session_id, session.value

    def _settlement(
        self,
        session_id: str,
        value: Mapping[str, object],
        *,
        replayed: bool,
    ) -> RetreatSettlement:
        users = tuple(
            _user_summary(_mapping(raw, "闭关结算.用户结果[]"))
            for raw in _sequence(value.get("用户结果"), "闭关结算.用户结果")
        )
        return RetreatSettlement(
            session_id,
            _text(value.get("地点"), "闭关结算.地点"),
            _nonnegative_int(value.get("完成轮数"), "闭关结算.完成轮数"),
            _positive_int(value.get("最多轮数"), "闭关结算.最多轮数"),
            len(_texts(value.get("参与用户"), "闭关结算.参与用户")),
            users,
            _parse_time(value.get("出关时间"), "闭关结算.出关时间"),
            replayed,
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("闭关核心尚未初始化")


def _user_summary(value: Mapping[str, object]) -> RetreatUserSummary:
    characters = tuple(
        RetreatCharacterSummary(
            _text(row.get("名称"), "闭关结算.角色.名称"),
            _boolean(row.get("道侣"), "闭关结算.角色.道侣"),
            _nonnegative_int(row.get("经验"), "闭关结算.角色.经验"),
            _positive_int(row.get("原等级"), "闭关结算.角色.原等级"),
            _positive_int(row.get("现等级"), "闭关结算.角色.现等级"),
            float(_number(row.get("血气"), "闭关结算.角色.血气")),
            float(_number(row.get("精神"), "闭关结算.角色.精神")),
            tuple(
                (
                    _text(change.get("名称"), "闭关结算.角色.疗伤.名称"),
                    _positive_int(change.get("原层数"), "闭关结算.角色.疗伤.原层数"),
                    _nonnegative_int(change.get("现层数"), "闭关结算.角色.疗伤.现层数"),
                )
                for change in (
                    _mapping(item, "闭关结算.角色.疗伤[]")
                    for item in _sequence(
                        row.get("疗伤", ()), "闭关结算.角色.疗伤", allow_empty=True
                    )
                )
            ),
            tuple(
                (
                    _text(injury.get("名称"), "闭关结算.角色.剩余伤势.名称"),
                    _positive_int(injury.get("层数"), "闭关结算.角色.剩余伤势.层数"),
                )
                for injury in (
                    _mapping(item, "闭关结算.角色.剩余伤势[]")
                    for item in _sequence(
                        row.get("剩余伤势", ()),
                        "闭关结算.角色.剩余伤势",
                        allow_empty=True,
                    )
                )
            ),
        )
        for row in (
            _mapping(raw, "闭关结算.角色[]")
            for raw in _sequence(value.get("角色"), "闭关结算.角色")
        )
    )
    insights = tuple(
        RetreatInsight(
            _positive_int(row.get("轮次"), "闭关结算.功法感悟.轮次"),
            _text(row.get("编号"), "闭关结算.功法感悟.编号"),
            _text(row.get("品级"), "闭关结算.功法感悟.品级"),
            _insight_outcome(row.get("结果")),
        )
        for row in (
            _mapping(raw, "闭关结算.功法感悟[]")
            for raw in _sequence(
                value.get("功法感悟"), "闭关结算.功法感悟", allow_empty=True
            )
        )
    )
    return RetreatUserSummary(
        _text(value.get("用户"), "闭关结算.用户"),
        _text(value.get("人物"), "闭关结算.人物"),
        characters,
        insights,
        _payload_activation(value.get("先天灵宝")),
    )


def _insights(value: object, completed_rounds: int) -> tuple[RetreatInsight, ...]:
    return tuple(
        RetreatInsight(
            _positive_int(row.get("轮次"), "功法感悟.轮次"),
            _text(row.get("编号"), "功法感悟.编号"),
            _text(row.get("品级"), "功法感悟.品级"),
        )
        for row in (
            _mapping(raw, "功法感悟[]")
            for raw in _sequence(value, "功法感悟", allow_empty=True)
        )
        if _positive_int(row.get("轮次"), "功法感悟.轮次") <= completed_rounds
    )


def _injury_changes(values) -> list[dict[str, object]]:
    return [
        {
            "编号": value.injury_id,
            "名称": value.name,
            "原层数": value.before_stacks,
            "现层数": value.after_stacks,
        }
        for value in values
    ]


def _activation_payload(
    activation: InnateTreasureActivation | None,
) -> dict[str, str] | None:
    if activation is None:
        return None
    return {
        "编号": activation.treasure_id,
        "名称": activation.name,
        "权柄": activation.authority,
        "结果": activation.summary,
    }


def _payload_activation(value: object) -> InnateTreasureActivation | None:
    if value is None:
        return None
    raw = _mapping(value, "闭关结算.先天灵宝")
    return InnateTreasureActivation(
        _text(raw.get("编号"), "闭关结算.先天灵宝.编号"),
        _text(raw.get("名称"), "闭关结算.先天灵宝.名称"),
        _text(raw.get("权柄"), "闭关结算.先天灵宝.权柄"),
        _text(raw.get("结果"), "闭关结算.先天灵宝.结果"),
    )


def _insight_outcome(value: object) -> str:
    outcome = _text(value, "闭关结算.功法感悟.结果")
    if outcome not in {"新得", "升品", "复悟"}:
        raise RetreatStateError(f"未知功法感悟结果：{outcome}")
    return outcome


def _participants(owner: str, values: tuple[str, ...], maximum: int) -> tuple[str, ...]:
    normalized = tuple(_user_id(value) for value in values) or (owner,)
    if normalized[0] != owner:
        raise ValueError("发起者必须位于参与用户首位")
    if len(normalized) != len(set(normalized)):
        raise ValueError("参与用户不能重复")
    if len(normalized) > maximum:
        raise ValueError(f"一次闭关最多{maximum}名用户")
    return normalized


def _stable_seed(owner: str, request_id: str) -> int:
    return int.from_bytes(
        hashlib.sha256(f"{owner}\0{request_id}".encode()).digest()[:8]
    )


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("闭关时间必须包含时区")
    return current.astimezone(timezone.utc)


def _parse_time(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, label))
    except ValueError as exc:
        raise RetreatStateError(f"{label}不是合法时间") from exc
    if parsed.tzinfo is None:
        raise RetreatStateError(f"{label}必须包含时区")
    return parsed.astimezone(timezone.utc)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    return mapping(value, label, error=RetreatStateError)


def _sequence(
    value: object, label: str, *, allow_empty: bool = False
) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise RetreatStateError(f"{label}必须是数组")
    if not allow_empty and not value:
        raise RetreatStateError(f"{label}不能为空")
    return value


def _texts(value: object, label: str) -> tuple[str, ...]:
    return tuple(_text(raw, f"{label}[]") for raw in _sequence(value, label))


def _text(value: object, label: str) -> str:
    return nonempty_text(value, label, error=RetreatStateError)


def _user_id(value: object) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError("user_id不能为空")
    return result


def _positive_int(value: object, label: str) -> int:
    return positive_int(value, label, error=RetreatStateError)


def _nonnegative_int(value: object, label: str) -> int:
    return nonnegative_int(value, label, error=RetreatStateError)


def _number(value: object, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RetreatStateError(f"{label}必须是数值")
    return value


def _ratio(value: object, label: str) -> float:
    number = _number(value, label)
    if not 0 <= number <= 1:
        raise JsonDataError(f"{label}必须在0至1之间")
    return float(number)


def _boolean(value: object, label: str) -> bool:
    return boolean(value, label, error=RetreatStateError)


__all__ = ["RetreatService"]
