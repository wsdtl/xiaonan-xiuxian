"""统一解析个人、队伍和宗门同行的有效行动参与者。"""

from __future__ import annotations

from collections.abc import Sequence

from game.core.data import JsonDataError, JsonDataService, mapping as _json_mapping
from game.core.sect import SectService
from game.core.team import TeamConflictError, TeamService

from .contracts import ActionGroup, ActionGroupError, ActionGroupServiceStatus


class ActionGroupService:
    def __init__(
        self, data: JsonDataService, team: TeamService, sect: SectService
    ) -> None:
        self._data = data
        self._team = team
        self._sect = sect
        self._initialized = False
        self._common_actions: tuple[str, ...] = ()
        self._common_action_set: frozenset[str] = frozenset()

    def initialize(self) -> ActionGroupServiceStatus:
        if self._initialized:
            raise RuntimeError("行动编排核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于行动编排核心启动")
        if not self._team.status().initialized:
            raise RuntimeError("队伍核心必须先于行动编排核心启动")
        if not self._sect.status().initialized:
            raise RuntimeError("宗门核心必须先于行动编排核心启动")
        rule = _json_mapping(
            self._data.dataset("宗门规则").get("宗门"), "宗门.json"
        )
        follow = _json_mapping(rule.get("同行"), "宗门.同行")
        self._common_actions = _actions(follow.get("共同行动"), "宗门.同行.共同行动")
        self._common_action_set = frozenset(self._common_actions)
        self._initialized = True
        return self.status()

    def status(self) -> ActionGroupServiceStatus:
        return ActionGroupServiceStatus(self._initialized)

    def common_actions(self) -> tuple[str, ...]:
        """同行能一起做的动作清单（`宗门.json` 的 `同行.共同行动`，按声明顺序）。"""

        self._require_initialized()
        return self._common_actions

    def allows(self, action: str) -> bool:
        """宗门同行能不能一起做这个动作；这是清单唯一的读取口。"""

        self._require_initialized()
        return str(action or "").strip() in self._common_action_set

    def require_common_action(self, action: str, owner: str) -> None:
        """玩法层开机时自报动作名，不在 `共同行动` 里就拒绝启动。

        `owner` 只用于错误信息（哪个玩法自报的）。这条让「同行能一起做什么」
        由数据说话：改数据就改行为，玩法层不再各自写死一份。
        """

        normalized = str(action or "").strip()
        if not self.allows(normalized):
            raise JsonDataError(
                f"{owner}声明的同行动作「{normalized or '<空>'}」不在"
                f"宗门.同行.共同行动里：{'、'.join(self.common_actions())}"
            )

    async def resolve(self, user_id: str) -> ActionGroup:
        self._require_initialized()
        team_membership = await self._team.membership(user_id)
        follow = await self._sect.follow_membership(user_id)
        if team_membership is not None and follow is not None:
            raise ActionGroupError("fellowship_conflict")
        if follow is not None:
            if follow.leader_user_id != user_id:
                raise ActionGroupError("member_cannot_start")
            return ActionGroup(
                "sect", follow.leader_user_id, follow.member_user_ids, follow.sect_id
            )
        try:
            participants = await self._team.action_participants(user_id)
        except TeamConflictError as exc:
            if exc.code == "member_cannot_start":
                raise ActionGroupError("member_cannot_start") from exc
            raise ActionGroupError("group_changed") from exc
        return ActionGroup(
            "team" if len(participants) > 1 else "personal",
            participants[0],
            participants,
            team_membership.team.team_id if team_membership is not None else "",
        )

    async def group_for_user(self, user_id: str) -> ActionGroup:
        """返回用户当前行动组；允许跟随者查询，但不授予发起权限。"""

        self._require_initialized()
        team_membership = await self._team.membership(user_id)
        follow = await self._sect.follow_membership(user_id)
        if team_membership is not None and follow is not None:
            raise ActionGroupError("fellowship_conflict")
        if follow is not None:
            return ActionGroup(
                "sect",
                follow.leader_user_id,
                follow.member_user_ids,
                follow.sect_id,
            )
        if team_membership is not None:
            team = team_membership.team
            return ActionGroup(
                "team" if len(team.member_user_ids) > 1 else "personal",
                team.leader_user_id,
                team.member_user_ids,
                team.team_id,
            )
        normalized = str(user_id or "").strip()
        if not normalized:
            raise ValueError("user_id不能为空")
        return ActionGroup("personal", normalized, (normalized,))

    async def participants(self, user_id: str) -> tuple[str, ...]:
        return (await self.resolve(user_id)).participant_user_ids

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("行动编排核心微服务尚未初始化")


def _actions(value: object, label: str) -> tuple[str, ...]:
    """`共同行动` 必须是非空、不重复的动作名列表（保持声明顺序）。"""

    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or not value
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        raise JsonDataError(f"{label}必须是非空字符串数组")
    normalized = tuple(item.strip() for item in value)
    if len(set(normalized)) != len(normalized):
        raise JsonDataError(f"{label}不能有重复动作")
    return normalized


__all__ = ["ActionGroupService"]
