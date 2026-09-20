"""种族登记表：结构、登记、正负配对都要真的成立。

种族是锁定技的**第四种载体**（参战者固有规则，见 `data/战斗/说明.md` 第 67 条）。它不挂卡、
没有卡面，所以它的规则没有渲染通道可查——只能靠这一条从服务入口走完整条路的测试。
判据侧另有一份（`tools/架构审查/检查规则层.py` 的「种族登记表」），两边盯的不是同一件事：
判据查组合与名额，这里查**这份表真的被服务读进来了、且能按参战者固有规则的形状交出去**。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "data"
BASE_RACE = "人族"


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


def test_every_race_rule_is_registered(services) -> None:
    """每个种族的天生规则都要是登记过的单位级规则，而且**组合各不相同**。"""

    layer = services.combat.rule_layer()
    races = services.enemy.races()
    assert len(races) == 180, f"种族数不对：{len(races)}"
    assert BASE_RACE in races, "基准族人族必须在表里"
    组合: dict[tuple[str, ...], str] = {}
    for name, entry in races.items():
        # 签名要带上参数：同一条 `不可被指定`，挡敌方与挡己方是两种完全不同的种族形状。
        names = tuple(
            sorted(
                str(dict(item).get("名称") or "")
                + (f"（{dict(item)['来源']}）" if dict(item).get("来源") else "")
                for item in entry.get("天生规则") or ()
            )
        )
        for rule_name in names:
            definition = layer.get(rule_name.split("（")[0])
            assert definition is not None, f"{name} 用了未登记的规则：{rule_name}"
            assert definition.get("归属") == "单位", f"{name} 的 {rule_name} 不是单位级规则"
        if name == BASE_RACE:
            assert names == (), f"基准族不许有天生规则：{names}"
            continue
        assert names, f"{name} 一条天生规则都没有"
        assert names not in 组合, f"{name} 与 {组合[names]} 的组合完全一样"
        组合[names] = name


def test_every_race_is_reachable_by_generation(services) -> None:
    """每个种族都要在敌方档次里出得来：抽不到就是躺着的死数据。"""

    tiers = services.enemy.races_by_tier()
    assert tiers, "档次→种族 是空的：生成侧抽不到任何种族"
    seen: set[str] = set()
    for names in tiers.values():
        seen |= set(names)
    missing = sorted(set(services.enemy.races()) - seen)
    assert not missing, f"这些种族任何档次都抽不到：{missing}"


def test_generated_enemies_carry_race_rules(services) -> None:
    """敌人真的会带上种族的天生规则（这一条从生成入口走到 `CombatantSpec`）。"""

    pools = services.data.pools()
    files = tuple(sorted(f for f, s in pools.items() if s == "敌人"))
    units = services.enemy.generate_category(
        section="敌人", pool_names=files, count=40, seed=20260921, instance_prefix="试"
    )
    layer = services.combat.rule_layer()
    带规则 = [unit for unit in units if unit.combatant.inherent_rules]
    assert 带规则, "40 个敌人一个都没带上天生规则"
    for unit in 带规则:
        for rule in unit.combatant.inherent_rules:
            assert str(dict(rule).get("名称") or "") in layer


def test_companions_have_a_registered_race(services) -> None:
    """道侣也定族：`道侣.json.可选种族` 里的族都登记过，且同一名道侣永远同一族。"""

    races = services.enemy.races()
    ids = tuple(services.data.entities("道侣"))[:5]
    assert ids, "库里没有道侣实体"
    for companion_id in ids:
        race = services.companion.race_of(companion_id)
        assert race in races, f"道侣 {companion_id} 的族没登记：{race}"
        assert services.companion.race_of(companion_id) == race
        for rule in services.companion.inherent_rules(companion_id):
            assert str(dict(rule).get("名称") or "") in services.combat.rule_layer()


def test_race_side_layers_are_readable(services) -> None:
    """种族的另外三样也要读得出来：寿元系数、成长修正、卡池来源。"""

    attributes = services.data.dataset("战斗定义").get("属性") or {}
    for name in services.enemy.races():
        assert services.enemy.growth_factors(name) == services.character.race_growth_factors(name)
        for key in services.enemy.growth_factors(name):
            assert key in attributes, f"{name} 的成长修正用了没登记的属性：{key}"
        assert services.enemy.pool_source(name) in {"敌方修士", "灵兽"}
        assert services.character.race_lifespan_factor(name) > 0
    assert services.character.race_lifespan_factor("人族") == 1.0


def test_race_rules_come_out_as_inherent_rules(services) -> None:
    """种族交给战斗的那一份，就是「参战者固有规则」的形状。"""

    races = services.enemy.races()
    for name in races:
        规则 = services.enemy.inherent_rules(name)
        assert all("名称" in dict(item) for item in 规则)
        assert len(规则) == len(races[name].get("天生规则") or ())
    assert services.enemy.inherent_rules(BASE_RACE) == ()
    with pytest.raises(Exception):
        services.enemy.inherent_rules("不存在的种族")
