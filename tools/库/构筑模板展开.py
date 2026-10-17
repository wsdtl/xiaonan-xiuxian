"""构筑 JSON 的共用读取入口（模板机制退役后只读、不展开）。

## 为什么还留着

构筑模板机制已于 2026-10-16 拆除：数据里所有引用都展开成了原子能力节点，装载期不再展开，
工具侧直接读 JSON 也看不到引用节点了。

但 10 支卡形判据与 3 个总闸项都 import 本模块的 `load_build_json` / `expand_build_document`，
所以保留同名入口、行为改成**直通**：文件照读，展开不再发生。要再加装载期改写，改一处即可。

## 用法

```python
from 构筑模板展开 import load_build_json, expand_build_document

document = load_build_json(path)        # 读文件并展开
obj = expand_build_document(json.loads(text))   # 已有对象时直接展开
```
"""

from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 构筑模板机制已退役：数据里所有引用都展开成了原子能力节点，判据直接读 JSON 也看不到引用节点了。
# 这里保留同名入口（10 支卡形判据与 3 个总闸项都 import 它），但不再需要加载模板库。


def library() -> dict[str, dict[str, Any]]:
    """构筑模板库；机制已退役，恒为空。"""

    return {}


def expand_build_document(value: Any) -> Any:
    """就地展开模板引用，返回同一个对象；机制已退役，这里直通。"""

    return value


def load_build_json(path: pathlib.Path) -> Any:
    """读一个构筑 JSON 文件并展开其中的模板引用。"""

    return expand_build_document(json.loads(path.read_text(encoding="utf-8")))


def template_name(template_id: str) -> str:
    """模板 ID 对应的机制说明；机制已退役，恒返回空串。"""

    return str(library().get(str(template_id), {}).get("说明") or "")


def describe_reference(value: Any) -> str:
    """把一张卡里的模板引用整理成一行可读说明，供人工查看数据时使用。"""

    if not isinstance(value, dict):
        return ""
    template_id = value.get("模板")
    if template_id is None:
        return ""
    name = template_name(str(template_id))
    params = value.get("参数") or {}
    return f"{template_id} {name}".strip() + (
        "\n  参数：" + "、".join(f"{key}={item}" for key, item in params.items())
        if isinstance(params, dict) and params
        else ""
    )


__all__ = [
    "describe_reference",
    "expand_build_document",
    "library",
    "load_build_json",
    "template_name",
]
