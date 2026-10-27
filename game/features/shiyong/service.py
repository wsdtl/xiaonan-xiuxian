"""统一使用入口：只查档案、解析物品、转发端口。"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from game.core.data import JsonDataError, JsonDataService, mapping, sequence
from game.core.item_catalog import ItemCatalogError, ItemCatalogService

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
_POSITIONS = {"无", "人物修行槽", "本命武器孔", "服用对象"}
_GRADES = {"必填", "可选", "不需要"}
_RESULTS = {"equip", "forge", "treasure", "medicine", "formation"}


class UseGatewayFeature:
    """跨域使用路由；不拥有任何领域结算。"""

    def __init__(
        self,
        data: JsonDataService,
        items: ItemCatalogService,
        ports: Mapping[str, UsePort],
    ) -> None:
        self._data = data
        self._items = items
        self._ports = dict(ports)
        self._profiles: dict[str, UseProfile] = {}
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
        profiles: dict[str, UseProfile] = {}
        for row in rows:
            value = mapping(row, "使用规则.使用方式[]")
            prefix = str(value.get("前缀") or "").strip()
            mode = str(value.get("方式") or "").strip()
            if len(prefix) != 2 or not prefix.isdecimal():
                raise JsonDataError(f"使用规则前缀必须是 2 位数字：{prefix}")
            if prefix in profiles:
                raise JsonDataError(f"使用规则前缀重复：{prefix}")
            if mode not in _MODES:
                raise JsonDataError(f"使用规则方式不合法：{prefix} {mode}")
            if mode == "执行":
                profile = self._execute_profile(prefix, value)
            else:
                profile = self._redirect_profile(prefix, value, mode)
            profiles[prefix] = profile
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
        profile = self._profiles.get(detail.item_id[:2])
        if profile is None:
            raise UseError(f"没有可用的使用档案：{detail.item_id}")
        normalized = replace(request, item_id=detail.item_id, name=detail.name)
        if profile.mode != "执行":
            return UseRedirect(profile.title, profile.message, profile.actions)
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
        if profile.position != "无" and not description.candidates:
            raise UseError(f"当前没有可用的{profile.position}。")
        return UsePlan(normalized, profile, description)

    async def execute(self, plan: UsePlan, candidate: str = "") -> UseOutcome:
        self._require_initialized()
        profile = plan.profile
        if profile.mode != "执行":
            raise UseError("这条档案不是执行方式")
        selected = str(candidate or "").strip()
        target = ""
        position = 0
        if profile.position != "无":
            if not selected:
                selected = plan.description.default
            values = {item.value for item in plan.description.candidates}
            if not selected or selected not in values:
                raise UseError(f"位置或目标不可用：{selected or '<空>'}")
            if profile.position == "服用对象":
                target = selected
            else:
                if not selected.isdecimal():
                    raise UseError(f"位置必须是数字：{selected}")
                position = int(selected)
        elif selected:
            raise UseError("这件物品不需要位置或目标")
        request = replace(plan.request, target=target, position=position)
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

    def _execute_profile(self, prefix: str, value: Mapping[str, object]) -> UseProfile:
        port = str(value.get("端口") or "").strip()
        position = str(value.get("位置") or "").strip()
        grade = str(value.get("品级") or "").strip()
        render_key = str(value.get("结果") or "").strip()
        if port not in self._ports:
            raise JsonDataError(f"使用规则端口不存在：{prefix} {port}")
        if position not in _POSITIONS:
            raise JsonDataError(f"使用规则位置不合法：{prefix} {position}")
        if grade not in _GRADES:
            raise JsonDataError(f"使用规则品级不合法：{prefix} {grade}")
        if render_key not in _RESULTS:
            raise JsonDataError(f"使用规则结果不合法：{prefix} {render_key}")
        candidates = tuple(
            str(item).strip()
            for item in (value.get("候选") or ())
            if str(item).strip()
        )
        return UseProfile(
            prefix=prefix,
            mode="执行",
            port=port,
            position=position,
            candidates=candidates,
            default=str(value.get("默认") or "").strip(),
            grade=grade,
            render_key=render_key,
        )

    def _redirect_profile(
        self, prefix: str, value: Mapping[str, object], mode: str
    ) -> UseProfile:
        title = str(value.get("标题") or "").strip()
        message = str(value.get("提示") or "").strip()
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
