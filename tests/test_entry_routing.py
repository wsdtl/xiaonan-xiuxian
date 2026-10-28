"""分支/参数合规由玩法入口判定，命令层不再维护动作表。"""
from __future__ import annotations

import asyncio

import pytest

from game.core.character.contracts import CharacterCreateCommand
from game.features.zongmen_cangjing import CangjingFeatureError
from game.features.zongmen_shengchan import SectProductionFeatureError


def _create(services, user_id: str, name: str) -> None:
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(user_id, f"create-{user_id}", name, "男", (15, 16), "")
        )
    )


def test_team_entry_returns_format_for_unknown_branch(services) -> None:
    _create(services, "entry-team", "队伍测试")
    entry = asyncio.run(
        services.features.duiwu.enter("entry-team", "team-entry", "队伍 胡说")
    )
    assert entry.kind == "format"


def test_fellowship_entry_returns_format_for_unknown_branch(services) -> None:
    _create(services, "entry-follow", "同行测试")
    entry = asyncio.run(
        services.features.zongmen_tongxing.enter(
            "entry-follow", "follow-entry", "宗门同行 胡说"
        )
    )
    assert entry.kind == "format"


def test_sect_entry_returns_format_for_unknown_branch(services) -> None:
    _create(services, "entry-sect", "宗门测试")
    asyncio.run(
        services.features.zongmen.create("entry-sect", "sect-entry-create", "入口宗")
    )
    entry = asyncio.run(
        services.features.zongmen.enter("entry-sect", "sect-entry", "宗门 胡说")
    )
    assert entry.kind == "format"


def test_library_rejects_unknown_branch(services) -> None:
    _create(services, "entry-library", "藏经测试")
    with pytest.raises(CangjingFeatureError):
        asyncio.run(
            services.features.zongmen_cangjing.enter(
                "entry-library", "library-entry", "藏经阁 胡说"
            )
        )


def test_production_rejects_unknown_branch(services) -> None:
    _create(services, "entry-production", "生产测试")
    with pytest.raises(SectProductionFeatureError):
        asyncio.run(
            services.features.zongmen_shengchan.enter(
                "灵脉", "entry-production", "production-entry", "胡说"
            )
        )

