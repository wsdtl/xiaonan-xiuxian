"""战前状态（战丹与长期伤势）必须真正跑得起来。

这条路径曾被漏测：功法、真意、气机、器律都走 `CombatBuildRef`，而战丹和长期
伤势走 `CombatantSpec.prepared_statuses`，两者的数据形状和装配入口完全不同。
只测构筑会整条漏掉战前状态。
"""

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from game.core.combat.contracts import (
    CombatBuildRef,
    CombatantSpec,
    CombatRequest,
    CombatStatusSpec,
)

DATA = Path(__file__).resolve().parents[1] / "data"
if str(DATA.parent / "tools") not in sys.path:
    sys.path.insert(0, str(DATA.parent / "tools"))

from 构筑模板展开 import expand_build_document  # noqa: E402
ATTRS = {
    "血气上限": 1200,
    "精神上限": 400,
    "攻击": 150,
    "防御": 60,
    "速度": 110,
    "命中率": 100,
    "闪避率": 5,
    "暴击率": 20,
    "抗暴率": 5,
    "暴击伤害": 150,
    "格挡率": 10,
    "破格率": 5,
    "格挡减伤": 30,
    # 加成口径的基准是 100（不增不减）：这里写 0 等于「伤害加成 0%」，会把伤害乘成 0。
    "伤害加成": 100,
    "伤害减免": 0,
}
#: 目前没有已知会崩的战前状态；任何一处崩溃都必须在这里显式登记理由。
KNOWN_LOOPING: set[str] = set()


def _battle_pills() -> list[dict]:
    entries: list[dict] = []
    for path in sorted((DATA / "物品/炼丹/内容/丹药/战丹").glob("*.json")):
        # 监听节点已经模板化；不展开拿到的是引用，会被判成「不是监听事件节点」。
        entries.extend(expand_build_document(json.loads(path.read_text(encoding="utf-8"))))
    return entries


def _injuries() -> list[dict]:
    return expand_build_document(
        json.loads((DATA / "角色" / "内容" / "伤势.json").read_text(encoding="utf-8"))
    )


@pytest.fixture(scope="module")
def services(tmp_path_factory):
    import game.app as app
    from main import create_app

    create_app()
    isolated = replace(
        app.game_config.database, path=tmp_path_factory.mktemp("db") / "game.db"
    )
    original = app.game_config
    app.game_config = replace(app.game_config, database=isolated)
    try:
        built = app.build_game_services(data_dir=DATA)
    finally:
        app.game_config = original
    try:
        yield built.core
    finally:
        built.core.database.close()


def _spec(pid: str, statuses: tuple[CombatStatusSpec, ...] = ()) -> CombatantSpec:
    return CombatantSpec(
        id=pid,
        name=pid,
        attributes=dict(ATTRS),
        build=(
            CombatBuildRef("功法", "400541", instance_id=f"{pid}:400541", born_order=0),
        ),
        prepared_statuses=statuses,
    )


def _prepared_statuses(services) -> list[CombatStatusSpec]:
    prepared: list[CombatStatusSpec] = []
    for entry in _battle_pills():
        effect = entry.get("使用效果") or {}
        if not effect.get("监听"):
            continue
        medicine = services.medicine.battle(entry["编号"], "01")
        prepared.append(services.medicine.prepared_status(medicine))
    for entry in _injuries():
        raw = entry.get("战斗状态") or {}
        if not raw.get("监听"):
            continue
        prepared.append(
            CombatStatusSpec(
                name=entry["名称"],
                category=raw["类别"],
                remaining_actions=raw["剩余行动"],
                duration_unit=raw["持续单位"],
                modifiers=tuple(
                    (str(key), float(value)) for key, value in (raw.get("属性") or {}).items()
                ),
                tags=tuple(raw.get("标签") or ()),
                listeners=tuple(dict(node) for node in raw["监听"]),
                source=entry["编号"],
                source_name=entry["名称"],
                action_limits=tuple(raw.get("行动限制") or ()),
            )
        )
    return prepared


def test_battle_pills_carry_complete_listeners() -> None:
    pills = _battle_pills()
    assert pills
    carrying = [entry for entry in pills if (entry.get("使用效果") or {}).get("监听")]
    assert carrying, "战丹必须自带监听节点正文"
    for entry in carrying:
        assert "战斗机制" not in entry["使用效果"], entry["编号"]
        for node in entry["使用效果"]["监听"]:
            assert node.get("能力") == "监听事件", entry["编号"]
            assert node.get("事件"), entry["编号"]


def test_long_term_injuries_carry_complete_listeners() -> None:
    injuries = _injuries()
    assert injuries
    carrying = [entry for entry in injuries if (entry.get("战斗状态") or {}).get("监听")]
    assert carrying, "长期伤势必须自带监听节点正文"
    for entry in carrying:
        assert "机制" not in entry["战斗状态"], entry["编号"]
        for node in entry["战斗状态"]["监听"]:
            assert node.get("能力") == "监听事件", entry["编号"]


def test_prepared_statuses_survive_real_battles(services) -> None:
    """战丹与长期伤势都必须能在真实战斗里装配并跑完。

    `KNOWN_LOOPING` 只登记已经确认的内容缺陷；集合必须与实际失败集合完全相等，
    这样修好数据时测试会提醒删除它，新出现的失败也不会被吞掉。
    """

    prepared = _prepared_statuses(services)
    assert len(prepared) >= 100, f"战前状态样本太少：{len(prepared)}"

    crashed: set[str] = set()
    messages: dict[str, str] = {}
    for index, status in enumerate(prepared):
        request = CombatRequest(
            left_team=(_spec("L", (status,)),),
            right_team=(_spec("R",),),
            seed=20260911 + index,
            action_limit=20,
        )
        try:
            asyncio.run(services.combat.execute(request))
        except Exception as exc:  # noqa: BLE001
            crashed.add(status.name)
            messages[status.name] = f"{type(exc).__name__}: {exc}"
    assert crashed == KNOWN_LOOPING, {
        name: messages.get(name, "已修复，请从 KNOWN_LOOPING 中删除") for name in crashed ^ KNOWN_LOOPING
    }
