"""先天灵宝查看与单槽执掌事务。"""

from __future__ import annotations

from collections.abc import Mapping

from game.core.data import JsonDataError, JsonDataService
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateConflictError,
    TransactionCommand,
)
from game.core.innate_treasure import InnateTreasureError, InnateTreasureService
from game.features.presentation import require_mapping

from .contracts import (
    InnateTreasureEquipRequest,
    InnateTreasureEquipResult,
    InnateTreasureFeatureConflictError,
    InnateTreasureFeatureError,
    InnateTreasureView,
)


class InnateTreasureFeature:
    """只编排灵宝核心，不复制收藏和槽位状态。"""

    def __init__(
        self,
        data: JsonDataService,
        treasures: InnateTreasureService,
        database: DatabaseService,
    ) -> None:
        self._data = data
        self._treasures = treasures
        self._database = database
        self._initialized = False
        self._copy: Mapping[str, object] = {}
        self._page_limit = 0

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("先天灵宝玩法微服务已经初始化")
        if not self._treasures.status().initialized:
            raise RuntimeError("先天灵宝核心必须先于玩法微服务启动")
        if not self._database.status().initialized:
            raise RuntimeError("数据库核心必须先于先天灵宝玩法启动")
        self._copy = require_mapping(
            self._data.dataset("先天灵宝展示").get("文本"),
            "先天灵宝/展示/文本.json",
        )
        self._page_limit = self._treasures.status().page_limit
        self._initialized = True

    def copy(self, key: str, **values: object) -> str:
        self._require_initialized()
        text = self._copy.get(key)
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError(f"先天灵宝展示缺少文本：{key}")
        return text.format_map(values)

    async def inspect(self, user_id: str, page: int = 1) -> InnateTreasureView:
        self._require_initialized()
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise InnateTreasureFeatureError("页码必须是正整数")
        try:
            collection = await self._treasures.collection(user_id)
        except InnateTreasureError as exc:
            raise InnateTreasureFeatureError(str(exc)) from exc
        page_count = max(1, (len(collection.owned) + self._page_limit - 1) // self._page_limit)
        if page > page_count:
            raise InnateTreasureFeatureError(f"页码超出范围：1至{page_count}")
        start = (page - 1) * self._page_limit
        return InnateTreasureView(
            collection.active,
            collection.owned[start : start + self._page_limit],
            page,
            page_count,
            len(collection.owned),
        )

    async def equip(
        self, request: InnateTreasureEquipRequest
    ) -> InnateTreasureEquipResult:
        self._require_initialized()
        committed = await self._database.committed_transaction(
            request.user_id, request.request_id
        )
        if committed is not None:
            if committed.receipt.business_type != "执掌先天灵宝":
                raise InnateTreasureFeatureConflictError("请求编号已经用于其他操作")
            treasure = self._treasures.resolve(
                str(committed.payload.get("先天灵宝编号") or "")
            )
            return InnateTreasureEquipResult(treasure, True)
        try:
            plan = await self._treasures.plan_equip(request.user_id, request.treasure)
            if plan.operation is None:
                raise InnateTreasureFeatureError("先天灵宝槽没有发生变化")
            receipt = await self._database.commit(
                TransactionCommand(
                    request.user_id,
                    request.request_id,
                    "执掌先天灵宝",
                    (plan.operation,),
                    {"先天灵宝编号": plan.treasure.treasure_id},
                )
            )
        except StateConflictError as exc:
            raise InnateTreasureFeatureConflictError("灵宝谱已经变化，请重试") from exc
        except IdempotencyConflictError as exc:
            raise InnateTreasureFeatureConflictError("请求编号已经用于其他操作") from exc
        except InnateTreasureError as exc:
            raise InnateTreasureFeatureError(str(exc)) from exc
        return InnateTreasureEquipResult(plan.treasure, receipt.replayed)

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("先天灵宝玩法微服务尚未初始化")


__all__ = ["InnateTreasureFeature"]
