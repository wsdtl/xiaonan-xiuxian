"""宗门灵田选定地形的回归：不选不变、选了收窄、非法当场拒。

灵田原本每轮从全体灵植里随机抽一株（`draw_item_category("灵植")`）；「选种地形」
把取品来源收窄到一个 `灵植-<地形>` 池。这三条就是它的行为边界：

- 没选地形时，产出仍然落在全体灵植里（旧档与旧行为一致）；
- 选了地形后，产出只出自该地形的池，而**品级仍然随机**（地形不改随机品级）；
- 声明了不是灵植池的地形，启动就报错；玩家给了不在清单里的地形，操作当场被拒。
"""

from __future__ import annotations

import asyncio
import importlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from game.core.data import JsonDataError, JsonDataService
from game.core.sect_production import (
    SectProductionError,
    SectProductionFacility,
    SectProductionService,
    SectProductionView,
)

DATA = Path(__file__).resolve().parents[1] / "data"
#: 池成员少而稳的一处地形（丹泉苑那类），便于断言「只出这个池」。
温泉谷地 = "灵植-温泉谷地"


@pytest.fixture(scope="module")
def services(tmp_path_factory):
    """整个存档栈建在临时库上——绝不碰试玩在用的 `database/game.db`。"""

    from game import app

    root = tmp_path_factory.mktemp("lingtian-terrain")
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


def _terrain_facility(services, kind: str = "灵田"):
    return next(
        facility
        for facility in services.core.sect_production.status().facilities
        if facility.kind == kind
    )


def _members(services, pool: str) -> set[str]:
    return set(services.core.data.pool_members((pool,), "基础物品"))


def test_可选地形就是全部灵植池(services) -> None:
    """`可选地形` 必须与已登记的灵植池逐一对上，不多不少、不重复。"""

    facility = _terrain_facility(services)
    declared = facility.terrain_options
    assert declared
    assert len(declared) == len(set(declared))
    pools = services.core.data.pools()
    assert set(declared) == {
        name
        for name, section in pools.items()
        if name.startswith("灵植-") and section == "基础物品"
    }


def test_未选地形时产出仍来自全部灵植(services) -> None:
    """默认行为不变：不选地形就还是全体灵植的随机池。"""

    service = services.core.sect_production
    facility = _terrain_facility(services)
    outputs, stones = service._roll(facility, "宗门-未选", 0, 240, 1.0, "")
    assert stones == 0
    assert outputs
    assert {output.category for output in outputs} == {"灵植"}
    items = {output.content_id for output in outputs}
    每池 = {pool: _members(services, pool) for pool in facility.terrain_options}
    assert items <= set().union(*每池.values())
    assert len([pool for pool, ids in 每池.items() if ids & items]) > 1


def test_选定地形后只出该地形池的灵植(services) -> None:
    """选了地形，产出只出自该池；品级仍走原来的随机掉落。"""

    service = services.core.sect_production
    facility = _terrain_facility(services)
    outputs, stones = service._roll(facility, "宗门-未选", 0, 240, 1.0, 温泉谷地)
    assert stones == 0
    assert outputs
    items = {output.content_id for output in outputs}
    assert items <= _members(services, 温泉谷地)
    assert len({output.grade_id for output in outputs}) > 1


def test_非法地形被拒(services) -> None:
    """不在清单里的地形、以及没有地形可选的灵脉，操作时都要报错。"""

    service = services.core.sect_production
    with pytest.raises(SectProductionError):
        asyncio.run(service.select_terrain("灵田", "玩家", "req-1", "灵植-不存在"))
    with pytest.raises(SectProductionError):
        asyncio.run(service.select_terrain("灵田", "玩家", "req-2", ""))
    with pytest.raises(SectProductionError):
        asyncio.run(service.select_terrain("灵脉", "玩家", "req-3", 温泉谷地))


def test_声明了非灵植池的地形拒绝启动(tmp_path) -> None:
    """`可选地形` 声明了不是灵植池的名字，启动期直接拒绝。"""

    tree = Path(shutil.copytree(DATA, tmp_path / "data"))
    rules = tree / "宗门" / "规则" / "生产.json"
    raw = json.loads(rules.read_text(encoding="utf-8"))
    raw["产出"]["灵田"]["可选地形"].append("灵矿-温泉谷地")
    rules.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    data = JsonDataService(tree)
    data.initialize()
    # initialize 只读数据服务，其余依赖在这一步还没被用到。
    service = SectProductionService(data, None, None, None, None, None, None)  # type: ignore[arg-type]
    with pytest.raises(JsonDataError):
        service.initialize()


class _假玩法:
    """只记调用，不碰数据库——这一条查的是命令层的接线，不是领域行为。"""

    def __init__(self, copy) -> None:
        self._copy = copy
        self.调用: list[tuple[str, str, str | None]] = []

    def copy(self):
        return self._copy

    def actions(self, view):
        return ()

    async def view(self, kind, user_id):
        self.调用.append(("view", kind, None))
        return _视图()

    async def select_terrain(self, kind, user_id, request_id, terrain):
        self.调用.append(("select_terrain", kind, terrain))
        return _视图()

    async def clear_terrain(self, kind, user_id, request_id):
        self.调用.append(("clear_terrain", kind, None))
        return _视图()

    async def start(self, kind, user_id, request_id):
        self.调用.append(("start", kind, None))
        raise AssertionError("这一条不该走到开启")

    async def collect(self, kind, user_id, request_id):
        self.调用.append(("collect", kind, None))
        raise AssertionError("这一条不该走到收取")


class _假管理器:
    def __init__(self) -> None:
        self.消息: list[object] = []

    async def send(self, message) -> None:
        self.消息.append(message)


def _视图() -> SectProductionView:
    facility = SectProductionFacility(
        "灵田", "灵田", 1800, 6, 1.0, (1, 3), (1, 3), (温泉谷地,)
    )
    return SectProductionView(facility, "宗主", True, True, None, 1, 900, 温泉谷地)


def test_命令层把选地形与清地形接到玩法层(services, monkeypatch) -> None:
    """玩家入口的接线：`灵田 选地形 [地形名]`、`灵田 清地形`；灵脉不给选。"""

    组件 = importlib.import_module("game.cmd.专属.宗门生产")
    假 = _假玩法(services.core.data.dataset("宗门生产展示").get("文本"))
    monkeypatch.setattr(
        组件,
        "current_game_services",
        lambda: SimpleNamespace(
            features=SimpleNamespace(zongmen_shengchan=假)
        ),
    )
    管理器 = _假管理器()

    def 跑(query: str) -> None:
        asyncio.run(组件._dispatch("灵田", "玩家", query, "请求", 管理器))

    def 跑灵脉(query: str) -> None:
        asyncio.run(组件._dispatch("灵脉", "玩家", query, "请求", 管理器))

    跑("选地形")
    assert 假.调用[-1] == ("view", "灵田", None)
    跑("选地形 冰谷")
    assert 假.调用[-1] == ("select_terrain", "灵田", "冰谷")
    跑("清地形")
    assert 假.调用[-1] == ("clear_terrain", "灵田", None)
    跑("乱写")
    assert "格式" in str(管理器.消息[-1])
    之前 = len(假.调用)
    跑灵脉("选地形 冰谷")
    assert len(假.调用) == 之前  # 灵脉没有地形可选，没被转给选地形
    assert "格式" in str(管理器.消息[-1])
    assert len(管理器.消息) == 5
