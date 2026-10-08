"""从角色核心的种族登记表派生种族图鉴。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from game.core.character import CharacterService
from game.core.data import JsonDataError, JsonDataService

from .contracts import RaceEntry, RaceLineage, RaceOverview, ZhongzuCopy

#: 展示数据集三节的键，缺一个或多一个都拒绝启动（与其它展示数据集同一套做法）。
COPY_SECTIONS: tuple[tuple[str, set[str]], ...] = (
    ("总览", {"标题", "引言", "页码", "提示"}),
    ("详情", {"标题", "基础", "编号", "族系", "档次", "寿元", "天生规则", "说明", "规则", "规则来源"}),
    ("错误", {"未找到", "页码有误"}),
)


class ZhongzuFeature:
    """只编排角色核心已经查死的登记表与展示数据集里的文案，不算数值。"""

    def __init__(self, data: JsonDataService, character: CharacterService) -> None:
        self._data = data
        self._character = character
        self._overview: RaceOverview | None = None
        self._copy: ZhongzuCopy | None = None
        self._by_number: dict[str, RaceEntry] = {}
        self._by_name: dict[str, RaceEntry] = {}

    def initialize(self) -> RaceOverview:
        if self._overview is not None:
            raise RuntimeError("种族图鉴玩法微服务已经初始化")
        if not self._character.status().initialized:
            raise RuntimeError("角色核心微服务必须先于种族图鉴玩法启动")
        self._copy = self._load_copy()
        races = self._character.races()
        grouped: dict[str, list[RaceEntry]] = {}
        tiers: list[str] = []
        for name, entry in races.items():
            entry_tiers = tuple(str(tier) for tier in entry.get("出现档次") or ())
            for tier in entry_tiers:
                if tier not in tiers:
                    tiers.append(tier)
            rules = tuple(
                (str(node.get("名称") or ""), str(node.get("来源") or ""))
                for node in entry.get("天生规则") or ()
                if isinstance(node, Mapping)
            )
            race = RaceEntry(
                number=str(entry.get("编号") or ""),
                name=name,
                lineage=str(entry.get("族系") or ""),
                tiers=entry_tiers,
                lifespan=float(str(entry.get("寿元系数") or 0)),
                rules=rules,
                summary=str(entry.get("说明") or ""),
            )
            grouped.setdefault(race.lineage, []).append(race)
            self._by_number[race.number] = race
            self._by_name[race.name] = race
        lineages = tuple(
            RaceLineage(name=lineage, races=tuple(sorted(rows, key=lambda row: row.number)))
            for lineage, rows in grouped.items()
        )
        overview = RaceOverview(total=len(races), lineages=lineages, tiers=tuple(tiers))
        self._overview = overview
        return overview

    def _load_copy(self) -> ZhongzuCopy:
        raw = self._data.dataset("种族展示").get("文本")
        if not isinstance(raw, Mapping):
            raise JsonDataError("种族展示缺少文本.json")
        text = MappingProxyType(
            {
                str(section): MappingProxyType(
                    {
                        str(key): str(value).strip()
                        for key, value in values.items()
                        if isinstance(value, str) and value.strip()
                    }
                )
                for section, values in raw.items()
                if isinstance(values, Mapping)
            }
        )
        for section, keys in COPY_SECTIONS:
            if set(text.get(section, {})) != keys:
                raise JsonDataError(f"种族展示{section}字段不完整")
        return ZhongzuCopy(text)

    def copy(self) -> ZhongzuCopy:
        if self._copy is None:
            raise RuntimeError("种族图鉴玩法微服务尚未初始化")
        return self._copy

    def overview(self) -> RaceOverview:
        if self._overview is None:
            raise RuntimeError("种族图鉴玩法微服务尚未初始化")
        return self._overview

    def find(self, key: str) -> RaceEntry | None:
        """按编号或名字取一个种族；都不是登记过的键就返回空。"""

        text = str(key or "").strip()
        if text in self._by_number:
            return self._by_number[text]
        return self._by_name.get(text)


__all__ = ["ZhongzuFeature"]
