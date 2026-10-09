"""换种族丹审查：丹里写的目标种族必须真的存在，且换完上限的变化是自洽的。

机制：特殊丹的 `使用效果.类型` 声明为 `转变种族`、并给出 `目标种族`（必填字段由使用效果契约在
装载期校验）。服下之后人物只改 `种族` 一个字段——天生规则、卡池来源、成长修正、寿元系数都是按
种族现算的派生值，所以自动跟着换；寿元上限随新种族重算，年龄由 `_clamp_age` 保证不越界。

本判据守两件事：

1. **目标种族必须已登记**：丹里写了一个不存在的种族名，玩家服下去只会得到一句报错，
   而这类错在装载期是看不出来的（契约只校验字段在不在，不校验值对不对）；
2. **换完的寿元上限自洽**：按真实数据算「境界寿元 × 新种族系数」，
   并确认 `_clamp_age` 在换到矮寿种族时把年龄收进新上限（换种族最危险的就是这一步）。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查换种族丹.py

**退出码：0 = 干净，1 = 有违规。**
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections.abc import Mapping

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.character.service import _clamp_age  # noqa: E402

DATA = ROOT / "data"
PILL_DIR = DATA / "物品" / "炼丹" / "内容" / "丹药"


def _races() -> dict[str, float]:
    rows = json.loads((DATA / "角色" / "规则" / "种族" / "种族.json").read_text(encoding="utf-8"))
    return {
        str(row.get("种族")): float(row.get("寿元系数") or 1.0)
        for row in rows
        if isinstance(row, Mapping) and row.get("种族")
    }


def _pills() -> list[tuple[pathlib.Path, Mapping[str, object]]]:
    out: list[tuple[pathlib.Path, Mapping[str, object]]] = []
    for path in sorted(PILL_DIR.rglob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        for row in body if isinstance(body, list) else [body]:
            if not isinstance(row, Mapping):
                continue
            effect = row.get("使用效果")
            if isinstance(effect, Mapping) and effect.get("类型") == "转变种族":
                out.append((path, row))
    return out


def check_target_race() -> list[str]:
    races = _races()
    pills = _pills()
    problems: list[str] = []
    if not pills:
        problems.append("一枚换种族丹都没有——判据等于没跑")
    for path, row in pills:
        effect = row.get("使用效果")
        target = str((effect or {}).get("目标种族") or "").strip()
        where = f"{path.relative_to(ROOT)} {row.get('编号')} {row.get('名称')}"
        if not target:
            problems.append(f"{where}：没有写目标种族")
        elif target not in races:
            problems.append(f"{where}：目标种族「{target}」不在种族登记表里")
    return problems


def check_cap_after_switch() -> list[str]:
    realms = json.loads((DATA / "角色" / "内容" / "境界.json").read_text(encoding="utf-8"))
    factors = sorted(set(_races().values()))
    if len(factors) < 2:
        return ["种族寿元系数只有一档，换种族不会改上限——判据等于没跑"]
    problems: list[str] = []
    rows = realms if isinstance(realms, list) else list(realms.values())
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("寿元"):
            continue
        base = int(row["寿元"])
        short = round(base * factors[0])
        long = round(base * factors[-1])
        age, full = _clamp_age(10_000, short)
        if age != short or not full:
            problems.append(f"{row.get('名称')}：换到矮寿种族后年龄应收进 {short}，实为 {age} / {full}")
        age2, full2 = _clamp_age(10_000, long)
        if age2 != min(10_000, long) or full2 != (10_000 >= long):
            problems.append(f"{row.get('名称')}：换到长寿种族后年龄算错")
    return problems


CHECKS = (
    ("目标种族已登记", check_target_race),
    ("换完的上限自洽", check_cap_after_switch),
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
        print(f"换种族丹审查失败：{failed} 项")
        return 1
    print("换种族丹审查通过：目标种族都在册，换完上限自洽")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
