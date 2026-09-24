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

from collections.abc import Mapping
from typing import Any

from game.core.combat import VIEW_PARTS, CombatService
from game.core.duel import DuelService
from game.core.sect_war import SectWarService

#: 一次调用要哪一份画面。与页面 `loadEndpoint` 的 `view` 参数一一对应（核心定的名单）。
VIEWS = VIEW_PARTS


class BattleReportFeature:
    """按战报编号供应页面要的那一份画面。"""

    def __init__(
        self, combat: CombatService, sect_war: SectWarService, duel: DuelService
    ) -> None:
        self._combat = combat
        self._sect_war = sect_war
        self._duel = duel
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
        """按分享地址里的编号取存档战报。

        两种编号：**宗门战**直接用宗门战编号（它的存档是共享实体，按编号就能取）；
        **切磋**的结果挂在发起者名下，所以地址写成 `切磋:<发起者>:<切磋编号>`
        （第 121 轮：试玩时发现切磋打完了没有入口能看那份战报）。
        """

        if key.startswith("切磋:"):
            parts = key.split(":", 2)
            if len(parts) != 3 or not parts[1] or not parts[2]:
                raise ValueError("切磋战报的编号要写成 切磋:<发起者>:<切磋编号>")
            return await self._duel.report(parts[1], parts[2])
        return await self._sect_war.report(key)

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("战报页面玩法微服务尚未初始化")


__all__ = ["VIEWS", "BattleReportFeature"]
