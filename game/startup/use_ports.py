"""组合根的使用端口适配：把各 feature 接到统一使用网关上。"""
from __future__ import annotations

from typing import Any

from game.features.fudan import MedicineUseRequest
from game.features.shiyong import (
    UseCandidate,
    UseDescription,
    UsePort,
    UseRequest,
)
from game.features.xiantian_lingbao import InnateTreasureEquipRequest


def build_use_ports(
    renwu_peiyang: Any,
    xiantian_lingbao: Any,
    fudan: Any,
) -> dict[str, UsePort]:
    async def describe_peiyang(request: UseRequest) -> UseDescription:
        target = await renwu_peiyang.resolve_use_target(request.user_id, request.item_id)
        position = "本命武器孔" if target.category == "器律" else "人物修行槽"
        return UseDescription(
            display=f"{request.grade}{target.name}",
            position_kind=position,
            candidates=tuple(
                UseCandidate(str(slot), str(slot), "位置") for slot in target.slots
            ),
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

    async def describe_treasure(request: UseRequest) -> UseDescription:
        return UseDescription(
            display=request.name,
            position_kind="无",
        )

    async def execute_treasure(request: UseRequest) -> object:
        return await xiantian_lingbao.equip(
            InnateTreasureEquipRequest(
                request.user_id, request.request_id, request.item_id
            )
        )

    async def describe_fudan(request: UseRequest) -> UseDescription:
        return UseDescription(
            display=f"{request.grade}{request.name}",
            position_kind="服用对象",
            candidates=(
                UseCandidate("人物", "人物", "目标"),
                UseCandidate("道侣", "道侣", "目标"),
            ),
            default="人物",
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

    return {
        "renwu_peiyang": UsePort(describe_peiyang, execute_peiyang),
        "xiantian_lingbao": UsePort(describe_treasure, execute_treasure),
        "fudan": UsePort(describe_fudan, execute_fudan),
    }


__all__ = ["build_use_ports"]
