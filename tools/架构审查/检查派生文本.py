"""派生文本：数据里不许再出现**抄来的**展示文本。

这次重构（2026-10）把两类抄本从数据里删掉了：

1. 种族实体的 `说明`——它把 `天生规则[]` 与规则层 `卡面` 又抄了一遍。规则一改说明就漂，
   上一轮为此写了脚本重建 103 条；现在风味句住展示数据集、本相/代价装载时合成；
2. 方向参数——规则条件写 `来源关系:$来源` 时方向由载体填，填错就变死规则。现在方向自带。

判据要拦住的是「抄本回来」，四项：

1. **种族实体不得有 `说明` 字段**（派生文本的老家）；
2. **数据里不得出现填好的「本相：/代价：」**——带 `{本相}` / `{代价}` 占位符的模板允许（那正是
   展示数据集里的那一份，唯一出处）；
3. **数据里不得出现规则层 `卡面` 原文**——只拿「卡面与规则名不同」的那些当指纹（卡面恰好等于名字的，
   载体里写的是合法引用，不是抄本）；
4. **风味句只许住在展示数据集**（`角色/展示/文本.json` 的 `风味` 节）。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查派生文本.py

**退出码：0 = 没有派生文本，1 = 有抄本。**
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RACE_FILE = DATA / "角色" / "规则" / "种族" / "种族.json"
LAYER_FILE = DATA / "战斗" / "定义" / "规则层.json"
COPY_FILE = DATA / "角色" / "展示" / "文本.json"
FLAVOR_SECTION = "风味"


def _data_files() -> list[pathlib.Path]:
    return sorted(p for p in DATA.rglob("*.json"))


def _layer() -> dict:
    return json.loads(LAYER_FILE.read_text(encoding="utf-8"))


def check_race_summary_absent() -> list[str]:
    """检查 1：种族实体不得有 `说明` 字段。"""

    rows = json.loads(RACE_FILE.read_text(encoding="utf-8"))
    return [
        "种族 %s 又带上了 说明：派生文本要由 `天生规则[]` + `卡面` 合成，不许落库" % row.get("种族")
        for row in rows
        if "说明" in row
    ]


def check_no_filled_sentence() -> list[str]:
    """检查 2：数据里不得出现填好的「本相：/代价：」（模板允许）。"""

    problems: list[str] = []
    for path in _data_files():
        rel = path.relative_to(ROOT).as_posix()
        for line in path.read_text(encoding="utf-8").splitlines():
            for key in ("本相：", "代价："):
                if key not in line:
                    continue
                if "{本相}" in line or "{代价}" in line:
                    continue
                problems.append("%s 抄了填好的句子：%s" % (rel, line.strip()[:48]))
    return problems


def _face_prints() -> dict[str, str]:
    """当指纹用的卡面：只取与规则名不同的那些（名字是载体里的合法引用）。"""

    prints: dict[str, str] = {}
    for name, row in _layer().items():
        base = str(row.get("卡面") or name).split("（来源")[0]
        if base != str(name) and len(base) >= 4:
            prints[base] = str(name)
    return prints


def check_no_face_copy() -> list[str]:
    """检查 3：数据里不得出现规则层卡面原文。"""

    prints = _face_prints()
    problems: list[str] = []
    for path in _data_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel == LAYER_FILE.relative_to(ROOT).as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        for base, name in prints.items():
            if base in text:
                problems.append("%s 出现规则 %s 的卡面原文「%s」" % (rel, name, base))
    return problems


def check_flavor_home() -> list[str]:
    """检查 4：风味句只许住在展示数据集。"""

    copy = json.loads(COPY_FILE.read_text(encoding="utf-8"))
    flavors = [str(v) for v in (copy.get(FLAVOR_SECTION) or {}).values()]
    allowed = COPY_FILE.relative_to(ROOT).as_posix()
    problems: list[str] = []
    for path in _data_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel == allowed:
            continue
        text = path.read_text(encoding="utf-8")
        for flavor in flavors:
            if len(flavor) >= 6 and flavor in text:
                problems.append("%s 出现风味句「%s」——它只该住在展示数据集" % (rel, flavor[:24]))
    return problems


CHECKS = (
    ("种族实体没有 说明", check_race_summary_absent),
    ("没有填好的本相/代价句", check_no_filled_sentence),
    ("没有卡面原文抄本", check_no_face_copy),
    ("风味句只住展示数据集", check_flavor_home),
)


def main() -> int:
    failed = 0
    for label, check in CHECKS:
        problems = check()
        if problems:
            failed += 1
            print("  [%d 处] %s" % (len(problems), label))
            for line in problems[:6]:
                print("        " + line)
        else:
            print("  [干净] %s" % label)
    if failed:
        print("派生文本审查失败：%d 项" % failed)
        return 1
    print("派生文本审查通过：展示文本只有一个出处，数据里没有抄本")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
