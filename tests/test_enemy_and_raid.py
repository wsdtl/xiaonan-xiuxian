"""敌人与讨伐这两条入口必须真的跑通。

`test_combat_entry_surfaces.py` 按「数据入口」组织，但漏了敌人这一条：**敌方池与讨伐生成
从来没被驱动过**。于是「丹药池按基础物品抽」这种一用就崩的缺陷在库里躺到了第 90 轮——
83 个敌方池里 21 个一生成就报「资源池集合不匹配」，探索与讨伐整条进不去。

这里补三件事：每个敌方定义都真生成一次、每个讨伐定义都真生成一次、讨伐真打一场，
并确认**没有撞上两条链的深度上限**（撞上就说明数据里的上限不够，玩家会看到效果被丢）。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from game.core.combat.contracts import (
    CombatBuildRef,
    CombatGroupSpec,
    CombatRequest,
    CombatantSpec,
)

DATA = Path(__file__).resolve().parents[1] / "data"
ENEMY_SECTIONS = ("敌人", "讨伐首领", "讨伐辅助", "讨伐属从")
SEED = 20260913
ATTRS = {
    "血气上限": 6000,
    "精神上限": 900,
    "攻击": 60,
    "防御": 200,
    "速度": 100,
    "命中率": 100,
    "闪避率": 0,
    "暴击率": 0,
    "抗暴率": 0,
    "暴击伤害": 150,
    "格挡率": 0,
    "破格率": 0,
    "格挡减伤": 0,
    "伤害加成": 100,
    "伤害减免": 0,
}


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


def _spec(pid: str, cards: tuple[str, ...], *, group_id: str = "") -> CombatantSpec:
    return CombatantSpec(
        id=pid,
        name=pid,
        attributes=dict(ATTRS),
        build=tuple(
            CombatBuildRef("功法", card, instance_id=f"{pid}:{card}", born_order=index)
            for index, card in enumerate(cards)
        ),
        group_id=group_id or f"玩家编组:{pid}",
    )


def test_every_enemy_definition_generates(services) -> None:
    """每个敌方定义都要真的生成得出来：一处抽错池子，整条探索/讨伐都进不去。"""

    pools = services.data.pools()
    broken: list[str] = []
    generated: set[str] = set()
    for section in ENEMY_SECTIONS:
        files = tuple(sorted(f for f, s in pools.items() if s == section))
        if not files:
            continue
        expected = set(services.data.pool_members(files, section))
        try:
            # 一次把该类别池里**每个定义**都抽出来：数量取并集大小，抽不重复优先。
            units = services.enemy.generate_category(
                section=section,
                pool_names=files,
                count=len(expected),
                seed=SEED,
                instance_prefix=f"测试:{section}",
            )
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{section}: {type(exc).__name__}: {exc}")
            continue
        generated |= {unit.combatant.name for unit in units}
        missing = expected - generated
        if missing:
            broken.append(f"{section} 没抽出来的定义：{'、'.join(sorted(missing)[:3])}")
    assert not broken, broken
    assert len(generated) >= 100


def test_every_raid_generates(services) -> None:
    """每个讨伐定义：首领 / 辅助 / 属从三池 + 奖励池都要抽得出来。"""

    ids = tuple(services.data.entities("讨伐"))
    assert ids, "库里没有讨伐定义"
    broken: list[str] = []
    for raid_id in ids:
        definition = services.raid.definition(raid_id)
        for 人数 in (1, 15):
            try:
                groups = services.raid.generate(
                    definition,
                    ally_group_count=人数,
                    seed=SEED,
                    instance_prefix=f"测试:{raid_id}:{人数}",
                )
            except Exception as exc:  # noqa: BLE001
                broken.append(f"{raid_id}/{人数}组: {type(exc).__name__}: {exc}")
                continue
            if not groups.groups or not groups.boss_group.primary_ids:
                broken.append(f"{raid_id}/{人数}组：首领编组为空")
    assert not broken, broken


def _raid_request(services, 人数: int, limit: int) -> CombatRequest:
    raid_id = sorted(services.data.entities("讨伐"))[0]
    definition = services.raid.definition(raid_id)
    groups = services.raid.generate(
        definition, ally_group_count=人数, seed=SEED, instance_prefix=f"测试:{人数}"
    )
    allies = tuple(
        _spec(f"L{index}", ("400541",), group_id=f"玩家编组:L{index}")
        for index in range(1, 人数 + 1)
    )
    enemies = tuple(
        member.combatant for group in groups.groups for member in group.combatants
    )
    return CombatRequest(
        left_team=allies,
        right_team=enemies,
        seed=SEED,
        action_limit=limit,
        left_groups=tuple(
            CombatGroupSpec(f"玩家编组:L{index}", (f"L{index}",), (f"L{index}",))
            for index in range(1, 人数 + 1)
        ),
        right_groups=tuple(
            CombatGroupSpec(
                group.group_id,
                tuple(item.combatant.id for item in group.combatants),
                group.primary_ids,
            )
            for group in groups.groups
        ),
    )


def test_raid_battle_runs_past_the_designed_depth(services) -> None:
    """讨伐真打一场：不抛错，而且没撞上两条链的深度上限。"""

    result = asyncio.run(services.combat.execute(_raid_request(services, 3, 60)))
    facts = {key for event in result.events for key in event.values}
    assert result.left_results and result.right_results
    assert any(event.kind == "行动开始" for event in result.events)
    assert "链深度跳过" not in facts, "事件链上限不够：有事件没往下触发"
    assert "能力链跳过" not in facts, "能力链上限不够：有能力没执行"
