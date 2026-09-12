"""创建人物流程编排。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from game.core.character import (
    CharacterAlreadyExistsError,
    CharacterCreateCommand,
    CharacterInputError,
    CharacterService,
)
from game.core.data import JsonDataError, JsonDataService
from game.core.world import LocationQuery, WorldService

from .contracts import (
    CharacterExistsError,
    CreateCharacterRequest,
    CreateCharacterResult,
    InvalidCreateCharacterError,
)


class CreateCharacterFeature:
    """解析出生地并把创建请求交给角色核心服务。"""

    def __init__(
        self,
        data: JsonDataService,
        world: WorldService,
        character: CharacterService,
    ) -> None:
        self._data = data
        self._world = world
        self._character = character
        self._birthplace = ""
        self._grade_names: dict[str, str] = {}

    def initialize(self) -> str:
        role_rule = self._data.dataset("角色规则").get("人物")
        if not isinstance(role_rule, Mapping):
            raise JsonDataError("角色规则缺少人物.json")
        creation = role_rule.get("创建")
        if not isinstance(creation, Mapping):
            raise JsonDataError("人物.json 缺少创建规则")
        source = creation.get("初始出生地")
        if not isinstance(source, Mapping):
            raise JsonDataError("人物.json.创建缺少初始出生地")
        section = str(source.get("数据集") or "").strip()
        entity_id = str(source.get("实体") or "").strip()
        field = str(source.get("字段") or "").strip()
        entity = self._data.entity(section, entity_id)
        birthplace = str(entity.get(field) or "").strip()
        if not birthplace:
            raise JsonDataError("人物初始出生地引用没有得到地点名")
        self._world.locate(LocationQuery(location_name=birthplace))
        self._birthplace = birthplace
        grades = self._data.dataset("基础定义").get("品级")
        if not isinstance(grades, Sequence) or isinstance(grades, (str, bytes)):
            raise JsonDataError("基础定义缺少品级.json")
        self._grade_names = {
            str(item.get("编号") or "").strip(): str(item.get("名称") or "").strip()
            for item in grades
            if isinstance(item, Mapping)
        }
        return birthplace

    async def create(self, request: CreateCharacterRequest) -> CreateCharacterResult:
        if not self._birthplace:
            raise RuntimeError("创建人物玩法微服务尚未初始化")
        location = self._world.locate(LocationQuery(location_name=self._birthplace))
        try:
            created = await self._character.create(
                CharacterCreateCommand(
                    user_id=request.user_id,
                    request_id=request.request_id,
                    name=request.name,
                    gender=request.gender,
                    birth_xy=location.xy,
                )
            )
        except CharacterInputError as exc:
            raise InvalidCreateCharacterError(str(exc)) from exc
        except CharacterAlreadyExistsError as exc:
            raise CharacterExistsError(str(exc)) from exc
        item_names = tuple(
            (
                str(self._data.entity(dataset, item_id).get("名称") or item_id),
                self._grade_names.get(grade, grade),
                quantity,
            )
            for dataset, item_id, grade, quantity in created.initial_items
        )
        return CreateCharacterResult(
            user_id=created.user_id,
            name=created.name,
            gender=created.gender,
            realm_id=created.realm_id,
            realm_name=created.realm_name,
            location_name=location.location_name,
            xy=location.xy,
            region=location.region,
            terrain=location.terrain,
            altitude=location.altitude,
            initial_items=item_names,
            replayed=created.replayed,
        )


__all__ = ["CreateCharacterFeature"]
