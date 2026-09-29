"""整套人物装配的内部计划器；复用角色原有实体、品级、相冲与器阶规则。"""
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from game.core.database import StateAddress, StateMutation

from .contracts import CharacterAssemblyPlan, CharacterCultivationError, CharacterStateError

if TYPE_CHECKING:
    from .service import CharacterService


async def plan_assembly(
    service: "CharacterService", user_id: str,
    build: Mapping[str, Sequence[Mapping[str, str] | None]],
    *, retain_replaced: bool,
) -> CharacterAssemblyPlan:
    categories = ("功法", "真意", "气机")
    if set(build) != {*categories, "器律"}:
        raise CharacterCultivationError("整套装配必须包含功法、真意、气机和器律")
    snapshots = await service._database.get_many(tuple(
        StateAddress(user_id, kind, "main") for kind in ("cultivation", "weapon")
    ))
    states = {value.address.state_type: value for value in snapshots}
    if len(states) != 2:
        raise CharacterStateError("人物缺少修行槽或本命武器")
    cultivation = dict(states["cultivation"].value)
    if service._sect_library is not None:
        cultivation = dict(await service._sect_library.effective_cultivation(user_id, cultivation))
    weapon = dict(states["weapon"].value)
    operations = []
    costs: Counter[tuple[str, str, str]] = Counter()
    returns: Counter[tuple[str, str, str]] = Counter()
    changed = 0
    for category in categories:
        old_slots = list(cultivation[category])
        chosen = list(build[category])
        if len(chosen) > len(old_slots):
            raise CharacterCultivationError(f"{category}槽位只有{len(old_slots)}个")
        chosen.extend([None] * (len(old_slots) - len(chosen)))
        seen = set()
        for index, entry in enumerate(chosen):
            old = old_slots[index]
            if entry is not None:
                _, _, content_id, grade = service._equip_target(
                    user_id, category, index + 1, entry["编号"], entry["品级"]
                )
                if content_id in seen:
                    raise CharacterCultivationError(f"{category}不能重复装配同一内容")
                seen.add(content_id)
                entry = {"编号": content_id, "品级": grade.grade_id}
            if entry is None and old is None:
                continue
            if old is not None and entry is not None and all(old.get(key) == value for key, value in entry.items()):
                chosen[index] = old
                continue
            changed += 1
            chosen[index] = entry
            if entry is not None:
                if category == "功法":
                    ownership = await service._asset.cultivation_ownership(
                        user_id, category, entry["编号"], entry["品级"]
                    )
                    # 所有权也参与版本检查，避免校验后被并发升级或移除。
                    operations.append(StateMutation(user_id, "cultivation_library", ownership.content_id,
                                                    {"编号": ownership.content_id, "品级": ownership.grade.grade_id},
                                                    ownership.version))
                else:
                    costs[(category, entry["编号"], entry["品级"])] += 1
                    if old is not None and retain_replaced:
                        returns[(category, old["编号"], old["品级"])] += 1
        cultivation[category] = chosen
    service._equip_conflict(cultivation)
    # 先检查所需库存，再结算灵宝返还；不得用本次返还的内容垫付本次消耗。
    for key in sorted(costs.keys() | returns.keys()):
        category, content_id, grade_id = key
        stack = await service._asset.cultivation_reserve_stack(user_id, category, content_id, grade_id)
        quantity = 0 if stack is None else stack.quantity
        if quantity < costs[key]:
            raise CharacterCultivationError(f"{category} {content_id} 品级{grade_id}不足：需要{costs[key]}份，现有{quantity}份")
        delta = returns[key] - costs[key]
        if delta:
            plan = await service._asset.plan_cultivation_reserve_change(
                user_id, category=category, content_id=content_id,
                grade_id=grade_id, quantity_delta=delta,
            )
            if (0 if stack is None else stack.version) != plan.operation.expected_version:
                raise CharacterCultivationError("修行资粮已经变化，请重试")
            operations.append(plan.operation)
        elif stack is not None:
            operations.append(StateMutation(user_id, "cultivation_reserve", f"{content_id}:{grade_id}",
                {"类别": category, "编号": content_id, "品级": grade_id, "数量": quantity}, stack.version))
    level = weapon["等级"]
    limit = service._forging.weapon_stage(level).open_law_slots
    laws = list(build["器律"])
    if len(laws) > limit:
        raise CharacterCultivationError(f"当前本命武器只开放{limit}个器律孔")
    laws.extend([None] * (limit - len(laws)))
    old_laws = list(weapon["器律"])
    old_laws.extend([None] * (limit - len(old_laws)))
    law_costs: Counter[str] = Counter()
    for index, entry in enumerate(laws):
        law_id = None if entry is None else entry["编号"]
        if entry is not None:
            if entry["品级"]:
                raise CharacterCultivationError("器律不使用品级")
            law = service._data.entity("器律", law_id)
            if not service._forging.law_allowed(level, str(law["器阶"])):
                raise CharacterCultivationError("该器律的器阶高于当前本命武器")
        if law_id != old_laws[index]:
            changed += 1
            if law_id is not None:
                law_costs[law_id] += 1
        laws[index] = law_id
    for law_id, count in law_costs.items():
        plan = await service._asset.plan_law_reserve_consumption(user_id, law_id, quantity=count)
        operations.append(plan.operation)
    weapon["器律"] = laws
    operations.extend((
        StateMutation(user_id, "cultivation", "main", cultivation, states["cultivation"].version),
        StateMutation(user_id, "weapon", "main", weapon, states["weapon"].version),
    ))
    return CharacterAssemblyPlan(tuple(operations), changed)
