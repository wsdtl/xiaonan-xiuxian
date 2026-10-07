"""解释铜雀台规则并计算道侣可转移修为。"""

from __future__ import annotations

import math

from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping as _mapping,
    nonempty_text as _text,
    positive_int as _positive_int,
)
from game.core.growth import GrowthService
from game.core.world import WorldService

from .contracts import (
    CultivationTransferError,
    CultivationTransferStatus,
    CultivationTransferValues,
)


class CultivationTransferService:
    """只负责正式规则和纯数值，不持有角色状态。"""


    def __init__(
        self, data: JsonDataService, growth: GrowthService, world: WorldService
    ) -> None:
        self._data = data
        self._growth = growth
        self._world = world
        self._initialized = False
        self._function = ""
        self._medicine_id = ""
        self._minimum_level = 0
        self._guard_rule = ""
        self._protected_rate = 0
        self._severed_rate = 0

    def initialize(self) -> CultivationTransferStatus:
        if self._initialized:
            raise RuntimeError("修为转移核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于修为转移核心启动")
        if not self._growth.status().initialized:
            raise RuntimeError("成长核心必须先于修为转移核心启动")
        if not self._world.status().initialized:
            raise RuntimeError("世界核心必须先于修为转移核心启动")
        rules = self._world.feature_config("夺元")
        self._function = "夺元"
        self._guard_rule = _text(rules.get("状态守卫"), "铜雀台.状态守卫")
        target = _mapping(rules.get("目标"), "铜雀台.目标")
        if target.get("角色类型") != "道侣" or target.get("必须同行") is not True:
            raise JsonDataError("铜雀台目标必须是当前同行道侣")
        if target.get("每次数量") != 1:
            raise JsonDataError("铜雀台每次只能处理一名道侣")
        self._minimum_level = _positive_int(target.get("最低等级"), "铜雀台.最低等级")
        protected = _mapping(rules.get("服丹"), "铜雀台.服丹")
        severed = _mapping(rules.get("未服丹"), "铜雀台.未服丹")
        self._medicine_id = _text(protected.get("丹药"), "铜雀台.服丹.丹药")
        medicine = self._data.entity("丹药", self._medicine_id)
        effect = _mapping(medicine.get("使用效果"), "铜雀台护契丹.使用效果")
        if effect.get("类型") != "护持道契":
            raise JsonDataError("铜雀台护契丹效果必须是护持道契")
        self._protected_rate = _rate(protected.get("转化率"), "铜雀台.服丹.转化率")
        self._severed_rate = _rate(severed.get("转化率"), "铜雀台.未服丹.转化率")
        if self._protected_rate != 100 or self._severed_rate != 70:
            raise JsonDataError("铜雀台当前契约要求护契100%、离契70%")
        reset = _mapping(rules.get("重置"), "铜雀台.重置")
        if reset.get("修为字段") != {
            "境界": "等级对应境界",
            "等级": 1,
            "经验": 0,
            "属性": "初始属性",
            "突破记录": (),
        }:
            raise JsonDataError("铜雀台必须把道侣修为重置为初境一级初始属性")
        if tuple(reset.get("清除来源") or ()) != ("等级成长", "突破永久属性"):
            raise JsonDataError("铜雀台必须清除等级成长和突破永久属性")
        if reset.get("资源处理") != "保留当前值并受初始属性上限约束":
            raise JsonDataError("铜雀台资源必须受重置后的初始属性上限约束")
        if tuple(reset.get("保留字段") or ()) != (
            "资质",
            "属性倍率",
            "功法",
            "真意",
            "气机",
            "本命武器",
            "器律",
            "自动用药",
            "待战战丹",
        ):
            raise JsonDataError("铜雀台保留字段与当前道侣培养契约不一致")
        self._initialized = True
        return self.status()

    def status(self) -> CultivationTransferStatus:
        return CultivationTransferStatus(
            self._initialized,
            self._function,
            self._medicine_id,
            self._minimum_level,
            self._guard_rule,
        )

    @property
    def medicine_id(self) -> str:
        self._require_initialized()
        return self._medicine_id

    @property
    def location_function(self) -> str:
        self._require_initialized()
        return self._function

    @property
    def minimum_level(self) -> int:
        self._require_initialized()
        return self._minimum_level

    @property
    def guard_rule(self) -> str:
        self._require_initialized()
        return self._guard_rule

    def values(
        self, *, level: int, experience: int, severed_rate: int | None = None
    ) -> CultivationTransferValues:
        self._require_initialized()
        if isinstance(level, bool) or not isinstance(level, int) or level < self._minimum_level:
            raise CultivationTransferError(
                f"同行道侣至少达到{self._minimum_level}级才能夺元"
            )
        if isinstance(experience, bool) or not isinstance(experience, int) or experience < 0:
            raise CultivationTransferError("道侣当前经验必须是非负整数")
        cultivation = experience + sum(
            self._growth.experience_required(current) for current in range(1, level)
        )
        effective_severed_rate = self._severed_rate if severed_rate is None else _rate(
            severed_rate, "铜雀台.离契转化率"
        )
        return CultivationTransferValues(
            cultivation,
            math.floor(cultivation * self._protected_rate / 100),
            math.floor(cultivation * effective_severed_rate / 100),
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("修为转移核心微服务尚未初始化")


def _rate(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise JsonDataError(f"{label}必须是0至100的整数")
    return value


__all__ = ["CultivationTransferService"]
