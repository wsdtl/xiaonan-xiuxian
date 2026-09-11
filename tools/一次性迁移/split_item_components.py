"""Split the legacy item component into basic materials and alchemy products."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def main() -> None:
    old = DATA / "基础物品"
    basic = DATA / "基础物品"
    alchemy = DATA / "炼丹"
    if not old.exists():
        raise SystemExit("data/物品 不存在")
    if basic.exists():
        raise SystemExit("data/基础物品 已存在")
    shutil.copytree(old, basic)
    medicine = basic / "内容" / "丹药"
    target = alchemy / "内容" / "丹药"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(medicine), str(target))
    shutil.rmtree(old)

    basic_manifest = basic / "组件.json"
    value = json.loads(basic_manifest.read_text(encoding="utf-8"))
    rows = []
    for row in value["读取规则"]:
        path = row["路径"]
        if "/丹药/" in path:
            continue
        row["路径"] = path.replace("基础物品/", "基础基础物品/")
        if row.get("实体类别") == "基础物品":
            row["实体类别"] = "基础物品"
        if row.get("编号类别") == "基础物品":
            row["编号类别"] = "基础物品"
        rows.append(row)
    value["组件"] = "基础物品"
    value["读取规则"] = rows
    basic_manifest.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    alchemy_manifest = alchemy / "组件.json"
    value = json.loads(alchemy_manifest.read_text(encoding="utf-8"))
    value["读取规则"].append({
        "数据集": "丹药",
        "路径": "炼丹/内容/丹药/*/*.json",
        "结构": "编号实体列表",
        "实体类别": "丹药",
        "编号类别": "丹药",
    })
    alchemy_manifest.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    entry = DATA / "基础/读取规则.json"
    value = json.loads(entry.read_text(encoding="utf-8"))
    value["扫描目录"] = ["基础物品" if x == "基础物品" else x for x in value["扫描目录"]]
    value["资源池字段"] = {k: ("基础物品" if v == "基础物品" else v) for k, v in value["资源池字段"].items()}
    value["文件名唯一"] = ["基础物品" if x == "基础物品" else x for x in value["文件名唯一"]]
    entry.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("split complete")


if __name__ == "__main__":
    main()
