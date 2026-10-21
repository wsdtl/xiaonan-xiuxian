# -*- coding: utf-8 -*-
"""百分比增幅的出处判据：只有意境能写「百分比 + 参战者属性」。

为什么要有它：对基础属性（血气、精神、神魂、攻击、防御）的百分比增幅，
现在只由意境与血脉提供，且只作用在成长值上——战斗里补的是
「成长那一份 ×（系数 − 1）」。如果哪天功法、丹药也开始写「百分比 + 参战者属性」，
就会绕过这条铁律，直接放大基础值，数值立刻失控。

判据只看数据：凡是 口径=百分比 且 归属=参战者属性 的条目，
只允许出现在 战斗/内容/意境/ 下。血脉的增幅在代码里算（按气血取觉醒倍数），
不落数据，所以不在这条判据的检查范围。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/战斗/检查百分比出处.py

退出码：0 = 出处正确，1 = 有越界。
"""
from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
ALLOWED_PREFIX = "战斗/内容/意境/"


def _walk(node, path, found):
    if isinstance(node, dict):
        if str(node.get("口径") or "") == "百分比" and str(node.get("归属") or "") == "参战者属性":
            found.append(path)
        for key, value in node.items():
            _walk(value, f"{path}.{key}", found)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _walk(item, f"{path}[{index}]", found)


def main() -> int:
    problems = []
    for path in sorted(DATA.rglob("*.json")):
        if path.name == "组件.json":
            continue
        relative = path.relative_to(DATA).as_posix()
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        found = []
        _walk(value, "", found)
        if not found:
            continue
        if relative.startswith(ALLOWED_PREFIX):
            continue
        problems.append(f"{relative}：{len(found)} 处百分比增幅")
    if problems:
        print("百分比增幅出现在意境之外：")
        for item in problems:
            print("  " + item)
        print()
        print("对基础属性的百分比只允许住意境；功法与丹药请用数值加成。")
        return 1
    print("百分比出处审查通过：只有意境写百分比增幅")
    return 0


if __name__ == "__main__":
    sys.exit(main())