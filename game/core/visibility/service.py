"""网页可见性：一条全局开关，管住所有「网页直接读你的数据」的页面。

状态放在共享实体 `web_public`：网页要能枚举「谁开了」，而玩家状态枚举不出来。
玩法层只负责命令与展示，开关事实由核心解释。
"""

from __future__ import annotations

from game.core.character import CharacterNotFoundError, CharacterService
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    SharedEntityMutation,
    StateConflictError,
    TransactionCommand,
)

from .contracts import VisibilityConflictError, VisibilityError, VisibilityScope

#: 开关的索引：一人一行。
ENTITY = "web_public"
BUSINESS = "网页资源公开"


class VisibilityService:
    def __init__(self, database: DatabaseService, character: CharacterService) -> None:
        self._database = database
        self._character = character
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("网页可见性核心已经初始化")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于网页可见性核心启动")
        if not self._character.status().initialized:
            raise RuntimeError("角色核心必须先于网页可见性核心启动")
        self._initialized = True

    def status(self) -> bool:
        return self._initialized

    async def is_public(self, user_id: str) -> bool:
        self._require_initialized()
        record = await self._database.get_shared_entity(ENTITY, user_id)
        return bool(record is not None and dict(record.value).get("公开"))

    async def scopes(self) -> list[VisibilityScope]:
        """已公开的人；没人开就是空清单。"""

        self._require_initialized()
        records = await self._database.list_shared_entities(ENTITY)
        ids = tuple(record.entity_id for record in records if dict(record.value).get("公开"))
        if not ids:
            return []
        profiles = await self._character.public_profiles(ids)
        return [VisibilityScope(profile.user_id, profile.name) for profile in profiles]

    async def set_public(self, user_id: str, request_id: str, enabled: bool) -> bool:
        """开或关；两个命令各管一头，所以收的是明确目标状态。"""

        self._require_initialized()
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != BUSINESS:
                raise VisibilityConflictError("请求编号已经用于其他操作")
            return bool(committed.payload.get("公开"))
        try:
            await self._character.profile(user_id)
        except CharacterNotFoundError as exc:
            raise VisibilityError("尚未创建人物") from exc
        record = await self._database.get_shared_entity(ENTITY, user_id)
        current = bool(record is not None and dict(record.value).get("公开"))
        if current == enabled:
            return enabled
        command = TransactionCommand(
            user_id,
            request_id,
            BUSINESS,
            (
                SharedEntityMutation(
                    ENTITY,
                    user_id,
                    {"名称": user_id, "公开": enabled},
                    0 if record is None else record.version,
                ),
            ),
            {"公开": enabled},
        )
        try:
            await self._database.commit(command)
        except (StateConflictError, IdempotencyConflictError) as exc:
            replay = await self._database.committed_transaction(user_id, request_id)
            if replay is not None:
                return bool(replay.payload.get("公开"))
            raise VisibilityError("开关状态已经变化，请重试") from exc
        return enabled

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("网页可见性核心尚未初始化")


__all__ = ["VisibilityService"]
