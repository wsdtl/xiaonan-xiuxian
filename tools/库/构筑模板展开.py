"""工具侧共用的构筑模板展开。

## 为什么需要它

游戏运行时，模板引用在**装载期**就展开进快照（`game.core.data.JsonDataService.initialize`
→ `game.core.combat.service.expand_build_section`），所以引擎、战报、渲染看到的都是
完整的树。

但 `tools/` 里的不少判据是**直接读 `data/` 里的 JSON 文件**的（渲染正文对照、构筑形状、
机械化盘点……）。它们不经过快照，迁移之后就会看到一个没有 `能力` 字段的引用节点，
于是报「未支持 被动技能.效果：None」这类错。

本模块给这些工具一个统一的展开入口，避免每个工具各写一套。

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
