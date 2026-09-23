"""藏经阁借阅在离开宗门后失效：退出／被逐出／解散都要还原原功法。

口径（负责人拍板 D3-B）：借来的功法**只在身处宗门期间生效**，`退出宗门`、`被逐出
宗门`、`宗门解散` 三条失效条件都写在 `data/宗门/规则/藏经阁.json` 的 `借阅.失效条件`
里。借阅落库时本来就记了两件事——借自哪个宗门、这个槽原本是什么功法——所以失效时
能就地还原：把槽换回原功法、把借阅记录清掉。

这份测试走真存档栈（临时库，不碰 `database/game.db`）：

- 借阅之后槽里是借来的功法，且带着借阅记录；
- 退出宗门后，槽里回到原功法、借阅记录消失（**库里真的改了**，不是只在读取时还原）；
- 逐出、解散两条路同样清干净；
- 没借过的槽不被顺手改动。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from game.core.asset import CultivationAcquisition
from game.core.database import StateAddress, StateMutation, TransactionCommand
from game.core.world import LocationQuery

DATA = Path(__file__).resolve().parents[1] / "data"
宗主 = "宗门-宗主"
弟子 = "宗门-弟子"
被逐者 = "宗门-被逐者"

#: 借来的功法与被顶掉的原功法（都用真编号；借阅要求本宗成员个人道藏里有这门功法）。
借来的 = "400001"  # 太白庚金剑典
原功法 = {"编号": "400002", "品级": "01"}  # 青冥照影剑经 · 黄品


@pytest.fixture(scope="module")
def services(tmp_path_factory):
    """整个存档栈建在临时库上——绝不碰试玩在用的 `database/game.db`。"""

    from game import app

    root = tmp_path_factory.mktemp("cangjing-borrow")
    original = app.game_config
    app.game_config = replace(
        original,
        database=replace(original.database, path=root / "game.db"),
    )
    try:
        value = app.build_game_services(data_dir=DATA)
    finally:
        app.game_config = original
    try:
        yield value
    finally:
        value.core.database.close()


def _出生地(services):
    return services.core.world.locate(
        LocationQuery(location_name=services.features.chuangjian_renwu._birthplace)
    ).xy


def _创建(services, user_id: str, name: str) -> None:
    from game.features.chuangjian_renwu import CreateCharacterRequest

    asyncio.run(
        services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user_id, request_id=f"创建:{user_id}", name=name, gender="男"
            )
        )
    )


async def _给功法(services, user_id: str, content_id: str, grade_id: str) -> None:
    """把一门功法写进个人道藏——藏经阁的书目就是从个人道藏里聚合出来的。"""

    plan = await services.core.asset.plan_cultivation_acquisitions(
        user_id, (CultivationAcquisition("功法", content_id, grade_id),)
    )
    await services.core.database.commit(
        TransactionCommand(
            user_id,
            f"得功法:{user_id}:{content_id}:{grade_id}",
            "测试置备",
            plan.operations,
            {},
        )
    )


async def _占槽(services, user_id: str, content_id: str, grade_id: str) -> None:
    """把某人的功法槽 1 置成某个真实功法，作为「原本的功法」。"""

    snapshot = await services.core.database.get(
        StateAddress(user_id, "cultivation", "main")
    )
    assert snapshot is not None
    cultivation = dict(snapshot.value)
    slots = list(cultivation["功法"])
    slots[0] = {"编号": content_id, "品级": grade_id}
    cultivation["功法"] = slots
    await services.core.database.commit(
        TransactionCommand(
            user_id,
            f"占槽:{user_id}",
            "测试置备",
            (
                StateMutation(
                    user_id, "cultivation", "main", cultivation, snapshot.version
                ),
            ),
            {},
        )
    )


async def _槽(services, user_id: str) -> object:
    snapshot = await services.core.database.get(
        StateAddress(user_id, "cultivation", "main")
    )
    assert snapshot is not None
    return list(snapshot.value["功法"])[0]


async def _入宗(services, leader: str, target: str) -> None:
    await services.core.sect.invite(leader, target, f"邀请:{target}")
    await services.core.sect.accept(target, f"接受:{target}")


def _借一次书(services, user_id: str, 请求前缀: str) -> None:
    """目标个人道藏里放着借来的那本、槽 1 放着原功法，然后借入槽 1。"""

    asyncio.run(_给功法(services, user_id, 借来的, "01"))
    asyncio.run(_占槽(services, user_id, 原功法["编号"], 原功法["品级"]))
    asyncio.run(
        services.core.sect_library.borrow(user_id, f"借阅:{请求前缀}", 借来的, 1)
    )


def _建宗(
    services, leader: str, 宗门名: str, members: tuple[str, ...] = (), 偏移: int = 0
) -> None:
    """同一地表格只容一个山门，第二个宗门入口往旁边挪一格。"""

    x, y = _出生地(services)
    asyncio.run(
        services.core.sect.create(
            leader, f"创建:{宗门名}", 宗门名, (x + 偏移, y)
        )
    )
    for target in members:
        asyncio.run(_入宗(services, leader, target))


@pytest.fixture(scope="module")
def 已借书的宗门(services):
    """宗主 + 借了书的弟子：借阅已经落到库里。"""

    for user_id, name in ((宗主, "宗主甲"), (弟子, "弟子乙"), (被逐者, "弟子丙")):
        _创建(services, user_id, name)
    _建宗(services, 宗主, "测试宗", (弟子, 被逐者))
    _借一次书(services, 弟子, "弟子")
    return services


def test_借阅落库带着记录(已借书的宗门) -> None:
    """借完之后槽里是借来的功法，并留了「借自哪个宗门 / 原本是什么」的记录。"""

    槽 = asyncio.run(_槽(已借书的宗门, 弟子))
    assert 槽["编号"] == 借来的
    assert 槽["藏经阁借阅"]["原功法"] == 原功法
    assert 槽["藏经阁借阅"]["宗门编号"]


def test_退出宗门后借阅失效并恢复原功法(已借书的宗门) -> None:
    """走玩法层退出——成员关系终止时借阅槽必须真的写回原功法。"""

    asyncio.run(已借书的宗门.features.zongmen.leave(弟子, "退出:弟子"))

    槽 = asyncio.run(_槽(已借书的宗门, 弟子))
    assert 槽 == 原功法
    assert asyncio.run(已借书的宗门.core.sect.membership(弟子)) is None


def test_逐出宗门后借阅失效并恢复原功法(已借书的宗门) -> None:
    """逐出与退出走同一条成员删除路径，借阅同样要清。"""

    _借一次书(已借书的宗门, 被逐者, "被逐者")
    assert asyncio.run(_槽(已借书的宗门, 被逐者))["编号"] == 借来的

    asyncio.run(已借书的宗门.features.zongmen.kick(宗主, 被逐者, "逐出:被逐者"))

    槽 = asyncio.run(_槽(已借书的宗门, 被逐者))
    assert 槽 == 原功法
    assert asyncio.run(已借书的宗门.core.sect.membership(被逐者)) is None


def test_解散宗门后借阅失效并恢复原功法(services) -> None:
    """解散清空全部成员记录，每个有借阅的成员都要被清。"""

    _创建(services, "解散-宗主", "宗主丁")
    _创建(services, "解散-弟子", "弟子戊")
    _建宗(services, "解散-宗主", "解散宗", ("解散-弟子",), 偏移=1)
    _借一次书(services, "解散-弟子", "解散")
    assert asyncio.run(_槽(services, "解散-弟子"))["编号"] == 借来的

    asyncio.run(services.features.zongmen.disband("解散-宗主", "解散:宗门"))

    槽 = asyncio.run(_槽(services, "解散-弟子"))
    assert 槽 == 原功法
    assert asyncio.run(services.core.sect.membership("解散-弟子")) is None


def test_没借过的槽不被顺手改动(services) -> None:
    """清理只看带借阅记录的槽：普通功法槽一格不许动。"""

    _创建(services, "旁观-修士", "旁观己")
    asyncio.run(_占槽(services, "旁观-修士", 原功法["编号"], "02"))

    清掉 = asyncio.run(
        services.core.sect_library.clear_borrowed("旁观-修士", "清:旁观")
    )
    assert 清掉 == 0
    assert asyncio.run(_槽(services, "旁观-修士")) == {
        "编号": 原功法["编号"],
        "品级": "02",
    }
