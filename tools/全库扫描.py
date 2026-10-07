"""全库扫描：把 `data/` 里的实体读出来，构筑模板引用先展开。

## 为什么单独一支

空位审计（`机械化盘点.py`）问的是「**全库**有没有人在用这个机制」，
但两个工具各自的 `SURFACES` 只覆盖四类构筑卡（功法/真意/气机/器律）。于是战丹 / 伤势 /
战场环境里已经用上的来源仍被报成「没人用」——`目标当前护盾` 就是这么被误报掉的。

模板迁移之后还有第二层：直接 `json.loads` 看到的只是一条 `{"模板": …}` 引用，
`读取数值`、监听节点这些藏在**模板主体**里，不展开就数不到。

本模块把这两件事一起做掉，避免每个审计工具各写一套（口径分叉正是上一轮的病根）。

用法：

```python
from 全库扫描 import 全库来源, 全库文档

for 相对路径, 文档 in 全库文档():        # 已展开模板引用；跳过 `定义/` 与规则文件
    ...
```
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any, Iterator

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from 构筑模板展开 import expand_build_document  # noqa: E402


def 全库文档() -> Iterator[tuple[str, Any]]:
    """`data/` 下每份内容 JSON 的 `(相对路径, 已展开的文档)`。

    `定义/` 与 `规则/` 里是引擎契约、不是内容：它们的字段名与内容侧同名却不同义
    （例如 `原子能力.json` 里也写着「来源」），扫进去会把空位报成假的「有人在用」。
    """

    标记 = ("/定义/", "/规则/", "/展示/")
    for path in sorted((ROOT / "data").rglob("*.json")):
        相对 = path.relative_to(ROOT).as_posix()
        if any(片段 in f"/{相对}" for 片段 in 标记):
            continue
        try:
            文档 = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        yield 相对, expand_build_document(文档)


def 全库来源() -> set[str]:
    """全库 `读取数值` 用到的来源名。"""

    used: set[str] = set()

    def 下探(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("能力") == "读取数值" and node.get("来源"):
                used.add(str(node["来源"]))
            for value in node.values():
                下探(value)
        elif isinstance(node, list):
            for value in node:
                下探(value)

    for _相对, 文档 in 全库文档():
        下探(文档)
    return used


__all__ = ["全库文档", "全库来源"]
