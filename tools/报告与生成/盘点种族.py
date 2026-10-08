"""种族盘点：180 个种族的强度画像，以及「名义规则数 vs 实际可达」。

改种族之前先留一份读数，改完再留一份，两份对照才谈得上「重评」。
口径见 `tools/库/锁定技可达性.py`：不可达的规则在当前内容下永远触发不了，
所以一个种族真正拿到的本相/代价数，要看**可达**那一列，不是天生规则的总条数。

画像摊开四样：出现档次数、天生规则条数（分可达 / 不可达）、成长修正、寿元系数；
另按族系与档次各给一张汇总表。**成长修正合计 = 各项 (倍率 − 1) 之和**，只作横向比较用。

    .venv/Scripts/python.exe -X utf8 tools/报告与生成/盘点种族.py
    .venv/Scripts/python.exe -X utf8 tools/报告与生成/盘点种族.py --输出 _输出/种族基准/改前.md

**退出码恒为 0**：这是盘点报告，判定归判据。
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys as _sys

_sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "库"))

import 锁定技可达性 as model

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _dead_names(race: dict, layer: dict, got: dict[str, set[str]]) -> list[str]:
    dead: list[str] = []
    for entry in (race.get("天生规则") or []):
        name = str(entry.get("名称"))
        rule = layer.get(name) or {}
        point = str(rule.get("拦截点") or "?")
        direction = model.rule_direction(rule, entry.get("来源"))
        if direction != "不限" and direction not in got.get(point, set()):
            dead.append(name)
    return dead


def _growth(race: dict) -> float:
    return sum(float(v) - 1 for v in (race.get("成长修正") or {}).values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--输出", default="", help="写进文件；默认打到标准输出")
    args = parser.parse_args()

    got, _ = model.reachable(model.nodes())
    layer = model.rules()
    races = model.races()

    per_family: dict[str, list] = collections.defaultdict(lambda: [0, 0, 0, 0.0, 0.0])
    per_tier: collections.Counter = collections.Counter()
    pool: collections.Counter = collections.Counter()
    rows: list[str] = []
    total_rules = total_dead = 0
    for race in races:
        rules_ = list(race.get("天生规则") or [])
        dead = _dead_names(race, layer, got)
        total_rules += len(rules_)
        total_dead += len(dead)
        tiers = [str(t) for t in (race.get("出现档次") or [])]
        for tier in tiers:
            per_tier[tier] += 1
        pool[str(race.get("卡池来源") or "默认（敌方修士）")] += 1
        family = str(race.get("族系") or "未标")
        stat = per_family[family]
        stat[0] += 1; stat[1] += len(rules_); stat[2] += len(dead)
        stat[3] += float(race.get("寿元系数") or 0); stat[4] += _growth(race)
        rows.append("| %s | %s | %s | %s | %d | %d | %g | %+g |" % (
            race.get("编号"), race.get("种族"), family, "/".join(tiers),
            len(rules_), len(dead), float(race.get("寿元系数") or 0), _growth(race)))

    out: list[str] = [
        "# 种族盘点", "",
        "- 种族 %d 个；族系 %d 个；天生规则条目 %d 条，其中**不可达 %d 条**（%.0f%%）"
          % (len(races), len(per_family), total_rules, total_dead,
             100 * total_dead / total_rules if total_rules else 0),
        "- 卡池来源：%s（没写就是默认）" % dict(pool.most_common()),
        "- 成长修正合计 = 各项 (倍率 − 1) 之和，只作横向比较。",
        "", "## 按族系", "",
        "| 族系 | 种族 | 规则 | 其中不可达 | 平均寿元 | 成长修正合计 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for family, stat in sorted(per_family.items(), key=lambda kv: -kv[1][2]):
        out.append("| %s | %d | %d | %d | %.1f | %+.1f |"
                   % (family, stat[0], stat[1], stat[2], stat[3] / stat[0], stat[4]))
    out += ["", "## 按出现档次（有多少种族能出现在该档次）", "",
            "| 档次 | 种族数 |", "| --- | --- |"]
    for tier, count in per_tier.most_common():
        out.append("| %s | %d |" % (tier, count))
    out += ["", "## 逐条", "",
            "| 编号 | 种族 | 族系 | 出现档次 | 规则 | 其中不可达 | 寿元系数 | 成长修正合计 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    out += rows

    text = chr(10).join(out) + chr(10)
    if args.输出:
        target = pathlib.Path(args.输出)
        if not target.is_absolute():
            target = ROOT / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print("已写入 %s" % target)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
