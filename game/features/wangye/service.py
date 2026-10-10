'''网页公开：一条全局开关，管住所有「网页直接读你的数据」的页面。

**存在哪、为什么**：存**共享索引** `web_public`（一人一行 `{名称, 公开}`），不是人物状态的一格。
理由是被数据库的公开口逼出来的：它能按共享实体枚举（`list_shared_entities`），却没有任何
「枚举全部人物状态」的口——而网页必须能枚举「谁开了」，所以索引只能放共享实体。
开关的**语义**仍然是全局的：一条开关管所有这类页面，页面不各造一个。

**可见性**：有人开了才看得见，没人开就什么都看不到；「全池」是装配台自己的东西，本包不提供。
'''

from __future__ import annotations

from collections.abc import Mapping

from game.core.character import CharacterNotFoundError, CharacterService
from game.core.data import JsonDataError, JsonDataService
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    SharedEntityMutation,
    StateConflictError,
    TransactionCommand,
)

from .contracts import WangyeConflictError, WangyeError, WangyeScope

#: 开关的索引：一人一行，网页靠它枚举「谁开了」。名字里不带任何旧功能的痕迹。
ENTITY = 'web_public'
BUSINESS = '网页资源公开'


class WangyeFeature:
    def __init__(self, data: JsonDataService, character: CharacterService, database: DatabaseService) -> None:
        self._data, self._character, self._database = data, character, database
        self._copy: Mapping[str, object] | None = None

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError('网页公开玩法已经初始化')
        # 数据集返回的是「文件名到正文」的视图，正文那一层要按文件名取（文本.json → '文本'）。
        copy = self._data.dataset('网页公开展示').get('文本')
        if not isinstance(copy, Mapping):
            raise JsonDataError('网页公开展示缺少文本.json')
        for group in ('公开', '错误'):
            if not isinstance(copy.get(group), Mapping):
                raise JsonDataError(f'网页公开展示缺少一组文案：{group}')
        self._copy = copy

    def copy(self, section: str, key: str) -> str:
        if self._copy is None:
            raise RuntimeError('网页公开玩法尚未初始化')
        group = self._copy.get(section)
        value = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(value, str):
            raise JsonDataError(f'网页公开展示缺少文案：{section}.{key}')
        return value

    async def is_public(self, user_id: str) -> bool:
        record = await self._database.get_shared_entity(ENTITY, user_id)
        return bool(record is not None and dict(record.value).get('公开'))

    async def scopes(self) -> list[WangyeScope]:
        '''已公开的人。没人开就是空清单——页面据此显示「还没有人公开」。'''

        records = await self._database.list_shared_entities(ENTITY)
        ids = tuple(record.entity_id for record in records if dict(record.value).get('公开'))
        if not ids:
            return []
        profiles = await self._character.public_profiles(ids)
        return [WangyeScope(profile.user_id, profile.name) for profile in profiles]

    async def set_public(self, user_id: str, request_id: str, enabled: bool) -> bool:
        '''开或关。两个命令各管一头，所以这里收的是明确的目标状态，不是取反。'''

        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != BUSINESS:
                raise WangyeConflictError('请求编号已经用于其他操作')
            return bool(committed.payload.get('公开'))
        try:
            await self._character.profile(user_id)
        except CharacterNotFoundError as exc:
            raise WangyeError('尚未创建人物') from exc
        record = await self._database.get_shared_entity(ENTITY, user_id)
        current = bool(record is not None and dict(record.value).get('公开'))
        if current == enabled:
            return enabled
        command = TransactionCommand(
            user_id, request_id, BUSINESS,
            (SharedEntityMutation(ENTITY, user_id, {'名称': user_id, '公开': enabled}, 0 if record is None else record.version),),
            {'公开': enabled},
        )
        try:
            await self._database.commit(command)
        except (StateConflictError, IdempotencyConflictError) as exc:
            replay = await self._database.committed_transaction(user_id, request_id)
            if replay is not None:
                return bool(replay.payload.get('公开'))
            raise WangyeError('开关状态已经变化，请重试') from exc
        return enabled


__all__ = ['WangyeFeature']
