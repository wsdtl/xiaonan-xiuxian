"""意境：看六条路各自的阶、给某一条路点阶；到坐忘台服忘境丹可以把六路退回重排。"""

from __future__ import annotations

from collections.abc import Mapping

from game.core.asset import AssetService, InventoryAdjustment, InventoryChangeError
from game.core.character import CharacterCultivationError, CharacterService
from game.core.data import JsonDataError, JsonDataService, nonempty_text as _text
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateConflictError,
    TransactionCommand,
)
from game.core.location import LocationService
from game.core.player_state import PlayerStateService
from game.core.world import LocationQuery, WorldService

from .contracts import (
    YijingConflictError,
    YijingError,
    YijingRefundResult,
    YijingRoute,
    YijingView,
)

#: 意境页面要用的文案键：**逐个点名**（页面缺一条就在这儿报错，判据也要求每个键都有消费者）。
PAGE_KEYS = (
    "标题",
    "说明",
    "挑人",
    "命令",
    "没人公开",
    "道行",
    "阶上限",
    "下一阶",
    "未点",
    "已满",
    "到上限",
    "点这一路",
    "还差",
    "退点",
    "退点命令",
    "复制退点",
)

#: 坐忘台的功能名（写死在代码里，多一个少一个声明都在启动期报错）。
FUNCTION = "坐忘"
#: 退点的业务类型：收据按它区分「这一笔是坐忘」。
BUSINESS = "意境退点"


class YijingFeature:
    """意境微服务：取视图、调人物核心的计划、落一笔事务。

    六条路各自记阶，**道行只有一份**（总额一百一十二，刚好点满一条），所以取舍在怎么分；
    想重排就得到坐忘台服一枚忘境丹——扣丹与退点写在**同一笔事务**里。
    """

    def __init__(
        self,
        data: JsonDataService,
        character: CharacterService,
        asset: AssetService,
        player_state: PlayerStateService,
        location: LocationService,
        world: WorldService,
        database: DatabaseService,
    ) -> None:
        self._data = data
        self._character = character
        self._asset = asset
        self._player_state = player_state
        self._location = location
        self._world = world
        self._database = database
        self._copy: Mapping[str, object] | None = None
        self._page: Mapping[str, object] | None = None
        self._medicine_id = ""
        self._medicine_name = ""
        self._guard_rule = ""

    def initialize(self) -> None:
        """坐忘的丹药与状态守卫都从地点功能配置读，代码里不硬编码编号。"""

        if self._copy is not None:
            raise RuntimeError("意境玩法已经初始化")
        rule = self._world.feature_config(FUNCTION)
        self._medicine_id = _text(rule.get("丹药"), "坐忘.丹药")
        self._guard_rule = _text(rule.get("状态守卫"), "坐忘.状态守卫")
        self._medicine_name = str(
            self._data.entity("丹药", self._medicine_id).get("名称") or "忘境丹"
        )
        copy = self._data.dataset("坐忘展示").get("文本")
        if not isinstance(copy, Mapping):
            raise JsonDataError("坐忘展示缺少文本.json")
        self._copy = copy
        page = self._data.dataset("意境展示").get("文本")
        if not isinstance(page, Mapping):
            raise JsonDataError("意境展示缺少文本.json")
        section = page.get("页面")
        if not isinstance(section, Mapping):
            raise JsonDataError("意境展示缺少页面文案")
        self._page = section

    def copy(self, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
        """展示文案一律走数据（`data/玩法/坐忘/展示/文本.json`），代码里不写死。"""

        if self._copy is None:
            raise RuntimeError("意境玩法尚未初始化")
        group = self._copy.get(section)
        value = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(value, str):
            raise JsonDataError(f"坐忘展示缺少文本：{section}.{key}")
        return value.format_map(values or {})

    async def page(self, user_id: str) -> dict:
        """**意境页面的数据口**：六路全表＋阶价阶梯＋道行余额＋当前境界的阶上限；文案从展示数据集取。

        六路那一份直接复用意境的视图（单源）——页面与命令看到的永远是同一套数。
        """

        if self._page is None:
            raise RuntimeError("意境玩法尚未初始化")
        view = await self.inspect(user_id)
        return {
            "ui": {
                key: _text(self._page.get(key), f"意境展示.页面.{key}")
                for key in PAGE_KEYS
            },
            "points": view.points,
            "cap": view.cap,
            "costs": [self._character.yijing_cost(tier) for tier in range(1, 10)],
            "routes": [
                {
                    "id": route.content_id,
                    "name": route.name,
                    "tier": route.tier,
                    "display": route.display,
                    "next_cost": route.next_cost,
                    "missing": route.missing,
                }
                for route in view.routes
            ],
        }

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

    async def refund(self, user_id: str, request_id: str) -> YijingRefundResult:
        """坐忘：在坐忘台服一枚忘境丹，六路练过的阶全部抹去、道行退回已发总额。

        与点阶同理，幂等排在最前；**扣丹与退点在同一笔事务里**，要么都成、要么都不动。
        """

        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != BUSINESS:
                raise YijingConflictError("请求编号已经用于其他操作")
            return _refund_result(committed.payload, True)
        await self._authorize(user_id)
        try:
            current = await self._location.current(user_id)
            place = self._world.locate(LocationQuery(xy=current.xy))
            if FUNCTION not in place.available_functions:
                raise YijingError(f"只有身在坐忘台才能{self.copy('结算', '动作')}")
            profile = await self._character.profile(user_id)
            plan = await self._character.plan_yijing_refund(user_id)
            stacks = await self._asset.inventory_stacks(user_id, self._medicine_id)
            if not stacks:
                raise YijingError(f"纳戒中没有{self._medicine_name}")
            stack = min(stacks, key=lambda value: value.grade.order)
            inventory = await self._asset.plan_inventory_changes(
                user_id,
                (InventoryAdjustment(self._medicine_id, stack.grade.grade_id, -1),),
            )
            payload = {
                "人物名称": profile.name,
                "丹药名称": self._medicine_name,
                "退点前": self._tiers_text(plan.tiers_before),
                "原有道行": plan.points_before,
                "退回道行": plan.points_after,
            }
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id,
                    request_id,
                    BUSINESS,
                    inventory.operations + (plan.mutation,),
                    payload,
                )
            )
        except (InventoryChangeError, CharacterCultivationError, StateConflictError) as exc:
            raise YijingError(str(exc)) from exc
        except IdempotencyConflictError as exc:
            raise YijingConflictError("请求编号已经用于其他操作") from exc
        return _refund_result(payload, receipt.replayed)

    def _tiers_text(self, rows: tuple[tuple[str, int], ...]) -> str:
        """退点前的那一行：名称＋中文阶，按编号排序（名称从数据现取）。"""

        names = dict(self._routes())
        return "、".join(
            f"{names.get(content_id, content_id)}{tier} 阶" for content_id, tier in rows
        )

    async def _authorize(self, user_id: str) -> None:
        result = await self._player_state.authorize(user_id, self._guard_rule)
        if not result.allowed:
            raise YijingError(result.reason)

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


def _refund_result(value: Mapping[str, object], replayed: bool) -> YijingRefundResult:
    return YijingRefundResult(
        str(value.get("人物名称") or ""),
        str(value.get("丹药名称") or ""),
        str(value.get("退点前") or ""),
        int(value.get("原有道行") or 0),
        int(value.get("退回道行") or 0),
        replayed,
    )


__all__ = ["YijingFeature"]
