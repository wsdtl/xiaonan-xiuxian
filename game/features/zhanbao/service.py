"""战报页面（分享地址）的数据供应。

页面是「分享链接」式的：`/battle/<战报编号>`，数据从同前缀取。这一层管的是**从存档战报
现算画面**：

- 存档里只有**战报**（`宗门战` 记录里的 `战报`）；画面不存——它比战报还大，
  而且每一步都能现算。
- **不缓存**：这类页面多半只看一次，而战报记录本身只留很短一段时间（历史记录过期就没了）。
  更重要的是——缓存一旦过期不对齐，玩家看到的就是上一版画面。所以每次调用都按**存档当前
  版本**现算：`/data` 只有一份整场 `game.battle_animation`，文本与动画共用。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from game.core.combat import VIEW_PARTS, CombatService
from game.core.data import JsonDataService
from game.core.duel import DuelService
from game.core.sect_war import SectWarService

#: 本玩法命令文案所在的数据集（登记在 data/战斗/组件.json）。
COPY_DATASET = "我的战报页面文案"

#: 一次调用要哪一份画面。与页面 `loadEndpoint` 的 `view` 参数一一对应（核心定的名单）。
VIEWS = VIEW_PARTS

#: 每类最多显示几条；多了没人看。
SECTION_LIMIT = 5

#: 每类查询最多拉多少条：先拉够再切前 5，避免被另一类挤掉。
FETCH_LIMIT = 200


class BattleReportLog(Protocol):
    """非资产战报库的**读**契约（由战报日志仓储 `battle_log/service.py` 实现）。

    战报是非资产数据：不归玩家所有、按编号对外分享、只留一段时间。`load` 只给未过期的，
    `peek` 连过期的也给——页面要能把「已过期」和「从来没有过」分开说；
    `recent` 按参与者列最近的未过期战报，供「我的战报」列表用。
    """

    def load(self, report_id: str) -> Any | None: ...

    def peek(self, report_id: str) -> Any | None: ...

    def recent(self, participant: str, *, kind: str = "", limit: int) -> Any: ...


@dataclass(frozen=True)
class MyReport:
    """列表里的一条战报：只够画一行，不带整份本体。"""

    report_id: str
    kind: str
    finished_at: str
    finished_timestamp: float
    participants: tuple[str, ...]


@dataclass(frozen=True)
class MyReportSections:
    """`战报` 一张卡的三栏；每栏最多 `SECTION_LIMIT` 条。"""

    personal: tuple[MyReport, ...] = ()
    team: tuple[MyReport, ...] = ()
    sect: tuple[MyReport, ...] = ()


class BattleReportFeature:
    """按战报编号供应页面要的那一份画面。"""

    def __init__(
        self,
        combat: CombatService,
        sect_war: SectWarService,
        duel: DuelService,
        battle_log: BattleReportLog | None = None,
        data: JsonDataService | None = None,
    ) -> None:
        self._combat = combat
        self._sect_war = sect_war
        self._duel = duel
        self._battle_log = battle_log
        self._data = data
        self._copy: Mapping[str, str] | None = None
        self._initialized = False
        if data is not None:
            raw_copy = dict(data.dataset(COPY_DATASET))
            values = raw_copy.get("文本", raw_copy)
            self._copy = {
                str(key): str(value)
                for key, value in dict(values).items()
            }

    def copy(self) -> Mapping[str, str]:
        """命令文案；没接数据集的旧装配会拿到空表（命令侧会自行回退）。"""

        return self._copy or {}

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("战报页面玩法微服务已经初始化")
        if not self._combat.status().initialized:
            raise RuntimeError("战斗核心必须先于战报页面玩法启动")
        if not self._sect_war.status().initialized:
            raise RuntimeError("宗门战核心必须先于战报页面玩法启动")
        self._initialized = True

    async def my_report_sections(self, participant: str) -> MyReportSections:
        """按 `战报` 的三栏取最近未过期记录，每栏最多 `SECTION_LIMIT` 条。"""

        self._require_initialized()
        name = str(participant or "").strip()
        if not name or self._battle_log is None:
            return MyReportSections()
        personal: list[MyReport] = []
        team: list[MyReport] = []
        sect: list[MyReport] = []
        for kind in ("切磋", "探险", "宗门战"):
            rows = list(
                self._battle_log.recent(name, kind=kind, limit=FETCH_LIMIT)
            )
            for row in rows:
                entry = _report_entry(row)
                if kind == "宗门战":
                    sect.append(entry)
                elif kind == "切磋":
                    (personal if len(entry.participants) <= 2 else team).append(entry)
                elif kind == "探险":
                    (personal if len(entry.participants) <= 1 else team).append(entry)
        return MyReportSections(
            personal=_latest(personal),
            team=_latest(team),
            sect=_latest(sect),
        )

    async def view(
        self,
        report_id: str,
        *,
        part: str = "animation",
    ) -> dict[str, Any] | None:
        """按编号现算整场战报；编号不存在或那场仗还没打完时返回 `None`。

        页面只有 `animation` 一份载荷，文本模式也从它组装；每次都重算，不读上一次结果。
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
        _header, parts = self._combat.build_report_view(report, only=part)
        return parts.get("animation")

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


def _report_entry(row: object) -> MyReport:
    return MyReport(
        report_id=str(getattr(row, "report_id")),
        kind=str(getattr(row, "kind")),
        finished_at=str(getattr(row, "finished_at")),
        finished_timestamp=float(getattr(row, "finished_timestamp")),
        participants=tuple(
            part
            for part in str(getattr(row, "participants")).splitlines()
            if part
        ),
    )


def _latest(values: list[MyReport]) -> tuple[MyReport, ...]:
    return tuple(
        sorted(values, key=lambda entry: entry.finished_timestamp, reverse=True)[
            :SECTION_LIMIT
        ]
    )


__all__ = ["VIEWS", "BattleReportFeature", "MyReport", "MyReportSections"]
