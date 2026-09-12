"""补第二维（限额）：给「限额塌陷且监听≥2」的卡把上限取值散开。

完成度指标里「两面同模」有 168 张，其中 66 张塌的是**限额取值**——卡里有多个监听节点，
但它们的 `每次行动最多触发` 全是同一个数。监听本来就多于一个，把档位按**事件实测频次**
分开即可（同一张卡的不同事件本来就有不同的发生频率，用同一个上限反而是没做功课）。

档值来源：`tools/限额分档.py` 的 `BANDS`（由 `tools/事件频次.py` 的实测平均次数分档）。

    .venv/Scripts/python.exe -X utf8 tools/补第二维限额.py            # 试算
    .venv/Scripts/python.exe -X utf8 tools/补第二维限额.py --写入 --授权集 _授权.json

**退出码：0 = 正常，2 = 没找到可改处。**
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SURFACES = (
    ("功法", "data/战斗/内容/功法/功法-*.json"),
    ("真意", "data/战斗/内容/真意/真意-*.json"),
    ("气机", "data/战斗/内容/气机/气机-*.json"),
    ("器律", "data/炼器/内容/器律-*.json"),
)
CAP_FIELD = "每次行动最多触发"
MEASURED_MEAN = {
    "技能冷却变化后": 2.20, "获得护盾后": 2.13, "获得护盾前": 1.99,
    "资源恢复前": 1.84, "资源恢复后": 1.84, "资源变化后": 1.60,
    "添加状态前": 1.46, "添加状态后": 1.46, "恢复前": 1.45, "事件转化后": 1.42,
    "战场规则变化后": 1.36, "技能变化后": 1.32, "命中判定前": 1.23, "命中后": 1.23,
    "造成伤害前": 1.23, "造成伤害后": 1.23, "受到伤害后": 1.23,
    "移除状态后": 1.22, "行动条变化后": 1.22, "技能冷却完成后": 1.18,
}


def band_of(event: str, current: int) -> int | None:
    """按实测频次给档；只对**有实测数据**的事件动手，且必须与原值不同。"""
    mean = MEASURED_MEAN.get(event)
    if mean is None:
        return None
    value = math.ceil(mean) + 1 if mean < 1.5 else math.ceil(mean) + 2
    value = max(2, min(5, value))
    return None if value == current else value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--写入", action="store_true", help="默认只试算，加这个才落盘")
    parser.add_argument("--授权集", default="", help="把授权卡清单写到这个 json")
    args = parser.parse_args()

    total: collections.Counter = collections.Counter()
    grant: dict[str, list[str]] = {}
    for _section, pattern in SURFACES:
        for path in sorted(ROOT.glob(pattern)):
            entries = json.loads(path.read_text(encoding="utf-8"))
            cards: list[str] = []
            for entry in entries:
                listeners: list[dict] = []
                sources: set[str] = set()

                def walk(node: object) -> None:
                    if isinstance(node, dict):
                        ability = str(node.get("能力") or "")
                        if ability == "监听事件":
                            listeners.append(node)
                        elif ability == "读取数值":
                            sources.add(str(node.get("来源") or "固定值"))
                        for value in node.values():
                            walk(value)
                    elif isinstance(node, list):
                        for value in node:
                            walk(value)

                walk(entry)
                if len(listeners) < 2:
                    continue
                caps = {str(node.get(CAP_FIELD, "（无）")) for node in listeners}
                if len(caps) > 1:
                    continue  # 限额这一维没塌，不归本工具管
                changed = 0
                for node in listeners:
                    current = int(node.get(CAP_FIELD, 1) or 1)
                    value = band_of(str(node.get("事件") or ""), current)
                    if value is not None:
                        node[CAP_FIELD] = value
                        changed += 1
                if changed and len({str(n.get(CAP_FIELD)) for n in listeners}) > 1:
                    total["改"] += changed
                    cards.append(str(entry["编号"]))
            if cards:
                grant[path.relative_to(ROOT).as_posix()] = sorted(cards)
                if args.写入:
                    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")

    if not total:
        print("没找到可改处。")
        return 2
    print(f"改动 {total['改']} 个限额节点 · 涉及 {sum(len(v) for v in grant.values())} 张卡")
    if args.授权集:
        pathlib.Path(args.授权集).write_text(
            json.dumps(grant, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"授权集写入 {args.授权集}")
    if not args.写入:
        print("这是试算；确认后再加 --写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
