"""卡名全库唯一：三处撞车的各给一个贴合环境的新名字。

## 为什么是这三处

第 74 轮把**能力名**（短名 / 全名）做成全库唯一时，留下的三处是**卡名**重复，当时
「要不要一并改，等负责人一句话」。第 76 轮负责人给了话：一并改。

实测全库编号实体 3615 个、名称 3612 个，撞车**正好这三处**：

| 旧名 | 撞在哪 | 谁改 | 新名 |
| --- | --- | --- | --- |
| `破格` | 气机 420013 / 伤势 620007 | **伤势**（气机那条是 `破格率` 属性的短名，`格挡破格`、`破格格减` 这些同族气机名都从它派生） | `格蚀` |
| `移星易宿` | 真意 410155 / 器律 700019 | **器律**（真意那条的词条叫 `移星裂意`，名字已经长在这张卡的池子上了） | `洗锋回元` |
| `婴变滞涩` | 伤势 621203 / 621210（同一境界的两个方向） | **621203**（621210 是「婴变 × 滞涩」那一格的本来名字） | `本命飘摇` |

三处新名字在全库 JSON 里一次都没出现过（实测 0 命中），所以不会造出新的撞车。

## 改哪些字段

* `名称`；
* `说明` 里的旧名（外来伤势是 `[破格]是…`，器律是 `器律[移星易宿]：…`，境界自生是
  `…留下的婴变滞涩。`——240 件自生伤势的说明是同一个模板，换名照模板走）；
* 外来伤势的 `匹配状态`（它与 `名称` 同值，且服务启动时要求 20 件互不重复）；
* 器律的 `能力[].名称` 前缀（`移星易宿（转事）` → `洗锋回元（转事）`——这套命名本来
  就是「卡名（词条）」）。

**派生名跟着走、词条名不动**：621203 的说明与 621210 的说明本来是「全名 / 去境界前缀」
两种模板，改完各自回到自己那一档（1~6 向写全名，7~12 向去前缀）。

幂等：三处都已是新名时报「已无撞名」，不写盘。

用法：
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/卡名去重.py            # 试算
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/卡名去重.py --落盘
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: 编号 → 改名规格。`改能力前缀` / `改匹配状态` 决定除了 `名称` 还要不要动别的字段。
改名表: dict[str, dict[str, Any]] = {
    "700019": {"旧": "移星易宿", "新": "洗锋回元", "改能力前缀": True},
    "620007": {"旧": "破格", "新": "格蚀", "改匹配状态": True},
    "621203": {"旧": "婴变滞涩", "新": "本命飘摇"},
}


def 改实体(实体: dict[str, Any], 规格: dict[str, Any]) -> list[str] | None:
    """按规格改一张卡；不是这张卡（或已经改过）返回 `None`。"""

    当前 = str(实体.get("名称") or "")
    if 当前 not in (规格["旧"], 规格["新"]):
        return None
    改动: list[str] = []
    if 当前 == 规格["旧"]:
        实体["名称"] = 规格["新"]
        改动.append(f"名称 {规格['旧']}→{规格['新']}")
    说明 = 实体.get("说明")
    if isinstance(说明, str) and 规格["旧"] in 说明:
        实体["说明"] = 说明.replace(规格["旧"], 规格["新"])
        改动.append("说明")
    if 规格.get("改匹配状态") and str(实体.get("匹配状态") or "") == 规格["旧"]:
        实体["匹配状态"] = 规格["新"]
        改动.append("匹配状态")
    if 规格.get("改能力前缀"):
        for 节点 in 实体.get("能力") or ():
            if not isinstance(节点, dict):
                continue
            名 = str(节点.get("名称") or "")
            if 名.startswith(规格["旧"]):
                节点["名称"] = 规格["新"] + 名[len(规格["旧"]) :]
                改动.append(f"能力名 {名}→{节点['名称']}")
    return 改动


def 扫描() -> tuple[list[tuple[pathlib.Path, list[str]]], set[str]]:
    """返回（要写的文件与改动，见过的编号）。"""

    待写: list[tuple[pathlib.Path, list[str]]] = []
    见过: set[str] = set()
    for path in sorted((ROOT / "data").rglob("*.json")):
        相对 = path.relative_to(ROOT).as_posix()
        if "/定义/" in f"/{相对}" or "/规则/" in f"/{相对}":
            continue
        try:
            文档 = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        条目 = 文档 if isinstance(文档, list) else [文档]
        改动: list[str] = []
        for 实体 in 条目:
            if not isinstance(实体, dict):
                continue
            编号 = str(实体.get("编号") or "")
            规格 = 改名表.get(编号)
            if 规格 is None:
                continue
            见过.add(编号)
            结果 = 改实体(实体, 规格)
            if 结果:
                改动.extend(f"{编号} {x}" for x in 结果)
        if 改动:
            待写.append((path, 改动))
    return 待写, 见过


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--落盘", action="store_true", help="真的写回数据")
    args = parser.parse_args()

    待写, 见过 = 扫描()
    缺 = sorted(set(改名表) - 见过)
    if 缺:
        print(f"这 {len(缺)} 个编号没找到实体：{'、'.join(缺)}")

    print(f"要改 {len(待写)} 个文件：")
    for path, 改动 in 待写:
        print(f"  {path.relative_to(ROOT).as_posix()}")
        for 条 in 改动:
            print(f"      {条}")

    if not 待写:
        print("已无撞名，不写盘")
        return 0
    if not args.落盘:
        print("（试算）加 --落盘 才会写入")
        return 0
    for path, _改动 in 待写:
        文档 = json.loads(path.read_text(encoding="utf-8"))
        条目 = 文档 if isinstance(文档, list) else [文档]
        for 实体 in 条目:
            if isinstance(实体, dict):
                规格 = 改名表.get(str(实体.get("编号") or ""))
                if 规格 is not None:
                    改实体(实体, 规格)
        path.write_text(
            json.dumps(文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"已写入 {len(待写)} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
