"""血脉（族谱）的事务编排。"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence

from game.core.bloodline import BloodlineService
from game.core.character import CharacterNotFoundError, CharacterService
from game.core.data import JsonDataService
from game.core.database import DatabaseService, TransactionCommand

from .contracts import (
    GenealogyCopy,
    GenealogyEntry,
    GenealogyQueryError,
    GenealogyView,
    SuccessionResult,
    XuemaiError,
)
from .presentation import load_xuemai_presentation

_USAGE = "传位 新生儿编号或名字"


class XuemaiFeature:
    """组合核心服务完成血脉族谱，不持有第二份状态。"""

    def __init__(
        self,
        data: JsonDataService,
        character: CharacterService,
        database: DatabaseService,
        bloodline: BloodlineService,
    ) -> None:
        self._data = data
        self._character = character
        self._database = database
        self._bloodline = bloodline
        self._initialized = False
        self._copy: GenealogyCopy | None = None
        self._buttons: tuple[Mapping[str, str], ...] = ()
        self._random = random.SystemRandom()

    def initialize(self) -> None:
        """校验依赖核心已启动，并装载血脉展示。"""

        if self._initialized:
            raise RuntimeError("血脉玩法微服务已经初始化")
        for ready, label in (
            (self._bloodline.status().initialized, "血脉核心"),
            (self._character.status().initialized, "角色核心"),
            (self._database.status().initialized, "数据库核心"),
        ):
            if not ready:
                raise RuntimeError(f"{label}必须先于血脉玩法启动")
        self._copy, self._buttons = load_xuemai_presentation(self._data.dataset("血脉展示"))
        self._initialized = True

    def copy(self) -> GenealogyCopy:
        """展示契约（文本与图标）。"""

        self._require_initialized()
        if self._copy is None:
            raise RuntimeError("血脉展示契约尚未完成初始化")
        return self._copy

    def rules(self):
        """血脉规则全表（32 条 ＋ 觉醒档）。"""

        self._require_initialized()
        return self._bloodline.rules()

    async def stored_dna(self, user_id: str) -> str:
        """只读已存 DNA；不创建、不回调角色。"""

        self._require_initialized()
        return await self._bloodline.stored_dna(user_id)

    async def dna(self, user_id: str) -> str:
        """读玩家 DNA；没有就按性别生成并落血脉核心状态。"""

        try:
            profile = await self._character.profile(user_id)
        except CharacterNotFoundError as exc:
            raise GenealogyQueryError("尚未创建人物") from exc
        return await self._bloodline.ensure_dna(user_id, profile.gender)

    def random_dna(self, gender: str) -> str:
        """实例化随机：6 组各自 0~99，G6 按性别取奇/偶。"""

        return self._bloodline.random_dna(gender, self._random)

    def breed(self, father: str, mother: str, gender: str) -> str:
        """父母各出 12 位，逐组算一个新 DNA。"""

        return self._bloodline.breed(father, mother, gender, self._random)

    def bloodline_growth(self, dna: str) -> dict[str, float]:
        """血脉加法表（基础值）。"""

        return self._bloodline.bloodline_growth(dna)

    def awakened_growth(self, dna: str, hp_percent: object) -> dict[str, float]:
        """血脉加法 x 觉醒倍数。"""

        return self._bloodline.awakened_growth(dna, hp_percent)

    def combat_growth(self, dna: str) -> dict[str, float]:
        """战斗侧只出基础加法；觉醒倍率由引擎乘在等级成长那一份上。"""

        return self._bloodline.combat_growth(dna)

    def awaken(self, hp_percent: object) -> object:
        """按真实气血百分比取觉醒倍率（护盾不计入）。"""

        return self._bloodline.awaken(hp_percent)

    def bloodlines(self, dna: str) -> tuple[str, ...]:
        """按 DNA 匹配出的血脉名字，按强度降序。"""

        return self._bloodline.bloodlines(dna)

    def buttons(self) -> tuple[Mapping[str, str], ...]:
        """血脉页面上的按钮。"""

        self._require_initialized()
        return self._buttons

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("血脉玩法微服务尚未初始化")

    def _entry(self, raw: object) -> GenealogyEntry:
        if not isinstance(raw, Mapping):
            raise GenealogyQueryError("族谱记录格式无效")
        return GenealogyEntry(
            code=str(raw.get("编号") or ""),
            blood_name=str(raw.get("族谱名") or ""),
            player_name=str(raw.get("玩家名") or ""),
            sex=str(raw.get("性别") or ""),
            generation=int(raw.get("代次") or 0),
            father_code=str(raw.get("父编号") or ""),
            mother_code=str(raw.get("母编号") or ""),
            dna=str(raw.get("DNA") or ""),
            retired=bool(raw.get("已传位")),
        )

    async def genealogy(self, user_id: str, query: str = "") -> GenealogyView:
        """读某人的族谱。只增不改：读到的就是记录当时的事实。"""

        self._require_initialized()
        try:
            profile = await self._character.profile(user_id)
        except CharacterNotFoundError as exc:
            raise GenealogyQueryError("尚未创建人物") from exc
        snapshot = await self._bloodline.genealogy_snapshot(user_id)
        entries: list[GenealogyEntry] = []
        generation = 0
        if snapshot is not None and isinstance(snapshot.value, Mapping):
            generation = int(snapshot.value.get("代次") or 0)
            raw_rows = snapshot.value.get("族谱")
            if isinstance(raw_rows, Sequence) and not isinstance(raw_rows, (str, bytes)):
                entries = [self._entry(raw) for raw in raw_rows]
        if query:
            needle = query.strip()
            entries = [
                entry
                for entry in entries
                if needle in entry.blood_name or needle in entry.player_name or needle == entry.code
            ]
        return GenealogyView(
            self_code=profile.name or user_id,
            generation=generation,
            entries=tuple(entries),
        )

    async def succession(self, user_id: str, child: str) -> SuccessionResult:
        """传位：选定一个新生儿，旧壳进族谱，换壳不换人，代次加一。

        第一版只落「换壳 + 族谱 + 代次」；按新 DNA 重算血脉要等血脉定义数据落地（批 3）。
        """

        self._require_initialized()
        target = str(child or "").strip()
        if not target:
            raise GenealogyQueryError("需要指定新生儿：%s" % _USAGE)
        try:
            profile = await self._character.profile(user_id)
        except CharacterNotFoundError as exc:
            raise GenealogyQueryError("尚未创建人物") from exc
        snapshot = await self._bloodline.genealogy_snapshot(user_id)
        rows = []
        generation = 0
        if snapshot is not None and isinstance(snapshot.value, Mapping):
            generation = int(snapshot.value.get("代次") or 0)
            raw = snapshot.value.get("族谱")
            if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
                rows = [dict(x) for x in raw if isinstance(x, Mapping)]
        candidates = [r for r in rows if not r.get("已传位")]
        picked = [r for r in candidates if target in (str(r.get("编号") or ""), str(r.get("族谱名") or ""))]
        if not picked:
            raise GenealogyQueryError("没有这个新生儿")
        if len(picked) > 1:
            raise GenealogyQueryError("有多个同名的新生儿，请报编号")
        child_row = picked[0]
        retired_code = str(profile.name or user_id)
        new_generation = generation + 1
        # 「已传位」标在【旧壳】那一行：当前壳的族谱条目就是它自己。
        # 只增不改：旧壳那一行不再动别的字段，新生儿那一行也不被标已传位。
        current_code = ""
        current_dna = ""
        if snapshot is not None and isinstance(snapshot.value, Mapping):
            current_code = str(snapshot.value.get("当前壳") or "")
            current_dna = str(snapshot.value.get("DNA") or "")
        marked = False
        for row in rows:
            if current_code and str(row.get("编号") or "") == current_code:
                row["已传位"] = True
                marked = True
        if not marked:
            # 旧壳第一次传位：族谱只记新生儿，玩家自己从没进过谱——这里补记一条。
            # 只增不改：补的是「当时的事实」（名字、性别、DNA、代次都取当下快照）。
            rows.append({
                "编号": str(user_id or ""),
                "族谱名": retired_code,
                "玩家名": retired_code,
                "性别": str(getattr(profile, "gender", "") or ""),
                "代次": generation,
                "父编号": "",
                "母编号": "",
                "DNA": str(current_dna or ""),
                "已传位": True,
            })
        child_row["代次"] = new_generation
        child_dna = str(child_row.get("DNA") or "")
        payload = {
            "代次": new_generation,
            "族谱": rows,
            "胎次": 0,
            "当前壳": str(child_row.get("编号") or ""),
        }
        operations = [
            self._bloodline.genealogy_mutation(
                user_id,
                payload,
                snapshot.version if snapshot is not None else 0,
            )
        ]
        if child_dna:
            operations.append(
                await self._bloodline.dna_mutation(user_id, child_dna)
            )
        await self._database.commit(
            TransactionCommand(
                user_id=user_id,
                request_id="传位:%s:%s" % (user_id, child_row.get("编号") or ""),
                business_type="血脉传位",
                operations=tuple(operations),
                payload={
                    "代次": new_generation,
                    "新壳": str(child_row.get("编号") or ""),
                    "DNA": child_dna,
                },
            )
        )
        return SuccessionResult(
            retired_code=retired_code,
            retired_name=str(profile.name or user_id),
            new_code=str(child_row.get("编号") or ""),
            new_name=str(child_row.get("族谱名") or ""),
            new_sex=str(child_row.get("性别") or ""),
            generation=new_generation,
            dna=str(child_row.get("DNA") or ""),
            bloodlines=self.bloodlines(str(child_row.get("DNA") or "000000000000")),
        )