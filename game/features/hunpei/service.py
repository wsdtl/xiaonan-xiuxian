"""生育：道侣生育与玩家求子，共用一次事务结算。

两条路的分工（设计稿 _输出/血脉开工总纲.md 第 29-43 行）：
- 道侣生育：玩家 ↔ NPC 道侣，对象就是当前同行道侣；
- 求子：玩家 ↔ 玩家，一男一女、双方同意（异步请求），孩子归求方、被求者不留记录。

求子请求本身住在非资产日志库（见 store.py）：它只活很短一段时间，过期即失效，
不进玩家存档、不占角色服务的写入权。
"""
from __future__ import annotations

import random
import time
from collections.abc import Mapping, Sequence

from game.core.asset import AssetService, InventoryAdjustment
from game.core.character import CharacterNotFoundError, CharacterService
from game.core.companion import CompanionService
from game.core.data import JsonDataService
from game.core.database import DatabaseService, StateAddress, StateMutation, TransactionCommand
from game.features.xuemai import XuemaiFeature

from .contracts import (
    BirthAsk,
    BirthDeniedError,
    BirthRequestView,
    BirthRespond,
    BirthResult,
    BirthView,
    HunpeiCopy,
    HunpeiError,
    Newborn,
)
from .presentation import load_hunpei_presentation
from .store import DONE, PENDING, REFUSED, BirthRequestStore

#: 每个道侣的 DNA 另存一份状态（首次需要时固定，不动既有道侣实例契约）。
COMPANION_STATE_TYPE = "xuemai_companion_dna"

#: 每代胎数上限的默认值（数据未登记时用）。
DEFAULT_BIRTH_LIMIT = 10

#: 求子请求的默认有效期（数据未登记时用）。
DEFAULT_ASK_SECONDS = 600


class HunpeiFeature:
    """组合核心服务完成生育，不持有第二份关系状态。"""

    def __init__(
        self,
        data: JsonDataService,
        character: CharacterService,
        companion: CompanionService,
        database: DatabaseService,
        xuemai: XuemaiFeature,
        asset: AssetService,
        weizhi: object,
        requests: BirthRequestStore,
    ) -> None:
        self._data = data
        self._character = character
        self._companion = companion
        self._database = database
        self._xuemai = xuemai
        self._asset = asset
        #: 位置服务（玩法服务，只用来问「现在站在哪个地点功能上」）。
        self._weizhi = weizhi
        #: 求子请求的日志库存储（非资产；过期即失效）。
        self._requests = requests
        self._initialized = False
        self._limit = DEFAULT_BIRTH_LIMIT
        self._ask_seconds = DEFAULT_ASK_SECONDS
        self._medicine_code = ""
        self._medicine_cost = 0
        self._location_function = ""
        self._copy: HunpeiCopy | None = None
        self._buttons: tuple[Mapping[str, str], ...] = ()
        self._random = random.SystemRandom()

    def initialize(self) -> None:
        if self._initialized:
            raise RuntimeError("婚配玩法微服务已经初始化")
        for ready, label in (
            (self._character.status().initialized, "角色核心"),
            (self._companion.status().initialized, "道侣核心"),
            (self._database.status().initialized, "数据库核心"),
        ):
            if not ready:
                raise RuntimeError(f"{label}必须先于婚配玩法启动")
        rule_block = self._data.dataset("婚配规则")
        body = rule_block.get("婚配")
        if not isinstance(body, Mapping):
            raise RuntimeError("婚配规则数据集缺少「婚配」块")
        self._copy, self._buttons = load_hunpei_presentation(self._data.dataset("婚配展示"))
        self._limit = int(body.get("每代胎数上限") or DEFAULT_BIRTH_LIMIT)
        #: 生育必须在哪个地点功能上（名字来自规则，代码不硬编码）。
        self._location_function = str(body.get("地点功能") or "")
        medicine = body.get("生育丹")
        cell = medicine if isinstance(medicine, Mapping) else {}
        # 「丹药」这一格放的是丹药编号（句柄一律用编号），照既有键名。
        self._medicine_code = str(cell.get("丹药") or "")
        self._medicine_cost = int(cell.get("每次消耗") or 0)
        ask = body.get("求子")
        if isinstance(ask, Mapping):
            self._ask_seconds = int(ask.get("有效秒数") or DEFAULT_ASK_SECONDS)
        self._requests.initialize()
        self._initialized = True

    def copy(self) -> HunpeiCopy:
        """展示契约（文本与图标）。"""

        self._require_initialized()
        if self._copy is None:
            raise RuntimeError("婚配展示契约尚未完成初始化")
        return self._copy

    def limit(self) -> int:
        """每代胎数上限（来自规则数据）。"""

        self._require_initialized()
        return self._limit

    def medicine(self) -> tuple[str, int]:
        """生育丹：(编号, 每次消耗)，来自规则数据。"""

        self._require_initialized()
        return self._medicine_code, self._medicine_cost

    def ask_seconds(self) -> int:
        """求子请求的有效秒数（来自规则数据）。"""

        self._require_initialized()
        return self._ask_seconds

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("婚配玩法微服务尚未初始化")

    async def view(self, user_id: str) -> BirthView:
        """生育前的状态：能不能生、为什么不能。"""

        self._require_initialized()
        active = await self._companion.active(user_id)
        if active is None:
            return BirthView("", "", False, "没有同行道侣", 0, 0, self._limit)
        # 道侣的名字与性别都在它的定义里（ActiveCompanion 只存编号与版本号）。
        mate_code = str(getattr(active, "companion_id", "") or "")
        mate_name = self._companion.definition(mate_code).name if mate_code else ""
        try:
            profile = await self._character.profile(user_id)
        except CharacterNotFoundError as exc:
            raise HunpeiError("尚未创建人物") from exc
        address = StateAddress(user_id, self._xuemai.state_type(), self._xuemai.state_key())
        snapshot = await self._database.get(address)
        value = dict(snapshot.value) if snapshot is not None and isinstance(snapshot.value, Mapping) else {}
        generation = int(value.get("代次") or 0)
        used = int(value.get("胎次") or 0)
        can, reason = await self._check(user_id, profile.gender, active, used)
        return BirthView(
            companion_code=mate_code,
            companion_name=mate_name,
            can_birth=can,
            reason=reason,
            generation=generation,
            births_this_generation=used,
            births_limit=self._limit,
        )

    async def _own_ready(self, user_id: str) -> tuple[object, dict, int, int, str]:
        """两条路共用的前置：寿元、胎次、生育丹、地点。返回 (档案, 状态值, 代次, 胎次, 拒绝原因)。"""

        profile = await self._character.profile(user_id)
        address = StateAddress(user_id, self._xuemai.state_type(), self._xuemai.state_key())
        snapshot = await self._database.get(address)
        value = dict(snapshot.value) if snapshot is not None and isinstance(snapshot.value, Mapping) else {}
        generation = int(value.get("代次") or 0)
        used = int(value.get("胎次") or 0)
        if bool(getattr(profile, "lifespan_full", False)):
            return profile, value, generation, used, "你寿元将尽，须先传位"
        if used >= self._limit:
            return profile, value, generation, used, "本代胎数已满（%d 胎）" % self._limit
        if self._medicine_code:
            stacks = await self._asset.inventory_stacks(user_id, self._medicine_code)
            total = sum(int(getattr(stack, "quantity", 0) or 0) for stack in stacks)
            if total < max(1, self._medicine_cost):
                return profile, value, generation, used, "没有生育丹"
        if self._location_function:
            position = await self._weizhi.current(user_id)
            location = getattr(position, "location", None)
            functions = tuple(getattr(location, "available_functions", ()) or ())
            if self._location_function not in functions:
                return profile, value, generation, used, "须在%s" % self._location_function
        return profile, value, generation, used, ""

    async def _check(self, user_id: str, gender: str, active: object, used: int) -> tuple[bool, str]:
        """规则里的六条条件，逐条落实（道侣那一路）。"""

        # 寿元、胎次、生育丹、地点：与求子共用同一段前置。
        _, _, _, _, reason = await self._own_ready(user_id)
        if reason:
            return False, reason
        # 道侣的性别要从它的定义里取：ActiveCompanion 只存道侣编号与版本号。
        mate_id = str(getattr(active, "companion_id", "") or "")
        if mate_id and gender:
            mate_gender = str(self._companion.definition(mate_id).gender or "")
            if mate_gender and gender == mate_gender:
                return False, "双方并非异性"
        # 道侣寿元将尽：血脉失效，也不能再生养（补救的路是夺元重置）。
        if mate_id and await self._companion.lifespan_full(user_id, mate_id):
            return False, "道侣寿元将尽"
        return True, ""

    async def ask(self, user_id: str, target_query: str) -> BirthAsk:
        """向附近一位异性玩家发出求子请求（异步：等对方回应）。"""

        self._require_initialized()
        profile, _, _, _, reason = await self._own_ready(user_id)
        if reason:
            raise BirthDeniedError(reason)
        wanted = str(target_query or "").strip()
        if not wanted:
            raise HunpeiError("求子要写对方的名字")
        person = await self._weizhi.inspect_cultivator(user_id, wanted)
        if person is None:
            raise HunpeiError("附近没有这位修士")
        target_id = str(getattr(person, "user_id", "") or "")
        target_name = str(getattr(person, "name", "") or "")
        if not target_id:
            raise HunpeiError("附近没有这位修士")
        if target_id == user_id:
            raise HunpeiError("不能向自己求子")
        target_gender = str(getattr(person, "gender", "") or "")
        own_gender = str(getattr(profile, "gender", "") or "")
        if not own_gender or not target_gender or own_gender == target_gender:
            raise BirthDeniedError("求子必须一男一女")
        if self._requests.open_from(user_id) is not None:
            raise HunpeiError("你已有一条求子请求还没被回应")
        request_id = "求子:%s:%d" % (user_id, int(self._now() * 1000))
        row = self._requests.create(
            request_id=request_id,
            asker_id=user_id,
            asker_name=str(getattr(profile, "name", "") or ""),
            target_id=target_id,
            target_name=target_name,
            seconds=self._ask_seconds,
        )
        return BirthAsk(
            request_id=row.request_id,
            target_id=row.target_id,
            target_name=row.target_name,
            expires_at=row.expires_at,
        )

    async def pending(self, user_id: str) -> tuple[BirthRequestView, ...]:
        """别人发给我的、还没回应的求子请求。"""

        self._require_initialized()
        rows = self._requests.open_for(user_id)
        return tuple(
            BirthRequestView(
                request_id=row.request_id,
                asker_id=row.asker_id,
                asker_name=row.asker_name,
                created_at=row.created_at,
                expires_at=row.expires_at,
            )
            for row in rows
        )

    async def respond(self, user_id: str, request_query: str, agree: bool) -> BirthRespond:
        """回应一条求子请求：同意就当场结算，孩子归求方。"""

        self._require_initialized()
        wanted = str(request_query or "").strip()
        row = (
            self._requests.find(wanted)
            if wanted
            else self._requests.latest_open_for(user_id)
        )
        if row is None:
            raise HunpeiError("没有待处理的求子请求")
        if row.target_id != user_id:
            raise HunpeiError("这条求子请求不是发给你的")
        if row.expires_at <= self._now():
            raise HunpeiError("这份求子请求已经过期")
        if row.status != PENDING:
            raise HunpeiError("这份求子请求已经处理过")
        if not agree:
            # 先占位再改状态：并发两次回应只有一次能成功。
            if not self._requests.mark(row.request_id, REFUSED):
                raise HunpeiError("这份求子请求已经处理过")
            return BirthRespond(
                request_id=row.request_id,
                asker_id=row.asker_id,
                asker_name=row.asker_name,
                agreed=False,
                result=None,
            )
        if not self._requests.mark(row.request_id, DONE):
            raise HunpeiError("这份求子请求已经处理过")
        result = await self._deliver(row.asker_id, row.target_id, row.request_id)
        return BirthRespond(
            request_id=row.request_id,
            asker_id=row.asker_id,
            asker_name=row.asker_name,
            agreed=True,
            result=result,
        )

    async def _deliver(self, asker_id: str, target_id: str, request_id: str) -> BirthResult:
        """求子的结算：用双方 DNA 生一个孩子，记进**求方**族谱。"""

        profile, value, generation, used, reason = await self._own_ready(asker_id)
        if reason:
            raise BirthDeniedError("求方现在不能生育：%s" % reason)
        target_profile = await self._character.profile(target_id)
        own_gender = str(getattr(profile, "gender", "") or "")
        target_gender = str(getattr(target_profile, "gender", "") or "")
        if not own_gender or not target_gender or own_gender == target_gender:
            raise BirthDeniedError("求子必须一男一女")
        own_dna = await self._xuemai.dna(asker_id)
        other_dna = await self._xuemai.dna(target_id)
        sex = "女" if self._random.random() < 0.5 else "男"
        if own_gender == "男":
            father_dna, mother_dna = own_dna, other_dna
            father_id, mother_id = asker_id, target_id
        else:
            father_dna, mother_dna = other_dna, own_dna
            father_id, mother_id = target_id, asker_id
        child_dna = self._xuemai.breed(father_dna, mother_dna, sex)
        code = "%06d" % (900000 + self._random.randrange(1, 99999))
        newborn = Newborn(
            code=code,
            name="",
            sex=sex,
            dna=child_dna,
            bloodlines=self._xuemai.bloodlines(child_dna),
            generation=generation,
        )
        address = StateAddress(asker_id, self._xuemai.state_type(), self._xuemai.state_key())
        snapshot = await self._database.get(address)
        rows = value.get("族谱")
        rows = [dict(r) for r in rows if isinstance(r, Mapping)] if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)) else []
        rows.append({
            "编号": code,
            "族谱名": newborn.name,
            "玩家名": "",
            "性别": sex,
            "代次": generation,
            "父编号": father_id,
            "母编号": mother_id,
            "DNA": child_dna,
            "已传位": False,
        })
        value["族谱"] = rows
        value["胎次"] = used + 1
        value.setdefault("代次", generation)
        value.setdefault("DNA", own_dna)
        medicine_plan = await self._asset.plan_inventory_changes(
            asker_id,
            (
                InventoryAdjustment(
                    self._medicine_code, "01", -max(1, self._medicine_cost)
                ),
            ),
        )
        await self._database.commit(
            TransactionCommand(
                user_id=asker_id,
                request_id="求子:%s" % request_id,
                business_type="婚配求子",
                operations=(
                    StateMutation(
                        user_id=asker_id,
                        state_type=self._xuemai.state_type(),
                        state_key=self._xuemai.state_key(),
                        value=value,
                        expected_version=snapshot.version if snapshot is not None else 0,
                    ),
                    *tuple(medicine_plan.operations),
                ),
                payload={"新生儿": code, "DNA": child_dna, "胎次": value["胎次"], "求子请求": request_id},
            )
        )
        return BirthResult(
            newborn=newborn,
            companion_code=target_id,
            companion_name=str(getattr(target_profile, "name", "") or ""),
            generation=generation,
            births_this_generation=value["胎次"],
            births_limit=self._limit,
            medicine_code=self._medicine_code,
            medicine_name="",
        )

    async def birth(self, user_id: str) -> BirthResult:
        """生育：消耗生育丹、生成新生儿、入族谱（对象是当前同行道侣）。"""

        self._require_initialized()
        state = await self.view(user_id)
        if not state.can_birth:
            raise BirthDeniedError(state.reason)
        own_dna = await self._xuemai.dna(user_id)
        mother_dna = await self.companion_dna(state.companion_code)
        sex = "女" if self._random.random() < 0.5 else "男"
        child_dna = self._xuemai.breed(own_dna, mother_dna, sex)
        generation = state.generation
        code = "%06d" % (900000 + self._random.randrange(1, 99999))
        newborn = Newborn(
            code=code,
            name="",
            sex=sex,
            dna=child_dna,
            bloodlines=self._xuemai.bloodlines(child_dna),
            generation=generation,
        )
        address = StateAddress(user_id, self._xuemai.state_type(), self._xuemai.state_key())
        snapshot = await self._database.get(address)
        value = dict(snapshot.value) if snapshot is not None and isinstance(snapshot.value, Mapping) else {}
        rows = value.get("族谱")
        rows = [dict(r) for r in rows if isinstance(r, Mapping)] if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes)) else []
        rows.append({
            "编号": code,
            "族谱名": newborn.name,
            "玩家名": "",
            "性别": sex,
            "代次": generation,
            "父编号": "",
            "母编号": state.companion_code,
            "DNA": child_dna,
            "已传位": False,
        })
        value["族谱"] = rows
        value["胎次"] = state.births_this_generation + 1
        value.setdefault("代次", generation)
        value.setdefault("DNA", own_dna)
        # 正式扣丹：与族谱写在同一次事务里，要么都成、要么都不成。
        medicine_plan = await self._asset.plan_inventory_changes(
            user_id,
            (
                InventoryAdjustment(
                    self._medicine_code, "01", -max(1, self._medicine_cost)
                ),
            ),
        )
        await self._database.commit(
            TransactionCommand(
                user_id=user_id,
                request_id="生育:%s:%d" % (user_id, len(rows)),
                business_type="婚配生育",
                operations=(
                    StateMutation(
                        user_id=user_id,
                        state_type=self._xuemai.state_type(),
                        state_key=self._xuemai.state_key(),
                        value=value,
                        expected_version=snapshot.version if snapshot is not None else 0,
                    ),
                    *tuple(medicine_plan.operations),
                ),
                payload={"新生儿": code, "DNA": child_dna, "胎次": value["胎次"]},
            )
        )
        return BirthResult(
            newborn=newborn,
            companion_code=state.companion_code,
            companion_name=state.companion_name,
            generation=generation,
            births_this_generation=value["胎次"],
            births_limit=self._limit,
            medicine_code=self._medicine_code,
            medicine_name="",
        )

    async def companion_dna(self, companion_code: str) -> str:
        """道侣的 DNA：另存一份状态，首次固定。"""

        if not companion_code:
            return "000000000000"
        address = StateAddress(companion_code, COMPANION_STATE_TYPE, "main")
        snapshot = await self._database.get(address)
        if snapshot is not None and isinstance(snapshot.value, Mapping):
            current = str(snapshot.value.get("DNA") or "")
            if current:
                return current
        dna = self._xuemai.random_dna("女" if self._random.random() < 0.5 else "男")
        await self._database.commit(
            TransactionCommand(
                user_id=companion_code,
                request_id="定道侣DNA:%s" % companion_code,
                business_type="血脉定道侣DNA",
                operations=(
                    StateMutation(
                        user_id=companion_code,
                        state_type=COMPANION_STATE_TYPE,
                        state_key="main",
                        value={"DNA": dna},
                        expected_version=snapshot.version if snapshot is not None else 0,
                    ),
                ),
                payload={"DNA": dna},
            )
        )
        return dna

    @staticmethod
    def _now() -> float:
        return time.time()
