"""从角色核心的种族登记表派生种族图鉴。"""

from __future__ import annotations

from game.core.character import CharacterService

from .contracts import RaceEntry, RaceLineage, RaceOverview


class ZhongzuFeature:
    """只编排角色核心已经查死的种族登记表，不读 JSON、不算数值。"""

    def __init__(self, character: CharacterService) -> None:
        self._character = character
        self._overview: RaceOverview | None = None
        self._by_number: dict[str, RaceEntry] = {}
        self._by_name: dict[str, RaceEntry] = {}

    def initialize(self) -> RaceOverview:
        if self._overview is not None:
            raise RuntimeError("种族图鉴玩法微服务已经初始化")
        if not self._character.status().initialized:
            raise RuntimeError("角色核心微服务必须先于种族图鉴玩法启动")
        races = self._character.races()
        grouped: dict[str, list[RaceEntry]] = {}
        tiers: list[str] = []
        for name, entry in races.items():
            entry_tiers = tuple(str(tier) for tier in entry.get("出现档次") or ())
            for tier in entry_tiers:
                if tier not in tiers:
                    tiers.append(tier)
            race = RaceEntry(
                number=str(entry.get("编号") or ""),
                name=name,
                lineage=str(entry.get("族系") or ""),
                tiers=entry_tiers,
                lifespan=float(str(entry.get("寿元系数") or 0)),
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

    def overview(self) -> RaceOverview:
        if self._overview is None:
            raise RuntimeError("种族图鉴玩法微服务尚未初始化")
        return self._overview

    def find(self, key: str) -> RaceEntry | None:
        """按编号或名字取一个种族；两者都不是登记过的名字就返回空。"""

        text = str(key or "").strip()
        if text in self._by_number:
            return self._by_number[text]
        return self._by_name.get(text)


__all__ = ["ZhongzuFeature"]
