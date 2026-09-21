"""多场探险的编组契约必须跟着存活名单收窄。

这条路径漏测了很久：一场探险可以连打多场（`最多场次`），上一场倒下的我方角色不会
进入下一场，但编组契约原本一直带着全队，于是第二场开打前被战斗核心判
「左方编组引用未知参战者」——整个 `开始探险` 直接抛异常，玩家只看到一次报错。
只跑「全队一起倒下」或「全队都没倒」的对局永远踩不到，必须正好**倒下一部分**。
"""

from game.core.combat.contracts import CombatGroupSpec
from game.core.exploration.service import _living_groups


def 组(编号: str, 成员: tuple[str, ...]) -> CombatGroupSpec:
    return CombatGroupSpec(group_id=编号, member_ids=成员, primary_ids=成员)


def test_全员存活时编组原样() -> None:
    编组 = (组("玩家编组:甲", ("甲", "甲的道侣")), 组("玩家编组:乙", ("乙",)))

    assert _living_groups(编组, {"甲", "甲的道侣", "乙"}) == 编组


def test_部分阵亡时只留存活并收窄主战者() -> None:
    编组 = (组("玩家编组:甲", ("甲", "甲的道侣")), 组("玩家编组:乙", ("乙",)))

    收窄 = _living_groups(编组, {"甲", "乙"})

    assert [value.group_id for value in 收窄] == ["玩家编组:甲", "玩家编组:乙"]
    assert 收窄[0].member_ids == ("甲",)
    assert 收窄[0].primary_ids == ("甲",)
    assert 收窄[1].member_ids == ("乙",)


def test_整组阵亡时去掉该编组() -> None:
    编组 = (组("玩家编组:甲", ("甲", "甲的道侣")), 组("玩家编组:乙", ("乙",)))

    收窄 = _living_groups(编组, {"乙"})

    assert [value.group_id for value in 收窄] == ["玩家编组:乙"]
    assert 收窄[0].member_ids == ("乙",)


def test_收窄后仍然覆盖全部存活者() -> None:
    """战斗核心要求编组恰好覆盖本场全部参战者，漏一个同样整单失败。"""

    编组 = (
        组("玩家编组:甲", ("甲", "甲的道侣")),
        组("玩家编组:乙", ("乙", "乙的道侣")),
        组("玩家编组:丙", ("丙",)),
    )
    存活 = {"甲", "乙的道侣", "丙"}

    收窄 = _living_groups(编组, 存活)

    覆盖 = {成员 for value in 收窄 for 成员 in value.member_ids}
    assert 覆盖 == 存活
    assert all(value.primary_ids for value in 收窄)
    assert all(set(value.primary_ids) <= set(value.member_ids) for value in 收窄)
