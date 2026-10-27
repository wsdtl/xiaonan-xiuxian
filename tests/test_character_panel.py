"""人物面板：资源覆盖与单一自动用药入口。"""

from __future__ import annotations

import asyncio

from game.core.character.contracts import CharacterCreateCommand
from game.cmd.查看与工具.角色 import reply
from message.renderers.plain_text import render_plain_text


def test_every_profile_resource_has_a_row(services) -> None:
    user = "character-panel-user"
    asyncio.run(
        services.core.character.create(
            CharacterCreateCommand(user, "create-character-panel", "面板", "男", (15, 17), "")
        )
    )
    result = asyncio.run(services.features.chakan_juese.inspect(user))
    message = reply.overview(result, result.altitude_unit)
    text = render_plain_text(message.document)

    for name, _value in result.character.resources:
        assert f"{name}:" in text, name
    assert "神魂上限" not in text
    assert "血气上限" not in text
    assert "精神上限" not in text
    assert text.count("自动用药") == 1
