"""规则层的行为验证：每条登记的规则都要**真的有作用**，且只在声明它的单位身上起作用。

`检查规则层.py` 只保证「登记与实现不脱钩」——它跑不动战斗。规则层是行为，所以另有一条
行为判据：直接用合成卡片驱动战斗核心（不走 `data/` 里的内容，语料不受影响），
每条规则跑「声明 / 不声明」两场，两场的唯一差别就是这条规则。

1. **不可被指定**：同一次攻击，声明的一侧一滴血不掉，没声明的一侧照掉；
2. **不受行动条提前**：对手把行动条推上去，声明的一侧行动次数明显更少；
3. **不可禁用**：对手开局禁用同一个技能名，声明的一侧照样放得出来，没声明的一次都放不出。

三条都要求**两个方向都成立**：只验「声明了有变化」会漏掉「什么都没做也通过」的假规则。

    .venv/Scripts/python.exe -X utf8 tools/验证规则层.py

**退出码：0 = 全部成立，1 = 有规则名不副实。**
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.core.combat.models import RuntimeCombatantSnapshot  # noqa: E402

#: 探针用属性：够硬也够脆，让「有没有挨打」在同一次行动里就看得出来。
ATTRIBUTES = {
    "血气上限": 1000.0,
    "精神上限": 400.0,
    "攻击": 100.0,
    "防御": 0.0,
    "速度": 100.0,
    "命中率": 100.0,
    "闪避率": 0.0,
    "暴击率": 0.0,
    "抗暴率": 0.0,
    "暴击伤害": 150.0,
    "格挡率": 0.0,
    "破格率": 0.0,
    "格挡减伤": 0.0,
    "伤害加成": 100.0,
    "伤害减免": 0.0,
}

SEED = 20260912
ACTION_LIMIT = 20


def _strike_skill(name: str, *, locked: bool = False) -> dict:
    """一发必定命中、必定不暴击、必定不被格挡的直伤。"""

    node = {
        "能力": "主动技能",
        "名称": name,
        "释放顺序": 1,
        "精神消耗": 0,
        "冷却行动": 0,
        "效果": [
            {
                "能力": "造成伤害",
                "目标": {"能力": "选择目标", "范围": "当前目标"},
                "数值": 120,
                "能否闪避": False,
                "能否暴击": False,
                "能否格挡": False,
            }
        ],
    }
    if locked:
        node["不可禁用"] = True
    return node


def _push_skill() -> dict:
    """把对手的行动条往前推 60 点。"""

    return {
        "能力": "主动技能",
        "名称": "探针推",
        "释放顺序": 1,
        "精神消耗": 0,
        "冷却行动": 0,
        "效果": [
            {
                "能力": "修改行动条",
                "目标": {"能力": "选择目标", "范围": "敌方"},
                "方式": "增加",
                "数值": 60,
            }
        ],
    }


def _ban_passive(skill_name: str) -> dict:
    """开局禁用对手的指定技能。"""

    return {
        "能力": "被动技能",
        "名称": "探针封",
        "结算顺序": 1,
        "效果": [
            {
                "能力": "监听事件",
                "事件": "战斗开始",
                "阵营关系": "任意敌方",
                "效果": [
                    {
                        "能力": "修改技能",
                        "目标": {"能力": "选择目标", "范围": "敌方"},
                        "技能": {"能力": "选择技能", "范围": "指定技能", "名称": skill_name},
                        "字段": "禁用",
                        "方式": "设置",
                        "值": True,
                    }
                ],
            }
        ],
    }


def _card(*abilities: dict) -> dict:
    return {"功法": "探针卡", "编号": "900001", "能力": list(abilities)}


def _rules(*entries: dict) -> dict:
    return {"能力": "规则文本", "规则": list(entries)}


def _fighter(pid: str, card: dict | None, *, health: float | None = None) -> RuntimeCombatantSnapshot:
    return RuntimeCombatantSnapshot(
        id=pid,
        name=pid,
        attributes=dict(ATTRIBUTES),
        level=5,
        health=health,
        techniques=(card,) if card else (),
    )


def _run(engine, left: RuntimeCombatantSnapshot, right: RuntimeCombatantSnapshot):
    return engine.simulate(
        left=left,
        right=right,
        medicine_definitions={},
        medicine_selection_strategy="",
        seed=SEED,
        action_limit=ACTION_LIMIT,
    )


def _health(result, pid: str) -> float:
    for value in (*result.left_results, *result.right_results):
        if value.id == pid:
            return float(value.health)
    return -1.0


def _count(result, *, kind: str, actor: str = "", skill: str = "") -> int:
    total = 0
    for event in result.events:
        if event.kind != kind:
            continue
        if actor and (event.source_id != actor and str(event.values.get("行动者") or "") != actor):
            continue
        if skill and str(event.values.get("技能") or "") != skill:
            continue
        total += 1
    return total


def probe_untargetable(engine) -> list[str]:
    """不可被指定：声明的一侧不掉血，没声明的一侧照掉。"""

    problems: list[str] = []
    attacker = _fighter("L1", _card(_strike_skill("探针斩")))
    plain = _run(engine, attacker, _fighter("R1", None))
    guarded = _run(
        engine,
        attacker,
        _fighter("R1", _card(_rules({"名称": "不可被指定", "来源": "敌方"}))),
    )
    plain_health = _health(plain, "R1")
    guarded_health = _health(guarded, "R1")
    print(f"  不可被指定：没有规则时 R1 剩 {plain_health:.0f}，声明后剩 {guarded_health:.0f}（上限 1000）")
    if plain_health >= 1000:
        problems.append("不可被指定：对照组根本没挨打，探针不成立")
    if guarded_health != 1000:
        problems.append(f"不可被指定：声明后仍然掉到 {guarded_health:.0f}")
    return problems


def probe_no_haste(engine) -> list[str]:
    """不受行动条提前：对手推条时，声明的一侧行动次数更少。"""

    problems: list[str] = []
    pusher = _fighter("L1", _card(_push_skill()))
    plain = _run(engine, pusher, _fighter("R1", None))
    guarded = _run(
        engine,
        pusher,
        _fighter("R1", _card(_rules({"名称": "不受行动条提前", "来源": "敌方"}))),
    )
    plain_actions = _count(plain, kind="行动开始", actor="R1")
    guarded_actions = _count(guarded, kind="行动开始", actor="R1")
    print(f"  不受行动条提前：R1 行动次数 没有规则 {plain_actions} → 声明后 {guarded_actions}")
    if plain_actions <= guarded_actions:
        problems.append(
            f"不受行动条提前：声明后没有变少（{plain_actions} → {guarded_actions}）"
        )
    return problems


def probe_no_disable(engine) -> list[str]:
    """不可禁用：同一个技能名被对手封禁，声明的一侧照样放得出来。"""

    problems: list[str] = []
    banner = _fighter("R1", _card(_ban_passive("探针锁")))
    plain = _run(engine, _fighter("L1", _card(_strike_skill("探针锁"))), banner)
    locked = _run(engine, _fighter("L1", _card(_strike_skill("探针锁", locked=True))), banner)
    plain_uses = _count(plain, kind="技能施放后", skill="探针锁")
    locked_uses = _count(locked, kind="技能施放后", skill="探针锁")
    print(f"  不可禁用：探针锁施展次数 没有规则 {plain_uses} → 声明后 {locked_uses}")
    if plain_uses != 0:
        problems.append(f"不可禁用：对照组没被封住（施展 {plain_uses} 次），探针不成立")
    if locked_uses <= 0:
        problems.append("不可禁用：声明后仍然一次都没放出来")
    return problems


CHECKS = (
    ("不可被指定", probe_untargetable),
    ("不受行动条提前", probe_no_haste),
    ("不可禁用", probe_no_disable),
)


def main() -> int:
    services = build_game_services()
    try:
        engine = services.core.combat._require_engine()
        problems: list[str] = []
        print(f"规则层行为验证：{len(CHECKS)} 条规则")
        for name, check in CHECKS:
            try:
                found = check(engine)
            except Exception as exc:  # noqa: BLE001
                found = [f"{type(exc).__name__}: {exc}"]
            for problem in found:
                print(f"  [{name}] {problem}")
            problems.extend(found)
    finally:
        services.core.database.close()
    if problems:
        print(f"规则名不副实 {len(problems)} 处")
        return 1
    print("规则层行为验证通过：三条规则都有作用，且只在声明它的单位身上起作用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
