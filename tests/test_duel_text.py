"""切磋组件的文本、撤回与战报可见性边界。"""

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
        "撤回切磋",
    ]


def test_duel_withdraw_clears_both_sides(services) -> None:
    _create(services, "P:决甲C", "决甲C")
    _create(services, "P:决乙C", "决乙C")
    feature = services.features.qiecuo
    target = asyncio.run(feature.resolve_target("P:决甲C", "决乙C"))
    asyncio.run(
        feature.start(
            DuelStartCommand(
                "P:决甲C", target, "决-" + __import__("uuid").uuid4().hex[:8]
            )
        )
    )
    asyncio.run(feature.withdraw("P:决甲C", "撤回-" + __import__("uuid").uuid4().hex[:8]))
    with pytest.raises(DuelError, match="没有待处理"):
        asyncio.run(feature.accept("P:决乙C", "接受-" + __import__("uuid").uuid4().hex[:8]))


def test_duel_report_is_visible_to_both_sides(services) -> None:
    _create(services, "P:决甲D", "决甲D")
    _create(services, "P:决乙D", "决乙D")
    feature = services.features.qiecuo
    target = asyncio.run(feature.resolve_target("P:决甲D", "决乙D"))
    asyncio.run(
        feature.start(
            DuelStartCommand(
                "P:决甲D", target, "决-" + __import__("uuid").uuid4().hex[:8]
            )
        )
    )
    value = asyncio.run(
        feature.accept("P:决乙D", "接受-" + __import__("uuid").uuid4().hex[:8])
    )
    assert value.events > 0
    for user_id in ("P:决甲D", "P:决乙D"):
        sections = asyncio.run(services.features.zhanbao.my_report_sections(user_id))
        assert sections.personal or sections.team
