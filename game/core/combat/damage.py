"""晓楠修仙战斗核心使用的固定层级伤害流水线。"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from .models import Fighter


@dataclass(frozen=True)
class DamageRequest:
    amount: float
    label: str
    damage_form: str = "直接"
    defense_rule: str = "普通"
    tags: tuple[str, ...] = ()
    can_miss: bool = False
    can_critical: bool = True
    can_block: bool = True
    bypass_shield: bool = False


@dataclass(frozen=True)
class DamageBreakdown:
    raw: float
    hit_chance: float
    hit_roll: float | None
    critical_chance: float
    critical_roll: float | None
    critical_multiplier: float
    after_critical: float
    defense: float
    effective_defense: float
    defense_multiplier: float
    after_defense: float
    rate_multiplier: float
    after_rates: float
    block_chance: float
    block_roll: float | None
    block_reduction: float
    after_block: float
    limited: float


@dataclass(frozen=True)
class DamageResolution:
    request: DamageRequest
    hit: bool
    critical: bool
    blocked: bool
    defeated: bool
    shield_broken: bool
    shield_damage: float
    health_damage: float
    overkill: float
    health_before: float
    health_after: float
    shield_before: float
    shield_after: float
    breakdown: DamageBreakdown

    @property
    def actual_damage(self) -> float:
        return self.shield_damage + self.health_damage

    def values(self) -> dict[str, Any]:
        value = self.breakdown
        return {
            "原始伤害": value.raw,
            "命中率": value.hit_chance,
            "命中判定值": value.hit_roll,
            "命中": self.hit,
            "暴击率": value.critical_chance,
            "暴击判定值": value.critical_roll,
            "暴击": self.critical,
            "暴击倍率": value.critical_multiplier,
            "暴击后伤害": value.after_critical,
            "原始防御": value.defense,
            "有效防御": value.effective_defense,
            "防御倍率": value.defense_multiplier,
            "防御后伤害": value.after_defense,
            "伤害倍率": value.rate_multiplier,
            "增减伤后伤害": value.after_rates,
            "格挡率": value.block_chance,
            "格挡判定值": value.block_roll,
            "格挡": self.blocked,
            "格挡减伤": value.block_reduction,
            "格挡后伤害": value.after_block,
            "边界后伤害": value.limited,
            "护盾伤害": self.shield_damage,
            "血气伤害": self.health_damage,
            "过量伤害": self.overkill,
            "实际伤害": self.actual_damage,
            "伤害前护盾": self.shield_before,
            "伤害后护盾": self.shield_after,
            "伤害前血气": self.health_before,
            "伤害后血气": self.health_after,
            "伤害形式": self.request.damage_form,
            "防御规则": self.request.defense_rule,
        }


class DamageEngine:
    """只结算一段伤害，不处理技能选择、触发链和奖励。"""

    def __init__(self, rules: Mapping[str, Any]) -> None:
        self.rules = dict(rules)

    def resolve(
        self,
        request: DamageRequest,
        *,
        source: Fighter,
        target: Fighter,
        rng: random.Random,
        judge: Callable[[str, float, float | None], bool] | None = None,
    ) -> DamageResolution:
        raw = max(0.0, float(request.amount))
        # 全局输出倍率：和 `恢复倍率` 对称的总闸。整条流水线都从 raw 长出来，
        # 所以乘在这里等于同比例缩放所有伤害，卡的相对强弱不变。
        # 只放大「打向别人」的伤害：自伤（血祭代价一类）是成本不是输出，
        # 跟着一起放大等于把成本也乘几倍，会让代价型卡整体失真。
        if source.side != target.side:
            raw *= max(0.0, float(self.rules.get("输出倍率", 100))) / 100.0
        minimum_hit = float(self.rules.get("最低命中率", 20)) / 100.0
        maximum_hit = float(self.rules.get("最高命中率", 100)) / 100.0
        base_hit = float(self.rules.get("基础命中率", 95)) / 100.0
        hit_chance = self._clamp(
            self._percent(source, "命中率", base_hit) - self._percent(target, "闪避率"),
            minimum_hit,
            maximum_hit,
        )
        hit_roll = rng.random() if request.can_miss else None
        hit = not request.can_miss or (
            judge("命中", hit_chance, hit_roll)
            if judge is not None
            else bool(hit_roll is not None and hit_roll < hit_chance)
        )
        if not hit:
            empty = DamageBreakdown(
                raw,
                hit_chance,
                hit_roll,
                0.0,
                None,
                1.0,
                raw,
                0.0,
                0.0,
                1.0,
                raw,
                1.0,
                raw,
                0.0,
                None,
                0.0,
                raw,
                0.0,
            )
            return DamageResolution(
                request,
                False,
                False,
                False,
                False,
                False,
                0.0,
                0.0,
                0.0,
                target.health,
                target.health,
                target.shield,
                target.shield,
                empty,
            )

        critical_chance = self._clamp(
            self._percent(source, "暴击率") - self._percent(target, "抗暴率"),
            0.0,
            1.0,
        )
        critical_roll = rng.random() if request.can_critical else None
        critical = bool(
            request.can_critical
            and (
                judge("暴击", critical_chance, critical_roll)
                if judge is not None
                else critical_roll is not None and critical_roll < critical_chance
            )
        )
        critical_multiplier = 1.0
        if critical:
            critical_multiplier = max(
                1.0,
                self._percent(source, "暴击伤害", 1.5)
                - self._percent(target, "暴击伤害减免"),
            )
            critical_multiplier = min(
                critical_multiplier,
                float(self.rules.get("最高暴击倍率", 400)) / 100.0,
            )
        after_critical = raw * critical_multiplier

        defense = 0.0
        effective_defense = 0.0
        defense_multiplier = 1.0
        if request.defense_rule not in {"无视防御", "真实"}:
            defense = target.value("防御", 0.0)
            rate_penetration = self._clamp(self._percent(source, "比例穿透"), 0.0, 1.0)
            flat_penetration = max(0.0, source.value("固定穿透", 0.0))
            effective_defense = defense * (1.0 - rate_penetration) - flat_penetration
            constant = max(0.0001, float(self.rules.get("防御常数", 100)))
            if effective_defense >= 0:
                defense_multiplier = constant / (constant + effective_defense)
            else:
                defense_multiplier = 2.0 - constant / (constant - effective_defense)
        after_defense = after_critical * defense_multiplier

        rate_multiplier = 1.0
        if request.defense_rule != "真实":
            # 减免是无上限的百分比，叠满就能把伤害压成 0；必须有天花板。
            # `最高伤害减免=100` 表示不设限，行为与加护栏之前完全一致。
            reduction = min(
                self._percent(target, "伤害减免"),
                float(self.rules.get("最高伤害减免", 100)) / 100.0,
            )
            rate_multiplier += self._percent(source, "伤害加成")
            rate_multiplier -= reduction
            rate_multiplier = self._clamp(
                rate_multiplier,
                0.0,
                float(self.rules.get("最高伤害倍率", 400)) / 100.0,
            )
        after_rates = after_defense * rate_multiplier

        block_chance = self._clamp(
            self._percent(target, "格挡率") - self._percent(source, "破格率"),
            0.0,
            float(self.rules.get("最高格挡率", 80)) / 100.0,
        )
        block_roll = (
            rng.random()
            if request.can_block and request.defense_rule != "真实"
            else None
        )
        blocked = bool(
            request.can_block
            and (
                judge("格挡", block_chance, block_roll)
                if judge is not None
                else block_roll is not None and block_roll < block_chance
            )
        )
        block_reduction = (
            self._clamp(self._percent(target, "格挡减伤"), 0.0, 0.9)
            if blocked
            else 0.0
        )
        after_block = after_rates * (1.0 - block_reduction)
        limited = after_block
        if limited > 0:
            limited = max(float(self.rules.get("最低伤害", 1)), limited)

        shield_before = target.shield
        shield_damage = 0.0 if request.bypass_shield else min(shield_before, limited)
        shield_after = max(0.0, shield_before - shield_damage)
        pending_health = max(0.0, limited - shield_damage)
        health_before = target.health
        health_damage = min(max(0.0, health_before), pending_health)
        health_after = max(0.0, health_before - health_damage)
        overkill = max(0.0, pending_health - health_damage)
        breakdown = DamageBreakdown(
            raw,
            hit_chance,
            hit_roll,
            critical_chance,
            critical_roll,
            critical_multiplier,
            after_critical,
            defense,
            effective_defense,
            defense_multiplier,
            after_defense,
            rate_multiplier,
            after_rates,
            block_chance,
            block_roll,
            block_reduction,
            after_block,
            limited,
        )
        return DamageResolution(
            request,
            True,
            critical,
            blocked,
            health_before > 0 and health_after <= 0,
            shield_before > 0 and shield_after <= 0,
            shield_damage,
            health_damage,
            overkill,
            health_before,
            health_after,
            shield_before,
            shield_after,
            breakdown,
        )

    @staticmethod
    def with_minimum_health(
        resolution: DamageResolution,
        minimum_health: float,
    ) -> DamageResolution:
        floor = max(0.0, min(resolution.health_before, float(minimum_health)))
        pending = max(0.0, resolution.breakdown.limited - resolution.shield_damage)
        health_damage = min(max(0.0, resolution.health_before - floor), pending)
        health_after = max(floor, resolution.health_before - health_damage)
        overkill = max(0.0, pending - health_damage)
        return replace(
            resolution,
            defeated=False,
            health_damage=health_damage,
            health_after=health_after,
            overkill=overkill,
        )

    @staticmethod
    def with_limited_damage(
        resolution: DamageResolution,
        amount: float,
    ) -> DamageResolution:
        """用伤害前裁定后的最终伤害重建资源变化。"""

        limited = max(0.0, min(float(amount), resolution.breakdown.limited))
        shield_damage = (
            0.0
            if resolution.request.bypass_shield
            else min(resolution.shield_before, limited)
        )
        shield_after = max(0.0, resolution.shield_before - shield_damage)
        pending_health = max(0.0, limited - shield_damage)
        health_damage = min(max(0.0, resolution.health_before), pending_health)
        health_after = max(0.0, resolution.health_before - health_damage)
        overkill = max(0.0, pending_health - health_damage)
        return replace(
            resolution,
            defeated=resolution.health_before > 0 and health_after <= 0,
            shield_broken=resolution.shield_before > 0 and shield_after <= 0,
            shield_damage=shield_damage,
            health_damage=health_damage,
            overkill=overkill,
            health_after=health_after,
            shield_after=shield_after,
            breakdown=replace(resolution.breakdown, limited=limited),
        )

    @staticmethod
    def _percent(target: Fighter, attribute: str, default: float = 0.0) -> float:
        if attribute not in target.attributes and not any(
            attribute in status.modifiers for status in target.statuses
        ):
            return float(default)
        return target.value(attribute, default * 100.0) / 100.0

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return min(maximum, max(minimum, float(value)))
