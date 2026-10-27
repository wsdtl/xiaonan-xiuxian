"""炼制环境、材料节省与个人灵石消耗的共用规则。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from game.core.data import JsonDataError, JsonDataService, mapping, positive_int
from game.core.location import LocationService
from game.core.world import CraftFacility, LocationQuery, WorldService

_MATERIAL_SAVING_SCALE = 10_000
_CRAFT_KINDS = frozenset({"炼器", "炼丹", "炼阵"})


def facility_payload(facility: CraftFacility | None) -> dict[str, object] | None:
    if facility is None:
        return None
    return {
        "类别": facility.category,
        "名称": facility.name,
        "材料节省万分比": facility.material_saving_bp,
    }


def facility_from_payload(value: object, label: str = "事务.设施") -> CraftFacility | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}必须是对象")
    category = str(value.get("类别") or "").strip()
    name = str(value.get("名称") or "").strip()
    raw_saving = value.get("材料节省万分比", 0)
    if category not in _CRAFT_KINDS or not name:
        raise ValueError(f"{label}缺少类别或名称")
    if isinstance(raw_saving, bool) or not isinstance(raw_saving, int) or not 0 <= raw_saving <= _MATERIAL_SAVING_SCALE:
        raise ValueError(f"{label}.材料节省万分比不合法")
    return CraftFacility(category, name, raw_saving)


def material_quantity(required: int, saving_bp: int) -> int:
    """按总需求一次性结算材料节省；批量越大，越容易把小数凑成整数。"""

    if isinstance(required, bool) or not isinstance(required, int) or required < 0:
        raise ValueError("材料需求必须是非负整数")
    if isinstance(saving_bp, bool) or not isinstance(saving_bp, int) or not 0 <= saving_bp <= _MATERIAL_SAVING_SCALE:
        raise ValueError("材料节省必须在 0 到 10000 的整数万分比之间")
    return max(1, required - required * saving_bp // _MATERIAL_SAVING_SCALE)


@dataclass(frozen=True)
class CraftEnvironment:
    location_name: str
    facility: CraftFacility | None = None

    @property
    def facility_name(self) -> str:
        return self.facility.name if self.facility else "随身"


async def current_environment(
    location: LocationService,
    world: WorldService,
    user_id: str,
    category: str,
) -> CraftEnvironment:
    """任何坐标都可炼制；只有坐标正好是带同类设施的城池时才取设施。"""

    if category not in _CRAFT_KINDS:
        raise ValueError(f"未知炼制类别：{category}")
    current = await location.current(user_id)
    place = world.locate(LocationQuery(xy=current.xy))
    facility = place.facility
    if facility is not None and facility.category != category:
        facility = None
    return CraftEnvironment(place.location_name or "随身", facility)


class CraftCostRules:
    """普通炼制与宗门炼制共用的灵石消耗表。"""

    def __init__(self, data: JsonDataService) -> None:
        raw = mapping(data.dataset("灵石消耗").get("灵石消耗"), "灵石消耗")
        base = mapping(raw.get("基础"), "灵石消耗.基础")
        self._base = {
            kind: positive_int(base.get(kind), f"灵石消耗.基础.{kind}")
            for kind in _CRAFT_KINDS
        }
        self._stage_multiplier = {
            str(key): positive_int(value, f"灵石消耗.器阶倍率.{key}")
            for key, value in mapping(raw.get("器阶倍率"), "灵石消耗.器阶倍率").items()
        }
        grade_rows = data.dataset("基础定义").get("品级")
        if not isinstance(grade_rows, Sequence) or isinstance(grade_rows, (str, bytes)):
            raise JsonDataError("品级.json 必须是数组")
        self._grade_multiplier: dict[str, int] = {}
        for index, row in enumerate(grade_rows):
            item = mapping(row, f"品级[{index}]")
            name = str(item.get("名称") or "").strip()
            if not name or name in self._grade_multiplier:
                raise JsonDataError(f"品级名称重复或为空：{name}")
            self._grade_multiplier[name] = positive_int(
                item.get("宗门炼制倍率"), f"品级[{index}].宗门炼制倍率"
            )

    def cost(self, kind: str, grade_or_stage: str) -> int:
        if kind not in _CRAFT_KINDS:
            raise ValueError(f"未知炼制类别：{kind}")
        key = str(grade_or_stage or "").strip()
        multiplier = (
            self._stage_multiplier.get(key)
            if kind == "炼器"
            else self._grade_multiplier.get(key)
        )
        if multiplier is None:
            raise ValueError(f"灵石消耗缺少{kind}的{key}倍率")
        return self._base[kind] * multiplier
