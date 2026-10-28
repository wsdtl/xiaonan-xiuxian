"""战报三栏：个人/组队/宗门组队，每栏只留最近五条。"""

from __future__ import annotations

from types import SimpleNamespace


class _Log:
    def __init__(self, rows):
        self.rows = rows

    def recent(self, participant, *, kind="", limit=200):
        return list(self.rows.get(kind, ()))[:limit]


def _row(report_id: str, kind: str, timestamp: float, participants: tuple[str, ...]):
    return SimpleNamespace(
        report_id=report_id,
        kind=kind,
        finished_at=f"2026-10-29 03:{int(timestamp):02d}",
        finished_timestamp=timestamp,
        participants="\n".join(participants),
    )


def test_sections_split_and_cap_five(services) -> None:
    feature = services.features.zhanbao
    rows = {
        "切磋": tuple(
            _row(f"p{index}", "切磋", index, ("甲", "乙"))
            for index in range(1, 7)
        )
        + (_row("t1", "切磋", 10, ("甲", "乙", "丙", "丁")),),
        "探险": (
            _row("e1", "探险", 11, ("甲",)),
            _row("e2", "探险", 12, ("甲", "乙")),
        ),
        "宗门战": tuple(
            _row(f"s{index}", "宗门战", index, ("甲", "乙"))
            for index in range(1, 7)
        ),
    }
    feature._battle_log = _Log(rows)
    sections = __import__("asyncio").run(feature.my_report_sections("甲"))
    assert len(sections.personal) == 5
    assert [entry.report_id for entry in sections.personal[:2]] == ["e1", "p6"]
    assert [entry.report_id for entry in sections.team] == ["e2", "t1"]
    assert len(sections.sect) == 5
    assert [entry.report_id for entry in sections.sect[:2]] == ["s6", "s5"]
