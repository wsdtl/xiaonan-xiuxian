"""战斗相关数据集全扫：放宽到"含任何战斗字段"，供负责人圈定范围。

判据（任一命中即算"和战斗有关"）：
  能力树 `能力` · 阶段 `阶段` · 丹效 `使用效果` · 伤势 `战斗状态` · 阵法 `阵法核心/品级` ·
  权柄 `权柄` · 事件 `事件` · 战斗属性 `属性`+`战斗` 同现 · 监听 `监听`

    .venv/Scripts/python.exe -X utf8 tools/战斗相关扫描.py
"""

from __future__ import annotations

import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
MARKERS = ("能力", "阶段", "使用效果", "战斗状态", "阵法核心", "品级", "权柄",
           "监听", "效果", "事件", "伤害", "属性变化", "行动限制")

buckets: dict[str, dict[str, object]] = {}
for path in sorted(ROOT.glob("data/**/*.json")):
    rel = path.relative_to(ROOT).as_posix()
    if "/池/" in rel or rel.startswith("data/战斗/定义") or rel.startswith("data/战斗/展示"):
        continue
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    entries = data if isinstance(data, list) else [data]
    hits = 0
    keys: collections.Counter = collections.Counter()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        present = {k for k in MARKERS if k in entry}
        # 递归找能力树/监听（有些战斗字段埋在子对象里）
        nested: set[str] = set()

        def walk(node: object) -> None:
            if isinstance(node, dict):
                for key in ("能力", "监听", "事件"):
                    if key in node:
                        nested.add(key)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(entry)
        if present or nested:
            hits += 1
            keys.update(present | nested)
    if not hits:
        continue
    parent = path.parent
    dataset = parent.relative_to(ROOT).as_posix()
    row = buckets.setdefault(dataset, {"文件": 0, "条目": 0, "字段": collections.Counter()})
    row["文件"] += 1
    row["条目"] += hits
    row["字段"].update(keys)  # type: ignore[union-attr]

print(f"{'数据集（父目录）':<40}{'文件':>5}{'条目':>7}  命中字段")
for name, row in sorted(buckets.items(), key=lambda kv: -int(kv[1]["条目"])):
    top = " ".join(f"{k}{v}" for k, v in row["字段"].most_common(5))  # type: ignore[union-attr]
    print(f"{name:<40}{row['文件']:>5}{row['条目']:>7}  {top}")
print(f"\n{len(buckets)} 个数据集 · {sum(int(r['条目']) for r in buckets.values())} 条")
