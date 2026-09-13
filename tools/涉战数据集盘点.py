"""涉战数据集盘点：凡内容里引用了**战斗原子能力**的数据集，都算涉战。

范围口径由负责人定：**"所有涉及战斗原子能力的"**。可判形式就是
`data/战斗/定义/原子能力.json` 里声明的能力名出现在内容的 `能力` 字段上。

    .venv/Scripts/python.exe -X utf8 tools/涉战数据集盘点.py
"""

from __future__ import annotations

import collections
import json
import pathlib

ROOT = pathlib.Path(r"C:\Users\DengXiaonan\Desktop\晓楠修仙")
ATOMS_FILE = ROOT / "data/战斗/定义/原子能力.json"


def load_atoms() -> set[str]:
    raw = json.loads(ATOMS_FILE.read_text(encoding="utf-8"))
    # 根字典本身就是能力表（键=能力名）；早先多取了一层 "原子能力" 键，于是解析出 0 种。
    table = raw.get("原子能力") if isinstance(raw, dict) and "原子能力" in raw else raw
    if isinstance(table, dict):
        return {str(k) for k in table}
    return {str(item.get("名称")) for item in table or () if isinstance(item, dict)}


ATOMS = load_atoms()
print(f"战斗原子能力 {len(ATOMS)} 种\n")

buckets: dict[str, dict[str, object]] = {}
for path in sorted(ROOT.glob("data/**/*.json")):
    rel = path.relative_to(ROOT).as_posix()
    if rel.startswith("data/战斗/定义/") or rel.startswith("data/战斗/展示/"):
        continue
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    entries = data if isinstance(data, list) else [data]
    hits: collections.Counter = collections.Counter()
    entries_with = 0
    for entry in entries:
        found: list[str] = []

        def walk(node: object) -> None:
            if isinstance(node, dict):
                name = node.get("能力")
                if isinstance(name, str) and name in ATOMS:
                    found.append(name)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(entry)
        if found:
            entries_with += 1
            hits.update(found)
    if not hits:
        continue
    # 归到"数据集"：用**父目录**（池目录再上提一层），这样 功法/真意/气机/战场环境/战丹/伤势
    # 各自成集，不会被上级目录混成一坨。
    parent = path.parent
    if parent.name == "池":
        parent = parent.parent
    dataset = parent.relative_to(ROOT).as_posix()
    bucket = buckets.setdefault(dataset, {"文件": 0, "条目": 0, "节点": 0,
                                          "动作": collections.Counter()})
    bucket["文件"] += 1
    bucket["条目"] += entries_with
    bucket["节点"] += sum(hits.values())
    bucket["动作"].update(hits)  # type: ignore[union-attr]

print(f"{'数据集':<34}{'文件':>5}{'涉战条目':>9}{'能力节点':>9}  主要动作")
for name, row in sorted(buckets.items(), key=lambda kv: -int(kv[1]["节点"])):
    top = " ".join(f"{k}{v}" for k, v in row["动作"].most_common(4))  # type: ignore[union-attr]
    print(f"{name:<34}{row['文件']:>5}{row['条目']:>9}{row['节点']:>9}  {top}")

total = sum(int(row["节点"]) for row in buckets.values())
print(f"\n合计 {len(buckets)} 个数据集 · {total} 个能力节点")
