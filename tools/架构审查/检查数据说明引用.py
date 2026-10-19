"""数据说明引用审查：`data/**/*.md` 点到的数据文件名，得真的存在。

委托方 2026-10：「更新说明…让说明文档与**代码现状一致**」。`tools/` 侧早有「悬空脚本引用」盯着，
（见 `检查历史遗留.py`）而**数据说明**这边一直没人管：改了数据文件名、说明没跟，就留下死引用。

**判法**：从 `data/**/*.md` 里抠出带后缀的引用（`` `xxx.json` `` 这类），在全库按**文件名**找；找不到就是悬空。
按文件名而不是按路径，是因为文档里常写裸文件名（`` `地势.json` ``），那不是路径。

**已知的 3 处不是缺陷**（都进白名单，按「文档 + 名字」记）：

- `data/角色/规则/说明.md` 里的 `精英敌人.json`／`天灾敌人.json`——原文是「**后续**按敌人档次拆分**时，应采用**…」，是计划不是现状；
- `data/说明.md` 里的 `规则/xx.json`——是**占位示例**（`xx`／`xy`／`z` 那一串）。

**第一次跑出来 63 处，63 处全是误报**：我把裸文件名当路径去拼，`地势.json` 在 `游戏/世界/基础/内容/` 下找不到，
可它在别的目录里。**判据先拿假阳性打自己的脸，再谈有没有真货。**

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查数据说明引用.py

**退出码：0 = 干净，1 = 有悬空引用。**
"""
from __future__ import annotations

import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SKIP_PARTS = {".venv", ".git", "__pycache__", "_输出", "BUILD"}
REFERENCE = re.compile(r"`([\w\u4e00-\u9fff/]+\.(?:json|md|py))`")

#: 已知的「不是缺陷」的引用：(文档相对路径, 被点的名字)。
KNOWN_PLANS = frozenset({
    ("data/角色/规则/说明.md", "精英敌人.json"),
    ("data/角色/规则/说明.md", "天灾敌人.json"),
    ("data/说明.md", "规则/xx.json"),
})


def main() -> int:
    # 剪枝走目录：`rglob('*')` 会先遍历到 .venv/.git 里再过滤，光走目录就十几秒；
    # 同一课在 `检查历史遗留.py` 与 `检查文档计数.py` 都记过。
    names: set[str] = set()
    for 目录, 子目录, 文件名 in os.walk(ROOT):
        子目录[:] = [值 for 值 in 子目录 if 值 not in SKIP_PARTS]
        names.update(文件名)
    problems: list[str] = []
    for doc in sorted((ROOT / "data").rglob("*.md")):
        rel = doc.relative_to(ROOT).as_posix()
        for number, line in enumerate(doc.read_text(encoding="utf-8").split("\n"), 1):
            for match in REFERENCE.finditer(line):
                target = match.group(1)
                if (rel, target) in KNOWN_PLANS:
                    continue
                base = target.rsplit("/", 1)[-1]
                if base in names or (ROOT / target).exists() or (doc.parent / target).exists():
                    continue
                problems.append(f"{rel}:{number} 点了不存在的 {target}")
    if problems:
        for item in problems:
            print(f"   {item}")
        print(f"数据说明引用 {len(problems)} 处")
        return 1
    print("数据说明引用审查通过：数据说明里的引用都还在")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
