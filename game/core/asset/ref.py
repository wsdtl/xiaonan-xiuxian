"""物品指称的统一语法：`<品级><物品>[<灵宝>]`。

规范（委托方 2026-10 拍板，全库唯一一种写法）：

- **品级**：定长 2——中文恰好 2 字（黄品/玄品/地品/天品/圣品），id 恰好 2 位（01~05）；**连写、不加分隔**；
- **物品**：中文名，或 6 位编号；
- **灵宝**：有生效灵宝才写，方括号包住；括号内同样是中文名或 6 位编号；
- **没有品级就不写**（不补 00），**没有灵宝就不写方括号**；
- 中文形态与 id 形态**只有 token 不同、格式完全一样**，两者可互相换算。

本模块**只管语法**（纯字符串）：认品级要品级表，所以由调用方把「品级名 → 编号」的映射传进来。
名称与编号的互查属于数据层（目录/资产），不在这里做。
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class ItemRefError(ValueError):
    """物品指称不符合统一语法。"""


#: 品级定长：中文 2 字、编号 2 位。改这个长度等于改语法，判据会红。
GRADE_WIDTH = 2


@dataclass(frozen=True)
class ItemRef:
    """一条物品指称的三个部分；空串表示没写。"""

    item: str
    grade: str = ""
    treasure: str = ""


def format_item_ref(ref: ItemRef) -> str:
    """拼回统一语法；parts 为空就不写那一段。"""

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
    return text


def parse_item_ref(text: str, *, grades: Mapping[str, str] | None = None) -> ItemRef:
    """按统一语法解析；`grades` 是「品级名 → 编号」，用来认出中文品级。

    认不出品级就当作「没写品级」（物品名本身可能以汉字开头）。
    """

    raw = " ".join(str(text or "").split())
    if not raw:
        raise ItemRefError("物品不能为空")
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
        # 认品级：给了表就按表（名称→编号）；没给就按定长约定——2 位数字，或以「品」结尾的 2 字前缀。
        known = (prefix in grades) if grades is not None else prefix.endswith("品")
        if prefix.isdigit() or known:
            grade = prefix
            item = item[GRADE_WIDTH:].strip()
    if not item:
        raise ItemRefError("物品不能为空")
    return ItemRef(item=item, grade=grade, treasure=treasure)


__all__ = ["ItemRef", "ItemRefError", "format_item_ref", "parse_item_ref", "GRADE_WIDTH"]