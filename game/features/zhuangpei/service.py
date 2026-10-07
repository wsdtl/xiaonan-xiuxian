"""公开装配工具：候选范围只筛选资料，聊天导入才修改执行者资产。"""
from collections.abc import Mapping

from game.core.asset import AssetService, AssetStateError
from game.core.character import CharacterService, CharacterNotFoundError, CharacterStateError
from game.core.combat import CombatService, render_body
from game.core.data import JsonDataService, JsonDataError, materialize
from game.core.database import (
    DatabaseService, SharedEntityMutation, TransactionCommand,
    StateConflictError, IdempotencyConflictError,
)
from game.core.innate_treasure import InnateTreasureService, InnateTreasureError
from game.core.player_state import PlayerStateService, PlayerStateError

from .codec import SECTIONS, decode, encode, normalize
from .contracts import Build, ZhuangpeiFeatureError, ZhuangpeiResult

PUBLIC_ENTITY = "zhuangpei_public"
IMPORT = "装配台整套导入"
PUBLISH = "装配台公开池"


class ZhuangpeiFeature:
    def __init__(
        self, data: JsonDataService, asset: AssetService, character: CharacterService,
        database: DatabaseService, innate_treasure: InnateTreasureService,
        player_state: PlayerStateService, combat: CombatService,
    ) -> None:
        self._data = data
        self._asset = asset
        self._character = character
        self._database = database
        self._treasure = innate_treasure
        self._player_state = player_state
        self._combat = combat
        self._copy = materialize(data.dataset("培养展示")["装配台"])

    def copy(self) -> dict:
        return self._copy

    async def toggle_public(self, user_id: str, request_id: str) -> bool:
        replay = await self._replay(user_id, request_id, PUBLISH)
        if replay is not None:
            return bool(replay["公开"])
        await self._character.profile(user_id)
        record = await self._database.get_shared_entity(PUBLIC_ENTITY, user_id)
        enabled = not (record is not None and record.value["公开"])
        command = TransactionCommand(
            user_id, request_id, PUBLISH,
            (SharedEntityMutation(PUBLIC_ENTITY, user_id,
                {"名称": user_id, "公开": enabled}, 0 if record is None else record.version),),
            {"公开": enabled},
        )
        try:
            await self._database.commit(command)
        except (StateConflictError, IdempotencyConflictError) as exc:
            replay = await self._replay(user_id, request_id, PUBLISH)
            if replay is not None:
                return bool(replay["公开"])
            raise ZhuangpeiFeatureError("公开状态已经变化，请重试") from exc
        return enabled

    async def scopes(self) -> list[dict[str, str]]:
        records = await self._database.list_shared_entities(PUBLIC_ENTITY)
        ids = tuple(record.entity_id for record in records if record.value["公开"])
        profiles = await self._character.public_profiles(ids)
        return [{"id": "all", "name": "全池"}, *(
            {"id": "user:" + profile.user_id, "name": profile.name}
            for profile in profiles
        )]

    async def page(self, scope: str = "all") -> dict:
        scopes = await self.scopes()
        if scope not in {value["id"] for value in scopes}:
            raise ZhuangpeiFeatureError("该清单未公开，请选择全池或其他公开用户")
        limits = self._character.assembly_limits()
        build: Build = {section: () for section in SECTIONS}
        entries: dict[tuple[str, str, str], dict] = {}
        if scope == "all":
            for section in SECTIONS:
                grades = ("",) if section == "器律" else tuple(value.grade_id for value in self._asset.grades())
                for content_id in self._data.entities(section):
                    for grade in grades:
                        entries[(section, content_id, grade)] = self._entry(section, content_id, grade)
        else:
            user_id = scope.removeprefix("user:")
            try:
                profile = await self._character.profile(user_id)
            except CharacterNotFoundError as exc:
                raise ZhuangpeiFeatureError("该用户没有公开池") from exc
            limits = dict(profile.cultivation_slots)
            limits["器律"] = profile.weapon.open_law_slots
            build = self._profile_build(profile)
            snapshot = await self._asset.snapshot(user_id)
            for entry in snapshot.entries:
                section = {"道藏": "功法", "器藏": "器律"}.get(entry.category, entry.subcategory)
                if section in SECTIONS:
                    item = self._entry(section, entry.content_id, entry.grade_id)
                    item["quantity"] = entry.quantity
                    entries[(section, entry.content_id, entry.grade_id)] = item
            # 已装入的资粮、器律可能已无库存，但仍属于本人的当前清单。
            for entry in (*profile.equipped_content, *profile.weapon.equipped_laws):
                key = (entry.category, entry.content_id, entry.grade)
                if key not in entries:
                    entries[key] = self._entry(*key)
                    entries[key]["quantity"] = 0
                entries[key]["equipped"].append(entry.slot)
            record = await self._database.get_shared_entity(PUBLIC_ENTITY, user_id)
            if record is None or not record.value["公开"]:
                raise ZhuangpeiFeatureError("该用户已关闭公开池")
        return {
            "scopes": scopes, "scope": scope, "limits": limits,
            "sections": list(SECTIONS), "entries": list(entries.values()),
            "current": build, "ui": self._copy,
        }

    def _entry(self, section: str, content_id: str, grade: str) -> dict:
        try:
            value = self._data.entity(section, content_id)
            grade_name = self._asset.grade(grade).name if grade else ""
        except (JsonDataError, AssetStateError) as exc:
            raise ZhuangpeiFeatureError(str(exc)) from exc
        return {
            "section": section, "id": content_id, "grade": grade,
            "name": str(value["名称"]), "grade_name": grade_name,
            "description": str(value["说明"]),
            "label": " · ".join(part for part in (str(value["名称"]), grade_name, str(value.get("器阶", ""))) if part),
            "quantity": None, "equipped": [],
        }

    def _profile_build(self, profile) -> Build:
        build = {section: [None] * count for section, count in profile.cultivation_slots}
        build["器律"] = [None] * profile.weapon.open_law_slots
        for entry in (*profile.equipped_content, *profile.weapon.equipped_laws):
            build[entry.category][entry.slot - 1] = {"编号": entry.content_id, "品级": entry.grade}
        return normalize(build)

    def scheme(self, build: object) -> dict:
        normalized = normalize(build)
        limits = self._character.assembly_limits()
        lines = []
        for section, entries in normalized.items():
            if len(entries) > limits[section]:
                raise ZhuangpeiFeatureError(f"{section}超出人物槽位上限")
            seen = set()
            for slot, entry in enumerate(entries, start=1):
                if entry is None:
                    continue
                item = self._entry(section, entry["编号"], entry["品级"])
                if section != "器律" and entry["编号"] in seen:
                    raise ZhuangpeiFeatureError(f"{section}不能重复装配同一内容")
                seen.add(entry["编号"])
                lines.append(f"{section}{slot}：{item['label']}")
        return {"build": normalized, "code": encode(normalized), "lines": lines}

    def open_code(self, code: str) -> dict:
        return self.scheme(decode(code))

    def detail(self, section: str, content_id: str, grade: str = "") -> dict:
        """一份内容的详情。

        **品级是实例级事实**（`data/基础/定义/编号.json` 的「编号不承载品级」），
        所以详情必须把它接进来显示：同一个编号在不同品级下是两份东西。
        品级只影响整门内容一层的威力倍率，**不改写卡面里的逐个数字**
        （见 `data/基础/定义/说明.md`「不得遍历所有数字进行无差别缩放」）。
        """

        if section not in SECTIONS:
            raise ZhuangpeiFeatureError("请选择功法、真意、气机或器律")
        if section == "器律" and grade:
            raise ZhuangpeiFeatureError("器律按器阶划分，没有品级")
        try:
            value = self._data.entity(section, content_id)
        except JsonDataError as exc:
            raise ZhuangpeiFeatureError(str(exc)) from exc
        lines, _ = render_body(value, self._combat.rule_layer())
        head = self._grade_line(grade)
        return {
            "name": value["名称"],
            "grade": grade,
            "grade_name": self._asset.grade(grade).name if grade else "",
            "lines": ([head] if head else []) + list(lines),
        }

    def _grade_line(self, grade: str) -> str:
        """详情头部的品级行；没给品级就说明「按基础值」，不假装知道。"""

        if not grade:
            return str(self._copy.get("品级缺省") or "")
        try:
            value = self._asset.grade(grade)
        except AssetStateError as exc:
            raise ZhuangpeiFeatureError(f"未知品级：{grade}") from exc
        template = str(self._copy.get("品级行") or "")
        return template.replace("{品级}", value.name).replace("{倍率}", f"{value.ability_multiplier:g}")

    async def current(self, user_id: str) -> ZhuangpeiResult:
        value = self.scheme(self._profile_build(await self._character.profile(user_id)))
        return ZhuangpeiResult(value["code"], tuple(value["lines"]))

    async def import_code(self, user_id: str, request_id: str, code: str) -> ZhuangpeiResult:
        # 先解析固定协议，再查回执；已经成功的请求不因库存消耗或目录变化重做。
        build = decode(code)
        canonical = encode(build)
        replay = await self._replay(user_id, request_id, IMPORT, canonical)
        if replay is not None:
            return self._result(replay, replayed=True)
        try:
            guards = await self._player_state.plan_guard(user_id, "自主空闲或休息")
            value = self.scheme(build)
            effect, treasure_guard = await self._treasure.plan_effect(user_id, "真意气机替换")
            retain = effect is not None and effect.ability == "保留被替换资粮"
            plan = await self._character.plan_assembly(user_id, build, retain_replaced=retain)
            payload = {"码": canonical, "明细": value["lines"], "变更槽位": plan.changed_slots}
            await self._database.commit(TransactionCommand(user_id, request_id, IMPORT, (*guards, treasure_guard, *plan.operations), payload))
        except (StateConflictError, IdempotencyConflictError) as exc:
            replay = await self._replay(user_id, request_id, IMPORT, canonical)
            if replay is not None:
                return self._result(replay, replayed=True)
            raise ZhuangpeiFeatureError("人物或库存已经变化，请重新导入") from exc
        except (AssetStateError, CharacterStateError, CharacterNotFoundError, JsonDataError, PlayerStateError, InnateTreasureError) as exc:
            # 同一个 request_id 的两个并发请求：后到的那个可能在库存校验时先失败
            # （前一个刚把库存扣掉）。只要前一个已经落库，这里就按回执回放，不重复扣料。
            replay = await self._replay(user_id, request_id, IMPORT, canonical)
            if replay is not None:
                return self._result(replay, replayed=True)
            raise ZhuangpeiFeatureError(str(exc)) from exc
        return self._result(payload, replayed=False)

    async def _replay(self, user_id: str, request_id: str, kind: str, code: str | None = None) -> Mapping | None:
        committed = await self._database.committed_transaction(user_id, request_id)
        if committed is None:
            return None
        if committed.receipt.business_type != kind or (code is not None and committed.payload.get("码") != code):
            raise ZhuangpeiFeatureError("同一请求编号不能用于不同操作")
        return committed.payload

    def _result(self, payload: Mapping, *, replayed: bool) -> ZhuangpeiResult:
        return ZhuangpeiResult(str(payload["码"]), tuple(payload["明细"]), replayed)
