"""道侣查看、交谈、赠礼、邀约与暂别的事务编排。"""

from __future__ import annotations

from game.core.companion import (
    CompanionDefinition,
    CompanionFarewellError,
    CompanionGiftError,
    CompanionInvitationError,
    CompanionNotFoundError,
    CompanionService,
    CompanionStateError,
)
from game.core.item_catalog import (
    ItemDetail,
    ItemCatalogService,
    ItemNameAmbiguousError,
    ItemNotFoundError,
)

from game.core.asset import AssetGrade, AssetService, InventoryAdjustment, InventoryChangeError

import random
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from game.core.character import CharacterService
from game.core.data import JsonDataService
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateConflictError,
    TransactionCommand,
)
from game.core.innate_treasure import (
    InnateTreasureActivation,
    InnateTreasureService,
)
from game.core.location import LocationService
from game.core.world import LocationQuery, WorldService

from .contracts import (
    CompanionAccessError,
    CompanionAction,
    CompanionConflictError,
    CompanionConversation,
    CompanionCopy,
    CompanionFarewellRequest,
    CompanionFarewellResult,
    CompanionGiftRequest,
    CompanionGiftResult,
    CompanionInvitationRequest,
    CompanionInvitationResult,
    CompanionQueryError,
    CompanionView,
)
from .presentation import (
    CompanionButton,
    load_companion_presentation,
    render_action,
)

_AFFECTION_QUANTUM = Decimal("0.1")


class CompanionInteractionFeature:
    """组合核心服务完成道侣结交，不持有第二份关系状态。"""

    def __init__(
        self,
        data: JsonDataService,
        companion: CompanionService,
        item_catalog: ItemCatalogService,
        asset: AssetService,
        character: CharacterService,
        location: LocationService,
        world: WorldService,
        database: DatabaseService,
        innate_treasure: InnateTreasureService,
    ) -> None:
        self._data = data
        self._companion = companion
        self._item_catalog = item_catalog
        self._asset = asset
        self._character = character
        self._location = location
        self._world = world
        self._database = database
        self._innate_treasure = innate_treasure
        self._initialized = False
        self._copy: CompanionCopy | None = None
        self._buttons: tuple[CompanionButton, ...] = ()
        self._random = random.SystemRandom()

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("道侣结交玩法微服务已经初始化")
        for status, label in (
            (self._companion.status().initialized, "道侣核心"),
            (self._item_catalog.status().initialized, "物品查询核心"),
            (self._asset.status().initialized, "资产核心"),
            (self._character.status().initialized, "角色核心"),
            (self._location.status().initialized, "位置核心"),
            (self._world.status().initialized, "世界核心"),
            (self._database.status().initialized, "数据库核心"),
            (self._innate_treasure.status().initialized, "先天灵宝核心"),
        ):
            if not status:
                raise RuntimeError(f"{label}必须先于道侣结交玩法启动")
        self._copy, self._buttons = load_companion_presentation(
            self._data.dataset("道侣展示")
        )
        self._initialized = True

    def copy(self) -> CompanionCopy:
        self._require_initialized()
        if self._copy is None:
            raise RuntimeError("道侣展示契约尚未完成初始化")
        return self._copy

    async def inspect(self, user_id: str, companion: str) -> CompanionView:
        self._require_initialized()
        definition = self._resolve_companion(companion)
        return await self._view(
            user_id, definition.companion_id, require_interactable=False
        )

    async def converse(self, user_id: str, companion: str) -> CompanionConversation:
        self._require_initialized()
        definition = self._resolve_companion(companion)
        view = await self._view(
            user_id, definition.companion_id, require_interactable=True
        )
        return CompanionConversation(view, self._choice(definition.dialogue.daily))

    async def gift(self, request: CompanionGiftRequest) -> CompanionGiftResult:
        self._require_initialized()
        definition = self._resolve_companion(request.companion)
        view = await self._view(
            request.user_id,
            definition.companion_id,
            require_interactable=True,
        )
        item = self._resolve_item(request.item)
        preference = (
            self._companion.gift_preference(definition.companion_id, item.item_id)
            if item.category == "灵植"
            else "拒绝"
        )
        if preference == "拒绝":
            return CompanionGiftResult(
                view,
                item,
                None,
                request.quantity,
                Decimal(0),
                False,
                "拒绝",
                Decimal(0),
                self._choice(definition.dialogue.refuse_gift),
                Decimal(0),
                view.relation.current_affection,
                view.relation.current_affection,
                None,
                None,
                0,
                False,
                False,
            )
        if isinstance(request.quantity, bool) or request.quantity < 1:
            raise CompanionQueryError("赠礼数量必须是正整数")
        grade = await self._gift_grade(
            request.user_id,
            item.item_id,
            request.grade,
        )
        preference_multiplier = (
            self._companion.rules().favorite_gift_multiplier
            if preference == "偏爱"
            else self._companion.rules().acceptable_gift_multiplier
        )
        affection_gain = (
            self._companion.rules().base_affection_per_item
            * preference_multiplier
            * grade.ability_multiplier
            * request.quantity
        ).quantize(_AFFECTION_QUANTUM, rounding=ROUND_HALF_UP)
        activation: InnateTreasureActivation | None = None
        if preference == "偏爱":
            treasure_effect = await self._innate_treasure.effect(
                request.user_id, "道侣赠礼"
            )
            if treasure_effect is not None:
                treasure, effect = treasure_effect
                if effect.ability == "提高偏爱好感":
                    ratio = Decimal(str(effect.values["比例"]))
                    before_treasure = affection_gain
                    affection_gain = (affection_gain * (Decimal(1) + ratio)).quantize(
                        _AFFECTION_QUANTUM, rounding=ROUND_HALF_UP
                    )
                    activation = InnateTreasureActivation(
                        treasure.treasure_id,
                        treasure.name,
                        treasure.authority,
                        f"偏爱好感 {before_treasure} → {affection_gain}",
                    )
        base_affection = (
            self._companion.rules().base_affection_per_item * request.quantity
        )
        occurred_at = _now()
        try:
            relation_plan = await self._companion.plan_gift(
                request.user_id,
                definition.companion_id,
                item_id=item.item_id,
                grade_id=grade.grade_id,
                quantity=request.quantity,
                affection_gain=affection_gain,
                occurred_at=occurred_at,
            )
        except (CompanionGiftError, CompanionStateError) as exc:
            raise CompanionQueryError(str(exc)) from exc
        adjustments = [
            InventoryAdjustment(item.item_id, grade.grade_id, -request.quantity)
        ]
        reward_item = None
        reward_grade = None
        reward_quantity = 0
        if relation_plan.first_full:
            reward = definition.reward
            reward_item = self._item_catalog.get(reward.item_id)
            reward_grade = self._asset.grade(reward.grade_id)
            reward_quantity = reward.quantity
            adjustments.append(
                InventoryAdjustment(
                    reward.item_id,
                    reward.grade_id,
                    reward.quantity,
                )
            )
        try:
            inventory_plan = await self._asset.plan_inventory_changes(
                request.user_id,
                adjustments,
            )
            receipt = await self._database.commit(
                TransactionCommand(
                    request.user_id,
                    request.request_id,
                    "道侣赠礼",
                    inventory_plan.operations + (relation_plan.operation,),
                    {
                        "道侣编号": definition.companion_id,
                        "物品编号": item.item_id,
                        "品级": grade.grade_id,
                        "数量": request.quantity,
                        "好感": float(affection_gain),
                    },
                )
            )
        except InventoryChangeError as exc:
            raise CompanionQueryError(str(exc)) from exc
        except StateConflictError as exc:
            raise CompanionConflictError(str(exc)) from exc
        except IdempotencyConflictError:
            current = await self._view(
                request.user_id,
                definition.companion_id,
                require_interactable=False,
            )
            return CompanionGiftResult(
                current,
                item,
                grade,
                request.quantity,
                base_affection,
                True,
                preference,
                preference_multiplier,
                self._gift_dialogue(definition, preference),
                affection_gain,
                current.relation.current_affection,
                current.relation.current_affection,
                None,
                None,
                0,
                False,
                True,
                activation,
            )
        current = await self._view(
            request.user_id,
            definition.companion_id,
            require_interactable=False,
        )
        return CompanionGiftResult(
            current,
            item,
            grade,
            request.quantity,
            base_affection,
            True,
            preference,
            preference_multiplier,
            self._gift_dialogue(definition, preference),
            affection_gain,
            relation_plan.relation_before.current_affection,
            relation_plan.relation_after.current_affection,
            reward_item,
            reward_grade,
            reward_quantity,
            relation_plan.first_full,
            receipt.replayed,
            activation,
        )

    def _gift_dialogue(self, definition: CompanionDefinition, preference: str) -> str:
        if preference == "偏爱":
            return self._choice(definition.dialogue.accept_gift)
        return self.copy().text["赠礼"]["合意话语"].format_map(
            {"名称": definition.name}
        )

    async def invite(
        self, request: CompanionInvitationRequest
    ) -> CompanionInvitationResult:
        self._require_initialized()
        definition = self._resolve_companion(request.companion)
        await self._ensure_accessible(request.user_id, definition.companion_id)
        if not definition.interactable:
            raise CompanionAccessError(f"{definition.name}当前不可交互")
        profile = await self._character.profile(request.user_id)
        try:
            plan = await self._companion.plan_invitation(
                request.user_id,
                definition.companion_id,
                player_gender=profile.gender,
                occurred_at=_now(),
            )
        except (CompanionInvitationError, CompanionStateError) as exc:
            raise CompanionQueryError(str(exc)) from exc
        if plan.already_active:
            view = await self._view(
                request.user_id,
                definition.companion_id,
                require_interactable=False,
            )
            return CompanionInvitationResult(
                view,
                plan.instance,
                definition.dialogue.invitation,
                False,
                True,
                True,
            )
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    request.user_id,
                    request.request_id,
                    "邀约道侣",
                    plan.operations,
                    {"道侣编号": definition.companion_id},
                )
            )
        except StateConflictError as exc:
            raise CompanionConflictError(str(exc)) from exc
        view = await self._view(
            request.user_id,
            definition.companion_id,
            require_interactable=False,
        )
        return CompanionInvitationResult(
            view,
            plan.instance,
            definition.dialogue.invitation,
            plan.first_invitation,
            False,
            receipt.replayed,
        )

    async def farewell(
        self, request: CompanionFarewellRequest
    ) -> CompanionFarewellResult:
        self._require_initialized()
        definition = self._resolve_companion(request.companion)
        try:
            plan = await self._companion.plan_farewell(
                request.user_id,
                definition.companion_id,
            )
            receipt = await self._database.commit(
                TransactionCommand(
                    request.user_id,
                    request.request_id,
                    "暂别道侣",
                    (plan.operation,),
                    {"道侣编号": definition.companion_id},
                )
            )
        except CompanionFarewellError as exc:
            raise CompanionQueryError(str(exc)) from exc
        except StateConflictError as exc:
            raise CompanionConflictError(str(exc)) from exc
        return CompanionFarewellResult(
            definition,
            definition.dialogue.farewell,
            receipt.replayed,
        )

    def actions(self, page: str, view: CompanionView) -> tuple[CompanionAction, ...]:
        self._require_initialized()
        result: list[CompanionAction] = []
        active_here = (
            view.active is not None
            and view.active.companion_id == view.definition.companion_id
        )
        for button in self._buttons:
            if button.page != page:
                continue
            if button.condition == "可邀约" and not view.can_invite:
                continue
            if button.condition == "同行中" and not active_here:
                continue
            result.append(render_action(button, view.definition.companion_id))
        return tuple(result)

    def farewell_actions(self, companion_id: str) -> tuple[CompanionAction, ...]:
        self._require_initialized()
        definition = self._companion.definition(companion_id)
        return tuple(
            render_action(button, definition.companion_id)
            for button in self._buttons
            if button.page == "暂别" and not button.condition
        )

    async def _view(
        self,
        user_id: str,
        companion_id: str,
        *,
        require_interactable: bool,
    ) -> CompanionView:
        definition = self._companion.definition(companion_id)
        await self._ensure_accessible(user_id, definition.companion_id)
        if require_interactable and not definition.interactable:
            raise CompanionAccessError(f"{definition.name}当前不可交互")
        relation = await self._companion.relation(user_id, definition.companion_id)
        active = await self._companion.active(user_id)
        profile = await self._character.profile(user_id)
        first_gender_allowed = (
            bool(relation.first_invited_at) or profile.gender != definition.gender
        )
        can_invite = (
            definition.interactable
            and relation.current_affection
            >= self._companion.rules().invitation_affection
            and active is None
            and first_gender_allowed
        )
        is_active = (
            active is not None and active.companion_id == definition.companion_id
        )
        return CompanionView(
            definition,
            relation,
            active,
            relation.version > 0,
            is_active,
            can_invite,
        )

    async def _ensure_accessible(self, user_id: str, companion_id: str) -> None:
        definition = self._companion.definition(companion_id)
        active = await self._companion.active(user_id)
        if active is not None and active.companion_id == companion_id:
            return
        current = await self._location.current(user_id)
        location = self._world.locate(LocationQuery(xy=current.xy))
        if location.location_name != definition.location_name:
            raise CompanionAccessError(
                f"{definition.name}如今不在此处；可前往{definition.location_name}寻访"
            )

    async def _gift_grade(self, user_id: str, item_id: str, query: str) -> AssetGrade:
        if str(query or "").strip():
            try:
                return self._asset.grade(query)
            except InventoryChangeError as exc:
                raise CompanionQueryError(str(exc)) from exc
        stacks = await self._asset.inventory_stacks(user_id, item_id)
        if not stacks:
            raise CompanionQueryError("纳戒中没有这株灵植")
        if len(stacks) > 1:
            choices = "、".join(stack.grade.name for stack in stacks)
            raise CompanionQueryError(f"这株灵植有多个品级，请明确指定：{choices}")
        return stacks[0].grade

    def _resolve_companion(self, value: str) -> CompanionDefinition:
        try:
            return self._companion.definition(value)
        except CompanionNotFoundError as exc:
            raise CompanionQueryError(str(exc)) from exc

    def _resolve_item(self, value: str) -> ItemDetail:
        try:
            return self._item_catalog.inspect(value)
        except ItemNameAmbiguousError as exc:
            choices = "、".join(
                f"{item.name}({item.item_id})" for item in exc.candidates
            )
            raise CompanionQueryError(f"物品名称不唯一，请使用编号：{choices}") from exc
        except ItemNotFoundError as exc:
            raise CompanionQueryError(str(exc)) from exc

    def _choice(self, values: tuple[str, ...]) -> str:
        return self._random.choice(values)

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("道侣结交玩法微服务尚未初始化")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


__all__ = ["CompanionInteractionFeature"]
