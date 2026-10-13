"""物品指称的统一语法：`<品级><物品>[<灵宝>]{<扩展位>}`。

规范（委托方 2026-10 拍板，全库唯一一种写法）：

- **品级**：定长 2——中文恰好 2 字（黄品/玄品/地品/天品/圣品），id 恰好 2 位（01~05）；**连写、不加分隔**；
- **物品**：中文名，或 6 位编号；
- **灵宝**：有生效灵宝才写，方括号包住；括号内同样是中文名或 6 位编号；
- **扩展位**：<名称=值,名称=值> —— 自描述键值对，逗号分隔、名称按**字典序**，可省；
  给将来的特殊物品用（例：圣品阵法把材料投入写进来）。**解析方必须原样保留不认识的字段**，这样规则不必再扩；
- **没有品级就不写**（不补 00），**没有灵宝就不写方括号**，**没有扩展就不写花括号**；
- 中文形态与 id 形态**只有 token 不同、格式完全一样**，两者可互相换算。

**数量与投入的分界**：同样的几件堆在一起＝**数量**，放值里、不进键；
而"这一件之所以是这一件"的属性（圣品阵法的材料投入等）＝**投入**，进扩展位。

本模块**只管语法**（纯字符串）：认品级要品级表，所以由调用方把「品级名 → 编号」的映射传进来。
名称与编号的互查属于数据层（目录/资产），不在这里做。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


class ItemRefError(ValueError):
    """物品指称不符合统一语法。"""


#: 品级定长：中文 2 字、编号 2 位。改这个长度等于改语法，判据会红。
GRADE_WIDTH = 2

#: 扩展位里名称与值都不许出现的字符（它们是语法分隔符）。
_EXTRA_FORBIDDEN = "=,{}[]"


@dataclass(frozen=True)
class ItemRef:
    """一条物品指称；空串表示没写。extra 是按名称排好序的扩展键值对。"""

    item: str
    grade: str = ""
    treasure: str = ""
    extra: tuple[tuple[str, str], ...] = ()


def _clean_extra(extra: Sequence[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    """扩展位：去空、查非法字符、按名称字典序；重名直接回绝。"""

    pairs: dict[str, str] = {}
    for name, value in extra:
        key = str(name or "").strip()
        text = str(value or "").strip()
        if not key:
            raise ItemRefError("扩展位不能有空名称")
        if any(char in key or char in text for char in _EXTRA_FORBIDDEN):
            raise ItemRefError(f"扩展位名称或值里不能带 {_EXTRA_FORBIDDEN}：{key}")
        if key in pairs:
            raise ItemRefError(f"扩展位名称重复：{key}")
        pairs[key] = text
    return tuple(sorted(pairs.items()))


def format_item_ref(ref: ItemRef) -> str:
    """拼回统一语法；空的段就不写。"""

    item = str(ref.item or "").strip()
    if not item:
        raise ItemRefError("物品不能为空")
    grade = str(ref.grade or "").strip()
    treasure = str(ref.treasure or "").strip()
    if grade and len(grade) != GRADE_WIDTH:
        raise ItemRefError(f"品级必须是 {GRADE_WIDTH} 字或 {GRADE_WIDTH} 位：{grade}")
    text = f"{grade}{item}"
    if treasure:
        if "[" in treasure or "]" in treasure:
            raise ItemRefError("灵宝名里不能带方括号")
        text += f"[{treasure}]"
    pairs = _clean_extra(ref.extra)
    if pairs:
        text += "{" + ",".join(f"{name}={value}" for name, value in pairs) + "}"
    return text


def parse_item_ref(text: str, *, grades: Mapping[str, str] | None = None) -> ItemRef:
    """按统一语法解析；`grades` 是「品级名 → 编号」，用来认出中文品级。

    认不出品级就当作「没写品级」（物品名本身可能以汉字开头）。
    """

    raw = " ".join(str(text or "").split())
    if not raw:
        raise ItemRefError("物品不能为空")
    extra: list[tuple[str, str]] = []
    if raw.endswith("}"):
        head, _, block = raw[:-1].rpartition("{")
        if not head:
            raise ItemRefError("扩展位前面必须还有物品")
        raw = head.strip()
        for piece in block.split(","):
            name, _, value = piece.partition("=")
            if not name.strip() or "=" not in piece:
                raise ItemRefError("扩展位写法是 名称=值，逗号分隔")
            extra.append((name.strip(), value.strip()))
    elif "{" in raw:
        raise ItemRefError("扩展位要用花括号包住：物品{名称=值}")
    body, _, tail = raw.partition("[")
    treasure = ""
    if tail:
        if not tail.endswith("]"):
            raise ItemRefError("灵宝要用方括号包住：物品[灵宝]")
        treasure = tail[:-1].strip()
        if not treasure or "[" in treasure:
            raise ItemRefError("灵宝名不能为空、也不能再套方括号")
    item = body.strip()
    grade = ""
    prefix = item[:GRADE_WIDTH]
    if len(item) > GRADE_WIDTH:
        rest = item[GRADE_WIDTH:]
        # 数字前缀只有在「剩下正好 6 位编号」时才算品级——否则 6 位物品编号会被误读成
        # 「2 位品级 + 4 位物品」。名称前缀按表认，或按约定「以品结尾的 2 字」。
        known = (prefix in grades) if grades is not None else prefix.endswith("品")
        if prefix.isdigit() and rest.isdigit() and len(rest) == 6:
            grade = prefix
            item = rest
        elif known:
            grade = prefix
            item = rest.strip()
    if not item:
        raise ItemRefError("物品不能为空")
    return ItemRef(item=item, grade=grade, treasure=treasure, extra=_clean_extra(extra))


__all__ = ["ItemRef", "ItemRefError", "format_item_ref", "parse_item_ref", "GRADE_WIDTH"]