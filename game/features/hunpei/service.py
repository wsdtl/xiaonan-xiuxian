"""生育：一次事务结算，生成新生儿并入族谱。"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence

from game.core.character import CharacterNotFoundError, CharacterService
from game.core.companion import CompanionService
from game.core.data import JsonDataService
from game.core.database import DatabaseService, StateAddress, StateMutation, TransactionCommand
from game.features.xuemai import XuemaiFeature

from .presentation import load_hunpei_presentation

from .contracts import (
    BirthDeniedError,
    BirthResult,
    BirthView,
    HunpeiCopy,
    HunpeiError,
    Newborn,
)

#: 每个道侣的 DNA 另存一份状态（首次需要时固定，不动既有道侣实例契约）。
COMPANION_STATE_TYPE = "xuemai_companion_dna"

#: 每代胎数上限的默认值（数据未登记时用）。
DEFAULT_BIRTH_LIMIT = 10


class HunpeiFeature:
    """组合核心服务完成生育，不持有第二份关系状态。"""

    def __init__(
        self,
        data: JsonDataService,
        character: CharacterService,
        companion: CompanionService,
        database: DatabaseService,
        xuemai: XuemaiFeature,
    ) -> None:
        self._data = data
        self._character = character
        self._companion = companion
        self._database = database
        self._xuemai = xuemai
        self._initialized = False
        self._limit = DEFAULT_BIRTH_LIMIT
        self._medicine_code = ""
        self._medicine_cost = 0
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
        medicine = body.get("生育丹")
        cell = medicine if isinstance(medicine, Mapping) else {}
        self._medicine_code = str(cell.get("丹药") or "")
        self._medicine_cost = int(cell.get("每次消耗") or 0)
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

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("婚配玩法微服务尚未初始化")

    async def view(self, user_id: str) -> BirthView:
        """生育前的状态：能不能生、为什么不能。"""

        self._require_initialized()
        active = await self._companion.active(user_id)
        if active is None:
            return BirthView("", "", False, "没有同行道侣", 0, 0, self._limit)
        try:
            profile = await self._character.profile(user_id)
        except CharacterNotFoundError as exc:
            raise HunpeiError("尚未创建人物") from exc
        address = StateAddress(user_id, self._xuemai.state_type(), self._xuemai.state_key())
        snapshot = await self._database.get(address)
        value = dict(snapshot.value) if snapshot is not None and isinstance(snapshot.value, Mapping) else {}
        generation = int(value.get("代次") or 0)
        used = int(value.get("胎次") or 0)
        can, reason = self._check(profile.gender, active, used)
        return BirthView(
            companion_code=str(getattr(active, "companion_id", "") or ""),
            companion_name=str(getattr(active, "name", "") or ""),
            can_birth=can,
            reason=reason,
            generation=generation,
            births_this_generation=used,
            births_limit=self._limit,
        )

    def _check(self, gender: str, active: object, used: int) -> tuple[bool, str]:
        if used >= self._limit:
            return False, "本代胎数已满（%d 胎）" % self._limit
        return True, ""

    async def birth(self, user_id: str) -> BirthResult:
        """生育：消耗生育丹、生成新生儿、入族谱。"""

        self._require_initialized()
        state = await self.view(user_id)
        if not state.can_birth:
            raise BirthDeniedError(state.reason)
        own_dna = await self._xuemai.dna(user_id)
        mother_dna = await self._companion_dna(state.companion_code)
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
            births_limit=DEFAULT_BIRTH_LIMIT,
            medicine_code=self._medicine_code,
            medicine_name="",
        )

    async def _companion_dna(self, companion_code: str) -> str:
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