"""战报页面服务端的契约：一个数据接口按 `view` 现算五种画面，与整份逐项相同。

页面是**实时查看**用的：`/battle/<编号>/data?view=…` 一个接口，每次调用都按存档现算，
服务端不缓存、也没有离线/预览模式。所以判据是两条：

- **切片只是搬运**：五种画面与一次算完整的对应部分一模一样（自己再拼一遍就会两处漂）；
- **接口只有一个、参数就是页面拼的那几个**：多一个少一个都会让页面拿到 404。

顺带钉住「首屏不给片段内容」（片段按需取）与「战报头里带花名册」这两件第 118/119 轮定的事。
"""

from __future__ import annotations

import asyncio

from game.app import build_game_services
from game.core.combat.contracts import (
    CombatBuildRef,
    CombatReportSpec,
    CombatRequest,
    CombatantSpec,
)

ATTRS = {
    "血气上限": 1200, "精神上限": 400, "攻击": 150, "防御": 60, "速度": 110,
    "命中率": 100, "闪避率": 5, "暴击率": 20, "抗暴率": 5, "暴击伤害": 150,
    "格挡率": 10, "破格率": 5, "格挡减伤": 30, "伤害加成": 100, "伤害减免": 0,
}
CARD = "410154"


def _battle(services) -> dict:
    def side(pid: str) -> CombatantSpec:
        return CombatantSpec(
            id=pid, name=pid, attributes=dict(ATTRS),
            build=(CombatBuildRef("真意", CARD, instance_id=f"{pid}:{CARD}", born_order=0),),
        )

    result = asyncio.run(
        services.core.combat.execute(
            CombatRequest(
                left_team=(side("L"),), right_team=(side("R"),),
                seed=20260911, action_limit=60,
                report=CombatReportSpec(scene="切磋", generated_at="2026-01-01T00:00:00+08:00"),
            )
        )
    )
    assert result.report, "这一场没生成战报，判据无从判起"
    return services.core.combat.build_report_presentation(result.report)


class _StoredWar:
    """替身：只实现页面要用的那两个读口（宗门战按编号、切磋按发起者+编号）。"""

    def __init__(self, report: dict) -> None:
        self._report = report

    async def report(self, war_id: str):
        return (self._report, 1) if war_id == "war-1" else None


class _StoredDuel:
    """切磋的存档挂在发起者名下：地址写成 `切磋:<发起者>:<编号>`。"""

    def __init__(self, report: dict) -> None:
        self._report = report

    async def report(self, owner: str, challenge_id: str):
        return (self._report, 1) if (owner, challenge_id) == ("甲", "d-1") else None


def test_views_match_the_whole_payload() -> None:
    services = build_game_services()
    try:
        header, parts = services.core.combat.build_report_view(_report(services))
        feature = services.features.zhanbao
        feature._sect_war = _StoredWar({"占位": True})
        feature._duel = _StoredDuel({"占位": True})
        feature._combat.build_report_view = lambda report: (header, parts)

        first = header["detail"]["segments"][0]["index"]
        assert "timeline" not in header["detail"]["segments"][0], (
            "首屏不许带片段内容（时间线按需取）"
        )
        assert header["roster"] and header["actors"] and header["palette"], "首屏要带花名册与角色表"

        assert asyncio.run(feature.view("war-1")) == header
        assert asyncio.run(feature.view("war-1", part="segment", index=first)) == parts["segments"][str(first)]
        assert asyncio.run(feature.view("war-1", part="events", index=first)) == parts["events"][str(first)]
        assert asyncio.run(
            feature.view("war-1", part="participants", index=first, snapshot="after")
        ) == parts["participants"][f"{first}:after"]
        assert asyncio.run(
            feature.view("war-1", part="transition", index=first, sequence=0)
        ) == parts["transitions"][f"{first}:0"]
        assert asyncio.run(feature.view("war-404")) is None
        assert asyncio.run(feature.view("war-1", part="segment", index=99)) is None
        # 切磋的战报：同样是这一条接口，按「切磋:<发起者>:<编号>」取（第 121 轮补）。
        assert asyncio.run(feature.view("切磋:甲:d-1")) == header
        assert asyncio.run(feature.view("切磋:甲:d-404")) is None
        try:
            asyncio.run(feature.view("切磋:甲"))
        except ValueError as exc:
            assert "切磋:<发起者>" in str(exc)
        else:
            raise AssertionError("编号写坏时要报错，不能当成宗门战去查")
    finally:
        services.core.database.close()


def _report(services) -> dict:
    result = asyncio.run(
        services.core.combat.execute(
            CombatRequest(
                left_team=(
                    CombatantSpec(
                        id="L", name="L", attributes=dict(ATTRS),
                        build=(CombatBuildRef("真意", CARD, instance_id=f"L:{CARD}", born_order=0),),
                    ),
                ),
                right_team=(
                    CombatantSpec(
                        id="R", name="R", attributes=dict(ATTRS),
                        build=(CombatBuildRef("真意", CARD, instance_id=f"R:{CARD}", born_order=0),),
                    ),
                ),
                seed=20260911, action_limit=60,
                report=CombatReportSpec(scene="切磋", generated_at="2026-01-01T00:00:00+08:00"),
            )
        )
    )
    return result.report


def test_the_page_has_one_data_interface() -> None:
    from game.cmd.通用.战报.site import router

    paths = {route.path for route in router.routes}
    assert paths == {"/battle/{report_id}", "/battle/{report_id}/data"}, (
        "页面与数据各一条路：数据只有一个接口，用 `view` 参数说明要哪一份"
    )
    data = next(route for route in router.routes if route.path.endswith("/data"))
    params = {param.name for param in data.dependant.query_params}
    assert params == {"view", "index", "snapshot", "sequence"}, f"数据接口的参数变了：{params}"
