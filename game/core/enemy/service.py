"""解释世界敌人定义并生成完整、可复现的战斗实例。"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

from game.core.asset import AssetService
from game.core.combat import CombatantSpec, CombatBuildRef, generate_five_elements
from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping as _mapping,
    positive_int as _positive_int,
)
from game.core.forging import ForgingService
from game.core.growth import GrowthService
from game.core.pool import PoolService

from .contracts import EnemyDrop, EnemyGroup, EnemyInstance, EnemyReward, EnemyStatus
from game.core.data import sequence as _sequence, strict_text as _text


class EnemyService:
    """拥有敌人 JSON 的解释权，不持有运行中的敌人状态。"""

    def __init__(
        self,
        data: JsonDataService,
        pool: PoolService,
        growth: GrowthService,
        asset: AssetService,
        forging: ForgingService,
    ) -> None:
        self._data = data
        self._pool = pool
        self._growth = growth
        self._asset = asset
        self._forging = forging
        self._initialized = False
        self._definitions: Mapping[str, Mapping[str, object]] = MappingProxyType({})
        self._definitions_by_section: dict[str, Mapping[str, Mapping[str, object]]] = {}
        self._role_rules: Mapping[str, Mapping[str, object]] = MappingProxyType({})
        self._attribute_definitions: Mapping[str, Mapping[str, object]] = (
            MappingProxyType({})
        )
        self._genders: tuple[str, ...] = ()
        self._five_element_rules: Mapping[str, object] = {}

    def initialize(self) -> EnemyStatus:
        if self._initialized:
            raise RuntimeError("敌人核心已经初始化")
        role_rules = self._data.dataset("角色规则")
        self._five_element_rules = _mapping(
            self._data.dataset("战斗规则").get("五行"), "战斗/规则/五行.json"
        )
        self._role_rules = MappingProxyType(
            {
                name: _mapping(role_rules.get(name), f"角色规则.{name}")
                for name in ("敌方修士", "灵兽")
            }
        )
        self._attribute_definitions = MappingProxyType(
            {
                str(name): _mapping(raw, f"属性.{name}")
                for name, raw in _mapping(
                    self._data.dataset("战斗定义").get("属性"), "战斗定义.属性"
                ).items()
            }
        )
        if not self._forging.status().initialized:
            raise RuntimeError("炼器核心必须先于敌人核心启动")
        gender = _mapping(self._data.dataset("角色定义").get("性别"), "性别")
        self._genders = _texts(gender.get("取值"), "性别.取值")
        for section in ("敌人", "讨伐首领", "讨伐辅助", "讨伐属从"):
            try:
                entities = self._data.entities(section)
            except JsonDataError:
                entities = {}
            definitions = {
                name: _mapping(raw, f"{section}.{name}")
                for name, raw in entities.items()
            }
            for name, raw in definitions.items():
                self._validate_definition(name, raw)
            self._definitions_by_section[section] = MappingProxyType(definitions)
        self._definitions = self._definitions_by_section["敌人"]
        self._initialized = True
        return self.status()

    def status(self) -> EnemyStatus:
        return EnemyStatus(self._initialized, len(self._definitions))

    def generate(
        self,
        *,
        pool_names: tuple[str, ...],
        count: int,
        seed: int,
        instance_prefix: str,
    ) -> tuple[EnemyInstance, ...]:
        return self.generate_category(
            section="敌人",
            pool_names=pool_names,
            count=count,
            seed=seed,
            instance_prefix=instance_prefix,
        )

    def generate_category(
        self,
        *,
        section: str,
        pool_names: tuple[str, ...],
        count: int,
        seed: int,
        instance_prefix: str,
        required_tier: str | None = None,
    ) -> tuple[EnemyInstance, ...]:
        self._require_initialized()
        definitions = self._definitions_by_section.get(str(section))
        if definitions is None:
            raise JsonDataError(f"未登记敌方内容类别：{section}")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("敌人数量必须是正整数")
        source = random.Random(seed)
        candidates = list(self._data.pool_members(pool_names, section))
        if required_tier is not None:
            required_tier = _text(required_tier, "敌方阶梯")
            candidates = [
                item
                for item in candidates
                if str(definitions[item].get("阶梯") or "").strip() == required_tier
            ]
            if not candidates:
                raise JsonDataError(
                    f"{section}池没有符合阶梯的实体：{required_tier}"
                )
        if not candidates:
            raise JsonDataError("地点敌人池不能为空")
        selected: list[str] = []
        remaining = list(candidates)
        while remaining and len(selected) < count:
            name = source.choices(
                remaining,
                weights=[
                    _positive_int(definitions[item].get("权重"), f"{item}.权重")
                    for item in remaining
                ],
                k=1,
            )[0]
            selected.append(name)
            remaining.remove(name)
        while len(selected) < count:
            selected.append(
                source.choices(
                    candidates,
                    weights=[
                        _positive_int(definitions[item].get("权重"), f"{item}.权重")
                        for item in candidates
                    ],
                    k=1,
                )[0]
            )
        return tuple(
            self._instance(
                name,
                source,
                instance_id=f"{instance_prefix}:{index}",
                definitions=definitions,
                required_tier=required_tier,
            )
            for index, name in enumerate(selected, start=1)
        )

    def generate_groups(
        self,
        *,
        pool_names: tuple[str, ...],
        group_count: int,
        unit_count_range: tuple[int, int],
        seed: int,
        instance_prefix: str,
    ) -> tuple[EnemyGroup, ...]:
        """按组独立抽取；每组独立决定数量、成员、等级和奖励。"""

        if isinstance(group_count, bool) or not isinstance(group_count, int) or group_count < 1:
            raise ValueError("敌方编组数量必须是正整数")
        low, high = unit_count_range
        if low < 1 or high < low:
            raise ValueError("敌方编组人数范围无效")
        source = random.Random(seed)
        groups: list[EnemyGroup] = []
        for index in range(1, group_count + 1):
            group_id = f"{instance_prefix}:组{index:02d}"
            members = self.generate(
                pool_names=pool_names,
                count=source.randint(low, high),
                seed=source.getrandbits(64),
                instance_prefix=group_id,
            )
            grouped = tuple(
                EnemyInstance(
                    item.name,
                    replace(item.combatant, group_id=group_id),
                    item.reward,
                )
                for item in members
            )
            groups.append(
                EnemyGroup(
                    group_id=group_id,
                    combatants=grouped,
                    primary_ids=tuple(item.combatant.id for item in grouped),
                )
            )
        return tuple(groups)

    def _instance(
        self,
        name: str,
        source: random.Random,
        *,
        instance_id: str,
        definitions: Mapping[str, Mapping[str, object]] | None = None,
        required_tier: str | None = None,
    ) -> EnemyInstance:
        raw = (definitions or self._definitions)[name]
        role_name = _text(raw.get("角色规则"), f"{name}.角色规则")
        role = self._role_rules[role_name]
        level = source.randint(*_range(raw.get("等级"), f"{name}.等级"))
        tier = _tier(role, level, role_name)
        declared_tier = str(raw.get("阶梯") or "").strip()
        if declared_tier and declared_tier != str(tier.get("阶梯") or "").strip():
            raise JsonDataError(f"{name}.阶梯与等级范围不一致")
        if required_tier is not None and str(tier.get("阶梯") or "").strip() != required_tier:
            raise JsonDataError(f"{name}实际等级未命中要求阶梯：{required_tier}")
        attributes = {
            key: _number(value.get("默认值"), f"属性.{key}.默认值")
            for key, value in self._attribute_definitions.items()
        }
        attributes.update(
            {
                str(key): _number(value, f"{name}.属性覆盖.{key}")
                for key, value in _mapping(
                    raw.get("属性覆盖"), f"{name}.属性覆盖"
                ).items()
            }
        )
        if role_name == "灵兽":
            per_level = _mapping(raw.get("每级成长"), f"{name}.每级成长")
            growth = {
                str(key): _number(value, f"{name}.每级成长.{key}") * max(0, level - 1)
                for key, value in per_level.items()
            }
        else:
            growth = dict(self._growth.cultivator_attribute_growth(max(0, level - 1)))
        for key, value in growth.items():
            attributes[key] = float(attributes.get(key, 0)) + float(value)
        attributes["速度"] = float(attributes.get("速度", 0)) + _number(
            tier.get("每级速度"), f"{role_name}.每级速度"
        ) * max(0, level - 1)
        attributes["控制抵抗率"] = _number(
            tier.get("固定控制抵抗率"), f"{role_name}.固定控制抵抗率"
        )
        attributes["韧性"] = _number(tier.get("固定韧性"), f"{role_name}.固定韧性")
        fluctuation = _mapping(raw.get("实力波动"), f"{name}.实力波动")
        low, high = _range(fluctuation.get("倍率"), f"{name}.实力波动.倍率")
        for attribute in _texts(fluctuation.get("属性"), f"{name}.实力波动.属性"):
            attributes[attribute] = (
                float(attributes[attribute]) * source.randint(low, high) / 100
            )
        attributes = {
            key: _clamp_attribute(key, value, self._attribute_definitions)
            for key, value in attributes.items()
        }
        pools = {
            category: _text(tier.get(f"{category}池"), f"{role_name}.{category}池")
            for category in ("功法", "真意", "气机")
        }
        slots = _mapping(tier.get("修行槽位"), f"{role_name}.修行槽位")
        build = self._growth.random_companion_build(
            pools=pools,
            slots={
                category: _positive_int(
                    slots.get(category), f"{role_name}.{category}槽"
                )
                for category in pools
            },
            seed=source.getrandbits(64),
        )
        build_refs = [
            CombatBuildRef(
                section=category,
                content_id=content_id,
                instance_id=f"{instance_id}:{category}:{index}",
                born_order=index,
                power_multiplier=self._content_multiplier(category, content_id),
            )
            for category, content_ids in (
                ("功法", build.techniques),
                ("真意", build.intents),
                ("气机", build.qi_patterns),
            )
            for index, content_id in enumerate(content_ids, start=1)
        ]
        weapon_attack = 0.0
        gender = ""
        if role_name == "敌方修士":
            gender = source.choice(self._genders)
            weapon = _mapping(raw.get("本命武器"), f"{name}.本命武器")
            weapon_attack = self._forging.weapon_attack(
                level,
                base_attack=_number(weapon.get("攻击"), f"{name}.本命武器.攻击"),
            )
            open_slots = self._forging.weapon_stage(level).open_law_slots
            laws = list(
                self._data.pool_members(
                    tuple(
                        _texts(
                            _mapping(role.get("本命武器"), "敌方修士.本命武器").get(
                                "器律池"
                            ),
                            "敌方修士.器律池",
                        )
                    ),
                    "器律",
                )
            )
            source.shuffle(laws)
            for index, content_id in enumerate(laws[:open_slots], start=1):
                build_refs.append(
                    CombatBuildRef(
                        "器律",
                        content_id,
                        f"{instance_id}:器律:{index}",
                        index,
                    )
                )
        combatant = CombatantSpec(
            id=instance_id,
            name=name,
            attributes=MappingProxyType(attributes),
            level=level,
            combatant_type=_text(role.get("角色类型"), f"{role_name}.角色类型"),
            weapon_attack=float(weapon_attack),
            build=tuple(build_refs),
            health=float(attributes["血气上限"]),
            spirit=float(attributes["精神上限"]),
            gender=gender,
            five_elements=generate_five_elements(self._five_element_rules, source),
        )
        return EnemyInstance(
            name, combatant, self._reward(name, raw, role_name, source)
        )

    def _reward(
        self,
        name: str,
        raw: Mapping[str, object],
        role_name: str,
        source: random.Random,
    ) -> EnemyReward:
        loot = _mapping(raw.get("掉落"), f"{name}.掉落")
        stones = source.randint(*_range(loot.get("灵石"), f"{name}.掉落.灵石"))
        rewards = _mapping(raw.get("交锋所得"), f"{name}.交锋所得")
        weapon_exp = source.randint(
            *_range(rewards.get("本命武器经验"), f"{name}.本命武器经验")
        )
        pool_names: list[str] = []
        if role_name == "灵兽":
            pool_names.append(f"兽宝-{name}")
        extra = loot.get("丹药池", ())
        if extra:
            pool_names.extend(_texts(extra, f"{name}.丹药池"))
        drops: list[EnemyDrop] = []
        for pool_name in pool_names:
            # 每个池子按**它自己声明的集合**抽：兽宝是基础物品、丹药池是丹药。
            # 这里原先一律当基础物品抽（`section="基础物品"`），于是带丹药池的敌人
            # 一生成就报「资源池集合不匹配」——83 个敌方池里有 21 个整条进不去。
            item_id = self._pool.draw_pools(
                (pool_name,), count=1, seed=source.getrandbits(64)
            )[0]
            grade = self._asset.draw_drop_grade(seed=source.getrandbits(64))
            drops.append(EnemyDrop(item_id, grade.grade_id, 1))
        return EnemyReward(stones, weapon_exp, tuple(drops))

    def _content_multiplier(self, category: str, content_id: str) -> float:
        grade_id = str(self._data.entity(category, content_id).get("品级") or "01")
        return float(self._asset.grade(grade_id).ability_multiplier)

    def _validate_definition(self, name: str, raw: Mapping[str, object]) -> None:
        role_name = _text(raw.get("角色规则"), f"{name}.角色规则")
        if role_name not in self._role_rules:
            raise JsonDataError(f"敌人 {name} 使用未知角色规则：{role_name}")
        _positive_int(raw.get("权重"), f"{name}.权重")
        _range(raw.get("等级"), f"{name}.等级")
        _mapping(raw.get("属性覆盖"), f"{name}.属性覆盖")
        _mapping(raw.get("掉落"), f"{name}.掉落")
        _mapping(raw.get("交锋所得"), f"{name}.交锋所得")

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("敌人核心尚未初始化")


def _tier(role: Mapping[str, object], level: int, label: str) -> Mapping[str, object]:
    matches = [
        _mapping(raw, f"{label}.阶梯[]")
        for raw in _sequence(role.get("阶梯"), f"{label}.阶梯")
        if _range(_mapping(raw, "阶梯").get("等级范围"), "阶梯.等级范围")[0]
        <= level
        <= _range(_mapping(raw, "阶梯").get("等级范围"), "阶梯.等级范围")[1]
    ]
    if len(matches) != 1:
        raise JsonDataError(f"{label}等级 {level} 无法唯一命中阶梯")
    return matches[0]


def _clamp_attribute(
    name: str,
    value: float,
    definitions: Mapping[str, Mapping[str, object]],
) -> int | float:
    definition = definitions[name]
    result = min(
        max(float(value), float(definition["最低值"])),
        float(definition["最高值"]),
    )
    rounded = round(result, 4)
    return int(rounded) if rounded.is_integer() else rounded


def _texts(value: object, label: str) -> tuple[str, ...]:
    result = tuple(_text(raw, f"{label}[]") for raw in _sequence(value, label))
    if not result:
        raise JsonDataError(f"{label}不能为空")
    return result


def _range(value: object, label: str) -> tuple[int, int]:
    values = _sequence(value, label)
    if len(values) != 2:
        raise JsonDataError(f"{label}必须包含下限和上限")
    low = _positive_int(values[0], f"{label}.下限")
    high = _positive_int(values[1], f"{label}.上限")
    if low > high:
        raise JsonDataError(f"{label}下限不能大于上限")
    return low, high


def _number(value: object, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JsonDataError(f"{label}必须是数值")
    return value


__all__ = ["EnemyService"]
