from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GiftAction:
    """赠送回执上的动作，字段名与 CommandAction 契约一致。"""

    action_id: str
    label: str
    command: str
    behavior: str
    style: str

from collections.abc import Mapping

from game.core.character import CharacterService
from game.core.data import JsonDataError, JsonDataService
from game.core.gift import GiftError, GiftResult, GiftSendCommand, GiftService
from game.core.item_catalog import ItemCatalogService
from game.features.presentation import parse_item_ref


@dataclass(frozen=True)
class GiftEntry:
    """一次赠送根命令的结果；分支与参数合规由玩法判定。"""

    kind: str
    target_name: str
    result: GiftResult


class GiftFeature:
    def __init__(self, data: JsonDataService, gift: GiftService, item_catalog: ItemCatalogService, character: CharacterService) -> None:
        self._data = data
        self._gift = gift
        self._items = item_catalog
        self._character = character
        self._copy: Mapping[str, object] | None = None

    def initialize(self) -> None:
        copy = self._data.dataset("赠送展示").get("文本")
        buttons = self._data.dataset("赠送按钮").get("按钮") or ()
        self._format_actions = tuple(
            GiftAction(
                str(row["编号"]), str(row["名称"]), str(row["命令"]),
                str(row["行为"]), str(row["样式"]),
            )
            for row in buttons
            if isinstance(row, Mapping)
        )
        if not isinstance(copy, Mapping):
            raise JsonDataError("玩法/赠送/展示/文本.json 必须是对象")
        self._copy = copy

    def format_actions(self) -> tuple[GiftAction, ...]:
        """格式与提示类回执的动作：只给「查看帮助」。"""

        return self._format_actions


    def text(self, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
        if self._copy is None:
            raise RuntimeError("赠送玩法尚未初始化")
        group = self._copy.get(section) if section else self._copy
        result = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(result, str):
            raise TypeError(f"赠送展示缺少文本：{key}")
        return result.format_map(values or {})

    async def enter(
        self, user_id: str, request_id: str, raw_message: str
    ) -> GiftEntry:
        """解析赠送根命令；分支与参数合规只由本玩法判定。"""

        parts = str(raw_message or "").split()
        if len(parts) == 3 and parts[1] == "灵石":
            target = await self.resolve_target(user_id, parts[0])
            target_name = await self.target_name(target)
            result = await self.send(
                GiftSendCommand(
                    user_id,
                    target,
                    request_id,
                    spirit_stones=self._positive(parts[2]),
                )
            )
            return GiftEntry("stones", target_name, result)
        if len(parts) not in {3, 4}:
            raise ValueError(self.text("命令", "物品格式"))
        if len(parts) == 4:
            item_word, grade = parts[1], parts[2]
            quantity = self._positive(parts[3])
        else:
            ref = parse_item_ref(parts[1])
            item_word, grade = ref.item, ref.grade
            quantity = self._positive(parts[2])
        target = await self.resolve_target(user_id, parts[0])
        target_name = await self.target_name(target)
        item_id = self.resolve_item(item_word)
        result = await self.send(
            GiftSendCommand(
                user_id,
                target,
                request_id,
                item_id=item_id,
                grade_id=grade,
                quantity=quantity,
            )
        )
        return GiftEntry("item", target_name, result)

    def _positive(self, value: str) -> int:
        if not value.isdecimal() or int(value) < 1:
            raise ValueError("数量必须是正整数")
        return int(value)

    async def resolve_target(self, user_id: str, query: str) -> str:
        return await self._gift.resolve_target(user_id, query)

    async def target_name(self, target_user_id: str) -> str:
        profiles = await self._character.public_profiles((target_user_id,))
        if not profiles:
            raise GiftError("接收者的人物信息不存在")
        return profiles[0].name

    async def send(self, command: GiftSendCommand) -> GiftResult:
        return await self._gift.send(command)

    def resolve_item(self, query: str) -> str:
        """把玩家写的物品名或编号换成物品编号。

        认不出或多条同名由物品查询核心按自己的话回绝（`ItemCatalogError` 是 `ValueError`），
        命令层不解释物品 JSON。
        """

        return self._items.inspect(query).item_id
