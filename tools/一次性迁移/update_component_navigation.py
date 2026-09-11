"""Generate component navigation and repair relocated Markdown links."""

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def main():
    mapping = json.loads((ROOT / "tools/组件迁移清单.json").read_text(encoding="utf-8"))["文件映射"]
    for old, new in mapping.items():
        if not old.endswith(".md"):
            continue
        path = DATA / new
        text = path.read_text(encoding="utf-8")

        def rewrite(match):
            target = match[1]
            if ":" in target or target.startswith("#"):
                return match[0]
            filename, separator, anchor = target.partition("#")
            prior = (DATA / old).parent / filename
            try:
                relative = prior.resolve().relative_to(DATA.resolve()).as_posix()
            except ValueError:
                return match[0]
            moved = mapping.get(relative)
            if moved is None:
                return match[0]
            link = Path(os.path.relpath(DATA / moved, path.parent)).as_posix()
            return "](" + link + (separator + anchor if separator else "") + ")"

        updated = re.sub(r"\]\(([^)]+)\)", rewrite, text)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
    for manifest in sorted(DATA.glob("*/组件.json")):
        value = json.loads(manifest.read_text(encoding="utf-8"))
        component = value["组件"]
        path = manifest.parent / "说明.md"
        if path.exists():
            continue
        lines = [f"# {component}数据包", "", "本包按组件维护数据，文件归属由 [组件.json](组件.json) 声明。数据集名是公共读取契约；编号、池文件名不随目录变化。", "", "## 数据集", "", "| 数据集 | 本包路径 |", "| --- | --- |"]
        for row in value["读取规则"]:
            local = row["路径"].removeprefix(component + "/")
            lines.append(f"| {row['数据集']} | `{local}` |")
        descriptions = sorted(p for p in manifest.parent.rglob("*说明.md") if p != path)
        if descriptions:
            lines += ["", "## 领域说明", ""]
            for doc in descriptions:
                local = doc.relative_to(manifest.parent).as_posix()
                lines.append(f"- [{local}]({local})")
        lines += ["", "修改前阅读对应领域说明；新增文件更新本包清单。只在基础读取入口登记新组件，不把玩法规则放入基础。", ""]
        path.write_text("\n".join(lines), encoding="utf-8")
    print("Component navigation generated; relocated links updated")


if __name__ == "__main__":
    main()
