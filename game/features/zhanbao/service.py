"""战报页面（分享地址）的数据供应。

页面是「分享链接」式的：`/battle/<战报编号>`，数据从同前缀取。这一层管的是**从存档战报
现算画面**：

- 存档里只有**战报**（`宗门战` 记录里的 `战报`）；画面不存——它比战报还大，
  而且每一步都能现算。
- **不缓存**：这类页面多半只看一次，而战报记录本身只留很短一段时间（历史记录过期就没了）。
  更重要的是——缓存一旦过期不对齐，玩家看到的就是上一版画面。所以每次调用都按**存档当前
  版本**现算：`/data` 带 `view` 参数说明要哪一份（首屏 / 片段 / 事件 / 参战者 / 行动前后状态）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

from game.core.combat import VIEW_PARTS, CombatService
from game.core.duel import DuelService
from game.core.sect_war import SectWarService

#: 一次调用要哪一份画面。与页面 `loadEndpoint` 的 `view` 参数一一对应（核心定的名单）。
VIEWS = VIEW_PARTS


class BattleReportLog(Protocol):
    """非资产战报库的**读**契约（由天道后台的非资产仓储实现）。

    战报是非资产数据：不归玩家所有、按编号对外分享、只留一段时间。`load` 只给未过期的，
    `peek` 连过期的也给——页面要能把「已过期」和「从来没有过」分开说。
    """

    def load(self, report_id: str) -> Any | None: ...

    def peek(self, report_id: str) -> Any | None: ...


class BattleReportFeature:
    """按战报编号供应页面要的那一份画面。"""

    def __init__(
        self,
        combat: CombatService,
        sect_war: SectWarService,
        duel: DuelService,
        battle_log: BattleReportLog | None = None,
    ) -> None:
        self._combat = combat
        self._sect_war = sect_war
        self._duel = duel
        self._battle_log = battle_log
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("战报页面玩法微服务已经初始化")
        if not self._combat.status().initialized:
            raise RuntimeError("战斗核心必须先于战报页面玩法启动")
        if not self._sect_war.status().initialized:
            raise RuntimeError("宗门战核心必须先于战报页面玩法启动")
        self._initialized = True

    async def view(
        self,
        report_id: str,
        *,
        part: str = "header",
        index: int = 0,
        snapshot: str = "",
        sequence: int = 0,
    ) -> dict[str, Any] | None:
        """按编号与 `part` 现算一份画面；编号不存在或那场仗还没打完时返回 `None`。

        `part` 取 `VIEWS` 里的名字：`header` 是首屏（概览、演员表、花名册、片段表），
        其余四份按片段取。**每次都重算**，不读上一次的结果。
        """

        self._require_initialized()
        if part not in VIEWS:
            raise ValueError(f"战报页面不认识这一份画面：{part or '<空>'}")
        key = str(report_id or "").strip()
        if not key:
            return None
        stored = await self._stored(key)
        if stored is None:
            return None
        report, _version = stored
        # 只算这一次要的那一份：翻页、取片段不再为整份视图付钱（结果与整份一致）。
        header, parts = self._combat.build_report_view(
            report, only=part, sequence=sequence
        )
        if part == "header":
            return header
        if part == "segment":
            return (parts.get("segments") or {}).get(str(index))
        if part == "events":
            return (parts.get("events") or {}).get(str(index))
        if part == "participants":
            return (parts.get("participants") or {}).get(f"{index}:{snapshot}")
        return (parts.get("transitions") or {}).get(f"{index}:{sequence}")

    async def _stored(self, key: str) -> tuple[Mapping[str, object], int] | None:
        """按**战报编号**从非资产库取战报。

        战报是非资产数据：按编号存在非资产库（`log_battle_reports`），与谁发起、存在谁名下
        都无关。过期与不存在分别说话——过期直接报错，不存在回 None（页面说 404）。
        """

        if self._battle_log is None:
            raise RuntimeError("战报页面玩法微服务缺少非资产战报库")
        identifier = str(key or "").strip()
        if not identifier:
            return None
        row = self._battle_log.load(identifier)
        if row is None:
            if self._battle_log.peek(identifier) is not None:
                raise ValueError("这份战报已经过期，战报只留最近一段时间")
            return None
        payload = json.loads(str(getattr(row, "report_json", "") or "{}"))
        report = payload.get("战报") if isinstance(payload, Mapping) else None
        if not isinstance(report, Mapping):
            raise ValueError("这份战报的内容无法解读")
        return report, 0

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("战报页面玩法微服务尚未初始化")


__all__ = ["VIEWS", "BattleReportFeature"]
