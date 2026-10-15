"""存档结构迁移：玩法侧的那一档（核心只提供注册口，不 import 玩法）。"""
from __future__ import annotations

from datetime import datetime, timezone

from game.features.xuemai.dna import random_dna


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def migrate_v1(entries: dict) -> None:
    """v1：补血脉状态（DNA／代次／胎次／族谱／当前壳）。**只加键，不改旧键**。

    性别就在同一行的 `character/main` 里，不必另查库。DNA 的末位按性别取奇偶，
    所以先认出性别再生成；认不出就按男算（G6 的奇偶只记录性别，不参与匹配）。
    """

    key = "xuemai_genealogy/main"
    if key in entries:
        return
    character = entries.get("character/main")
    value = character.get("value") if isinstance(character, dict) else None
    gender = ""
    if isinstance(value, dict):
        gender = str(value.get("性别") or "")
    dna = random_dna(gender if gender in ("男", "女") else "男")
    entries[key] = {
        "value": {"DNA": dna, "代次": 0, "胎次": 0, "族谱": [], "当前壳": ""},
        "version": 1,
        "updated_at": _now(),
    }


__all__ = ["migrate_v1"]