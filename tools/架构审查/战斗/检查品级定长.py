"""判据：品级必须是定长 2（中文名恰好 2 字、编号恰好 2 位）。

统一语法 <品级><物品>[<灵宝>] 靠「品级定长、连写不分隔」才可解析——
一旦有人加一个 3 字的品级，id 形态与中文形态的边界就糊了。这条把前提钉死。
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
GRADE_TABLE = ROOT / "data/基础/定义/品级.json"
WIDTH = 2


def main() -> int:
    rows = json.loads(GRADE_TABLE.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        print("品级表为空或不是数组", GRADE_TABLE)
        return 1
    broken: list[str] = []
    for row in rows:
        number = str(row.get("编号") or "")
        name = str(row.get("名称") or "")
        if len(number) != WIDTH or not number.isdigit():
            broken.append("编号不是 2 位数字：" + number)
        if len(name) != WIDTH:
            broken.append("名称不是 2 字：" + name)
    if broken:
        print("品级定长（2 字 / 2 位）：", len(broken), "处不合规")
        for one in broken:
            print("   ", one)
        return 1
    print("品级定长（2 字 / 2 位）：", len(rows), "档全部合规")
    return 0


if __name__ == "__main__":
    sys.exit(main())