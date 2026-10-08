"""模板库盘查：库里定义的模板有没有人引用、数据引用的模板在不在库里。

模板库是**生成物**（`game/core/combat/template_data.py`，由 `tools/报告与生成/构筑模板代码化.py`
按引用闭包生成，文件头写着「自动生成，不要手改」）。它的正确形态有两条不变量：

1. **库里没有孤儿**：每个模板都必须被 `data/` 里某处引用。库的生成方式是「按引用闭包裁剪死条目」，
   所以出现孤儿只有一种可能——**曾经有人引用的数据被改写成了内联**，库没跟着重生成。
2. **数据没有悬空**：引用的模板编号必须在库里存在。

为什么单独盘这一条：`检查构筑模板.py` 管的是**库内部自洽**（说明、编号=主体哈希、簇表、面表、
每面目录有卡），它不回答「库里还有没有人引用」。2026-10 器律 64 条由模板引用改为内联之后，
库里 57 条器律模板正好成了孤儿，而当时没有任何判据会报出来。

**这份是盘查报告，不是必过项**：孤儿只能靠重生成库消除，而重生成要先 `--展开`（把 data/ 里的
引用就地展开成原文）——那会重写功法/真意/战丹/战场环境/伤势共约 4690 处引用，属于数据形态变更，
要单独决策。在此之前把它挂在门禁上只会让门禁长期红灯。

    .venv/Scripts/python.exe -X utf8 tools/报告与生成/盘点模板库.py

**退出码：0 = 两条不变量都成立，1 = 有孤儿或悬空。**
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "game" / "core" / "combat" / "template_data.py"
DATA = ROOT / "data"
REFERENCE = re.compile(r'"模板"\s*:\s*"([0-9a-f]+)"')


def _library_faces() -> dict[str, str]:
    """库里每份模板的归属面：FACES_JSON 是唯一无法从主体算出来的信息。"""

    text = LIBRARY.read_text(encoding="utf-8")
    matched = re.search(r'FACES_JSON\s*=\s*r?"""(.*?)"""', text, re.S)
    if matched is None:
        raise SystemExit("template_data.py 里读不到 FACES_JSON")
    return {str(k): str(v) for k, v in json.loads(matched.group(1)).items()}


def _references() -> tuple[dict[str, set[str]], int]:
    """全库引用：模板编号 -> 引用它的文件（相对 data/）。"""

    used: dict[str, set[str]] = {}
    scanned = 0
    for path in sorted(DATA.rglob("*.json")):
        scanned += 1
        text = path.read_text(encoding="utf-8")
        for name in REFERENCE.findall(text):
            used.setdefault(name, set()).add(str(path.relative_to(DATA)))
    return used, scanned


def main() -> int:
    faces = _library_faces()
    used, scanned = _references()
    orphans = sorted(name for name in faces if name not in used)
    dangling = sorted(name for name in used if name not in faces)

    by_face: dict[str, int] = {}
    for name in orphans:
        by_face[faces[name]] = by_face.get(faces[name], 0) + 1

    print(f"data/ 下扫描 {scanned} 份 json；库中定义 {len(faces)} 个模板，被引用 {len(used)} 个")
    print(f"孤儿（库里有、无人引用）{len(orphans)} 个" + (f"：{dict(sorted(by_face.items()))}" if by_face else ""))
    for name in orphans[:20]:
        print(f"    {name}（{faces[name]}）")
    if len(orphans) > 20:
        print(f"    …其余 {len(orphans) - 20} 个")
    print(f"悬空（数据引用、库里没有）{len(dangling)} 个" + (f"：{dangling[:10]}" if dangling else ""))
    return 1 if (orphans or dangling) else 0


if __name__ == "__main__":
    raise SystemExit(main())
