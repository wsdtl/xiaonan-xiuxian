"""解释先天灵宝 JSON，并拥有玩家灵宝谱与单槽状态。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService
from game.core.database import DatabaseService, StateAddress, StateMutation

from .contracts import (
    InnateTreasure,
    InnateTreasureCollection,
    InnateTreasureEffect,
    InnateTreasureError,
    InnateTreasureMutationPlan,
    InnateTreasureStatus,
)

STATE_TYPE = "innate_treasure"
STATE_KEY = "main"

_ABILITY_FIELDS = {
    "返还主要辅材": {"数量"},
    "返还灵矿": {"比例", "最低数量"},
    "提高总势": {"比例"},
    "增加每轮感悟判定": {"次数"},
    "增加每轮疗养进度": {"进度"},
    "提高恢复量": {"比例"},
    "最低品战利品升品": {"数量"},
    "保留被替换资粮": {"比例"},
    "提高偏爱好感": {"比例"},
    "提高通用采集": {"比例", "最低数量"},
    "提高贡献": {"比例", "最低数量"},
    "增加成丹": {"数量"},
    "提高转化效率": {"效率"},
    "提高材料阵势": {"材料", "比例"},
    "提高永久属性": {"比例", "最低数量"},
    "增加兽宝": {"数量"},
    "提高采药": {"比例", "最低数量"},
    "提高采矿": {"比例", "最低数量"},
    "提高每轮经验": {"比例"},
}


class InnateTreasureService:
    """先天灵宝的唯一规则解释和状态写入边界。"""

    state_types = frozenset({STATE_TYPE})

    def __init__(self, data: JsonDataService, database: DatabaseService) -> None:
        self._data = data
        self._database = database
        self._initialized = False
        self._treasures: Mapping[str, InnateTreasure] = MappingProxyType({})
        self._by_name: Mapping[str, str] = MappingProxyType({})
        self._page_limit = 0

    def initialize(self) -> InnateTreasureStatus:
        if self._initialized:
            raise RuntimeError("先天灵宝核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于先天灵宝核心启动")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于先天灵宝核心启动")
        rules = _mapping(
            self._data.dataset("先天灵宝规则").get("先天灵宝"),
            "先天灵宝/规则/先天灵宝.json",
        )
        self._validate_rules(rules)
        self._page_limit = _positive_int(
            _mapping(rules.get("分页"), "先天灵宝.分页").get("每页上限"),
            "先天灵宝.分页.每页上限",
        )
        treasures = {
            treasure_id: _treasure(treasure_id, raw)
            for treasure_id, raw in self._data.entities("先天灵宝").items()
        }
        if len(treasures) != 21:
            raise JsonDataError("首批先天灵宝必须完整定义21件")
        names = {value.name: value.treasure_id for value in treasures.values()}
        if len(names) != len(treasures):
            raise JsonDataError("先天灵宝名称不能重复")
        self._treasures = MappingProxyType(treasures)
        self._by_name = MappingProxyType(names)
        self._initialized = True
        return self.status()

    def status(self) -> InnateTreasureStatus:
        return InnateTreasureStatus(
            self._initialized, len(self._treasures), 1 if self._initialized else 0, self._page_limit
        )

    def treasures(self) -> tuple[InnateTreasure, ...]:
        self._require_initialized()
        return tuple(self._treasures[key] for key in sorted(self._treasures))

    def resolve(self, identifier: str) -> InnateTreasure:
        self._require_initialized()
        query = _text(identifier, "先天灵宝编号或名称")
        treasure = self._treasures.get(query)
        if treasure is None:
            treasure = self._treasures.get(self._by_name.get(query, ""))
        if treasure is None:
            raise InnateTreasureError(f"未找到先天灵宝：{query}")
        return treasure

    def effect_for(
        self, treasure_id: str | None, node: str
    ) -> InnateTreasureEffect | None:
        self._require_initialized()
        if not treasure_id:
            return None
        treasure = self._treasures.get(str(treasure_id))
        if treasure is None:
            raise InnateTreasureError("活动快照引用了未知先天灵宝")
        return treasure.effect if treasure.effect.node == node else None

    async def collection(self, user_id: str) -> InnateTreasureCollection:
        self._require_initialized()
        user = _text(user_id, "user_id")
        snapshot = await self._database.get(StateAddress(user, STATE_TYPE, STATE_KEY))
        if snapshot is None:
            return InnateTreasureCollection(user, (), None, 0)
        value = _mapping(snapshot.value, "先天灵宝状态")
        owned_ids = _unique_ids(value.get("已获得"), "先天灵宝.已获得")
        active_id = str(value.get("当前执掌") or "").strip()
        unknown = set(owned_ids) - set(self._treasures)
        if unknown:
            raise InnateTreasureError(f"灵宝谱包含未知编号：{sorted(unknown)}")
        if active_id and active_id not in owned_ids:
            raise InnateTreasureError("当前执掌的先天灵宝不在灵宝谱中")
        return InnateTreasureCollection(
            user,
            tuple(self._treasures[item] for item in owned_ids),
            self._treasures.get(active_id),
            snapshot.version,
        )

    async def active(self, user_id: str) -> InnateTreasure | None:
        return (await self.collection(user_id)).active

    async def effect(
        self, user_id: str, node: str
    ) -> tuple[InnateTreasure, InnateTreasureEffect] | None:
        active = await self.active(user_id)
        if active is None or active.effect.node != node:
            return None
        return active, active.effect

    async def plan_acquire(
        self, user_id: str, treasure_id: str
    ) -> InnateTreasureMutationPlan:
        """供后续秘境结算把一件灵宝永久收入玩家灵宝谱。"""

        treasure = self.resolve(treasure_id)
        collection = await self.collection(user_id)
        if treasure.treasure_id in {value.treasure_id for value in collection.owned}:
            return InnateTreasureMutationPlan(treasure, None, True)
        owned = sorted(
            [*(value.treasure_id for value in collection.owned), treasure.treasure_id]
        )
        return InnateTreasureMutationPlan(
            treasure,
            StateMutation(
                collection.user_id,
                STATE_TYPE,
                STATE_KEY,
                {
                    "已获得": owned,
                    "当前执掌": (
                        collection.active.treasure_id if collection.active else ""
                    ),
                },
                collection.version,
            ),
        )

    async def plan_equip(
        self, user_id: str, identifier: str
    ) -> InnateTreasureMutationPlan:
        treasure = self.resolve(identifier)
        collection = await self.collection(user_id)
        owned_ids = [value.treasure_id for value in collection.owned]
        if treasure.treasure_id not in owned_ids:
            raise InnateTreasureError("灵宝谱中没有这件先天灵宝")
        if collection.active == treasure:
            raise InnateTreasureError("当前已经执掌这件先天灵宝")
        return InnateTreasureMutationPlan(
            treasure,
            StateMutation(
                collection.user_id,
                STATE_TYPE,
                STATE_KEY,
                {"已获得": owned_ids, "当前执掌": treasure.treasure_id},
                collection.version,
            ),
        )

    def _validate_rules(self, rules: Mapping[str, object]) -> None:
        slot = _mapping(rules.get("槽位"), "先天灵宝.槽位")
        expected = {
            "承载者": "玩家人物",
            "数量": 1,
            "未执掌允许": True,
            "替换消耗": 0,
            "替换守卫": "自主空闲或休息",
            "活动快照": "开始时冻结",
            "道侣可用": False,
        }
        if dict(slot) != expected:
            raise JsonDataError("先天灵宝槽位规则必须保持玩家单槽、无消耗替换")
        ownership = _mapping(rules.get("归属"), "先天灵宝.归属")
        if dict(ownership) != {
            "获得后": "永久认主",
            "允许交易": False,
            "允许捐献": False,
            "允许掉落": False,
            "允许重复获得": False,
        }:
            raise JsonDataError("先天灵宝必须永久认主且不可流通、掉落或重复获得")
        values = _mapping(rules.get("数值"), "先天灵宝.数值")
        if dict(values) != {
            "比例取整": "向上取整",
            "正向数量最低增加": 1,
            "数值上限": "不超过原业务上限",
        }:
            raise JsonDataError("先天灵宝数值规则必须保证正向效果至少实际生效一次")

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("先天灵宝核心微服务尚未初始化")


def _treasure(treasure_id: str, value: object) -> InnateTreasure:
    raw = _mapping(value, f"先天灵宝 {treasure_id}")
    if _text(raw.get("编号"), "先天灵宝.编号") != treasure_id:
        raise JsonDataError("先天灵宝编号与索引不一致")
    effect_raw = _mapping(raw.get("规则介入"), "先天灵宝.规则介入")
    node = _text(effect_raw.get("节点"), "先天灵宝.规则介入.节点")
    ability = _text(effect_raw.get("能力"), "先天灵宝.规则介入.能力")
    fields = set(effect_raw) - {"节点", "能力"}
    expected = _ABILITY_FIELDS.get(ability)
    if expected is None or fields != expected:
        raise JsonDataError(f"先天灵宝能力字段不完整：{ability}")
    values = {key: effect_raw[key] for key in sorted(fields)}
    for key, raw_value in values.items():
        if key in {"比例", "效率"}:
            _positive_number(raw_value, f"先天灵宝.{ability}.{key}")
        elif key in {"数量", "最低数量", "次数", "进度"}:
            _positive_int(raw_value, f"先天灵宝.{ability}.{key}")
        elif key == "材料" and raw_value not in {"兽宝", "灵矿", "灵植"}:
            raise JsonDataError("先天灵宝阵势材料只能是兽宝、灵矿或灵植")
    return InnateTreasure(
        treasure_id,
        _text(raw.get("名称"), "先天灵宝.名称"),
        _text(raw.get("权柄"), "先天灵宝.权柄"),
        _text(raw.get("说明"), "先天灵宝.说明"),
        InnateTreasureEffect(node, ability, MappingProxyType(values)),
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def _text(value: object, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise InnateTreasureError(f"{label}不能为空")
    return result


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise JsonDataError(f"{label}必须是正整数")
    return value


def _positive_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise JsonDataError(f"{label}必须是正数")
    return float(value)


def _unique_ids(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise InnateTreasureError(f"{label}必须是编号数组")
    result = tuple(_text(item, f"{label}[]") for item in value)
    if len(result) != len(set(result)):
        raise InnateTreasureError(f"{label}不能重复")
    return result


__all__ = ["STATE_KEY", "STATE_TYPE", "InnateTreasureService"]
