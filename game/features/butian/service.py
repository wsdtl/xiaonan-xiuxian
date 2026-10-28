from __future__ import annotations

from game.core.asset import (
    InventoryStack,
    AssetService,
    InventoryAdjustment,
    InventoryChangeError,
)

from collections.abc import Mapping

from game.core.character import CharacterCultivationError, CharacterService
from game.core.companion import CompanionCultivationError, CompanionService
from game.core.data import JsonDataError, JsonDataService, nonempty_text as _text
from game.core.database import (
    DatabaseService,
    IdempotencyConflictError,
    StateConflictError,
    TransactionCommand,
)
from game.core.location import LocationService
from game.core.medicine import MedicineError, MedicineService
from game.core.player_state import PlayerStateService
from game.core.world import LocationQuery, WorldService

from .contracts import ButianConflictError, ButianError, ButianResult


class ButianFeature:
    def __init__(self, data: JsonDataService, medicine: MedicineService, character: CharacterService, companion: CompanionService, asset: AssetService, player_state: PlayerStateService, location: LocationService, world: WorldService, database: DatabaseService) -> None:
        self._data, self._medicine, self._character, self._companion, self._asset = data, medicine, character, companion, asset
        self._player_state, self._location, self._world, self._database = player_state, location, world, database
        self._copy: Mapping[str, object] | None = None
        self._medicine_id = ""
        self._location_function = ""
        self._guard_rule = ""

    def initialize(self) -> None:
        if self._copy is not None:
            raise RuntimeError("补天玩法已经初始化")
        rule = self._world.feature_config("补天")
        self._medicine_id = _text(rule.get("丹药"), "补天.丹药")
        self._location_function = "补天"
        self._guard_rule = _text(rule.get("状态守卫"), "补天.状态守卫")
        copy = self._data.dataset("补天展示").get("文本")
        if not isinstance(copy, Mapping):
            raise JsonDataError("补天展示缺少文本.json")
        self._copy = copy

    def copy(self, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
        if self._copy is None:
            raise RuntimeError("补天玩法尚未初始化")
        group = self._copy.get(section)
        value = group.get(key) if isinstance(group, Mapping) else None
        if not isinstance(value, str):
            raise JsonDataError(f"补天展示缺少文本：{section}.{key}")
        return value.format_map(values or {})

    async def apply_from_text(
        self, user_id: str, request_id: str, raw_message: str
    ) -> ButianResult:
        parts = str(raw_message or "").split()
        if len(parts) != 3:
            raise ButianError("格式：补天 人物或道侣 同境界 单属性突破丹编号")
        return await self.apply(
            user_id, request_id, parts[0], parts[1], parts[2]
        )

    async def apply(self, user_id: str, request_id: str, target: str, realm: str, source_medicine_id: str) -> ButianResult:
        target = str(target or "").strip()
        if target not in {"人物", "道侣"}:
            raise ButianError("补天目标只能是人物或道侣")
        source_query = str(source_medicine_id or "").strip()
        requested_realm = str(realm or "").strip()
        if not requested_realm:
            raise ButianError("必须指定要补正的境界")
        if not source_query:
            raise ButianError("必须指定同境界单属性突破丹")
        try:
            source = self._medicine.resolve(source_query)
        except MedicineError as exc:
            raise ButianError(str(exc)) from exc
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is not None:
            if committed.receipt.business_type != "九霄补天":
                raise ButianConflictError("请求编号已经用于其他操作")
            if committed.payload.get("请求目标") != target or committed.payload.get("请求境界") != requested_realm or committed.payload.get("请求来源丹药") != source:
                raise ButianConflictError("补天请求与已提交事务不一致")
            return _result(committed.payload, True)
        await self._context(user_id)
        try:
            if target == "人物":
                plan = await self._character.plan_breakthrough_correction(user_id, source_medicine_id=source)
                target_name = (await self._character.profile(user_id)).name
                operations = (plan.operation,)
                attrs = plan.attributes
                realm = plan.target_realm
            else:
                plan = await self._companion.plan_breakthrough_correction(user_id, source_medicine_id=source)
                target_name = self._companion.definition(plan.companion_id).name
                operations = plan.operations
                attrs = plan.attributes
                realm = plan.target_realm
            realm_raw = self._data.entity("境界", realm)
            realm_name = str(realm_raw.get("名称") or realm)
            if requested_realm not in {realm, realm_name}:
                raise ButianError(f"当前可补正的突破节点是{realm_name}")
            stack = await self._lowest_stack(user_id, self._medicine_id)
            if stack is None:
                raise ButianError("纳戒中没有九霄补天丹")
            inventory = await self._asset.plan_inventory_changes(user_id, (InventoryAdjustment(self._medicine_id, stack.grade.grade_id, -1),))
            attribute, value = attrs[0]
            payload = {"请求目标": target, "请求境界": requested_realm, "请求来源丹药": source, "目标": target, "目标名称": target_name, "境界": realm_name, "属性": attribute, "数值": value, "丹药名称": str(self._data.entity("丹药", self._medicine_id).get("名称") or "九霄补天丹")}
            receipt = await self._database.commit(TransactionCommand(user_id, request_id, "九霄补天", inventory.operations + operations, payload))
        except (InventoryChangeError, CharacterCultivationError, CompanionCultivationError, StateConflictError) as exc:
            raise ButianError(str(exc)) from exc
        except IdempotencyConflictError as exc:
            raise ButianConflictError("请求编号已经用于其他操作") from exc
        return _result(payload, receipt.replayed)

    async def page(self, user_id: str) -> dict:
        '''页面用的只读视图：当前可补正的节点、包里的候选丹、以及可直接复制的命令原文。

        **不自己判规则**：可补正与否、哪枚丹合法，全部由核心的计划说话——计划不报错就是合法，
        报错就把原话转给页面。页面只负责把核心的结论摆整齐。
        '''

        group = self._copy.get('页面') if isinstance(self._copy, Mapping) else None
        if not isinstance(group, Mapping):
            raise JsonDataError('补天展示缺少页面一组文案')
        # 逐键字面取：页面用的键要在这里点名，判据才认得出谁在读这份文案。
        pick = lambda key: str(group.get(key) or '')
        copy = {
            '标题': pick('标题'),
            '说明': pick('说明'),
            '挑人': pick('挑人'),
            '没人公开': pick('没人公开'),
            '当前境界': pick('当前境界'),
            '可补正': pick('可补正'),
            '不可补正': pick('不可补正'),
            '候选丹': pick('候选丹'),
            '丹药': pick('丹药'),
            '没有丹': pick('没有丹'),
            '命令': pick('命令'),
            '道侣': pick('道侣'),
            '没有道侣': pick('没有道侣'),
        }
        snapshot = await self._asset.snapshot(user_id)
        candidates = tuple(
            entry for entry in snapshot.entries if entry.subcategory == '突破丹'
        )
        profile = await self._character.profile(user_id)
        targets = [await self._target('人物', profile.realm_name, user_id, candidates)]
        try:
            instance = await self._companion.active_instance(user_id)
        except Exception:
            instance = None
        if instance is not None:
            name = self._companion.definition(instance.instance.companion_id).name
            realm_raw = self._data.entity('境界', instance.instance.realm_id)
            realm_name = str(realm_raw.get('名称') or instance.instance.realm_id)
            targets.append(
                await self._target('道侣', realm_name, user_id, candidates, name=name)
            )
        return {
            'ui': dict(copy),
            # 每次补天另扣的那枚丹：编号一直有发但页面没用；把名字也带上，页面才好照印。
            'medicine_id': self._medicine_id,
            'medicine_name': str(
                self._data.entity('丹药', self._medicine_id).get('名称') or ''
            ),
            'targets': targets,
            'candidates': [
                {
                    'id': entry.content_id,
                    'grade': entry.grade_id,
                    'grade_name': entry.grade_name,
                    'quantity': entry.quantity,
                    'name': str(self._data.entity('丹药', entry.content_id).get('名称') or ''),
                }
                for entry in candidates
            ],
        }

    async def _target(
        self, kind: str, realm_name: str, user_id: str, candidates, name: str = ''
    ) -> dict:
        '''问核心：这个节点补不补得了；再逐枚丹问哪一枚合法。报错原话照转。'''

        legal: list[dict[str, str]] = []
        reason = ''
        for entry in candidates:
            try:
                if kind == '人物':
                    plan = await self._character.plan_breakthrough_correction(
                        user_id, source_medicine_id=entry.content_id
                    )
                else:
                    plan = await self._companion.plan_breakthrough_correction(
                        user_id, source_medicine_id=entry.content_id
                    )
            except Exception as exc:
                reason = str(exc)
                continue
            legal.append({'id': entry.content_id, 'grade': entry.grade_id})
            if not reason:
                reason = ''
            del plan
        return {
            'kind': kind,
            'name': name or '',
            'realm': realm_name,
            'correctable': bool(legal),
            'legal': legal,
            'reason': reason,
        }

    async def _authorize(self, user_id: str) -> None:
        result = await self._player_state.authorize(user_id, self._guard_rule)
        if not result.allowed:
            raise ButianError(result.reason)

    async def _context(self, user_id: str) -> None:
        await self._authorize(user_id)
        current = await self._location.current(user_id)
        place = self._world.locate(LocationQuery(xy=current.xy))
        if self._location_function not in place.available_functions:
            raise ButianError("只有身在裂天原才能使用补天丹")

    async def _lowest_stack(self, user_id: str, item_id: str) -> InventoryStack | None:
        stacks = await self._asset.inventory_stacks(user_id, item_id)
        return min(stacks, key=lambda value: value.grade.order) if stacks else None


def _result(value: Mapping[str, object], replayed: bool) -> ButianResult:
    return ButianResult(str(value.get("目标") or ""), str(value.get("目标名称") or ""), str(value.get("境界") or ""), str(value.get("属性") or ""), float(value.get("数值") or 0), str(value.get("丹药名称") or ""), replayed)


__all__ = ["ButianFeature"]
