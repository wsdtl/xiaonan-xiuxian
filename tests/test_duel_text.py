"""切磋组件的文本与按钮边界。"""

from __future__ import annotations

import asyncio

import pytest

from game.features.chuangjian_renwu.contracts import CreateCharacterRequest
from game.features.qiecuo import DuelError, DuelStartCommand


def _create(services, uid: str, name: str) -> None:
    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(uid, "创建:" + uid, name, "男")
        )
    )


def test_duel_self_target_is_rejected_by_name(services) -> None:
    _create(services, "P:决甲", "决甲")
    with pytest.raises(DuelError, match="不能和自己切磋"):
        asyncio.run(services.features.qiecuo.resolve_target("P:决甲", "决甲"))


def test_duel_challenge_has_accept_and_reject_buttons(services) -> None:
    _create(services, "P:决甲B", "决甲B")
    _create(services, "P:决乙B", "决乙B")
    feature = services.features.qiecuo
    target = asyncio.run(feature.resolve_target("P:决甲B", "决乙B"))
    value = asyncio.run(
        feature.start(
            DuelStartCommand(
                "P:决甲B", target, "决-" + __import__("uuid").uuid4().hex[:8]
            )
        )
    )
    from game.cmd.战斗.切磋.reply import challenge

    message = challenge(feature, value, "决乙B")
    assert [action.label for action in message.document.actions] == [
        "接受切磋",
        "拒绝切磋",
    ]
