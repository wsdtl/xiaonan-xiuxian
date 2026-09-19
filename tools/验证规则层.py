"""规则层的行为验证：**每条登记的规则都要真的有作用**，且只在声明它的载体上起作用。

`检查规则层.py` 只核「登记与实现不脱钩」，它跑不动战斗。规则层是行为，所以另有一条
行为判据，而且它**随登记表自动生长**：每条规则按自己的 `拦截点` 落进对应的标准探针场景，
跑「声明 / 不声明」两场真战斗，两场的唯一差别就是这条规则。

探针用合成卡片驱动战斗核心（不走 `data/` 里的内容，所以语料不受影响），
**正反两个方向都要成立**：只看「声明后有变化」会漏掉「什么都没做也通过」的假规则，
只看正方向还会漏掉「把这一处请求全拦掉」的过宽规则——后者由一条通用的反方向探针收掉
（把请求标签换掉一项，条件不成立时 `拒绝` 必须变成不拒绝）；条件里没有标签字面量、
这条探针做不了的规则，工具会**照实说出来**，不静默放过。

**标准探针场景覆盖到了哪些请求标签，`rules.INTERCEPTION_POINTS` 里逐个声明**；
登记一条落在覆盖范围外的规则，`检查规则层.py` 会要求先扩探针场景（那是代码）。

    .venv/Scripts/python.exe -X utf8 tools/验证规则层.py

**退出码：0 = 全部成立，1 = 有规则名不副实。**
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _path in (str(ROOT), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from game.app import build_game_services  # noqa: E402
from game.core.combat.models import RuntimeCombatantSnapshot  # noqa: E402
from game.core.combat.rules import expand_rule, probe_tags  # noqa: E402

REGISTRY = ROOT / "data" / "战斗" / "定义" / "规则层.json"

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
#: 事件改写的探针要看得见「少了多少」：血量够厚才不会把差值顶到上限。
TANK_ATTRIBUTES = {**ATTRIBUTES, "血气上限": 6000.0, "攻击": 10.0, "防御": 200.0}
SEED = 20260912
ACTION_LIMIT = 20


def _card(*abilities: dict) -> dict:
    return {"功法": "探针卡", "编号": "900001", "能力": list(abilities)}


def _rules(*entries: dict) -> dict:
    return {"能力": "规则文本", "规则": list(entries)}


def _fighter(
    pid: str,
    card: dict | None,
    *,
    health: float | None = None,
    tank: bool = False,
) -> RuntimeCombatantSnapshot:
    return RuntimeCombatantSnapshot(
        id=pid,
        name=pid,
        attributes=dict(TANK_ATTRIBUTES if tank else ATTRIBUTES),
        level=5,
        health=health,
        techniques=(card,) if card else (),
    )


def _strike_skill(name: str = "探针斩", rules: list | None = None) -> dict:
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
    if rules:
        node["规则"] = rules
    return node


def _listener_passive(event: str, effects: list[dict], name: str = "探针被动") -> dict:
    return {
        "能力": "被动技能",
        "名称": name,
        "结算顺序": 1,
        "效果": [
            {
                "能力": "监听事件",
                "事件": event,
                "阵营关系": "任意",
                "效果": effects,
            }
        ],
    }


def _push_skill() -> dict:
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


def _ban_passive(skill_name: str, field: str = "禁用", value: object = True) -> dict:
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
                        "字段": field,
                        "方式": "设置",
                        "值": value,
                    }
                ],
            }
        ],
    }


def _heal_passive(amount: float = 500) -> dict:
    """目标自己每次行动开始时恢复血气——每次都会派发「恢复前」。

    恢复量要比「行动开始恢复」的自然回血大得多，否则观测里分不出探针那一份。
    """

    return {
        "能力": "被动技能",
        "名称": "探针养",
        "结算顺序": 1,
        "效果": [
            {
                "能力": "监听事件",
                "事件": "行动开始",
                "阵营关系": "自身",
                "效果": [
                    {
                        "能力": "恢复资源",
                        "目标": {"能力": "选择目标", "范围": "自身"},
                        "资源": "血气",
                        "数值": amount,
                    }
                ],
            }
        ],
    }


def _run(engine, left, right):
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


def _healed(result, pid: str) -> float:
    """目标身上真正结算成功的恢复量（恢复后 的实际数值）。"""

    return sum(
        float(event.values.get("实际数值") or 0)
        for event in result.events
        if event.kind == "恢复后" and event.target_id == pid
    )


def _damage_taken(result, pid: str) -> float:
    return sum(
        float(event.values.get("实际数值") or 0)
        for event in result.events
        if event.kind == "造成伤害后" and event.target_id == pid
    )


def _scene_targeted(engine, entry: dict, rule: dict) -> tuple[str, float, float, bool]:
    """被选为目标：目标一共挨了多少伤害。"""

    attacker = _fighter("L1", _card(_strike_skill()))
    plain = _run(engine, attacker, _fighter("R1", None))
    guarded = _run(engine, attacker, _fighter("R1", _card(_rules(entry))))
    return (
        "目标受到的伤害",
        _damage_taken(plain, "R1"),
        _damage_taken(guarded, "R1"),
        _damage_taken(guarded, "R1") < _damage_taken(plain, "R1"),
    )


def _scene_action_bar(engine, entry: dict, rule: dict) -> tuple[str, float, float, bool]:
    """行动条被改写：对手推条后，目标自己的行动次数。"""

    pusher = _fighter("L1", _card(_push_skill()))
    plain = _run(engine, pusher, _fighter("R1", None))
    guarded = _run(engine, pusher, _fighter("R1", _card(_rules(entry))))
    count_plain = _count(plain, kind="行动开始", actor="R1")
    count_guarded = _count(guarded, kind="行动开始", actor="R1")
    return ("目标行动次数", count_plain, count_guarded, count_guarded < count_plain)


def _scene_event_rewrite(engine, entry: dict, rule: dict) -> tuple[str, float, float, bool]:
    """事件被改写：按这条规则挡的是哪种改写，挑对应的探针组合。

    - `改写:取消`：对手在「造成伤害前」取消事件 → 看目标实际挨到多少伤害；
    - `改写:数值`：对手把这次伤害减去 90 → 同上；
    - `改写:转化`：目标自己回血，对手把「恢复前」转成「获得护盾前」→ 看目标回了多少血。
    """

    tags = probe_tags(rule)
    if "改写:转化" in tags:
        # 目标必须先掉血：满血时回复会溢出，观测不到「回没回成」。
        healer = _fighter("R1", _card(_heal_passive()), tank=True, health=3000.0)
        converter = _listener_passive(
            "恢复前",
            [{"能力": "转化事件", "事件": "获得护盾前"}],
            name="探针转",
        )
        plain = _run(engine, _fighter("L1", _card(converter), tank=True), healer)
        guarded = _run(
            engine,
            _fighter("L1", _card(converter), tank=True),
            _fighter("R1", _card(_heal_passive(), _rules(entry)), tank=True, health=3000.0),
        )
        # 转化事件是**换事件**：原事件不再记录，改派发新事件（见 mechanics._dispatch_event），
        # 所以「回血变护盾」在资源上未必立刻看得出差别。观测量直接取这件事本身：
        # 关于目标的事件被转化了几次——这正是 不可转化 要挡的东西。
        converted_plain = _count(plain, kind="事件转化后")
        converted_guarded = _count(guarded, kind="事件转化后")
        return ("事件被转化的次数", converted_plain, converted_guarded, converted_guarded < converted_plain)
    if "改写:数值" in tags:
        saboteur = _listener_passive(
            "造成伤害前",
            [{"能力": "修改事件数值", "方式": "减少", "数值": 90}],
            name="探针削",
        )
    else:
        saboteur = _listener_passive(
            "造成伤害前",
            [{"能力": "取消事件"}],
            name="探针销",
        )
    plain = _run(
        engine,
        _fighter("L1", _card(_strike_skill()), tank=True),
        _fighter("R1", _card(saboteur), tank=True),
    )
    guarded = _run(
        engine,
        _fighter("L1", _card(_strike_skill()), tank=True),
        _fighter("R1", _card(saboteur, _rules(entry)), tank=True),
    )
    return (
        "目标受到的伤害",
        _damage_taken(plain, "R1"),
        _damage_taken(guarded, "R1"),
        _damage_taken(guarded, "R1") > _damage_taken(plain, "R1"),
    )


def _scene_skill_rewrite(engine, entry: dict, rule: dict) -> tuple[str, float, float, bool]:
    """技能被改写：对手禁用这个技能名后，自己放出来的次数。

    **反方向也要成立**：这一行上「别的」改写必须照旧生效。`不可禁用` 只管 `禁用`，
    对手把这一行的效果清空照样得清得掉。只验正方向的话，一条**没有条件**、把这一处
    所有请求都拦掉的规则会「两面都通过」——这正是它第一次写出来的样子。
    """

    banner = _fighter("R1", _card(_ban_passive("探针锁")))
    plain = _run(engine, _fighter("L1", _card(_strike_skill("探针锁"))), banner)
    guarded = _run(
        engine,
        _fighter("L1", _card(_strike_skill("探针锁", rules=[entry]))),
        banner,
    )
    used_plain = _count(plain, kind="技能施放后", skill="探针锁")
    used_guarded = _count(guarded, kind="技能施放后", skill="探针锁")
    # 同行别的改写：对手把这一行的 `效果` 清空。没有规则时这一行打不出伤害，
    # 规则放它过去就该一样打不出伤害；被误拦才会打回原样。
    clearer = _fighter("R1", _card(_ban_passive("探针锁", field="效果", value=[])))
    plain_other = _run(engine, _fighter("L1", _card(_strike_skill("探针锁"))), clearer)
    guarded_other = _run(
        engine,
        _fighter("L1", _card(_strike_skill("探针锁", rules=[entry]))),
        clearer,
    )
    same = _damage_taken(guarded_other, "R1") == _damage_taken(plain_other, "R1")
    return (
        "探针锁施展次数（并核同行别的改写照旧生效）",
        used_plain,
        used_guarded,
        used_guarded > used_plain and same,
    )


SCENES = {
    "被选为目标": _scene_targeted,
    "行动条被改写": _scene_action_bar,
    "事件被改写": _scene_event_rewrite,
    "技能被改写": _scene_skill_rewrite,
}


def _params_for(definition: dict) -> dict:
    """取一组能让条件成立、且探针场景能触发的参数。"""

    params: dict[str, object] = {}
    for field, spec in dict(definition.get("字段") or {}).items():
        options = [str(item) for item in spec.get("选项") or []]
        params[field] = options[0] if options else spec.get("默认", "")
    return params


class _载体:
    """只为 `_rules_deny` 造一个「身上带着规则」的东西（真身是参战者或技能行）。"""

    def __init__(self, rules: dict) -> None:
        self.rules = rules


def _overreach(engine, name: str, rule: dict) -> str | None:
    """条件不该匹配的请求必须放过去。

    返回值：`""` = 放过（合格）· 一句话 = 误拦（不合格）· `None` = 这条规则的条件里
    没有标签字面量，**反方向探针做不了**（工具会照实说出来，不再静默跳过）。

    把这条规则的请求标签换掉一项，造一个「条件必然不成立」的请求：`拒绝` 必须变成
    「不拒绝」。**没有这条反方向探针，一条把这一处全部请求都拦掉的规则，与一条名实
    相符的规则在正方向探针里长得一模一样。**
    """

    tags = sorted(probe_tags(rule))
    if not tags:
        return None
    mutated = ["不匹配:探针", *tags[1:]]
    carrier = _载体({name: rule})
    if not engine._rules_deny(None, carrier, str(rule.get("拦截点") or ""), owner=None, tags=tuple(mutated)):
        return ""
    return f"{name}：条件不匹配的请求也被拦（{'、'.join(mutated)}）"


def main() -> int:
    layer = json.loads(REGISTRY.read_text(encoding="utf-8"))
    services = build_game_services()
    problems: list[str] = []
    try:
        engine = services.core.combat._require_engine()
        print(f"规则层行为验证：{len(layer)} 条规则")
        for name, definition in sorted(layer.items()):
            point = str(definition.get("拦截点") or "")
            scene = SCENES.get(point)
            if scene is None:
                problems.append(f"{name} 的拦截点没有标准探针场景：{point}")
                continue
            params = _params_for(definition)
            entry = {"名称": name, **params}
            rule = expand_rule(name, params, layer)
            try:
                label, plain, guarded, ok = scene(engine, entry, rule)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{name}：探针跑不起来（{type(exc).__name__}: {exc}）")
                continue
            print(f"  {name:<16} {label}：没有规则 {plain:.0f} → 声明后 {guarded:.0f}")
            if plain == guarded:
                problems.append(f"{name}：声明前后完全一样，探针没有区分度")
            elif not ok:
                problems.append(f"{name} 名不副实：{label} {plain:.0f} → {guarded:.0f}")
            overreach = _overreach(engine, name, rule)
            if overreach is None:
                print(f"  {'':<16} 条件里没有标签字面量：反方向探针跳过")
            else:
                print(f"  {'':<16} 条件不匹配的请求：{'误拦' if overreach else '放过'}")
                if overreach:
                    problems.append(overreach)
    finally:
        services.core.database.close()
    if problems:
        print(f"规则名不副实 {len(problems)} 处")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("规则层行为验证通过：每条规则都有作用，且只在声明它的载体上起作用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
