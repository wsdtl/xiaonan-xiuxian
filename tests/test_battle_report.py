"""战报契约：静态资源、仓储与页面服务端。

由原 test_battle_report_assets.py + test_battle_report_store.py + test_battle_report_site.py 并档而来：它们本就同属一个领域，
分开写只会让每份都重新装一遍服务。
"""
from __future__ import annotations

import pathlib
import re

静态目录 = pathlib.Path(__file__).resolve().parents[1] / "static" / "battle-report"

#: 页面与模块里所有「从别处取东西」的写法。
引用模式 = re.compile(r'(?:href|src)\s*=\s*"([^"]+)"|from\s+"([^"]+)"')


def 收集引用() -> list[tuple[str, int, str]]:
    引用: list[tuple[str, int, str]] = []
    for 文件 in sorted(静态目录.glob("*")):
        if 文件.suffix not in {".html", ".js", ".css"}:
            continue
        for 行号, 行 in enumerate(文件.read_text(encoding="utf-8").splitlines(), 1):
            for 匹配 in 引用模式.finditer(行):
                地址 = 匹配.group(1) or 匹配.group(2)
                引用.append((文件.name, 行号, 地址))
    return 引用


def test_report_page_assets_are_absolute() -> None:
    """页面与模块之间的引用一律走 `/static/battle-report/…`，不许相对路径。"""

    相对 = [
        (文件, 行号, 地址)
        for 文件, 行号, 地址 in 收集引用()
        if not 地址.startswith("/static/") and not 地址.startswith("http")
    ]
    assert not 相对, (
        "战报页在 /battle/<编号> 下，相对引用会被解析成 /battle/… 并被战报路由吞成 HTML："
        + "；".join(f"{文件}:{行号} {地址}" for 文件, 行号, 地址 in 相对)
    )


def test_every_referenced_asset_exists() -> None:
    """引用的每个地址都要在静态目录里真的有那个文件（改名/搬家后立刻红）。"""

    缺失 = []
    for 文件, 行号, 地址 in 收集引用():
        if not 地址.startswith("/static/battle-report/"):
            continue
        目标 = 静态目录 / 地址[len("/static/battle-report/") :]
        if not 目标.is_file():
            缺失.append(f"{文件}:{行号} {地址}")
    assert not 缺失, "引用的静态资源不存在：" + "；".join(缺失)


def test_report_page_has_exactly_one_module_entry() -> None:
    """页面只许有一个模块入口，且它必须存在——避免再出现"半套资源"的页面。"""

    html = (静态目录 / "index.html").read_text(encoding="utf-8")
    模块 = re.findall(r'<script[^>]+type="module"[^>]+src="([^"]+)"', html)
    assert 模块 == ["/static/battle-report/app.js"], 模块
    assert (静态目录 / "app.js").is_file()

# ─────────── 原 tests/test_battle_report_store.py ───────────

import sqlite3
import time

import pytest

from launch.battle_log import BattleReportStore

NOW = time.time()


def store(tmp_path, *, retention=3600):
    value = BattleReportStore(tmp_path / "runtime_log.db", retention_seconds=retention)
    value.initialize()
    return value


def test_round_trip_and_last_write_wins(tmp_path):
    storage = store(tmp_path)
    storage.save(
        report_id="abc123", kind="切磋", participants=("甲", "乙"),
        finished_at="2026-09-30T10:00:00+08:00", finished_timestamp=NOW, report_json='{"events":[]}',
    )
    first = storage.load("abc123")
    assert first is not None
    assert (first.report_id, first.kind, first.participants) == ("abc123", "切磋", "甲\n乙")
    assert first.report_json == '{"events":[]}'

    storage.save(
        report_id="abc123", kind="宗门战", participants=("甲",),
        finished_at="2026-09-30T11:00:00+08:00", finished_timestamp=NOW + 1, report_json='{"events":[1]}',
    )
    again = storage.load("abc123")
    assert again is not None
    assert (again.kind, again.participants, again.report_json) == ("宗门战", "甲", '{"events":[1]}')


@pytest.mark.parametrize("kind, report_id, report_json", [
    ("不存在", "abc", "{}"),
    ("切磋", "   ", "{}"),
    ("切磋", "abc", "   "),
])
def test_refuses_bad_rows(tmp_path, kind, report_id, report_json):
    storage = store(tmp_path)
    with pytest.raises(ValueError):
        storage.save(
            report_id=report_id, kind=kind, participants=(),
            finished_at="2026-09-30T10:00:00+08:00", finished_timestamp=NOW, report_json=report_json,
        )


def test_expired_report_is_invisible(tmp_path):
    """过期与不存在对外必须表现一致：都回 None，由命令组件决定怎么说。"""
    storage = store(tmp_path, retention=60)
    storage.save(
        report_id="stale", kind="切磋", participants=("甲",),
        finished_at="2026-09-30T10:00:00+08:00",
        finished_timestamp=NOW - 61, report_json="{}",
    )
    assert storage.load("stale") is None
    storage.save(
        report_id="fresh", kind="切磋", participants=("甲",),
        finished_at="2026-09-30T10:00:00+08:00", finished_timestamp=NOW, report_json="{}",
    )
    assert storage.load("fresh") is not None


def test_cleanup_keeps_newest_rows_only(tmp_path):
    storage = store(tmp_path)
    for index in range(5):
        storage.save(
            report_id=f"r{index}", kind="切磋", participants=("甲",),
            finished_at=f"2026-09-30T1{index}:00:00+08:00",
            finished_timestamp=NOW + index, report_json="{}",
        )
    storage.cleanup(now_timestamp=NOW - 1, max_rows=2)
    assert storage.load("r4") is not None and storage.load("r3") is not None
    for gone in ("r0", "r1", "r2"):
        assert storage.load(gone) is None


def test_cleanup_drops_expired_rows(tmp_path):
    storage = store(tmp_path, retention=60)
    storage.save(
        report_id="old", kind="切磋", participants=("甲",),
        finished_at="2026-09-30T10:00:00+08:00", finished_timestamp=NOW - 120, report_json="{}",
    )
    storage.cleanup(now_timestamp=NOW, max_rows=100)
    with sqlite3.connect(tmp_path / "runtime_log.db") as connection:
        left = connection.execute("SELECT COUNT(*) FROM log_battle_reports").fetchone()[0]
    assert left == 0

# ─────────── 原 tests/test_battle_report_site.py ───────────

import asyncio
import json

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


class _StoredReports:
    """替身：非资产库的读口（按战报编号取；只实现页面要用的两个方法）。"""

    def __init__(self, reports: dict) -> None:
        self._reports = reports

    def load(self, report_id: str):
        report = self._reports.get(report_id)
        if report is None:
            return None
        return type("Row", (), {"report_json": json.dumps({"战报": report}, ensure_ascii=False)})()

    def peek(self, report_id: str):
        return self.load(report_id) if report_id in self._reports else None


def test_views_match_the_whole_payload() -> None:
    services = build_game_services()
    try:
        header, parts = services.core.combat.build_report_view(_report(services))
        feature = services.features.zhanbao
        feature._battle_log = _StoredReports({"war-1": {"占位": True}})
        feature._combat.build_report_view = lambda report, **_kwargs: (header, parts)

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
    assert paths == {"/battle/{report_id:path}", "/battle/{report_id:path}/data"}, (
        "页面与数据各一条路：数据只有一个接口，用 `view` 参数说明要哪一份。"
        "`{report_id:path}` 让同一对路由同时吃单段编号与 `/<发起者>/<切磋编号>` 两段分享地址"
    )
    data = next(route for route in router.routes if route.path.endswith("/data"))
    params = {param.name for param in data.dependant.query_params}
    assert params == {"view", "index", "snapshot", "sequence"}, f"数据接口的参数变了：{params}"
