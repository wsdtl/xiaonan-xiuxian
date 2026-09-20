"""第四种锁定技载体——**参战者固有规则**——必须真的从契约走到引擎。

前三处载体（卡面根 `规则文本` / 被动技能行 / 状态定义）都在内容里，靠 `tools/验证规则层.py`
的四种写法对照验；但**能从 `CombatantSpec` 直接写进来的那条路只被临时探针跑过**，
临时脚本不进回归，等于没验。这里按服务入口把它钉住：写得进去、判得生效、写重了报错、
写错载体报错。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from game.core.combat.contracts import CombatBuildRef, CombatRequest, CombatantSpec

DATA = Path(__file__).resolve().parents[1] / "data"
SEED = 20260912
PROBE_CARD = "400541"
ATTRS = {
    "血气上限": 1000,
    "精神上限": 400,
    "攻击": 100,
    "防御": 0,
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
def combat(tmp_path_factory):
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
        yield built.core.combat
    finally:
        built.core.database.close()


def _unit(pid: str, *, armed: bool, rules: tuple = ()) -> CombatantSpec:
    return CombatantSpec(
        id=pid,
        name=pid,
        attributes=dict(ATTRS),
        build=(
            (CombatBuildRef("功法", PROBE_CARD, instance_id=f"{pid}:卡", born_order=0),)
            if armed
            else ()
        ),
        inherent_rules=rules,
    )


def _strike(combat, right_rules: tuple) -> float:
    """左打手砍右靶子一场，返回靶子挨到的总伤害。"""

    result = asyncio.run(
        combat.execute(
            CombatRequest(
                left_team=(_unit("L1", armed=True),),
                right_team=(_unit("R1", armed=False, rules=right_rules),),
                seed=SEED,
                action_limit=20,
            )
        )
    )
    return sum(
        float(event.values.get("实际数值") or 0)
        for event in result.events
        if event.kind == "造成伤害后" and event.target_id == "R1"
    )


def test_inherent_rules_actually_intercept(combat) -> None:
    """写在参战者上的锁定技要和写在卡面上的一样管用。"""

    bare = _strike(combat, ())
    armed = _strike(combat, ({"名称": "不可被指定", "来源": "敌方"},))
    assert bare > 0, "靶子没挨打，这条探针没有区分度"
    assert armed == 0, f"固有规则没拦住：挨了 {armed}"


def test_inherent_rules_duplicate_is_refused(combat) -> None:
    """同一条单位级规则写两遍，当场报错，不挑一条悄悄用。

    同一处 `规则[]` 里写重、和**跨载体**跟卡面写重走两条报错，这里各钉一个：
    跨载体的那条（`固有规则` 撞卡面）由 `tools/验证规则层.py` 的四种写法对照负责。
    """

    with pytest.raises(ValueError, match="重复声明了同一条规则"):
        _strike(combat, ({"名称": "不可被指定", "来源": "敌方"},) * 2)


def test_inherent_rules_reject_wrong_carrier(combat) -> None:
    """行级规则（不可禁用）不能写在单位上。"""

    with pytest.raises(ValueError, match="不能写在单位里"):
        _strike(combat, ({"名称": "不可禁用"},))
