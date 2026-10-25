"""血脉核心服务：规则、DNA 生成与匹配。

它只解释「一段 DNA 命中哪些血脉、加多少属性、觉醒几倍」；
族谱状态与传位仍归玩法层。
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from game.core.data import JsonDataError, JsonDataService

from .dna import breed as _breed, random_dna as _random_dna
from .rules import (
    BloodlineRules,
    awaken_multiplier,
    load_bloodline_rules,
    matched,
)


@dataclass(frozen=True)
class BloodlineStatus:
    """血脉核心的装载状态。"""

    initialized: bool
    bloodline_count: int


class BloodlineService:
    """血脉规则与 DNA 的公共解释入口，不拥有玩家族谱状态。"""

    def __init__(self, data: JsonDataService) -> None:
        self._data = data
        self._initialized = False
        self._rules: BloodlineRules | None = None
        self._random = random.SystemRandom()

    def initialize(self) -> BloodlineStatus:
        if self._initialized:
            raise RuntimeError("血脉核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于血脉核心启动")
        rule_block = self._data.dataset("血脉规则")
        body = rule_block.get("血脉")
        if not isinstance(body, Mapping):
            raise JsonDataError("血脉规则数据集缺少「血脉」块")
        content = self._data.dataset("血脉内容")
        rows: list[object] = []
        if isinstance(content, Mapping):
            if "血脉" in content and isinstance(content["血脉"], Mapping):
                content = content["血脉"]
            if "普通血脉" in content or "天外" in content:
                rows.extend(content.get("普通血脉") or ())
                rows.extend(content.get("天外") or ())
            else:
                for value in content.values():
                    if isinstance(value, (list, tuple)):
                        rows.extend(value)
                    elif isinstance(value, Mapping):
                        rows.append(value)
        elif isinstance(content, (list, tuple)):
            rows.extend(content)
        else:
            raise JsonDataError("血脉内容数据集格式不正确")
        merged = dict(body)
        merged["普通血脉"] = tuple(
            row
            for row in rows
            if isinstance(row, Mapping) and str(row.get("类别") or "普通") == "普通"
        )
        merged["天外"] = tuple(
            row
            for row in rows
            if isinstance(row, Mapping) and str(row.get("类别") or "") == "天外"
        )
        self._rules = load_bloodline_rules(merged)
        self._initialized = True
        return BloodlineStatus(True, len(self._rules.bloodlines))

    def status(self) -> BloodlineStatus:
        count = len(self._rules.bloodlines) if self._rules is not None else 0
        return BloodlineStatus(self._initialized, count)

    def rules(self) -> BloodlineRules:
        self._require_initialized()
        if self._rules is None:
            raise RuntimeError("血脉规则尚未装载")
        return self._rules

    def bloodline_growth(self, dna: str) -> dict[str, float]:
        """命中血脉的固定属性加成汇总（只算基础加法）。"""

        out: dict[str, float] = {}
        for blood in matched(self.rules(), dna):
            for ability in blood.abilities:
                if str(ability.get("能力")) != "固定属性加成":
                    continue
                for key, value in dict(ability.get("属性") or {}).items():
                    out[str(key)] = out.get(str(key), 0.0) + float(value)
        return out

    def awakened_growth(self, dna: str, hp_percent: object) -> dict[str, float]:
        """基础加法 x 觉醒倍数；不能觉醒的血脉恒 x1.0。"""

        rules = self.rules()
        factor = Decimal(str(awaken_multiplier(rules, Decimal(str(hp_percent)))))
        out: dict[str, float] = {}
        for blood in matched(rules, dna):
            scale = factor if blood.awake else Decimal("1.0")
            for ability in blood.abilities:
                if str(ability.get("能力")) != "固定属性加成":
                    continue
                for key, value in dict(ability.get("属性") or {}).items():
                    out[str(key)] = out.get(str(key), 0.0) + float(
                        Decimal(str(value)) * scale
                    )
        return out

    def combat_growth(self, dna: str) -> dict[str, float]:
        """战斗侧只出基础加法；觉醒倍率由引擎乘在等级成长那一份上。"""

        return self.bloodline_growth(dna)

    def awaken(self, hp_percent: object) -> object:
        """按真实气血百分比取觉醒倍率（护盾不计入）。"""

        return awaken_multiplier(self.rules(), Decimal(str(hp_percent)))

    def bloodlines(self, dna: str) -> tuple[str, ...]:
        """按 DNA 匹配出的血脉名字，按强度降序。"""

        return tuple(blood.name for blood in matched(self.rules(), dna))

    def matched(self, dna: str):
        return matched(self.rules(), dna)

    def random_dna(self, gender: str, randomizer: random.Random | None = None) -> str:
        return _random_dna(gender, randomizer or self._random)

    def breed(
        self,
        father: str,
        mother: str,
        gender: str,
        randomizer: random.Random | None = None,
    ) -> str:
        return _breed(father, mother, gender, randomizer or self._random)

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("血脉核心微服务尚未初始化")


__all__ = ["BloodlineService", "BloodlineStatus"]
