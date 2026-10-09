"""寿元边界审查：年龄永远不越界，且上限变化时两边自洽。

年龄是展示值，但它有两个真边界：

1. **努力不够**：life修行岁数迟早会把上限用满（尤其矮寿种族 × 低境界）；
2. **上限会变**：换种族（寿元系数 0.6~10.0，落差 **16.7 倍**）或突破换境界，上限当场变大变小。

规则只有一条（`game/core/character/service.py` 的 `_clamp_age`）：

    life = 起点 + 修行日数 × 比例        一生活过多少年，不设上限
    上限 = 境界寿元 × 种族寿元系数        会随境界/种族变
    年龄 = min(life, 上限)               展示值，恒不越界
    将尽 = life >= 上限                  上限被用满

于是：上限被压低（换矮寿种族）→ 年龄 = 新上限、标记将尽；上限被抬高（换长寿种族或突破）→
**之前被上限盖住的年岁放回来**，年龄 = life。本判据用**真实数据**的全表（13 个境界 × 14 档系数）验这两件事。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查寿元边界.py

**退出码：0 = 边界自洽，1 = 有越界或不可逆。**
"""

from __future__ import annotations

import pathlib
import sys
from collections.abc import Mapping

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.character.service import _clamp_age  # noqa: E402

DATA = ROOT / "data"


def _caps() -> list[tuple[str, int, float, int]]:
    """真实数据里的全部（境界, 寿元, 种族系数, 上限）组合。"""

    import json

    realms = json.loads((DATA / "角色" / "内容" / "境界.json").read_text(encoding="utf-8"))
    races = json.loads((DATA / "角色" / "规则" / "种族" / "种族.json").read_text(encoding="utf-8"))
    factors = sorted({float(r.get("寿元系数") or 1.0) for r in races if isinstance(r, Mapping)})
    rows = realms if isinstance(realms, list) else list(realms.values())
    out: list[tuple[str, int, float, int]] = []
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("寿元"):
            continue
        for factor in factors:
            out.append((str(row.get("名称")), int(row["寿元"]), factor, round(int(row["寿元"]) * factor)))
    return out


def check_never_over() -> list[str]:
    """任何life下，年龄都不许超过上限。"""

    problems: list[str] = []
    table = _caps()
    if len(table) < 100:
        problems.append(f"真实组合只有 {len(table)} 条，判据等于没跑")
    for name, base, factor, cap in table:
        for life in (0, 1, cap - 1, cap, cap + 1, cap * 3, 100000):
            age, full = _clamp_age(life, cap)
            if age > cap or age < 0:
                problems.append(f"{name} ×{factor} 上限 {cap}：life {life} 得到年龄 {age}，越界")
            if (life >= cap) != full:
                problems.append(f"{name} ×{factor} 上限 {cap}：life {life} 的「将尽」标记应为 {life >= cap}")
    return problems


def check_switch_race() -> list[str]:
    """换种族两个方向都要自洽：压低不小越界，抬高把年岁放回来。"""

    problems: list[str] = []
    table = _caps()
    if not table:
        return ["拿不到真实组合"]
    low = min(cap for *_rest, cap in table)
    high = max(cap for *_rest, cap in table)
    # 一生life 500 年：先活在长寿上限里，再换到矮寿上限，再换回来。
    life = 500
    first, _ = _clamp_age(life, high)
    if first != life:
        problems.append(f"上限 {high} 下life {life} 应原样展示，实为 {first}")
    dropped, full_low = _clamp_age(life, low)
    if dropped != low or not full_low:
        problems.append(f"上限压低到 {low} 后应为 {low} 且标记将尽，实为 {dropped} / {full_low}")
    back, full_back = _clamp_age(life, high)
    if back != life or full_back:
        problems.append(f"上限抬回 {high} 后应把年岁放回来（{life}），实为 {back} / {full_back}")
    # 退化输入：上限 0 或负数不许抛出、不许越界。
    zero_age, zero_full = _clamp_age(life, 0)
    if zero_age != 0 or not zero_full:
        problems.append(f"上限 0 应收成 0 并标记将尽，实为 {zero_age} / {zero_full}")
    return problems


CHECKS = (
    ("年龄永不越界", check_never_over),
    ("换种族两个方向自洽", check_switch_race),
)


def main() -> int:
    failed = 0
    for label, check in CHECKS:
        problems = check()
        if problems:
            failed += 1
            print(f"  [{len(problems)} 处] {label}")
            for line in problems[:6]:
                print("        " + line)
        else:
            print(f"  [干净] {label}")
    if failed:
        print(f"寿元边界审查失败：{failed} 项")
        return 1
    print("寿元边界审查通过：年龄永不越界，上限变化两个方向都自洽")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
