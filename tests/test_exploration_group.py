"""探险组队入口至少要把同行名单带进正式参战名单。"""

from __future__ import annotations

import asyncio

from game.features.chuangjian_renwu.contracts import CreateCharacterRequest


def _create(services, uid: str, name: str) -> None:
    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(uid, "创建:" + uid, name, "男")
        )
    )


def test_team_exploration_starts_with_all_members(services) -> None:
    _create(services, "P:队甲", "队甲")
    _create(services, "P:队乙", "队乙")
    team = services.core.team
    asyncio.run(team.invite("P:队甲", "P:队乙", "队-邀请"))
    asyncio.run(team.accept("P:队乙", "队-接受"))
    entry = asyncio.run(
        services.features.tanxian.enter_bare("P:队甲", "队-探险")
    )
    assert entry.kind == "started"
    assert entry.started is not None
    assert entry.started.participant_count == 2
