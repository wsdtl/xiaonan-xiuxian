"""血脉匹配：普通血脉看区间条件，天外看数字形态。两套互不干涉。"""

from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from game.core.data import JsonDataError, mapping as require_mapping, strict_text as _text

#: DNA 的组数（12 位 = 6 组，每组 0~99）。
GROUPS = 6

#: 形态判定写成 DNA 表达式（住数据）：记号 G1..G6 是 DNA 的六组，
#: 可用 + - * // % 与比较、且/或/非、链式比较，另有 最多重复数。


@dataclass(frozen=True)
class Bloodline:
    """一条血脉定义。"""

    code: str
    name: str
    strength: str
    awake: bool
    conditions: tuple[tuple[int, int, int], ...]
    """普通血脉的区间条件：(组序号1起, 下限含, 上限不含)。"""

    shape_name: str
    """天外的形态名（给人看的，来自数据）；普通血脉为空串。"""

    judge: str
    """天外的形态判定表达式（来自数据）；普通血脉为空串。"""

    abilities: tuple[Mapping[str, object], ...]
    """战斗原子能力原样保留（固定属性加成 / 条件执行）。

    血脉不解释这些能力——装配与结算交给战斗引擎，血脉只负责"这个 DNA 命中哪些血脉"。
    """

    outer: bool
    """是否天外。"""


@dataclass(frozen=True)
class BloodlineRules:
    """血脉规则全表。"""

    bloodlines: tuple[Bloodline, ...]
    awaken_tiers: tuple[tuple[Decimal, Decimal, Decimal], ...]
    """觉醒档：(下限含, 上限不含, 倍率)，按气血百分比。"""


def parse_dna(dna: str) -> tuple[int, ...]:
    """12 位数字串 → 6 组整数。"""

    text = str(dna or "").strip()
    if len(text) != GROUPS * 2 or not text.isdigit():
        raise JsonDataError("DNA 必须是 12 位数字")
    return tuple(int(text[i : i + 2]) for i in range(0, GROUPS * 2, 2))


def format_dna(groups: Sequence[int]) -> str:
    """6 组整数 → 12 位数字串。"""

    if len(groups) != GROUPS:
        raise JsonDataError("DNA 必须是 6 组")
    return "".join("%02d" % int(value) for value in groups)


def match_shape(groups: Sequence[int], expression: str) -> bool:
    """按数据里的 DNA 表达式匹配数字形态。

    表达式住数据（例如 G1+G6=99 ／ G1<G2<G3<G4<G5<G6 ／ 最多重复数>=3），
    这里只做解释：记号 G1..G6 是 DNA 的六组，可用 + - * // % 与比较、且/或/非、链式比较。
    """

    text = str(expression or "").strip()
    if not text:
        raise JsonDataError("形态判定不能为空")
    names = _dna_names(groups)
    source = text.replace("且", " and ").replace("或", " or ").replace("非", " not ")
    source = re.sub(r"(?<![<>!=])=(?!=)", "==", source)
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise JsonDataError("形态判定写错了：%s" % text) from exc
    return bool(_eval_node(tree, names))


#: 形态表达式里允许出现的记号：
#:   G1..G6      —— 那一组的整组值
#:   G11 G12     —— 第 1 组的第 1 个 / 第 2 个数字（即十位 / 个位）
#:   最多重复数   —— 六组里重复出现最多的次数
def _dna_names(groups: Sequence[int]) -> dict[str, int]:
    names: dict[str, int] = {}
    for index, value in enumerate(groups):
        number = int(value)
        names["G%d" % (index + 1)] = number
        ten, one = divmod(number, 10)
        names["G%d1" % (index + 1)] = ten
        names["G%d2" % (index + 1)] = one
    names["最多重复数"] = max(Counter(int(v) for v in groups).values())
    return names


def _eval_node(node: object, names: Mapping[str, int]) -> object:
    """按白名单解释形态表达式的一个节点（不用 eval）。"""

    if isinstance(node, ast.Expression):
        return _eval_node(node.body, names)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise JsonDataError("形态判定里出现未知记号：%s" % node.id)
        return names[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval_node(node.operand, names)
    if isinstance(node, ast.BoolOp):
        values = [_eval_node(value, names) for value in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, names)
        right = _eval_node(node.right, names)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, (ast.Div, ast.FloorDiv)):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        raise JsonDataError("形态判定里有不允许的运算符")
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, names)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, names)
            if isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, ast.Lt):
                ok = left < right
            elif isinstance(op, ast.LtE):
                ok = left <= right
            elif isinstance(op, ast.Gt):
                ok = left > right
            elif isinstance(op, ast.GtE):
                ok = left >= right
            else:
                raise JsonDataError("形态判定里有不允许的比较")
            if not ok:
                return False
            left = right
        return True
    raise JsonDataError("形态判定里有不允许的写法")

def load_bloodline_rules(dataset: Mapping[str, object]) -> BloodlineRules:
    """装载血脉规则：22 条普通 ＋ 10 件天外 ＋ 觉醒档。"""

    rows: list[Bloodline] = []
    for block, outer in (("普通血脉", False), ("天外", True)):
        value = dataset.get(block)
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise JsonDataError("血脉规则缺少列表：%s" % block)
        for index, raw in enumerate(value):
            item = require_mapping(raw, "%s[%d]" % (block, index))
            conditions: list[tuple[int, int, int]] = []
            if not outer:
                conds = item.get("条件")
                if not isinstance(conds, Sequence) or isinstance(conds, (str, bytes)) or not conds:
                    raise JsonDataError("%s[%d] 至少要有 1 条条件" % (block, index))
                for cond in conds:
                    row = require_mapping(cond, "%s[%d].条件" % (block, index))
                    conditions.append(
                        (int(row.get("组") or 0), int(row.get("下限") or 0), int(row.get("上限") or 0))
                    )
            shape_name = "" if not outer else _text(item.get("形态"), "%s[%d].形态" % (block, index))
            judge = ""
            if outer:
                judge = _text(item.get("判定"), "%s[%d].判定" % (block, index))
                # 装载期就试着解释一次：判定写错了要在这里报，不能带进战斗。
                match_shape(parse_dna("000000000000"), judge)
            abilities: list[Mapping[str, object]] = []
            for ability in item.get("能力") or ():
                abilities.append(require_mapping(ability, "%s[%d].能力" % (block, index)))
            rows.append(
                Bloodline(
                    code=_text(item.get("编号"), "%s[%d].编号" % (block, index)),
                    name=_text(item.get("名称"), "%s[%d].名称" % (block, index)),
                    strength=_text(item.get("强度") or "极强", "%s[%d].强度" % (block, index)),
                    awake=bool(item.get("能觉醒")),
                    conditions=tuple(conditions),
                    shape_name=shape_name,
                    judge=judge,
                    abilities=tuple(abilities),
                    outer=outer,
                )
            )
    tiers: list[tuple[Decimal, Decimal, Decimal]] = []
    for index, raw in enumerate(dataset.get("觉醒档") or ()):
        row = require_mapping(raw, "觉醒档[%d]" % index)
        tiers.append(
            (
                Decimal(str(row.get("下限") or 0)),
                Decimal(str(row.get("上限") or 100)),
                Decimal(_text(row.get("倍率"), "觉醒档[%d].倍率" % index)),
            )
        )
    if not tiers:
        raise JsonDataError("血脉规则缺少觉醒档")
    return BloodlineRules(bloodlines=tuple(rows), awaken_tiers=tuple(tiers))


def matched(rules: BloodlineRules, dna: str) -> tuple[Bloodline, ...]:
    """一个 DNA 命中的全部血脉，按强度从高到低、再按编号排。"""

    groups = parse_dna(dna)
    hit = [
        b
        for b in rules.bloodlines
        if (
            all(lo <= groups[g - 1] < hi for g, lo, hi in b.conditions)
            if not b.outer
            else match_shape(groups, b.judge)
        )
    ]
    order = {"极强": 0, "强": 1, "中": 2, "弱": 3}
    return tuple(sorted(hit, key=lambda b: (order.get(b.strength, 9), b.code)))


def awaken_multiplier(rules: BloodlineRules, hp_percent: Decimal) -> Decimal:
    """按真实气血百分比取觉醒倍率。"""

    for low, high, factor in rules.awaken_tiers:
        if low <= hp_percent < high:
            return factor
    return Decimal("1.0")