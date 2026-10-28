"""探险总结的战报链接文本。"""

from __future__ import annotations

from datetime import UTC, datetime

from game.core.exploration import ExplorationSettlement
from game.cmd.行动.探险.reply import settlement_summary


def _settlement(ids: tuple[str, ...]) -> ExplorationSettlement:
    return ExplorationSettlement(
        session_id="session",
        location_name="溪隐台",
        battle_count=len(ids),
        defeated_enemies=len(ids),
        participant_count=1,
        total_spirit_stones=0,
        total_item_quantity=0,
        users=(),
        settled_at=datetime.now(UTC),
        replayed=False,
        total_battles=6,
        early=False,
        battle_report_ids=ids,
    )


def test_settlement_lists_each_battle_report(services) -> None:
    feature = services.features.tanxian
    ids = tuple(f"explore-session-{index:02d}" for index in range(1, 7))
    message = settlement_summary(feature.copy(), feature, _settlement(ids))
    section = next(
        block
        for block in message.document.blocks
        if "".join(getattr(span, "value", "") for span in getattr(block, "title", ()))
        == "本轮战报"
    )
    urls = [
        getattr(span, "url", "")
        for line in section.lines
        for span in line.content
        if getattr(span, "url", "")
    ]
    assert len(urls) == 6
    assert all(f"explore-session-{index:02d}" in url for index, url in enumerate(urls, 1))


def test_settlement_without_reports_says_none(services) -> None:
    feature = services.features.tanxian
    message = settlement_summary(feature.copy(), feature, _settlement(()))
    text = "\n".join(
        "".join(getattr(span, "value", "") for span in line.content)
        for block in message.document.blocks
        for line in getattr(block, "lines", ())
    )
    assert "本轮无战报" in text
