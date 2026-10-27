'''网页资源开关：命令与展示；开关事实在 core/visibility。

**语义**：一条全局开关，管住所有「网页直接读你的数据」的页面，页面不各造一个。
本包只做文案、参数与命令编排；「谁开了、开关怎么写」由核心服务解释。
'''

from __future__ import annotations

from collections.abc import Mapping

from game.core.data import JsonDataError, JsonDataService
from game.core.visibility import (
    VisibilityConflictError,
    VisibilityError,
    VisibilityService,
)

from .contracts import WangyeConflictError, WangyeError, WangyeScope


class WangyeFeature:
    def __init__(self, data: JsonDataService, visibility: VisibilityService) -> None:
        self._data = data
        self._visibility = visibility
        self._copy: Mapping[str, object] | None = None

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError('网页资源开关玩法已经初始化')
        if not self._visibility.status():
            raise RuntimeError('网页可见性核心必须先于网页资源开关玩法启动')
        # 数据集返回的是「文件名到正文」的视图，正文那一层要按文件名取（文本.json → '文本'）。
        copy = self._data.dataset('网页资源开关展示').get('文本')
        if not isinstance(copy, Mapping):
            raise JsonDataError('网页资源开关展示缺少文本.json')
        for group in ('公开', '错误'):
            if not isinstance(copy.get(group), Mapping):
                raise JsonDataError(f'网页资源开关展示缺少一组文案：{group}')
        self._copy = copy

    def copy(self, section: str, key: str) -> str:
        if self._copy is None:
            raise RuntimeError('网页资源开关玩法尚未初始化')
        group = self._copy.get(section)
        value = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(value, str):
            raise JsonDataError(f'网页资源开关展示缺少文案：{section}.{key}')
        return value

    async def is_public(self, user_id: str) -> bool:
        return await self._visibility.is_public(user_id)

    async def scopes(self) -> list[WangyeScope]:
        '''已公开的人。没人开就是空清单——页面据此显示「还没有人公开」。'''

        return [
            WangyeScope(scope.user_id, scope.name)
            for scope in await self._visibility.scopes()
        ]

    async def set_public(self, user_id: str, request_id: str, enabled: bool) -> bool:
        '''开或关。两个命令各管一头，所以这里收的是明确的目标状态，不是取反。'''

        try:
            return await self._visibility.set_public(user_id, request_id, enabled)
        except VisibilityConflictError as exc:
            raise WangyeConflictError(str(exc)) from exc
        except VisibilityError as exc:
            raise WangyeError(str(exc)) from exc


__all__ = ['WangyeFeature']
