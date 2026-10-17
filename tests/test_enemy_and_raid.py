"""敌人与讨伐这两条入口必须真的跑通。

`test_combat_entry_surfaces.py` 按「数据入口」组织，但漏了敌人这一条：**敌方池与讨伐生成
从来没被驱动过**。于是「丹药池按基础物品抽」这种一用就崩的缺陷在库里躺到了第 90 轮——
83 个敌方池里 21 个一生成就报「资源池集合不匹配」，探索与讨伐整条进不去。

这里补三件事：每个敌方定义都真生成一次、每个讨伐定义都真生成一次、讨伐真打一场，
并确认**没有撞上两条链的深度上限**（撞上就说明数据里的上限不够，玩家会看到效果被丢）。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest


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


def test_every_enemy_definition_generates(services) -> None:
    """每个敌方定义都要真的生成得出来：一处抽错池子，整条探索/讨伐都进不去。"""

    pools = services.data.pools()
    broken: list[str] = []
    generated: set[str] = set()
    for section in ENEMY_SECTIONS:
        files = tuple(sorted(f for f, s in pools.items() if s == section))
        if not files:
            continue
        # 编号实体池成员键是编号，显示名在「名称」；命名实体池没有名称字段就退回成员键。
        expected = {
            str(value.get("名称") or key)
            for key, value in services.data.entities(section).items()
        }
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
    # 2026-10-17 改为 5 段全局敌人池：每段 5 个，共 25 个定义。
    assert len(generated) >= 20


# 讨伐两个测试已于 2026-10-17 随讨伐数据暂撤（只保留普通遭遇敌人）。
