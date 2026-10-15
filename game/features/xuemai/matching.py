"""血脉匹配：普通血脉看区间条件，天外看数字形态。两套互不干涉。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from game.core.data import JsonDataError, mapping as require_mapping, strict_text as _text

#: DNA 的组数（12 位 = 6 组，每组 0~99）。
GROUPS = 6

#: 天外的十种数字形态（必须与 data/玩法/血脉/规则/血脉.json 的写法逐字一致）。
_SHAPES = (
    "六组全奇",
    "六组全偶",
    "六组依次递增（顺子）",
    "六组依次递减",
    "首尾相同（G1=G6）",
    "首尾互补（G1+G6=99）",
    "G1、G3、G5 个位相同",
    "回文（G1=G6 且 G2=G5）",
    "任三组相同",
    "六组全同（组6 手调触发）",
)


@dataclass(frozen=True)
class Bloodline:
    """一条血脉定义。"""

    code: str
    name: str
    strength: str
    awake: bool
    conditions: tuple[tuple[int, int, int], ...]
    """普通血脉的区间条件：(组序号1起, 下限含, 上限不含)。"""

    shape: str
    """天外的形态名；普通血脉为空串。"""

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


def match_shape(groups: Sequence[int], shape: str) -> bool:
    """按数字形态匹配。"""

    g = list(groups)
    if shape == "六组全奇":
        return all(v % 2 == 1 for v in g)
    if shape == "六组全偶":
        return all(v % 2 == 0 for v in g)
    if shape == "六组依次递增（顺子）":
        return all(g[i] < g[i + 1] for i in range(GROUPS - 1))
    if shape == "六组依次递减":
        return all(g[i] > g[i + 1] for i in range(GROUPS - 1))
    if shape == "首尾相同（G1=G6）":
        return g[0] == g[-1]
    if shape == "首尾互补（G1+G6=99）":
        return g[0] + g[-1] == 99
    if shape == "G1、G3、G5 个位相同":
        return g[0] % 10 == g[2] % 10 == g[4] % 10
    if shape == "回文（G1=G6 且 G2=G5）":
        return g[0] == g[5] and g[1] == g[4]
    if shape == "任三组相同":
        return max(Counter(g).values()) >= 3
    if shape == "六组全同（组6 手调触发）":
        return len(set(g)) == 1
    raise JsonDataError("未知血脉形态：%s" % shape)


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
            shape = "" if not outer else _text(item.get("形态"), "%s[%d].形态" % (block, index))
            if outer and shape not in _SHAPES:
                raise JsonDataError("%s[%d] 未知形态：%s" % (block, index, shape))
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
                    shape=shape,
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
            else match_shape(groups, b.shape)
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