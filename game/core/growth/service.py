"""只解释正式 JSON 的共用成长计算服务。"""

from __future__ import annotations

import math
import random
import secrets
from collections.abc import Mapping, Sequence

from game.core.data import (
    ContractSet,
    JsonDataError,
    JsonDataService,
    mapping as _mapping,
    positive_int as _positive_int,
)
from game.core.pool import EXPAND_DEDUPLICATED, PoolRequest, PoolService

from .contracts import (
    CultivationCategoryBuild,
    ExperienceAdvance,
    GrowthError,
    GrowthStatus,
    RandomCultivationBuild,
    RealmDefinition,
)
from game.core.data import number as _number, sequence as _sequence, strict_text as _text

_CATEGORIES = ("功法", "真意", "气机")


class GrowthService:
    """为人物和道侣提供同一套等级、境界与构筑计算。"""

    def __init__(self, data: JsonDataService, pool: PoolService) -> None:
        self._data = data
        self._pool = pool
        self._initialized = False
        self._cultivator_rule: Mapping[str, object] = {}
        self._realms: dict[str, RealmDefinition] = {}
        self._conflicts: tuple[tuple[str, tuple[frozenset[str], ...]], ...] = ()
        self._attempt_limit = 0

    def initialize(self) -> GrowthStatus:
        if self._initialized:
            raise RuntimeError("成长核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于成长核心启动")
        if not self._pool.status().initialized:
            raise RuntimeError("资源池微服务必须先于成长核心启动")
        rules = self._data.dataset("角色规则")
        self._cultivator_rule = _mapping(rules.get("修士修炼"), "修士修炼.json")
        contract = ContractSet.load(
            self._data.dataset("角色字段契约").get("角色字段契约"),
            "角色/规则/角色字段契约.json",
        )
        self._realms = {}
        for realm_id, value in self._data.entities("境界").items():
            contract.validate(value, "境界", f"境界 {realm_id}")
            self._realms[realm_id] = RealmDefinition(
                realm_id,
                _text(value.get("名称"), f"境界 {realm_id}.名称"),
                _positive_int(value.get("等级下限"), f"境界 {realm_id}.等级下限"),
                _positive_int(value.get("等级上限"), f"境界 {realm_id}.等级上限"),
                str(value.get("下一境界") or "").strip(),
                _positive_int(value.get("寿元"), f"境界 {realm_id}.寿元"),
            )
        build_rules = self._data.dataset("构筑规则")
        generation = _mapping(build_rules.get("生成"), "构筑/生成.json")
        self._attempt_limit = _positive_int(generation.get("尝试上限"), "构筑.尝试上限")
        self._conflicts = tuple(
            (
                _text(_mapping(row, "构筑/相冲.json[]").get("名称"), "相冲.名称"),
                tuple(
                    frozenset(_strings(side, "相冲.相冲[]"))
                    for side in _sequence(
                        _mapping(row, "构筑/相冲.json[]").get("相冲"), "相冲.相冲"
                    )
                ),
            )
            for row in _sequence(build_rules.get("相冲"), "构筑/相冲.json")
        )
        self._validate_static_rules()
        self._initialized = True
        return self.status()

    def status(self) -> GrowthStatus:
        return GrowthStatus(
            self._initialized,
            len(self._realms),
            int(self._cultivator_rule.get("等级上限") or 0),
        )

    def realm(self, realm_id: str) -> RealmDefinition:
        self._require_initialized()
        value = self._realms.get(str(realm_id or "").strip())
        if value is None:
            raise GrowthError(f"未知境界：{realm_id or '<空>'}")
        return value

    def next_realm(self, realm_id: str) -> RealmDefinition:
        current = self.realm(realm_id)
        if not current.next_realm_id:
            raise GrowthError(f"{current.name}已经是最高境界")
        return self.realm(current.next_realm_id)

    def realm_for_level(self, level: int) -> RealmDefinition:
        """返回唯一覆盖指定等级的正式境界。"""

        self._require_initialized()
        if isinstance(level, bool) or not isinstance(level, int) or level < 1:
            raise GrowthError("等级必须是正整数")
        matches = tuple(
            realm
            for realm in self._realms.values()
            if realm.minimum_level <= level <= realm.maximum_level
        )
        if len(matches) != 1:
            raise GrowthError(f"等级{level}无法唯一归属境界")
        return matches[0]

    def experience_required(self, level: int) -> int:
        self._require_initialized()
        maximum = _positive_int(self._cultivator_rule.get("等级上限"), "成长.等级上限")
        if (
            isinstance(level, bool)
            or not isinstance(level, int)
            or not 1 <= level <= maximum
        ):
            raise GrowthError(f"等级必须在1至{maximum}之间")
        if level >= maximum:
            return 0
        curve = _mapping(self._cultivator_rule.get("经验"), "成长.经验")
        base = math.floor(
            _number(curve.get("幂次基数"), "经验.幂次基数")
            * level ** _number(curve.get("等级幂次"), "经验.等级幂次")
            + _number(curve.get("等级基数"), "经验.等级基数") * level
        )
        late = _mapping(curve.get("后段"), "经验.后段")
        start = _positive_int(late.get("起始等级"), "经验.后段.起始等级")
        if level <= start:
            return max(1, base)
        span = _positive_int(late.get("跨度"), "经验.后段.跨度")
        progress = max(0.0, (level - start) / span)
        multiplier = 1.0
        for prefix in ("中段", "高段", "终段"):
            multiplier += _number(
                late.get(f"{prefix}系数"), f"经验.后段.{prefix}系数"
            ) * (
                progress
                ** _number(late.get(f"{prefix}幂次"), f"经验.后段.{prefix}幂次")
            )
        return max(1, math.floor(base * multiplier))

    def advance_cultivator(
        self,
        *,
        level: int,
        experience: int,
        realm_id: str,
        gained: int,
    ) -> ExperienceAdvance:
        self._require_initialized()
        current_realm = self.realm(realm_id)
        return self._advance(
            level=level,
            experience=experience,
            gained=gained,
            maximum_level=current_realm.maximum_level,
        )

    def cultivator_attribute_growth(
        self, levels: int, *, multiplier: float = 1.0
    ) -> Mapping[str, int | float]:
        """计算若干次升级带来的属性增量。"""

        self._require_initialized()
        if isinstance(levels, bool) or not isinstance(levels, int) or levels < 0:
            raise GrowthError("升级次数必须是非负整数")
        if (
            isinstance(multiplier, bool)
            or not isinstance(multiplier, (int, float))
            or multiplier <= 0
        ):
            raise GrowthError("成长倍率必须大于0")
        growth = _mapping(
            _mapping(self._cultivator_rule.get("属性成长"), "修士修炼.属性成长").get(
                "每级"
            ),
            "修士修炼.属性成长.每级",
        )
        result: dict[str, int | float] = {}
        for attribute, raw in growth.items():
            value = _number(raw, f"每级成长.{attribute}") * levels * multiplier
            result[str(attribute)] = (
                int(value) if value.is_integer() else round(value, 4)
            )
        return result

    def random_companion_build(
        self,
        *,
        pools: Mapping[str, str],
        slots: Mapping[str, int],
        seed: int | None = None,
    ) -> RandomCultivationBuild:
        self._require_initialized()
        actual_seed = secrets.randbits(64) if seed is None else seed
        if isinstance(actual_seed, bool) or not isinstance(actual_seed, int):
            raise GrowthError("随机种子必须是整数")
        source = random.Random(actual_seed)
        for _ in range(self._attempt_limit):
            selected: dict[str, tuple[str, ...]] = {}
            for category in _CATEGORIES:
                count = _positive_int(slots.get(category), f"道侣.{category}槽位")
                pool_name = _text(pools.get(category), f"道侣.{category}池")
                selected[category] = self._pool.draw(
                    PoolRequest(
                        section=category,
                        count=count,
                        mode=EXPAND_DEDUPLICATED,
                        file_ids=(pool_name,),
                        seed=source.getrandbits(64),
                    )
                ).entity_ids
            if self.build_conflict(selected) is None:
                return RandomCultivationBuild(
                    actual_seed,
                    selected["功法"],
                    selected["真意"],
                    selected["气机"],
                )
        raise GrowthError("道侣个人修行池无法生成无相冲构筑")

    def build_conflict(
        self, build: Mapping[str, Sequence[str]]
    ) -> str | None:
        """返回构筑触发的相冲规则名；没有相冲时返回 None。"""

        self._require_initialized()
        selected: set[str] = set()
        for category in _CATEGORIES:
            for content_id in build.get(category, ()):
                selected.add(str(content_id))
        for name, sides in self._conflicts:
            if all(selected & side for side in sides):
                return name
        return None

    def redraw_companion_category(
        self,
        *,
        pools: Mapping[str, str],
        current: Mapping[str, Sequence[str]],
        category: str,
        slots: Mapping[str, int],
        seed: int | None = None,
    ) -> CultivationCategoryBuild:
        """只重抽道侣一类构筑，其他类别由调用方原样保留。"""

        self._require_initialized()
        normalized = str(category or "").strip()
        if normalized not in _CATEGORIES:
            raise GrowthError("只能重做功法、真意或气机")
        count = _positive_int(slots.get(normalized), f"道侣.{normalized}槽位")
        pool_name = _text(pools.get(normalized), f"道侣.{normalized}池")
        source = random.Random(secrets.randbits(64) if seed is None else seed)
        preserved = {
            name: tuple(str(item) for item in current.get(name, ()))
            for name in _CATEGORIES
        }
        for _ in range(self._attempt_limit):
            chosen = self._pool.draw(
                PoolRequest(
                    section=normalized,
                    count=count,
                    mode=EXPAND_DEDUPLICATED,
                    file_ids=(pool_name,),
                    seed=source.getrandbits(64),
                )
            ).entity_ids
            preserved[normalized] = chosen
            if self.build_conflict(preserved) is None:
                return CultivationCategoryBuild(normalized, chosen)
        raise GrowthError("道侣个人修行池无法生成无相冲构筑")

    def _advance(
        self,
        *,
        level: int,
        experience: int,
        gained: int,
        maximum_level: int,
    ) -> ExperienceAdvance:
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (level, experience, gained)
        ):
            raise GrowthError("等级和经验必须是整数")
        if level < 1 or experience < 0 or gained < 0:
            raise GrowthError("等级必须为正，经验不能为负")
        current_level = level
        current_experience = experience + gained
        while current_level < maximum_level:
            required = self.experience_required(current_level)
            if current_experience < required:
                break
            current_experience -= required
            current_level += 1
        return ExperienceAdvance(
            level,
            current_level,
            experience,
            current_experience,
            gained,
            current_level - level,
            current_level >= maximum_level,
        )

    def _validate_static_rules(self) -> None:
        maximum = _positive_int(self._cultivator_rule.get("等级上限"), "修士等级上限")
        if maximum != 100:
            raise JsonDataError("当前成长契约要求人物等级上限为100")
        if not self._realms:
            raise JsonDataError("境界定义不能为空")
        for realm in self._realms.values():
            if realm.next_realm_id and realm.next_realm_id not in self._realms:
                raise JsonDataError(f"境界下一境界不存在：{realm.realm_id}")
        # 寿元必须随境界**不倒退**（种族的 `寿元系数` 乘在它上面，倒退会让高境界更短命）。
        ordered = sorted(self._realms.values(), key=lambda item: item.minimum_level)
        previous = 0
        for realm in ordered:
            if realm.lifespan < previous:
                raise JsonDataError(
                    f"境界 {realm.name} 的寿元比上一境界低：{realm.lifespan} < {previous}"
                )
            previous = realm.lifespan
        for level in range(1, maximum + 1):
            matches = tuple(
                realm
                for realm in self._realms.values()
                if realm.minimum_level <= level <= realm.maximum_level
            )
            if len(matches) != 1:
                raise JsonDataError(f"等级{level}必须唯一归属一个境界")
        self._validate_conflicts()

    def _validate_conflicts(self) -> None:
        """相冲规则必须成对、互不重叠，并且只引用构筑类别的真实卡片。"""

        known = {
            category: set(self._data.entities(category))
            for category in _CATEGORIES
        }
        names: set[str] = set()
        for name, sides in self._conflicts:
            if name in names:
                raise JsonDataError(f"相冲规则名重复：{name}")
            names.add(name)
            if len(sides) != 2:
                raise JsonDataError(f"相冲规则{name}必须声明两组卡片")
            for side in sides:
                if not side:
                    raise JsonDataError(f"相冲规则{name}存在空分组")
                for content_id in side:
                    if not any(content_id in known[category] for category in _CATEGORIES):
                        raise JsonDataError(
                            f"相冲规则{name}引用未知卡片：{content_id}"
                        )
            if sides[0] & sides[1]:
                overlap = "、".join(sorted(sides[0] & sides[1]))
                raise JsonDataError(f"相冲规则{name}两组卡片重叠：{overlap}")

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("成长核心微服务尚未初始化")


def _strings(value: object, label: str) -> tuple[str, ...]:
    result = tuple(_text(raw, label) for raw in _sequence(value, label))
    if not result:
        raise JsonDataError(f"{label}不能为空")
    return result


__all__ = ["GrowthService"]
