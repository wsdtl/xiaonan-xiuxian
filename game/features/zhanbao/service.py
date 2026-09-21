"""战报页面（分享地址）的数据供应。

页面是「分享链接」式的：`/battle/<战报编号>`，数据从同前缀取（战报头、片段、事件、
参战者、行动前后状态五份）。这一层管的是**从存档战报现算展示包并按片段切**：

- 存档里只有**战报**（`宗门战` 记录里的 `战报`）；展示包不存——它比战报还大，
  而且每一步都能现算（第 118 轮）。
- 现算一次要几百毫秒（一场十五人对十五人的仗），所以按编号**留最近几份**在内存里：
  页面打开会连着要五份数据，不缓存就是算五遍。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from game.core.combat import CombatService
from game.core.sect_war import SectWarService


class BattleReportFeature:
    """按战报编号供应页面要的五份数据。"""

    #: 内存里留几份现算好的展示包：页面一次只用一份，留几份是给「来回翻片段」用的。
    CACHE_LIMIT = 4

    def __init__(self, combat: CombatService, sect_war: SectWarService) -> None:
        self._combat = combat
        self._sect_war = sect_war
        self._cache: OrderedDict[str, tuple[dict[str, Any], dict[str, Any]]] = OrderedDict()
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("战报页面玩法微服务已经初始化")
        if not self._combat.status().initialized:
            raise RuntimeError("战斗核心必须先于战报页面玩法启动")
        if not self._sect_war.status().initialized:
            raise RuntimeError("宗门战核心必须先于战报页面玩法启动")
        self._initialized = True

    async def payload(self, report_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """`（战报头, 明细包）`；编号不存在或那场仗还没打完时返回 `None`。"""

        self._require_initialized()
        key = str(report_id or "").strip()
        if not key:
            return None
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        report = await self._sect_war.report(key)
        if report is None:
            return None
        built = self._combat.build_report_presentation(report)
        self._cache[key] = built
        while len(self._cache) > self.CACHE_LIMIT:
            self._cache.popitem(last=False)
        return built

    async def main(self, report_id: str) -> dict[str, Any] | None:
        """战报头：概览、演员表、花名册与片段列表（片段本身按需取）。"""

        payload = await self.payload(report_id)
        return None if payload is None else payload[0]

    async def segment(self, report_id: str, index: int) -> dict[str, Any] | None:
        """一个片段的全部内容（时间线 + 参战者快照）。"""

        payload = await self.payload(report_id)
        if payload is None:
            return None
        return (payload[1].get("segments") or {}).get(str(index))

    async def events(self, report_id: str, index: int) -> dict[str, Any] | None:
        """一个片段的全部事件（详细模式用）。"""

        payload = await self.payload(report_id)
        if payload is None:
            return None
        return (payload[1].get("events") or {}).get(str(index))

    async def participants(
        self, report_id: str, index: int, snapshot: str
    ) -> dict[str, Any] | None:
        """一个片段里某一侧（战前 / 战后）的参战者记录。"""

        payload = await self.payload(report_id)
        if payload is None:
            return None
        return (payload[1].get("participants") or {}).get(f"{index}:{snapshot}")

    async def transition(self, report_id: str, index: int, sequence: int) -> dict[str, Any] | None:
        """一次行动的「行动前后状态」。"""

        payload = await self.payload(report_id)
        if payload is None:
            return None
        return (payload[1].get("transitions") or {}).get(f"{index}:{sequence}")

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("战报页面玩法微服务尚未初始化")


__all__ = ["BattleReportFeature"]
