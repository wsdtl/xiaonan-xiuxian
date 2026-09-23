"""聚合本宗道藏并把借阅功法写入人物当前有效构筑。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from game.core.asset import AssetService
from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping,
    mapping as _json_mapping,
    nonempty_text as _rule_text,
    sequence,
)
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateAddress,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)
from game.core.growth import GrowthService
from game.core.sect import SectService

from .contracts import (
    SectBorrowResult,
    SectLibraryConflictError,
    SectLibraryError,
    SectLibraryStatus,
    SectLibraryView,
    SectTechnique,
)

#: 借阅失效条件：三条都要在规则里声明，且不得多写（规则与实现对得上才启动）。
INVALIDATION_CONDITIONS = ("退出宗门", "被逐出宗门", "宗门解散")


class SectLibraryService:
    """藏经阁只共享功法使用权，不改变个人道藏所有权。"""

    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        sect: SectService,
        asset: AssetService,
        growth: GrowthService,
    ) -> None:
        self._data = data
        self._database = database
        self._sect = sect
        self._asset = asset
        self._growth = growth
        self._initialized = False

    def initialize(self) -> SectLibraryStatus:
        if self._initialized:
            raise RuntimeError("藏经阁核心已经初始化")
        rule = _json_mapping(
            self._data.dataset("宗门规则").get("藏经阁"), "宗门/藏经阁.json"
        )
        source = _json_mapping(rule.get("来源"), "藏经阁.来源")
        borrow = _json_mapping(rule.get("借阅"), "藏经阁.借阅")
        if source.get("类别") != "功法" or source.get("同编号处理") != "取最高品级":
            raise JsonDataError("藏经阁必须按功法编号聚合本宗最高品级")
        if borrow.get("所有权") != "不转移":
            raise JsonDataError("藏经阁借阅的所有权必须不转移")
        if _失效条件(borrow.get("失效条件")) != INVALIDATION_CONDITIONS:
            raise JsonDataError(
                "藏经阁借阅的失效条件必须是退出宗门、被逐出宗门与宗门解散"
            )
        self._initialized = True
        return self.status()

    def status(self) -> SectLibraryStatus:
        return SectLibraryStatus(self._initialized)

    async def view(self, user_id: str) -> SectLibraryView:
        member = await self._member(user_id)
        return SectLibraryView(member.sect_id, await self._techniques(member.sect_id))

    async def borrow(
        self,
        user_id: str,
        request_id: str,
        identifier: str,
        slot: int,
    ) -> SectBorrowResult:
        member = await self._member(user_id)
        if isinstance(slot, bool) or not isinstance(slot, int) or slot < 1:
            raise SectLibraryError("功法槽位必须是正整数")
        technique = self._resolve(await self._techniques(member.sect_id), identifier)
        snapshot = await self._database.get(
            StateAddress(user_id, "cultivation", "main")
        )
        if snapshot is None:
            raise SectLibraryError("人物缺少修行构筑")
        cultivation = dict(_mapping(snapshot.value, "cultivation/main"))
        techniques = list(_slots(cultivation.get("功法"), "功法"))
        if slot > len(techniques):
            raise SectLibraryError(f"人物只有{len(techniques)}个功法槽")
        current = techniques[slot - 1]
        original = current
        if isinstance(current, Mapping):
            borrowed = current.get("藏经阁借阅")
            if isinstance(borrowed, Mapping):
                original = borrowed.get("原功法")
        techniques[slot - 1] = {
            "编号": technique.content_id,
            "品级": technique.grade_id,
            "藏经阁借阅": {
                "宗门编号": member.sect_id,
                "原功法": original,
            },
        }
        cultivation["功法"] = techniques
        build = {
            category: tuple(
                str(value["编号"])
                for raw in _slots(cultivation.get(category), category)
                if raw is not None
                for value in (_mapping(raw, f"{category}槽"),)
            )
            for category in ("功法", "真意", "气机")
        }
        conflict = self._growth.build_conflict(build)
        if conflict is not None:
            raise SectLibraryError(f"该借阅构筑触发相冲：{conflict}")
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id,
                    request_id,
                    "藏经阁借阅",
                    (
                        StateMutation(
                            user_id,
                            "cultivation",
                            "main",
                            cultivation,
                            snapshot.version,
                        ),
                    ),
                    {
                        "宗门编号": member.sect_id,
                        "功法编号": technique.content_id,
                        "品级": technique.grade_id,
                        "槽位": slot,
                    },
                )
            )
        except (StateConflictError, IdempotencyConflictError) as exc:
            raise SectLibraryConflictError("人物构筑刚刚发生变化，请重试") from exc
        return SectBorrowResult(slot, technique, receipt.replayed)

    async def clear_borrowed(
        self, user_id: str, request_id: str
    ) -> int:
        """离开宗门时清掉借阅记录，把借出过的槽还原成原本的功法。

        规则的三条失效条件（`退出宗门`、`被逐出宗门`、`宗门解散`）都落到这里：调用点
        在成员关系已经删除之后，因此只按「槽里的借阅记录还指着哪个宗门」判——成员关系
        还在同一宗门时保留借阅，否则还原。重复调用是安全的：借阅记录清掉之后本方法
        再也找不到可清的槽，直接返回 0，不写事务。
        """

        self._require_initialized()
        user = _rule_text(user_id, "user_id")
        snapshot = await self._database.get(
            StateAddress(user, "cultivation", "main")
        )
        if snapshot is None:
            return 0
        cultivation = dict(_mapping(snapshot.value, "cultivation/main"))
        techniques = list(_slots(cultivation.get("功法"), "功法"))
        member = await self._sect.membership(user)
        cleared = 0
        for index, raw in enumerate(techniques):
            if not isinstance(raw, Mapping):
                continue
            borrowed = raw.get("藏经阁借阅")
            if not isinstance(borrowed, Mapping):
                continue
            sect_id = str(borrowed.get("宗门编号") or "")
            if member is not None and member.sect_id == sect_id:
                continue
            techniques[index] = borrowed.get("原功法")
            cleared += 1
        if not cleared:
            return 0
        cultivation["功法"] = techniques
        try:
            await self._database.commit(
                TransactionCommand(
                    user,
                    _rule_text(request_id, "request_id"),
                    "清除宗门借阅",
                    (
                        StateMutation(
                            user,
                            "cultivation",
                            "main",
                            cultivation,
                            snapshot.version,
                        ),
                    ),
                    {"宗门编号": "", "清除槽位数": cleared},
                )
            )
        except (StateConflictError, IdempotencyConflictError) as exc:
            raise SectLibraryConflictError("人物构筑刚刚发生变化，请重试") from exc
        return cleared

    async def effective_cultivation(
        self, user_id: str, cultivation: Mapping[str, object]
    ) -> Mapping[str, object]:
        """宗门关系有效时保留借阅，否则只在读取视图中恢复原功法。"""

        self._require_initialized()
        member = await self._sect.membership(user_id)
        value = dict(cultivation)
        techniques = list(_slots(value.get("功法"), "功法"))
        changed = False
        for index, raw in enumerate(techniques):
            if not isinstance(raw, Mapping):
                continue
            borrowed = raw.get("藏经阁借阅")
            if not isinstance(borrowed, Mapping):
                continue
            sect_id = str(borrowed.get("宗门编号") or "")
            if member is not None and member.sect_id == sect_id:
                continue
            techniques[index] = borrowed.get("原功法")
            changed = True
        if changed:
            value["功法"] = techniques
        return value

    async def _techniques(self, sect_id: str) -> tuple[SectTechnique, ...]:
        members = await self._sect.members(sect_id)
        highest: dict[str, str] = {}
        for member in members:
            snapshots = await self._database.list_for_user(
                member.user_id, state_type="cultivation_library"
            )
            for snapshot in snapshots:
                value = _mapping(snapshot.value, "个人道藏")
                content_id = str(value.get("编号") or "").strip()
                grade_id = str(value.get("品级") or "").strip()
                if not content_id or not grade_id:
                    raise SectLibraryError("个人道藏中的功法实例不完整")
                current = highest.get(content_id)
                if (
                    current is None
                    or self._asset.grade(grade_id).order
                    > self._asset.grade(current).order
                ):
                    highest[content_id] = grade_id
        return tuple(
            SectTechnique(
                content_id,
                str(self._data.entity("功法", content_id).get("名称") or content_id),
                grade_id,
                self._asset.grade(grade_id).name,
            )
            for content_id, grade_id in sorted(highest.items())
        )

    @staticmethod
    def _resolve(values: tuple[SectTechnique, ...], identifier: str) -> SectTechnique:
        query = str(identifier or "").strip()
        direct = next((value for value in values if value.content_id == query), None)
        if direct is not None:
            return direct
        matches = tuple(value for value in values if value.name == query)
        if len(matches) != 1:
            raise SectLibraryError("藏经阁中没有找到唯一功法")
        return matches[0]

    async def _member(self, user_id: str):
        self._require_initialized()
        member = await self._sect.membership(user_id)
        if member is None:
            raise SectLibraryError("尚未加入宗门")
        return member

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("藏经阁核心尚未初始化")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    return mapping(value, label, error=SectLibraryError)


def _失效条件(value: object) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not all(isinstance(item, str) for item in value)
    ):
        raise JsonDataError("藏经阁.借阅.失效条件必须是字符串数组")
    return tuple(value)


def _slots(value: object, label: str) -> tuple[object, ...]:
    return sequence(value, label, error=SectLibraryError)


__all__ = ["SectLibraryService"]
