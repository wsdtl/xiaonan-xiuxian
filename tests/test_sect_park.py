"""宗门只能建在宗门园区；园区面板统一。"""
from __future__ import annotations

import asyncio

import pytest

from game.core.character.contracts import CharacterCreateCommand
from game.features.zongmen import SectFeatureError


def _create(services, user_id: str, name: str, xy: tuple[int, int]) -> None:
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(user_id, f"create-{user_id}", name, "男", xy, "")
        )
    )


def test_sect_cannot_be_created_outside_park(services) -> None:
    _create(services, "sect-elsewhere", "寻宗者", (15, 17))
    with pytest.raises(SectFeatureError) as caught:
        asyncio.run(
            services.features.zongmen.create("sect-elsewhere", "sect-create", "别处宗")
        )
    assert caught.value.code == "not_at_park"


def test_sect_can_be_created_at_park(services) -> None:
    _create(services, "sect-at-park", "立宗者", (15, 16))
    result = asyncio.run(
        services.features.zongmen.create("sect-at-park", "sect-create", "园区宗")
    )
    assert result.page.page == "宗主"


def test_spirit_vein_can_select_terrain(services) -> None:
    _create(services, "lingmai-owner", "矿脉主", (15, 16))
    asyncio.run(
        services.features.zongmen.create("lingmai-owner", "lingmai-sect", "矿脉宗")
    )
    asyncio.run(
        services.features.zongmen_shengchan.start(
            "灵脉", "lingmai-owner", "lingmai-start"
        )
    )
    view = asyncio.run(
        services.features.zongmen_shengchan.select_terrain(
            "灵脉", "lingmai-owner", "lingmai-terrain", "灵矿-溪谷"
        )
    )
    assert view.terrain == "灵矿-溪谷"


def test_non_member_park_panel_is_same_function_list(services) -> None:
    _create(services, "park-visitor", "游客甲", (15, 16))
    actions = asyncio.run(
        services.features.weizhi.current_location_actions("park-visitor")
    )
    labels = {action.label for action in actions}
    assert "宗门事务" in labels
    assert "采药" not in labels
    assert "采矿" not in labels
