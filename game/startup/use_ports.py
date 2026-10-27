"""组合根的使用端口适配：把各 feature 接到统一使用网关上。"""
from __future__ import annotations

from typing import Any

from game.core.asset import ItemRef, format_item_ref

from game.features.daolv_peiyang import (
    CompanionCultivationFeatureError,
    CompanionLawRequest,
)
from game.features.fudan import MedicineUseRequest
from game.features.shiyong import (
    UseDescription,
    UseOption,
    UsePort,
    UseRequest,
)
from game.features.xiantian_lingbao import InnateTreasureEquipRequest


def build_use_ports(
    renwu_peiyang: Any,
    daolv_peiyang: Any,
    xiantian_lingbao: Any,
    fudan: Any,
    buzhen: Any,
) -> dict[str, UsePort]:
    async def describe_peiyang(request: UseRequest) -> UseDescription:
        target = await renwu_peiyang.resolve_use_target(request.user_id, request.item_id)
        options = tuple(
            UseOption("", slot, str(slot)) for slot in target.slots
        )
        return UseDescription(
            display=f"{request.grade}{target.name}",
            options=options,
            position_default="1" if options else "",
        )

    async def execute_peiyang(request: UseRequest) -> object:
        target = await renwu_peiyang.resolve_use_target(request.user_id, request.item_id)
        return await renwu_peiyang.use(
            request.user_id,
            request.request_id,
            target,
            request.grade,
            request.position,
        )

    async def _companion_law_slots(request: UseRequest) -> int:
        try:
            view = await daolv_peiyang.inspect(request.user_id)
        except CompanionCultivationFeatureError:
            return 0
        return int(view.open_law_slots)

    async def describe_law(request: UseRequest) -> UseDescription:
        player = await renwu_peiyang.resolve_use_target(request.user_id, request.item_id)
        options = [
            UseOption("人物", slot, f"人物 {slot}") for slot in player.slots
        ]
        companion_slots = await _companion_law_slots(request)
        options.extend(
            UseOption("道侣", slot, f"道侣 {slot}")
            for slot in range(1, companion_slots + 1)
        )
        return UseDescription(
            display=request.name,
            options=tuple(options),
            target_default="人物",
            position_default="1",
        )

    async def execute_law(request: UseRequest) -> object:
        if request.target == "道侣":
            return await daolv_peiyang.forge_law(
                CompanionLawRequest(
                    request.user_id,
                    request.request_id,
                    request.item_id,
                    request.position,
                )
            )
        target = await renwu_peiyang.resolve_use_target(request.user_id, request.item_id)
        return await renwu_peiyang.use(
            request.user_id,
            request.request_id,
            target,
            request.grade,
            request.position,
        )

    async def describe_treasure(request: UseRequest) -> UseDescription:
        return UseDescription(display=request.name)

    async def execute_treasure(request: UseRequest) -> object:
        return await xiantian_lingbao.equip(
            InnateTreasureEquipRequest(
                request.user_id, request.request_id, request.item_id
            )
        )

    async def describe_fudan(request: UseRequest) -> UseDescription:
        return UseDescription(
            display=f"{request.grade}{request.name}",
            options=(
                UseOption("人物", 0, "人物"),
                UseOption("道侣", 0, "道侣"),
            ),
            target_default="人物",
        )

    async def execute_fudan(request: UseRequest) -> object:
        return await fudan.use(
            MedicineUseRequest(
                request.user_id,
                request.request_id,
                request.target or "人物",
                request.item_id,
                request.grade,
            )
        )

    async def describe_buzhen(request: UseRequest) -> UseDescription:
        return UseDescription(display=request.name)

    async def execute_buzhen(request: UseRequest) -> object:
        identifier = format_item_ref(
            ItemRef(
                item=request.name,
                grade=request.grade,
                treasure=request.treasure,
            )
        )
        return await buzhen.arm(
            request.user_id, request.request_id, identifier
        )

    return {
        "renwu_peiyang": UsePort(describe_peiyang, execute_peiyang),
        "law": UsePort(describe_law, execute_law),
        "xiantian_lingbao": UsePort(describe_treasure, execute_treasure),
        "fudan": UsePort(describe_fudan, execute_fudan),
        "buzhen": UsePort(describe_buzhen, execute_buzhen),
    }


__all__ = ["build_use_ports"]
