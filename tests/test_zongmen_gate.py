"""宗门不占地：山门是固定公共地点，同一格可以立多个宗门。

旧口径把宗门的存在绑在一个**唯一的地表格**上（创建时取宗主当时的 `xy`，由共享位置占位，
同一格只能有一个宗门）——地表 100×100 就是宗门数的硬顶。现在山门固定成公共地点「宗门园区」，
所有宗门从那一格进本宗洞天，`入口坐标` 降级为展示用的驻地。
"""

from __future__ import annotations

import pytest

from game.core.world import LocationQuery
from game.features.chuangjian_renwu.contracts import CreateCharacterRequest


async def _人物(services, user: str, name: str) -> None:
    await services.features.chuangjian_renwu.create(
        CreateCharacterRequest(user_id=user, request_id="建-" + name, name=name, gender="男")
    )


@pytest.fixture
def 同格() -> tuple[int, int]:
    """两宗共用的那一格——故意用同一个坐标。"""

    return (15, 17)


def test_同一格可以立两个宗门(services, 同格) -> None:
    import asyncio

    async def run():
        await _人物(services, "P:立宗甲", "立宗甲")
        await _人物(services, "P:立宗乙", "立宗乙")
        甲 = await services.core.sect.create("P:立宗甲", "请求甲", "判据宗甲", 同格)
        乙 = await services.core.sect.create("P:立宗乙", "请求乙", "判据宗乙", 同格)
        assert 甲.entrance_xy == 同格 and 乙.entrance_xy == 同格
        assert 甲.sect_id != 乙.sect_id and 甲.cave_id != 乙.cave_id
        # 解散一个不再要求"入口位置记录"存在（那条记录已经不写了）。
        await services.core.sect.disband("P:立宗乙", "解散乙")
        assert await services.core.sect.sect(乙.sect_id) is None
        assert await services.core.sect.sect(甲.sect_id) is not None

    asyncio.run(run())


def test_山门认的是地点功能而不是某一格(services) -> None:
    山门 = services.features.zongmen_shanmen
    宗门园区 = services.core.world.locate(LocationQuery(location_name="宗门园区"))
    assert "宗门" in 宗门园区.available_functions
    assert 山门._at_gate(宗门园区.xy) is True
    # 溪隐台（出生地）不是山门——旧口径下"你创建时站的那一格"才是。
    溪隐台 = services.core.world.locate(LocationQuery(location_name="溪隐台"))
    assert 山门._at_gate(溪隐台.xy) is False
    # 守卫来自那个地点的 功能配置.宗门，不是代码里写死的字面量。
    assert 山门._enter_guard == "自主空闲或休息"
