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
    assert len(races) >= 10, f"种族太少，像是表没读进来：{len(races)}"
    assert BASE_RACE in races, "基准族人族必须在表里"
    组合: dict[tuple[str, ...], str] = {}
    for name, entry in races.items():
        names = tuple(
            sorted(str(dict(item).get("名称") or "") for item in entry.get("天生规则") or ())
        )
        for rule_name in names:
            definition = layer.get(rule_name)
            assert definition is not None, f"{name} 用了未登记的规则：{rule_name}"
            assert definition.get("归属") == "单位", f"{name} 的 {rule_name} 不是单位级规则"
        if name == BASE_RACE:
            assert names == (), f"基准族不许有天生规则：{names}"
            continue
        assert names, f"{name} 一条天生规则都没有"
        assert names not in 组合, f"{name} 与 {组合[names]} 的组合完全一样"
        组合[names] = name


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
