"""战报页面服务端的契约：五个接口切出来的东西，要与整份展示包逐项相同。

页面按「分享地址」取五份数据（`/data`、片段、事件、参战者、行动前后状态）。这五份是
**从存档战报现算的展示包**里切出来的，所以判据只有一条：**切出来的每一份，与一次算完整份
的对应部分一模一样**——切片只是搬运，不许自己再拼一遍（拼一遍就会两处漂）。

顺带钉住这一轮的两件事：`/data` 里**不带片段内容**（片段按需取），路由必须正好是页面拼的
那五条（多一条少一条都会让页面拿到 404 或读不到数据）。
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
    """跑一场真战斗，返回它的**展示包**（与页面现算的是同一条路）。"""

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
    """替身：只实现页面要用的那一个读口。"""

    def __init__(self, report: dict) -> None:
        self._report = report

    async def report(self, war_id: str):
        return self._report if war_id == "war-1" else None


def test_slices_match_the_whole_payload() -> None:
    services = build_game_services()
    try:
        main, bundle = _battle(services)
        feature = services.features.zhanbao
        feature._sect_war = _StoredWar({"占位": True})
        # 直接喂展示包：切片的判据不该依赖「战报重新算一遍是否稳定」——那条由战报通道管。
        feature._combat.build_report_presentation = lambda report: (main, bundle)

        first = main["detail"]["segments"][0]["index"]
        assert main["detail"]["segments"][0].keys() == {
            "index", "position_label", "title", "outcome", "started_at",
            "finished_at", "duration_label", "system_visual", "counts", "formations",
        }, "战报头里不许再带片段内容（时间线与参战者按需取）"

        assert asyncio.run(feature.main("war-1")) == main
        assert asyncio.run(feature.segment("war-1", first)) == bundle["segments"][str(first)]
        assert asyncio.run(feature.events("war-1", first)) == bundle["events"][str(first)]
        assert asyncio.run(
            feature.participants("war-1", first, "after")
        ) == bundle["participants"][f"{first}:after"]
        assert asyncio.run(
            feature.transition("war-1", first, 0)
        ) == bundle["transitions"][f"{first}:0"]
        assert asyncio.run(feature.main("war-404")) is None
    finally:
        services.core.database.close()


def test_routes_match_the_page_paths() -> None:
    from game.cmd.通用.战报.site import router

    paths = {route.path for route in router.routes}
    assert paths == {
        "/battle/{report_id}",
        "/battle/{report_id}/data",
        "/battle/{report_id}/segments/{index}",
        "/battle/{report_id}/segments/{index}/events",
        "/battle/{report_id}/segments/{index}/participants/{snapshot}",
        "/battle/{report_id}/segments/{index}/transitions/{sequence}",
    }, "路由要与页面 `loadEndpoint` 拼的路径一一对应"
