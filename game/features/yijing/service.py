"""意境：看路、选路、用道行升阶。"""

from __future__ import annotations

from game.core.character import CharacterCultivationError, CharacterService

from game.core.data import JsonDataService
from game.core.database import DatabaseService, TransactionCommand

from .contracts import YijingConflictError, YijingError, YijingView


class YijingFeature:
    """意境微服务：只做薄薄一层——取视图、调人物核心的计划、落一笔事务。"""

    def __init__(
        self, data: JsonDataService, character: CharacterService, database: DatabaseService
    ) -> None:
        self._data = data
        self._character = character
        self._database = database

    def initialize(self) -> None:
        """启动期不需要额外配置；留一个口子与其它玩法特性同形。"""

    def _routes(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (content_id, str(entity.get("名称") or ""))
            for content_id, entity in sorted(self._data.entities("意境").items())
        )

    async def inspect(self, user_id: str) -> YijingView:
        """看：路、阶、道行，以及距下一阶还差多少道行。"""

        profile = await self._character.profile(user_id)
        cap = self._character.yijing_cap(profile.realm_id)
        yijing = profile.yijing
        content_id = yijing.content_id if yijing else ""
        name = yijing.name if yijing else ""
        display = yijing.display if yijing else ""
        tier = yijing.tier if yijing else 0
        points = yijing.daoxing if yijing else await self._pending_points(user_id)
        next_cost = self._character.yijing_cost(tier + 1) if tier < 9 else 0
        missing = max(0, next_cost - points) if next_cost else 0
        return YijingView(content_id, name, display, tier, points, cap, next_cost, missing, self._routes())

    async def choose(self, user_id: str, request_id: str, content_id: str) -> YijingView:
        """选修一条意境的路：编号必须在册；改路把已练的阶清零。

        幂等排在最前：同一条请求编号重放时**不再算计划**（状态已经改过，再算会得到另一份计划，
        甚至撞上境界上限直接报错），直接回看改完之后的现状。
        """

        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "意境选路":
                raise YijingConflictError("请求编号已经用于其他操作")
            return await self.inspect(user_id)
        try:
            plan = await self._character.plan_yijing_choose(user_id, content_id=content_id)
        except CharacterCultivationError as exc:
            raise YijingError(str(exc)) from exc
        await self._commit(user_id, request_id, "意境选路", plan.mutation, plan.content_id)
        return await self.inspect(user_id)

    async def upgrade(self, user_id: str, request_id: str) -> YijingView:
        """花道行升一阶；升到一阶就是激活。受境界给的阶上限约束。

        与选路同理：幂等排在最前，重放直接回看现状，不重算计划。
        """

        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "意境升阶":
                raise YijingConflictError("请求编号已经用于其他操作")
            return await self.inspect(user_id)
        try:
            plan = await self._character.plan_yijing_upgrade(user_id)
        except CharacterCultivationError as exc:
            raise YijingError(str(exc)) from exc
        await self._commit(user_id, request_id, "意境升阶", plan.mutation, plan.content_id)
        return await self.inspect(user_id)

    async def _pending_points(self, user_id: str) -> int:
        """还没选路时人物档案里是 None——道行**向人物核心要**（状态格的解释权在它），
        这样玩家在选路前攒的点也看得见，玩法层不自己解 `character/main`。"""

        return await self._character.yijing_points(user_id)

    async def _commit(self, user_id, request_id, business_type, mutation, content_id) -> None:
        await self._database.commit(
            TransactionCommand(
                user_id=user_id,
                request_id=request_id,
                business_type=business_type,
                operations=(mutation,),
                payload={"意境": content_id},
            )
        )


__all__ = ["YijingFeature"]
