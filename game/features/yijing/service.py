"""意境：看六条路各自的阶，用共享的道行给某一条路点阶。"""

from __future__ import annotations

from game.core.character import CharacterCultivationError, CharacterService

from game.core.data import JsonDataService
from game.core.database import DatabaseService, TransactionCommand

from .contracts import YijingConflictError, YijingError, YijingRoute, YijingView


class YijingFeature:
    """意境微服务：只做薄薄一层——取视图、调人物核心的计划、落一笔事务。

    六条路各自记阶，**道行只有一份**（总额一百一十二，刚好点满一条），所以取舍在怎么分。
    """

    def __init__(
        self, data: JsonDataService, character: CharacterService, database: DatabaseService
    ) -> None:
        self._data = data
        self._character = character
        self._database = database

    def initialize(self) -> None:
        """启动期不需要额外配置；留一个口子与其它玩法特性同形。"""

    def _routes(self) -> tuple[tuple[str, str], ...]:
        """六条路：编号与名称，按编号排序（展示顺序稳定）。"""

        return tuple(
            (content_id, str(entity.get("名称") or ""))
            for content_id, entity in sorted(self._data.entities("意境").items())
        )

    async def inspect(self, user_id: str) -> YijingView:
        """看：六条路各自的阶、共享的道行、当前境界给的阶上限。"""

        profile = await self._character.profile(user_id)
        cap = self._character.yijing_cap(profile.realm_id)
        points = await self._character.yijing_points(user_id)
        pointed = {item.content_id: item for item in profile.yijing}
        routes = tuple(
            self._route(content_id, name, pointed, cap, points)
            for content_id, name in self._routes()
        )
        return YijingView(points=points, cap=cap, routes=routes)

    def _route(self, content_id, name, pointed, cap, points) -> YijingRoute:
        """把「点没点过、点到几阶」拼成一行；没点过的按 0 阶算。"""

        item = pointed.get(content_id)
        tier = item.tier if item is not None else 0
        limit = min(9, cap)
        cost = self._character.yijing_cost(tier + 1) if tier < limit else 0
        return YijingRoute(
            content_id=content_id,
            name=name,
            tier=tier,
            display=item.display if item is not None else "",
            next_cost=cost,
            missing=max(0, cost - points) if cost else 0,
        )

    async def point(self, user_id: str, request_id: str, content_id: str) -> YijingView:
        """给**某一条路**点一阶：没点过的从 0 升到 1 就是激活，道行六路共享。

        幂等排在最前：同一条请求编号重放时**不再算计划**（状态已经改过，再算会得到另一份计划，
        甚至撞上境界上限直接报错），直接回看改完之后的现状。
        """

        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "意境点阶":
                raise YijingConflictError("请求编号已经用于其他操作")
            return await self.inspect(user_id)
        try:
            plan = await self._character.plan_yijing_point(user_id, content_id=content_id)
        except CharacterCultivationError as exc:
            raise YijingError(str(exc)) from exc
        await self._commit(user_id, request_id, "意境点阶", plan.mutation, plan.content_id)
        return await self.inspect(user_id)

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
