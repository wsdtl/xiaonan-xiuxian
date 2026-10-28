"""探险总结不再直接挂战报链接，历史战报统一走战报命令。"""

from __future__ import annotations

from datetime import UTC, datetime

from game.core.exploration import ExplorationSettlement
from game.cmd.行动.探险.reply import settlement_summary


def _settlement() -> ExplorationSettlement:
    return ExplorationSettlement(
        session_id="session",
        location_name="溪隐台",
        battle_count=6,
        defeated_enemies=6,
        participant_count=1,
        total_spirit_stones=0,
        total_item_quantity=0,
        users=(),
        settled_at=datetime.now(UTC),
        replayed=False,
        total_battles=6,
        early=False,
    )


def test_settlement_has_no_direct_report_links(services) -> None:
    feature = services.features.tanxian
    message = settlement_summary(feature.copy(), feature, _settlement())
    text = "\n".join(
        "".join(getattr(span, "value", "") for span in line.content)
        for block in message.document.blocks
        for line in getattr(block, "lines", ())
    )
    assert "打开战报" not in text
    assert "本轮战报" not in text
