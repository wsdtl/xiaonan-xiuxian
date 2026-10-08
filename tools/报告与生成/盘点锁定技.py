"""锁定技盘点：每条登记规则在**真实内容**下还能不能被触发。

仓库已有的 `tools/行为验证/验证规则层.py` 用**合成探针**证明「引擎机能逐条成立」；
但它故意不走 `data/` 里的内容，所以抓不到另一类问题——**内容根本不会发出这类请求**。
本脚本补的正是这一格。口径与边界见 `tools/库/锁定技可达性.py`（与判据共用同一份模型）。

    .venv/Scripts/python.exe -X utf8 tools/报告与生成/盘点锁定技.py
    .venv/Scripts/python.exe -X utf8 tools/报告与生成/盘点锁定技.py --输出 _输出/锁定技可达性.md

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--输出", default="", help="写进文件；默认打到标准输出")
    args = parser.parse_args()

    got, scopes = model.reachable(model.nodes())
    layer = model.rules()
    out: list[str] = ["# 锁定技可达性盘点", "", "## 各拦截点的内容侧发出者", "",
                      "| 拦截点 | 可达来源关系 | 发出范围分布 |", "| --- | --- | --- |"]
    for point in model.EMITTERS:
        out.append("| %s | %s | %s |" % (point, "/".join(sorted(got[point])), str(scopes[point])))

    usage: collections.Counter = collections.Counter()
    dead: collections.Counter = collections.Counter()
    affected: set[str] = set()
    total = 0
    for race in model.races():
        for entry in (race.get("天生规则") or []):
            name = str(entry.get("名称"))
            total += 1
            rule = layer.get(name) or {}
            point = str(rule.get("拦截点") or "?")
            direction = model.rule_direction(rule, entry.get("来源"))
            usage[(point, name, direction)] += 1
            if direction != "不限" and direction not in got.get(point, set()):
                dead[(point, name, direction)] += 1
                affected.add(str(race.get("编号")))

    out += ["", "## 不可达组合", "",
            "| 拦截点 | 规则 | 载体填的方向 | 被几个种族使用 |", "| --- | --- | --- | --- |"]
    for (point, name, direction), count in sorted(dead.items(), key=lambda kv: -kv[1]):
        out.append("| %s | %s | %s | %d |" % (point, name, direction, count))
    out += ["", "## 汇总", "",
            "- 种族 %d 个；天生规则条目 %d 条；涉及 (拦截点,规则,方向) 组合 %d 个"
              % (len(model.races()), total, len(usage)),
            "- 不可达组合 %d 个；受影响种族 %d 个；空转条目 %d 条（%.0f%%）"
              % (len(dead), len(affected), sum(dead.values()),
                 100 * sum(dead.values()) / total if total else 0),
            "- 口径：拿不准的方向一律算可达，所以这张表是**下界**。"]

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
