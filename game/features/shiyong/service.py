"""统一使用入口：只查档案、解析物品、转发端口。"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from game.core.data import JsonDataError, JsonDataService, mapping, sequence
from game.core.item_catalog import ItemCatalogError, ItemCatalogService
from game.core.location import LocationService

from .contracts import (
    UseAction,
    UseCandidate,
    UseDescription,
    UseError,
    UseOutcome,
    UsePlan,
    UsePort,
    UseProfile,
    UseRedirect,
    UseRequest,
)

_MODES = {"执行", "重定向", "暂缓", "不可使用"}
_TARGETS = {"无", "人物或道侣"}
_POSITIONS = {"无", "人物修行槽", "本命武器孔"}
_GRADES = {"必填", "可选", "不需要"}
_RESULTS = {"equip", "forge", "law", "treasure", "medicine", "formation"}


class UseGatewayFeature:
    """跨域使用路由；不拥有任何领域结算。"""

    def __init__(
        self,
        data: JsonDataService,
        items: ItemCatalogService,
        location: LocationService,
        ports: Mapping[str, UsePort],
    ) -> None:
        self._data = data
        self._items = items
        self._location = location
        self._ports = dict(ports)
        self._profiles: dict[str, dict[str, UseProfile]] = {}
        self._text: dict[str, str] = {}
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("使用网关已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于使用网关启动")
        if not self._items.status().initialized:
            raise RuntimeError("物品查询微服务必须先于使用网关启动")
        raw = self._data.dataset("使用规则")
        document = self._one_document(raw)
        text = mapping(document.get("文本"), "使用规则.文本")
        self._text = {
            "错误标题": str(text.get("错误标题") or "").strip(),
            "错误状态": str(text.get("错误状态") or "").strip(),
            "缺品级": str(text.get("缺品级") or "").strip(),
            "写法": str(text.get("写法") or "").strip(),
            "错误尾注": str(text.get("错误尾注") or "").strip(),
        }
        if any(not value for value in self._text.values()):
            raise JsonDataError("使用规则.文本字段不完整")
        rows = sequence(document.get("使用方式"), "使用规则.使用方式")
        profiles: dict[str, dict[str, UseProfile]] = {}
        for row in rows:
            value = mapping(row, "使用规则.使用方式[]")
            prefix = str(value.get("前缀") or "").strip()
            mode = str(value.get("方式") or "").strip()
            effect = str(value.get("效果") or "").strip()
            if len(prefix) != 2 or not prefix.isdecimal():
                raise JsonDataError(f"使用规则前缀必须是 2 位数字：{prefix}")
            group = profiles.setdefault(prefix, {})
            if effect in group:
                raise JsonDataError(f"使用规则效果重复：{prefix} {effect}")
            if mode not in _MODES:
                raise JsonDataError(f"使用规则方式不合法：{prefix} {mode}")
            if mode == "执行":
                profile = self._execute_profile(prefix, effect, value)
            else:
                profile = self._redirect_profile(prefix, effect, value, mode)
            if not effect and group:
                raise JsonDataError(f"使用规则同前缀必须用效果区分：{prefix}")
            if effect and "" in group:
                raise JsonDataError(f"使用规则同前缀不能用空效果混排：{prefix}")
            group[effect] = profile
        base = self._data.dataset("基础定义").get("编号")
        if not isinstance(base, Mapping):
            raise JsonDataError("基础定义缺少编号定义")
        expected = {
            str(row.get("前缀") or "").strip()
            for row in sequence(base.get("编号前缀"), "基础定义.编号前缀")
            if isinstance(row, Mapping)
        }
        missing = expected - set(profiles)
        extra = set(profiles) - expected
        if missing or extra:
            raise JsonDataError(
                "使用规则前缀与编号定义不一致："
                f"缺 {sorted(missing)}，多 {sorted(extra)}"
            )
        self._profiles = profiles
        self._initialized = True

    def copy(self, key: str) -> str:
        self._require_initialized()
        value = self._text.get(key, "")
        if not value:
            raise RuntimeError(f"使用规则缺少文本：{key}")
        return value

    async def plan(self, request: UseRequest) -> UsePlan | UseRedirect:
        self._require_initialized()
        try:
            detail = self._items.inspect_entity(request.item_id)
        except ItemCatalogError as exc:
            raise UseError(str(exc)) from exc
        group = self._profiles.get(detail.item_id[:2])
        if not group:
            raise UseError(f"没有可用的使用档案：{detail.item_id}")
        profile = self._select_profile(group, detail)
        normalized = replace(request, item_id=detail.item_id, name=detail.name)
        if profile.mode != "执行":
            actions = list(profile.actions)
            if profile.location:
                current = await self._location.current(request.user_id)
                current_name = str(getattr(current, "location_name", "") or "")
                if current_name != profile.location:
                    actions.append(
                        UseAction(
                            f"去 {profile.location}",
                            f"去 {profile.location}",
                        )
                    )
            return UseRedirect(profile.title, profile.message, tuple(actions))
        if profile.grade == "必填" and not normalized.grade.strip():
            raise UseError(self.copy("缺品级"))
        port = self._ports.get(profile.port)
        if port is None:
            raise UseError(f"使用端口没有接线：{profile.port}")
        try:
            description = await port.describe(normalized)
        except UseError:
            raise
        except (ValueError, RuntimeError) as exc:
            raise UseError(str(exc)) from exc
        return UsePlan(normalized, profile, description)

    async def execute(
        self, plan: UsePlan, target: str = "", position: int = 0
    ) -> UseOutcome:
        self._require_initialized()
        profile = plan.profile
        if profile.mode != "执行":
            raise UseError("这条档案不是执行方式")
        selected_target = str(target or plan.request.target or "").strip()
        if profile.target == "无":
            if selected_target:
                raise UseError("这件物品不需要目标")
        else:
            if not selected_target:
                selected_target = plan.description.target_default
            if not selected_target:
                raise UseError("请选择目标")
        selected_position = int(position or plan.request.position or 0)
        if profile.position == "无":
            if selected_position:
                raise UseError("这件物品不需要位置")
        else:
            if not selected_position:
                if plan.description.position_default:
                    selected_position = int(plan.description.position_default)
                else:
                    slots = {
                        option.position
                        for option in plan.description.options
                        if profile.target == "无"
                        or option.target == selected_target
                    }
                    if len(slots) == 1:
                        selected_position = next(iter(slots))
            if not selected_position:
                raise UseError("请选择位置")
        if plan.description.options:
            valid = any(
                option.target == (selected_target if profile.target != "无" else "")
                and option.position == selected_position
                for option in plan.description.options
            )
            if not valid:
                raise UseError(
                    f"目标或位置不可用：{selected_target or '<空>'} "
                    f"{selected_position or '<空>'}"
                )
        request = replace(
            plan.request,
            target=selected_target,
            position=selected_position,
        )
        port = self._ports.get(profile.port)
        if port is None:
            raise UseError(f"使用端口没有接线：{profile.port}")
        try:
            result = await port.execute(request)
        except UseError:
            raise
        except (ValueError, RuntimeError) as exc:
            raise UseError(str(exc)) from exc
        return UseOutcome(profile.render_key, result)

    def _select_profile(
        self, group: Mapping[str, UseProfile], detail: object
    ) -> UseProfile:
        if len(group) == 1 and "" in group:
            return group[""]
        fields = getattr(detail, "fields", {})
        effect = ""
        if isinstance(fields, Mapping):
            raw = fields.get("使用效果")
            if isinstance(raw, Mapping):
                effect = str(raw.get("类型") or "").strip()
        profile = group.get(effect)
        if profile is None:
            raise UseError(f"没有匹配的使用效果：{effect or '<空>'}")
        return profile

    def _execute_profile(
        self, prefix: str, effect: str, value: Mapping[str, object]
    ) -> UseProfile:
        port = str(value.get("端口") or "").strip()
        target = str(value.get("目标") or "无").strip()
        target_default = str(value.get("目标默认") or "").strip()
        position = str(value.get("位置") or "无").strip()
        grade = str(value.get("品级") or "可选").strip()
        render_key = str(value.get("结果") or "").strip()
        if port not in self._ports:
            raise JsonDataError(f"使用规则端口不存在：{prefix} {port}")
        if target not in _TARGETS:
            raise JsonDataError(f"使用规则目标不合法：{prefix} {target}")
        if position not in _POSITIONS:
            raise JsonDataError(f"使用规则位置不合法：{prefix} {position}")
        if grade not in _GRADES:
            raise JsonDataError(f"使用规则品级不合法：{prefix} {grade}")
        if render_key not in _RESULTS:
            raise JsonDataError(f"使用规则结果不合法：{prefix} {render_key}")
        return UseProfile(
            prefix=prefix,
            mode="执行",
            effect=effect,
            port=port,
            target=target,
            target_default=target_default,
            position=position,
            grade=grade,
            render_key=render_key,
        )

    def _redirect_profile(
        self,
        prefix: str,
        effect: str,
        value: Mapping[str, object],
        mode: str,
    ) -> UseProfile:
        title = str(value.get("标题") or "").strip()
        message = str(value.get("提示") or "").strip()
        location = str(value.get("地点") or "").strip()
        if not title or not message:
            raise JsonDataError(f"使用规则提示不完整：{prefix}")
        actions = tuple(
            UseAction(str(row.get("名称") or "").strip(), str(row.get("命令") or "").strip())
            for row in sequence(value.get("帮助") or (), f"使用规则.{prefix}.帮助")
            if isinstance(row, Mapping)
        )
        if any(not action.label or not action.command for action in actions):
            raise JsonDataError(f"使用规则帮助动作不完整：{prefix}")
        if mode in {"重定向", "暂缓"} and not actions:
            raise JsonDataError(f"使用规则重定向缺少帮助：{prefix}")
        return UseProfile(
            prefix=prefix,
            mode=mode,
            effect=effect,
            location=location,
            title=title,
            message=message,
            actions=actions,
        )

    @staticmethod
    def _one_document(raw: Mapping[str, object]) -> Mapping[str, object]:
        if "使用" in raw:
            return mapping(raw["使用"], "使用规则")
        if len(raw) == 1:
            return mapping(next(iter(raw.values())), "使用规则")
        raise JsonDataError("使用规则数据集必须有且只有一个文件")

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("使用网关尚未初始化")


__all__ = ["UseGatewayFeature"]
