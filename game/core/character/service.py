"""由角色 JSON 驱动的玩家创建与初始状态服务。"""

from __future__ import annotations

from game.core.bloodline import BloodlineService
from game.core.database import (
    StateSnapshot,
    DatabaseService,
    StateAddress,
    StateConflictError,
    StateMutation,
    TransactionCommand,
)
from game.core.asset import AssetGrade, AssetService, AssetStateError
from game.core.asset.ref import ItemRefError, parse_item_ref

import copy
import math
import random
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING

from game.core.combat import (
    CombatantSpec,
    CombatBuildRef,
    CombatStatusSpec,
    generate_five_elements,
)
from game.core.data import (
    JsonDataError,
    JsonDataService,
    mapping,
    mapping as _mapping,
    materialize,
    nonnegative_int,
    positive_int,
    positive_int as _positive_int,
    boolean,
    boolean as _bool,
    sequence as _sequence,
    strict_text,
    strict_text as _text,
    bounded_number,
)
from game.core.forging import ForgingError, ForgingService
from game.core.growth import GrowthError, GrowthService
from game.core.location import LocationService
from game.core.medicine import PreparedBattleMedicine
from game.core.player_state import PlayerStateService

if TYPE_CHECKING:
    from game.core.sect_library import SectLibraryService

from .races import load_races
from .contracts import (
    CharacterSlotPlan,
    CharacterAssemblyPlan,
    CharacterAbsorptionPlan,
    CharacterAlreadyExistsError,
    CharacterBattleMedicinePlan,
    CharacterBattlePlan,
    CharacterBreakthroughCorrectionPlan,
    CharacterBreakthroughPlan,
    CharacterBreakthroughPreview,
    CharacterContributionPlan,
    CharacterCreateCommand,
    CharacterCreationResult,
    CharacterCultivationError,
    CharacterEquipPlan,
    CharacterGenderPlan,
    CharacterGrowthPlan,
    CharacterFiveElementsPlan,
    CharacterYijingPlan,
    CharacterYijingRefundPlan,
    YijingProfile,
    CharacterRedemptionPlan,
    CharacterIdentityPlan,
    CharacterInputError,
    CharacterLawPlan,
    CharacterMedicineSettingPlan,
    CharacterNotFoundError,
    CharacterProfile,
    CharacterPublicProfile,
    CharacterRecoveryPlan,
    CharacterRetreatPlan,
    CharacterSpiritStonePlan,
    CharacterStateError,
    CharacterStatus,
    CharacterTechniqueUpgradePlan,
    EquippedContent,
    InventorySummary,
    WeaponProfile,
)


class CharacterService:
    """拥有玩家角色状态写权限的唯一核心服务。"""


    def __init__(
        self,
        data: JsonDataService,
        database: DatabaseService,
        player_state: PlayerStateService,
        location: LocationService,
        asset: AssetService,
        growth: GrowthService,
        forging: ForgingService,
        bloodline: BloodlineService,
        sect_library: SectLibraryService | None = None,
    ) -> None:
        self._data = data
        self._database = database
        self._player_state = player_state
        self._location = location
        self._asset = asset
        self._growth = growth
        self._forging = forging
        self._sect_library = sect_library
        #: 血脉核心：规则、DNA 与觉醒倍率都由它解释；角色不再接收玩法回调。
        self._bloodline = bloodline
        self._initialized = False
        self._role_rule: Mapping[str, object] = {}
        self._gender_values: tuple[str, ...] = ()
        self._grade_values: frozenset[str] = frozenset()
        self._attributes: Mapping[str, object] = {}
        self._medicine_default = True
        self._five_element_rules: Mapping[str, object] = {}
        self._races: Mapping[str, Mapping[str, object]] = MappingProxyType({})
        self._races_by_id: Mapping[str, Mapping[str, object]] = MappingProxyType({})
        self._initial_race = ""

    def _bloodline_service(self) -> BloodlineService:
        if self._bloodline is None:
            raise RuntimeError("血脉核心必须先于角色核心注入")
        return self._bloodline

    def initialize(self) -> CharacterStatus:
        if self._initialized:
            raise RuntimeError("角色核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据服务必须先于角色服务启动")
        if not self._database.status().initialized:
            raise RuntimeError("核心数据库必须先于角色服务启动")
        if not self._player_state.status().initialized:
            raise RuntimeError("人物状态服务必须先于角色服务启动")
        if not self._location.status().initialized:
            raise RuntimeError("玩家位置服务必须先于角色服务启动")
        if not self._asset.status().initialized:
            raise RuntimeError("玩家资产服务必须先于角色服务启动")
        if not self._growth.status().initialized:
            raise RuntimeError("成长核心必须先于角色服务启动")
        if not self._forging.status().initialized:
            raise RuntimeError("炼器核心必须先于角色服务启动")
        if not self._bloodline_service().status().initialized:
            raise RuntimeError("血脉核心必须先于角色服务启动")
        role_rules = self._data.dataset("角色规则")
        role_rule = role_rules.get("人物")
        if not isinstance(role_rule, Mapping):
            raise JsonDataError("角色规则缺少人物.json")
        gender_definition = self._data.dataset("角色定义").get("性别")
        if not isinstance(gender_definition, Mapping):
            raise JsonDataError("角色定义缺少性别.json")
        genders = gender_definition.get("取值")
        if not _strings(genders):
            raise JsonDataError("角色定义.性别.取值不能为空")
        grade_rows = self._data.dataset("基础定义").get("品级")
        if not isinstance(grade_rows, Sequence) or isinstance(grade_rows, (str, bytes)):
            raise JsonDataError("基础定义缺少品级.json")
        creation = _mapping(role_rule.get("创建"), "人物.json.创建")
        _mapping(creation.get("初始本命武器"), "人物.json.创建.初始本命武器")
        attributes = self._data.dataset("战斗字段定义").get("属性")
        self._five_element_rules = _mapping(
            self._data.dataset("战斗规则").get("五行"), "战斗/规则/五行.json"
        )
        medicine_rules = _mapping(
            self._data.dataset("服丹规则").get("服丹"), "玩法/服丹/规则/服丹.json"
        )
        medicine_auto = _mapping(medicine_rules.get("自动用药"), "服丹.自动用药")
        self._role_rule = role_rule
        self._coverable = frozenset(
            str(value)
            for value in (self._role_rule.get("属性覆盖白名单") or ())
        )
        self._gender_values = _strings(genders)
        self._grade_values = frozenset(
            str(_mapping(raw, "品级.json").get("编号") or "").strip()
            for raw in grade_rows
        )
        self._attributes = _mapping(attributes, "战斗定义.属性")
        self._medicine_default = _bool(
            medicine_auto.get("默认开启"), "服丹.自动用药.默认开启"
        )
        self._races = MappingProxyType(self._load_races())
        self._races_by_id = MappingProxyType(
            {str(entry["编号"]): entry for entry in self._races.values()}
        )
        self._initial_race = str(creation.get("初始种族") or "").strip()
        if self._initial_race not in self._races:
            raise JsonDataError(
                f"人物.json.创建.初始种族不是登记的种族：{self._initial_race or '<空>'}"
            )
        self._validate_static_rules()
        self._initialized = True
        initial_items = _initial_items(self._role_rule)
        return CharacterStatus(
            initialized=True,
            role_name=str(self._role_rule.get("角色类型") or ""),
            gender_count=len(self._gender_values),
            initial_item_count=len(initial_items),
        )

    def _load_races(self) -> dict[str, Mapping[str, object]]:
        """种族登记表：结构由 `races` 模块统一读取。"""

        return load_races(self._data)

    def races(self) -> Mapping[str, Mapping[str, object]]:
        """种族登记表（只读）。"""

        self._require_initialized()
        return self._races

    def race_by_id(self) -> Mapping[str, Mapping[str, object]]:
        """种族登记表（按编号索引，只读）。"""

        self._require_initialized()
        return self._races_by_id

    def inherent_rules(self, race: str) -> tuple[Mapping[str, object], ...]:
        """某个种族的**天生锁定技**，按「参战者固有规则」的形状交出去。"""

        self._require_initialized()
        name = str(race or "").strip()
        entry = self._races.get(name)
        if entry is None:
            raise JsonDataError(f"未登记的种族：{name or '<空>'}")
        return tuple(
            copy.deepcopy(dict(item)) for item in entry.get("天生规则") or ()
        )

    def initial_race(self) -> str:
        """没指定种族时用的那一族（人物.json 的 `创建.初始种族`，现在是基准族人族）。"""

        self._require_initialized()
        return self._initial_race

    def race_lifespan_factor(self, race: str) -> float:
        """种族的**寿元系数**：没写就是 1.0（人族基准）。

        寿元上限 = 当前境界的 `寿元` × 这个系数；这一轮只算上限，衰老与寿终还没做。
        """

        self._require_initialized()
        name = str(race or "").strip()
        entry = self._races.get(name)
        if entry is None:
            raise JsonDataError(f"未登记的种族：{name or '<空>'}")
        return float(entry.get("寿元系数") or 1.0)

    def _age(self, character: Mapping[str, object], lifespan: int) -> int:
        """**一生修行累计**的岁数（不设上限）：起点 + 修行日数 × 比例。

        注意这里**不钳制**：累计是「活过多少年」，上限只是「这一生允许活多少年」。
        钳制交给 `_clamp_age`——这样上限变化（换种族、换境界）时两边都能自洽。
        """

        from datetime import datetime, timezone

        creation = _mapping(self._role_rule.get("创建"), "人物.json.创建")
        base = int(creation.get("初始年龄") or 16)
        ratio = float(creation.get("年岁比例") or 1.0)
        born = character.get("诞生")
        days = 0.0
        if isinstance(born, str) and born:
            try:
                started = datetime.fromisoformat(born)
            except ValueError:
                started = None
            if started is not None:
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                days = (datetime.now(timezone.utc) - started).total_seconds() / 86400
        # 真正驱动年龄的是**修行日数**（数据库提交时按天盖戳，见 database/service.py）：
        # 离开多久都只算回来的那一天，所以久未回归不会顶到上限。没盖过戳时退回现实天数。
        trained = int(character.get("修行日数") or 0)
        progress = trained if trained else days * ratio
        return int(base + progress)

    def _without_level_growth(
        self, attributes: Mapping[str, float], level: int
    ) -> dict[str, float]:
        """寿元将尽：扣掉等级成长那一份，只留基础、装备、血脉等非成长加成。"""

        growth = self._growth.cultivator_attribute_growth(max(0, level - 1))
        result = dict(attributes)
        for name, amount in growth.items():
            result[str(name)] = max(0.0, float(result.get(str(name), 0.0)) - float(amount))
        return result


    def status(self) -> CharacterStatus:
        initial_items = _initial_items(self._role_rule) if self._initialized else ()
        return CharacterStatus(
            initialized=self._initialized,
            role_name=str(self._role_rule.get("角色类型") or "")
            if self._initialized
            else "",
            gender_count=len(self._gender_values),
            initial_item_count=len(initial_items),
        )

    def attribute_baselines(self) -> tuple[tuple[str, float], ...]:
        """每个属性的基准值：属性定义里的 默认值，也就是「不增不减」的那个数。

        展示层靠它判断「这条属性有没有信息」——等于基准的属性不值得占玩家的屏幕
        （见 data/战斗/定义/说明.md：默认值也是这个属性的基准值）。
        """

        self._require_initialized()
        return tuple(
            (name, float(_mapping(raw, f"属性.{name}").get("默认值") or 0.0))
            for name, raw in self._attributes.items()
        )

    async def profile(self, user_id: str) -> CharacterProfile:
        """读取一个人物的完整角色事实，不补造缺失状态。"""

        self._require_initialized()
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            raise ValueError("user_id 不能为空")
        snapshots = await self._database.list_for_user(normalized_user_id)
        states = {
            (snapshot.address.state_type, snapshot.address.state_key): snapshot.value
            for snapshot in snapshots
        }
        character = states.get(("character", "main"))
        if character is None:
            raise CharacterNotFoundError("尚未创建人物")
        cultivation = states.get(("cultivation", "main"))
        weapon = states.get(("weapon", "main"))
        if cultivation is None or weapon is None:
            raise CharacterStateError("人物资产不完整：缺少修行槽或本命武器")

        realm_id = _state_text(character.get("境界"), "人物.境界")
        realm_name = _state_text(
            self._data.entity("境界", realm_id).get("名称"),
            f"境界 {realm_id}.名称",
        )
        if self._sect_library is not None:
            cultivation = await self._sect_library.effective_cultivation(
                normalized_user_id, cultivation
            )
        cultivation_slots, equipped_content = self._cultivation_profile(cultivation)
        weapon_profile = self._weapon_profile(weapon)
        inventory = _inventory_summary(states)
        race = _state_text(character.get("种族"), "人物.种族")
        # 寿元上限 = 当前境界的寿元 × 种族的寿元系数。
        lifespan = int(
            round(self._growth.realm(realm_id).lifespan * self.race_lifespan_factor(race))
        )
        lifetime = self._age(character, lifespan)
        age, lifespan_full = _clamp_age(lifetime, lifespan)
        level = _state_positive_int(character.get("等级"), "人物.等级")
        attributes = _state_numbers(character.get("属性"), "人物.属性")
        resources = _state_numbers(character.get("资源"), "人物.资源")
        dna = await self._bloodline_service().stored_dna(normalized_user_id)
        if lifespan_full:
            attributes = self._without_level_growth(attributes, level)
            if dna:
                attributes = _subtract_numbers(
                    attributes, self._bloodline_service().bloodline_growth(dna)
                )
            resources = _clamp_life_resources(resources, attributes)
        yijing = () if lifespan_full else _yijing_profiles(
            self._data, character.get("意境"), character.get("境界")
        )
        return CharacterProfile(
            user_id=normalized_user_id,
            name=_state_text(character.get("姓名"), "人物.姓名"),
            gender=_state_text(character.get("性别"), "人物.性别"),
            character_type=_state_text(character.get("角色类型"), "人物.角色类型"),
            realm_id=realm_id,
            realm_name=realm_name,
            level=level,
            experience=_state_nonnegative_int(character.get("经验"), "人物.经验"),
            spirit_stones=await self._asset.spirit_stone_balance(normalized_user_id),
            sect_contribution=_state_nonnegative_int(
                character.get("宗门贡献", 0), "人物.宗门贡献"
            ),
            automatic_medicine=_state_bool(character.get("自动用药"), "人物.自动用药"),
            prepared_battle_medicine=_prepared_battle_medicine(
                character.get("待战战丹"), "人物.待战战丹"
            ),
            attributes=attributes,
            resources=resources,
            cultivation_slots=cultivation_slots,
            equipped_content=equipped_content,
            weapon=weapon_profile,
            inventory=inventory,
            five_elements=_state_five_elements(character.get("五行根性")),
            dna=dna,
            yijing=yijing,
            age=age,
            lifespan_full=lifespan_full,
            race=race,
            lifespan=lifespan,
        )

    async def public_profiles(
        self, user_ids: tuple[str, ...]
    ) -> tuple[CharacterPublicProfile, ...]:
        """批量读取附近展示所需的人物公开摘要。"""

        self._require_initialized()
        normalized = _user_ids(user_ids)
        snapshots = await self._database.get_many(
            tuple(StateAddress(user_id, "character", "main") for user_id in normalized)
        )
        by_user = {snapshot.address.user_id: snapshot.value for snapshot in snapshots}
        result: list[CharacterPublicProfile] = []
        for user_id in normalized:
            value = by_user.get(user_id)
            if value is None:
                continue
            realm_id = _state_text(value.get("境界"), "人物.境界")
            realm_name = _state_text(
                self._data.entity("境界", realm_id).get("名称"),
                f"境界 {realm_id}.名称",
            )
            result.append(
                CharacterPublicProfile(
                    user_id=user_id,
                    name=_state_text(value.get("姓名"), "人物.姓名"),
                    gender=_state_text(value.get("性别"), "人物.性别"),
                    realm_id=realm_id,
                    realm_name=realm_name,
                    level=_state_positive_int(value.get("等级"), "人物.等级"),
                )
            )
        return tuple(result)

    async def contributions(
        self, user_ids: tuple[str, ...]
    ) -> tuple[tuple[str, int], ...]:
        """批量读取个人宗门贡献，供宗门等级汇总使用。"""

        self._require_initialized()
        normalized = _user_ids(user_ids)
        snapshots = await self._database.get_many(
            tuple(StateAddress(user_id, "character", "main") for user_id in normalized)
        )
        by_user = {snapshot.address.user_id: snapshot.value for snapshot in snapshots}
        if len(by_user) != len(normalized):
            raise CharacterStateError("宗门成员缺少人物主体")
        return tuple(
            (
                user_id,
                _state_nonnegative_int(
                    by_user[user_id].get("宗门贡献", 0), "人物.宗门贡献"
                ),
            )
            for user_id in normalized
        )

    def _yijing_battle(
        self, profile: CharacterProfile, attributes: dict[str, object], weapon_attack: float
    ) -> tuple[float, tuple[CombatStatusSpec, ...], float]:
        """把人物身上的意境落进战斗快照。

        **每条点过的路各落一个状态**：增幅里归属为「参战者属性」的项并进属性
        （开局上限与初始值只认属性，状态修正改不了它们），归属为「状态修正」的项写进状态修正。
        各路的动态档用**数据里各自的计量名**——战斗核心的计量键是（参战者、构筑实例、计量名），
        所以六路同时开着也各有各的档、互不串。
        """

        statuses: list[CombatStatusSpec] = []
        #: 放大「等级成长那一份」的百分比之和（小数）：意境的百分比项按阶数累加。
        amplifier = 0.0
        for yijing in profile.yijing:
            row = self._data.entity("意境", yijing.content_id)
            carrier = _mapping(row.get("载体"), "意境.载体")
            # 基础数值与增幅已合成一张表：每项自己写 口径（绝对值/百分比）与 归属（参战者属性/状态修正）。
            amp = _mapping(carrier.get("增幅"), "意境.载体.增幅")
            per_tier = _mapping(amp.get("每阶"), "意境.增幅.每阶")
            baseline = _mapping(amp.get("基准"), "意境.增幅.基准")
            modifiers_list: list[tuple[str, float]] = []
            for name, spec in per_tier.items():
                key = str(name)
                cell = _mapping(spec, f"意境.增幅.每阶.{key}")
                step = float(_number(cell.get("数值"), f"意境.增幅.每阶.{key}.数值"))
                caliber = _state_text(cell.get("口径"), f"意境.增幅.每阶.{key}.口径")
                owner = _state_text(cell.get("归属"), f"意境.增幅.每阶.{key}.归属")
                if owner == "状态修正":
                    modifiers_list.append((key, float(baseline.get(key, 0)) + step * yijing.tier))
                    continue
                if key in {"血气上限", "神魂上限"}:
                    # 两条命线的上限是同一类资源上限：百分比直接扩大上限，不走等级成长。
                    base = float(attributes.get(key, 100.0))
                    attributes[key] = (
                        base * (1.0 + step * yijing.tier / 100.0)
                        if caliber == "百分比"
                        else base + step * yijing.tier
                    )
                elif key == "器的量":
                    weapon_attack += step * yijing.tier
                elif caliber == "百分比":
                    # 这是「放大等级成长」的百分比，**不加到基础值上**（委托方 2026-10-16 最终口径：
                    # 基础攻击太小、加百分比等于没有效果），累加成系数交给等级成长那一份去乘。
                    amplifier += step * yijing.tier / 100.0
                else:
                    base = _number(attributes.get(key, 0), f"意境.{key}")
                    attributes[key] = base + step * yijing.tier
            modifiers = tuple(modifiers_list)
            raw_listeners = row.get("质变监听") or {}
            picked = (
                [value for key, value in raw_listeners.items() if key.isdigit() and int(key) <= yijing.tier]
                if isinstance(raw_listeners, Mapping)
                else []
            )
            listeners = [dict(value) for value in picked if isinstance(value, Mapping)]
            counter = _mapping(row.get("战斗档"), "意境.战斗档")
            counter_name = _state_text(counter.get("计量"), "意境.战斗档.计量")
            # 动态档的计量由核心开：数据不知道玩家买到几阶，上限只能在这儿给。
            # **无条件开**：涨档要靠它，跟这条路上有没有质变监听无关。
            listeners.append(
                {
                    "能力": "监听事件",
                    "事件": "行动开始",
                    "观察角色": "行动者",
                    "阵营关系": "自身",
                    "效果": [
                        {
                            "能力": "修改构筑计量",
                            "计量": counter_name,
                            "方式": "增加",
                            "数值": 0,
                            "初始值": 0,
                            "最低值": 0,
                            "最高值": yijing.tier,
                            "目标": {"能力": "选择目标", "范围": "自身"},
                        }
                    ],
                    "每次行动最多触发": 1,
                }
            )
            # 涨档：**事件与观察角色都写在数据里**（各路的「涨一档看什么」），核心只把上限兜住
            # （上面那条的「最高值＝激活阶」）。数据没写涨法就不挂——那一路的动态档就一直是 0。
            rise = counter.get("涨")
            if isinstance(rise, Mapping):
                listeners.append(
                    {
                        "能力": "监听事件",
                        "事件": _state_text(rise.get("事件"), "意境.战斗档.涨.事件"),
                        "观察角色": _state_text(rise.get("观察"), "意境.战斗档.涨.观察"),
                        "阵营关系": "自身",
                        "效果": [
                            {
                                "能力": "修改构筑计量",
                                "计量": counter_name,
                                "方式": "增加",
                                "数值": 1,
                                "目标": {"能力": "选择目标", "范围": "自身"},
                            }
                        ],
                        "每次行动最多触发": 1,
                    }
                )
            listeners = tuple(listeners)
            limits: tuple[str, ...] = ()
            rule = row.get("戒律")
            if isinstance(rule, Mapping) and int(rule.get("阶") or 0) <= yijing.tier:
                limits = tuple(str(value) for value in (rule.get("行动限制") or ()))
            statuses.append(
                CombatStatusSpec(
                    name=f"意境·{yijing.name}·{yijing.tier}阶",
                    category="增益",
                    remaining_actions=999,
                    duration_unit="状态承受者行动",
                    modifiers=modifiers,
                    listeners=listeners,
                    action_limits=limits,
                    source=yijing.content_id,
                    source_name=yijing.name,
                )
            )
        return weapon_attack, tuple(statuses), amplifier

    async def combatant(
        self, user_id: str, *, profile: CharacterProfile | None = None
    ) -> CombatantSpec:
        """把人物事实转换成战斗核心公共快照。

        `profile` 可由调用方传入——同一次命令里**刚读过**的同一个人物事实。一个人物的
        整份状态读取实测约 2 ms（每次都要新开一次 sqlite 连接），而一次 15 对 15
        的宗门战要读 30 个人物，能省一趟是一趟。不传时的行为与从前完全一致；
        传进来的人物对不上号时也退回自己读，绝不拿错人。
        """

        normalized = str(user_id or "").strip()
        if profile is None or profile.user_id != normalized:
            profile = await self.profile(user_id)
        attributes = dict(profile.attributes)
        resources = dict(profile.resources)
        # 意境：归属为「参战者属性」的项要先并进属性（开局上限与初始值只认属性），其余走状态修正。
        weapon_attack, yijing_statuses, yijing_amplifier = self._yijing_battle(
            profile, attributes, float(profile.weapon.attack)
        )
        dna = profile.dna
        build = tuple(
            CombatBuildRef(
                section=value.category,
                content_id=value.content_id,
                instance_id=f"{profile.user_id}:{value.category}:{value.slot}",
                born_order=value.slot,
                power_multiplier=(
                    float(self._asset.grade(value.grade).ability_multiplier)
                    if value.grade
                    else 1.0
                ),
            )
            for value in (*profile.equipped_content, *profile.weapon.equipped_laws)
        )
        return CombatantSpec(
            id=f"player:{profile.user_id}",
            name=profile.name,
            dna=dna,
            bloodline_disabled=bool(profile.lifespan_full),
            attributes=attributes,
            level=profile.level,
            combatant_type=profile.character_type,
            weapon_attack=weapon_attack,
            build=build,
            health=float(resources.get("血气", attributes.get("血气上限", 0))),
            spirit=float(resources.get("精神", attributes.get("精神上限", 0))),
            soul=float(resources.get("神魂", attributes.get("神魂上限", 0))),
            auto_medicine=profile.automatic_medicine,
            owner_id=profile.user_id,
            controller_id=profile.user_id,
            inventory_owner_id=profile.user_id,
            gender=profile.gender,
            five_elements=dict(profile.five_elements),
            inherent_rules=self.inherent_rules(profile.race),
            prepared_statuses=yijing_statuses,
            # 铁律：等级成长那一份 ×（觉醒倍数 + 意境百分比）。觉醒按战斗内气血取，由引擎加。
            growth_base=(
                {}
                if profile.lifespan_full
                else {
                    str(key): float(value)
                    for key, value in self._growth.cultivator_attribute_growth(
                        max(0, int(profile.level) - 1)
                    ).items()
                }
            ),
            growth_amplifier=1.0 + yijing_amplifier,
        )

    async def create(self, command: CharacterCreateCommand) -> CharacterCreationResult:
        self._require_initialized()
        self._validate_command(command)
        creation = _mapping(self._role_rule.get("创建"), "人物.json.创建")
        realm_id = str(creation.get("初始境界") or "").strip()
        realm = self._data.entity("境界", realm_id)
        realm_name = str(realm.get("名称") or "").strip()
        if not realm_name:
            raise JsonDataError(f"初始境界缺少名称：{realm_id}")
        initial_level = _positive_int(self._role_rule.get("等级"), "人物初始等级")
        if not _in_range(initial_level, realm.get("等级下限"), realm.get("等级上限")):
            raise JsonDataError("初始等级不属于初始境界")

        character_state = self._character_state(command, realm_id)
        cultivation_state = self._cultivation_state()
        weapon_state = self._weapon_state(creation)
        item_rows = _initial_items(self._role_rule)
        operations = [
            StateMutation(command.user_id, "character", "main", character_state, 0),
            StateMutation(command.user_id, "cultivation", "main", cultivation_state, 0),
            StateMutation(command.user_id, "weapon", "main", weapon_state, 0),
            self._player_state.initial_mutation(command.user_id),
            self._location.initial_mutation(command.user_id, command.birth_xy),
        ]
        operations.extend(
            self._asset.initial_inventory_mutations(command.user_id, item_rows)
        )
        _dna, dna_mutation = await self._bloodline_service().plan_dna(
            command.user_id, command.gender
        )
        if dna_mutation is not None:
            operations.append(dna_mutation)
        try:
            receipt = await self._database.commit(
                TransactionCommand(
                    user_id=command.user_id,
                    request_id=command.request_id,
                    business_type="创建人物",
                    operations=tuple(operations),
                    payload={
                        "姓名": command.name,
                        "性别": command.gender,
                        "种族": command.race or self._initial_race,
                        "出生地": list(command.birth_xy),
                        "初始境界": realm_id,
                    },
                )
            )
        except StateConflictError as exc:
            existing = await self._database.get(
                StateAddress(command.user_id, "character", "main")
            )
            if existing is not None:
                raise CharacterAlreadyExistsError("该用户已经创建过人物") from exc
            raise
        return CharacterCreationResult(
            user_id=command.user_id,
            name=command.name,
            gender=command.gender,
            realm_id=realm_id,
            realm_name=realm_name,
            birth_xy=command.birth_xy,
            initial_items=item_rows,
            replayed=receipt.replayed,
            race=command.race or self._initial_race,
        )

    async def plan_growth(
        self,
        user_id: str,
        *,
        experience: int = 0,
        weapon_experience: int = 0,
    ) -> CharacterGrowthPlan:
        """生成一次人物与其本命武器的独立成长变更。"""

        self._require_initialized()
        normalized_user_id = _required_user_id(user_id)
        character_snapshot, weapon_snapshot = await self._growth_snapshots(
            normalized_user_id
        )
        character = dict(_state_mapping(character_snapshot.value, "character/main"))
        weapon = dict(_state_mapping(weapon_snapshot.value, "weapon/main"))
        try:
            cultivator_advance = self._growth.advance_cultivator(
                level=_state_positive_int(character.get("等级"), "人物.等级"),
                experience=_state_nonnegative_int(character.get("经验"), "人物.经验"),
                realm_id=_state_text(character.get("境界"), "人物.境界"),
                gained=_nonnegative_request_int(experience, "人物经验"),
            )
            weapon_advance = self._forging.advance_weapon(
                level=_state_positive_int(weapon.get("等级"), "本命武器.等级"),
                experience=_state_nonnegative_int(weapon.get("经验"), "本命武器.经验"),
                gained=_nonnegative_request_int(weapon_experience, "本命武器经验"),
            )
        except (GrowthError, ForgingError) as exc:
            raise CharacterCultivationError(str(exc)) from exc
        character["等级"] = cultivator_advance.level_after
        character["经验"] = cultivator_advance.experience_after
        # 种族不再提供成长倍率（种族只留天生规则与寿元系数）：等级成长直接并入，不乘任何倍率。
        grown = self._growth.cultivator_attribute_growth(cultivator_advance.levels_gained)
        profile = await self.profile(normalized_user_id)
        if profile.dna and not profile.lifespan_full:
            # 这里只并入基础加法；觉醒随战内气血，归战斗的「行动开始」。
            grown = _add_numbers(
                grown, self._bloodline_service().bloodline_growth(profile.dna)
            )
        character["属性"] = _add_numbers(
            _state_mapping(character.get("属性"), "人物.属性"),
            grown,
        )
        weapon["等级"] = weapon_advance.level_after
        weapon["经验"] = weapon_advance.experience_after
        weapon["器阶"] = weapon_advance.stage_after
        return CharacterGrowthPlan(
            cultivator_advance.level_before,
            cultivator_advance.level_after,
            weapon_advance.level_before,
            weapon_advance.level_after,
            (
                StateMutation(
                    normalized_user_id,
                    "character",
                    "main",
                    character,
                    character_snapshot.version,
                ),
                StateMutation(
                    normalized_user_id,
                    "weapon",
                    "main",
                    weapon,
                    weapon_snapshot.version,
                ),
            ),
        )

    async def plan_absorb_experience(
        self, user_id: str, *, experience: int
    ) -> CharacterAbsorptionPlan:
        """生成不允许越过当前境界等级上限的修为承接计划。"""

        self._require_initialized()
        normalized_user_id = _required_user_id(user_id)
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "character", "main")
        )
        if snapshot is None:
            raise CharacterNotFoundError("尚未创建人物")
        offered = _nonnegative_request_int(experience, "夺元修为")
        character = dict(_state_mapping(snapshot.value, "character/main"))
        level_before = _state_positive_int(character.get("等级"), "人物.等级")
        experience_before = _state_nonnegative_int(character.get("经验"), "人物.经验")
        realm_id = _state_text(character.get("境界"), "人物.境界")
        realm = self._growth.realm(realm_id)
        capacity = -experience_before
        for level in range(level_before, realm.maximum_level):
            capacity += self._growth.experience_required(level)
        accepted = min(offered, max(0, capacity))
        advance = self._growth.advance_cultivator(
            level=level_before,
            experience=experience_before,
            realm_id=realm_id,
            gained=accepted,
        )
        character["等级"] = advance.level_after
        character["经验"] = advance.experience_after
        character["属性"] = _add_numbers(
            _state_mapping(character.get("属性"), "人物.属性"),
            self._growth.cultivator_attribute_growth(advance.levels_gained),
        )
        return CharacterAbsorptionPlan(
            offered,
            accepted,
            offered - accepted,
            level_before,
            advance.level_after,
            advance.experience_after,
            StateMutation(
                normalized_user_id,
                "character",
                "main",
                character,
                snapshot.version,
            ),
        )

    async def plan_medicine_setting(
        self, user_id: str, *, enabled: bool
    ) -> CharacterMedicineSettingPlan:
        """生成只改变人物自动用药开关的状态变更。"""

        if not isinstance(enabled, bool):
            raise CharacterCultivationError("自动用药开关必须是布尔值")
        user, snapshot, character = await self._medicine_state(user_id)
        if _state_bool(character.get("自动用药"), "人物.自动用药") == enabled:
            raise CharacterCultivationError(
                f"人物自动用药已经{'开启' if enabled else '关闭'}"
            )
        character["自动用药"] = enabled
        return CharacterMedicineSettingPlan(
            enabled,
            StateMutation(user, "character", "main", character, snapshot.version),
        )

    async def plan_recovery(
        self, user_id: str, *, resource: str, recovery_percent: float
    ) -> CharacterRecoveryPlan:
        """按人物资源上限生成一次主动恢复。"""

        user, snapshot, character = await self._medicine_state(user_id)
        normalized_resource = _medicine_resource(resource)
        percent = _positive_number(recovery_percent, "恢复百分比")
        attributes = _state_mapping(character.get("属性"), "人物.属性")
        resources = dict(_state_mapping(character.get("资源"), "人物.资源"))
        maximum = _number(
            attributes.get(f"{normalized_resource}上限"), f"{normalized_resource}上限"
        )
        before = bounded_number(
            resources.get(normalized_resource), maximum, f"当前{normalized_resource}"
        )
        if before >= maximum:
            raise CharacterCultivationError(f"人物{normalized_resource}已满")
        after = min(maximum, before + maximum * percent / 100)
        resources[normalized_resource] = _clean_number(after)
        character["资源"] = resources
        return CharacterRecoveryPlan(
            normalized_resource,
            before,
            after,
            after - before,
            StateMutation(user, "character", "main", character, snapshot.version),
        )

    def yijing_cost(self, tier: int) -> int:
        """升到第 N 阶要多少道行。

        一处真源：突破发点与命令升阶都走它，免得两处各存一张表、日后漂移。
        """

        return _yijing_tier_cost(_positive_int(tier, "意境.阶"))

    def yijing_cap(self, realm_id: str) -> int:
        """该境界允许的意境阶上限（二十境界九阶，序号由等级下限推）。"""

        realm = self._data.entity("境界", str(realm_id))
        return _yijing_tier_cap(_realm_order(realm.get("等级下限")))

    async def yijing_points(self, user_id: str) -> int:
        """已经攒下的道行——**一条路都没点时也能读**（点是玩家共有的，不挂在某条路上）。

        状态格的解释权在本核心：玩法层要读道行就调这里，
        不要自己去读 `character/main` 的「意境」一格。
        """

        _, _, character = await self._medicine_state(user_id)
        paths, points = _state_yijing(character.get("意境")) or ({}, 0)
        return int(points)

    async def plan_yijing_point(
        self, user_id: str, *, content_id: str
    ) -> CharacterYijingPlan:
        """给**某一条路**点一阶（没点过的从 0 升到 1＝激活）。

        六条路各自记阶、**道行共享那一份**；每条路各自受境界给的阶上限约束。
        投进去的道行不退（洗点是忘境丹那条线，见台账施工单）。
        """

        user, snapshot, character = await self._medicine_state(user_id)
        content_id = str(content_id)
        self._data.entity("意境", content_id)
        cell = dict(character.get("意境") or {})
        paths, points = _state_yijing(cell) or ({}, 0)
        tier = int(paths.get(content_id, 0))
        realm_id = _state_text(character.get("境界"), "人物.境界")
        cap = _yijing_tier_cap(
            _realm_order(self._data.entity("境界", realm_id).get("等级下限"))
        )
        if tier >= 9:
            raise CharacterCultivationError("这条意境已满九阶")
        if tier >= cap:
            raise CharacterCultivationError(f"当前境界只撑得到{cap}阶意境")
        cost = _yijing_tier_cost(tier + 1)
        if points < cost:
            raise CharacterCultivationError(f"道行还差{cost - points}点")
        paths[content_id] = tier + 1
        cell.pop("编号", None)
        cell.pop("阶", None)
        cell["路"] = {key: paths[key] for key in sorted(paths)}
        cell["道行"] = points - cost
        character["意境"] = cell
        return CharacterYijingPlan(
            content_id, tier, tier + 1, cost, points - cost,
            StateMutation(user, "character", "main", character, snapshot.version),
        )

    async def plan_yijing_refund(self, user_id: str) -> CharacterYijingRefundPlan:
        """坐忘：把六条路练过的阶全部抹去，道行退回到**已发总额**（按当前境界的阶上限算累计价）。

        道行只来自境界突破，所以「已发总额」＝阶价 1..阶上限 的累计，与突破实际发下来的数一致；
        退点不惩罚、不抽成，玩家可以重新分配。一条路都没点过就没有可退的，直接拒。
        """

        user, snapshot, character = await self._medicine_state(user_id)
        cell = dict(character.get("意境") or {})
        paths, points = _state_yijing(cell) or ({}, 0)
        if not paths:
            raise CharacterCultivationError("六条意境一条都没点过，无需坐忘")
        realm_id = _state_text(character.get("境界"), "人物.境界")
        cap = self.yijing_cap(realm_id)
        granted = sum(_yijing_tier_cost(tier) for tier in range(1, cap + 1))
        cell.pop("编号", None)
        cell.pop("阶", None)
        cell["路"] = {}
        cell["道行"] = granted
        character["意境"] = cell
        return CharacterYijingRefundPlan(
            tuple(sorted(paths.items())),
            points,
            granted,
            StateMutation(user, "character", "main", character, snapshot.version),
        )

    async def plan_identity_change(
        self, user_id: str, *, race: str
    ) -> CharacterIdentityPlan:
        """把人物换成另一个种族（换种族丹用）。

        目标种族必须在登记表里，取不到就报错、不静默；已经长出来的属性**不回溯**（换种族不重算历史成长），
        但天生规则、卡池来源、寿元系数都是现算的派生值，改完立刻跟着换。
        """

        user, snapshot, character = await self._medicine_state(user_id)
        wanted = str(race or "").strip()
        if not wanted:
            raise CharacterCultivationError("换种族丹没有指明目标种族")
        if wanted not in self._races:
            raise JsonDataError(f"未登记的种族：{wanted}")
        before = _state_text(character.get("种族"), "人物.种族")
        if before == wanted:
            raise CharacterCultivationError(f"你已经就是{wanted}")
        character["种族"] = wanted
        return CharacterIdentityPlan(
            before,
            wanted,
            StateMutation(user, "character", "main", character, snapshot.version),
        )

    async def plan_five_elements_change(
        self, user_id: str, *, seed: str
    ) -> CharacterFiveElementsPlan:
        """把五行根性整体重掷一次（洗根丹用）。

        与建号时同一套生成规则（generate_five_elements：一条主、一条次、三条余，合计一百），
        所以产出照样过得了入库校验。随机种子由调用方给——同一条请求重放必须掷出同一副，
        换一条请求才是新的一掷。撞回原来那副就继续掷（洗根的意义就是换个样子），
        掷到第几次也算得出来，重放因此仍然一致。
        """

        user, snapshot, character = await self._medicine_state(user_id)
        before = _state_five_elements(character.get("五行根性"))
        source = random.Random(seed)
        after = before
        repeated = 0
        for _ in range(50):
            after = generate_five_elements(self._five_element_rules, source)
            if after != before:
                break
            repeated += 1
        character["五行根性"] = after
        return CharacterFiveElementsPlan(
            before,
            after,
            repeated,
            StateMutation(user, "character", "main", character, snapshot.version),
        )

    async def plan_code_redemption(
        self, user_id: str, *, code_id: str, limit: int, spirit_stones: int = 0
    ) -> CharacterRedemptionPlan:
        """兑换码的人物侧交割：记一次兑换，并可同时发放灵石。

        每人限次只看状态里的「已兑换码」，**不看请求编号**——请求编号管的是同一条请求重放，
    换一条请求就能再兑一次，那是两回事。灵石与兑换记录同址，所以合成一份变更。
        """

        user, snapshot, character = await self._medicine_state(user_id)
        wanted = str(code_id or "").strip()
        if len(wanted) != 6 or not wanted.isdigit():
            raise CharacterCultivationError("兑换码编号必须是六位数字")
        times = _nonnegative_request_int(limit, "每人限次") or 1
        redeemed = _state_redeemed(character.get("已兑换码"))
        used = sum(1 for item in redeemed if item == wanted)
        if used >= times:
            raise CharacterCultivationError("这个兑换码你已经用过了")
        stones = _request_int(spirit_stones, "灵石发放")
        before_stones = await self._asset.spirit_stone_balance(user)
        after_stones = before_stones + stones
        stone_plan = await self._asset.plan_spirit_stone_change(user, stones)
        character["已兑换码"] = list(redeemed) + [wanted]
        return CharacterRedemptionPlan(
            wanted,
            used,
            used + 1,
            before_stones,
            after_stones,
            (
                StateMutation(user, "character", "main", character, snapshot.version),
            )
            + stone_plan.operations,
        )

    async def plan_battle_medicine(
        self,
        user_id: str,
        *,
        medicine: PreparedBattleMedicine | None,
        require_empty: bool = False,
    ) -> CharacterBattleMedicinePlan:
        """寄存或清除人物下一场正式战斗使用的战丹。"""

        user, snapshot, character = await self._medicine_state(user_id)
        before = _prepared_battle_medicine(character.get("待战战丹"), "人物.待战战丹")
        if require_empty and before is not None:
            raise CharacterCultivationError("人物已有待战战丹")
        if before == medicine:
            raise CharacterCultivationError("人物待战战丹没有变化")
        character["待战战丹"] = _prepared_battle_value(medicine)
        return CharacterBattleMedicinePlan(
            before,
            medicine,
            StateMutation(user, "character", "main", character, snapshot.version),
        )

    async def _medicine_state(self, user_id: str) -> tuple[str, StateSnapshot, dict[str, object]]:
        self._require_initialized()
        normalized_user_id = _required_user_id(user_id)
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "character", "main")
        )
        if snapshot is None:
            raise CharacterNotFoundError("尚未创建人物")
        return (
            normalized_user_id,
            snapshot,
            dict(_state_mapping(snapshot.value, "character/main")),
        )

    async def plan_battle_settlement(
        self,
        user_id: str,
        *,
        health: float,
        spirit: float,
        spirit_stones_delta: int = 0,
        weapon_experience: int = 0,
    ) -> CharacterBattlePlan:
        """只结算战后资源、灵石和本命武器经验。"""

        self._require_initialized()
        normalized_user_id = _required_user_id(user_id)
        character_snapshot, weapon_snapshot = await self._growth_snapshots(
            normalized_user_id
        )
        character = dict(_state_mapping(character_snapshot.value, "character/main"))
        weapon = dict(_state_mapping(weapon_snapshot.value, "weapon/main"))
        attributes = _state_mapping(character.get("属性"), "人物.属性")
        resources = dict(_state_mapping(character.get("资源"), "人物.资源"))
        health_after = bounded_number(health, attributes.get("血气上限"), "战后血气")
        spirit_after = bounded_number(spirit, attributes.get("精神上限"), "战后精神")
        stone_delta = _request_int(spirit_stones_delta, "灵石变化")
        stone_plan = await self._asset.plan_spirit_stone_change(
            normalized_user_id, stone_delta
        )
        gained = _nonnegative_request_int(weapon_experience, "本命武器经验")
        try:
            advance = self._forging.advance_weapon(
                level=_state_positive_int(weapon.get("等级"), "本命武器.等级"),
                experience=_state_nonnegative_int(weapon.get("经验"), "本命武器.经验"),
                gained=gained,
            )
        except ForgingError as exc:
            raise CharacterCultivationError(str(exc)) from exc
        resources.update({"血气": health_after, "精神": spirit_after, "护盾": 0})
        character["资源"] = resources
        weapon["等级"] = advance.level_after
        weapon["经验"] = advance.experience_after
        weapon["器阶"] = advance.stage_after
        return CharacterBattlePlan(
            health_after,
            spirit_after,
            stone_delta,
            gained,
            (
                StateMutation(
                    normalized_user_id,
                    "character",
                    "main",
                    character,
                    character_snapshot.version,
                ),
                StateMutation(
                    normalized_user_id,
                    "weapon",
                    "main",
                    weapon,
                    weapon_snapshot.version,
                ),
            )
            + stone_plan.operations,
        )

    async def plan_battle_delta(
        self,
        user_id: str,
        *,
        health_delta: float,
        spirit_delta: float,
        spirit_stones_delta: int = 0,
        weapon_experience: int = 0,
    ) -> CharacterBattlePlan:
        """只结算战后资源增量、灵石和武器经验。

        探险在开局预演战斗，结算时不能把预演终值整块盖回当前人物；
        这里读当前资源，加上「本场终值 − 开局快照」的变化量，再夹上限。
        """

        self._require_initialized()
        normalized_user_id = _required_user_id(user_id)
        character_snapshot, weapon_snapshot = await self._growth_snapshots(
            normalized_user_id
        )
        character = dict(_state_mapping(character_snapshot.value, "character/main"))
        weapon = dict(_state_mapping(weapon_snapshot.value, "weapon/main"))
        attributes = _state_mapping(character.get("属性"), "人物.属性")
        resources = dict(_state_mapping(character.get("资源"), "人物.资源"))
        health_change = _number(health_delta, "战后血气变化")
        spirit_change = _number(spirit_delta, "战后精神变化")
        health_after = bounded_number(
            _number(resources.get("血气"), "人物.血气") + float(health_change),
            attributes.get("血气上限"),
            "战后血气",
        )
        spirit_after = bounded_number(
            _number(resources.get("精神"), "人物.精神") + float(spirit_change),
            attributes.get("精神上限"),
            "战后精神",
        )
        stone_delta = _request_int(spirit_stones_delta, "灵石变化")
        stone_plan = await self._asset.plan_spirit_stone_change(
            normalized_user_id, stone_delta
        )
        gained = _nonnegative_request_int(weapon_experience, "本命武器经验")
        try:
            advance = self._forging.advance_weapon(
                level=_state_positive_int(weapon.get("等级"), "本命武器.等级"),
                experience=_state_nonnegative_int(weapon.get("经验"), "本命武器.经验"),
                gained=gained,
            )
        except ForgingError as exc:
            raise CharacterCultivationError(str(exc)) from exc
        resources.update({"血气": health_after, "精神": spirit_after, "护盾": 0})
        character["资源"] = resources
        weapon["等级"] = advance.level_after
        weapon["经验"] = advance.experience_after
        weapon["器阶"] = advance.stage_after
        return CharacterBattlePlan(
            health_after,
            spirit_after,
            stone_delta,
            gained,
            (
                StateMutation(
                    normalized_user_id,
                    "character",
                    "main",
                    character,
                    character_snapshot.version,
                ),
                StateMutation(
                    normalized_user_id,
                    "weapon",
                    "main",
                    weapon,
                    weapon_snapshot.version,
                ),
            )
            + stone_plan.operations,
        )

    async def plan_retreat_settlement(
        self,
        user_id: str,
        *,
        experience: int,
        health_recovery_ratio: float,
        spirit_recovery_ratio: float,
    ) -> CharacterRetreatPlan:
        """合并闭关经验与资源恢复，只修改人物主体。"""

        self._require_initialized()
        normalized_user_id = _required_user_id(user_id)
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "character", "main")
        )
        if snapshot is None:
            raise CharacterNotFoundError("尚未创建人物")
        character = dict(_state_mapping(snapshot.value, "character/main"))
        gained = _nonnegative_request_int(experience, "闭关人物经验")
        health_ratio = _request_ratio(health_recovery_ratio, "闭关血气恢复比例")
        spirit_ratio = _request_ratio(spirit_recovery_ratio, "闭关精神恢复比例")
        try:
            advance = self._growth.advance_cultivator(
                level=_state_positive_int(character.get("等级"), "人物.等级"),
                experience=_state_nonnegative_int(character.get("经验"), "人物.经验"),
                realm_id=_state_text(character.get("境界"), "人物.境界"),
                gained=gained,
            )
        except GrowthError as exc:
            raise CharacterCultivationError(str(exc)) from exc
        attributes = _add_numbers(
            _state_mapping(character.get("属性"), "人物.属性"),
            self._growth.cultivator_attribute_growth(advance.levels_gained),
        )
        resources = dict(_state_mapping(character.get("资源"), "人物.资源"))
        health_maximum = _number(attributes.get("血气上限"), "血气上限")
        spirit_maximum = _number(attributes.get("精神上限"), "精神上限")
        health = bounded_number(
            _number(resources.get("血气"), "人物.血气") + health_maximum * health_ratio,
            health_maximum,
            "闭关后血气",
        )
        spirit = bounded_number(
            _number(resources.get("精神"), "人物.精神") + spirit_maximum * spirit_ratio,
            spirit_maximum,
            "闭关后精神",
        )
        resources.update({"血气": health, "精神": spirit})
        character.update(
            {
                "等级": advance.level_after,
                "经验": advance.experience_after,
                "属性": attributes,
                "资源": resources,
            }
        )
        return CharacterRetreatPlan(
            gained,
            advance.level_before,
            advance.level_after,
            health,
            spirit,
            StateMutation(
                normalized_user_id,
                "character",
                "main",
                character,
                snapshot.version,
            ),
        )

    async def plan_borrow_slot(
        self,
        user_id: str,
        slot: int,
        content_id: str,
        grade_id: str,
        sect_id: str,
    ) -> "CharacterSlotPlan":
        """藏经阁借阅：把某一格功法换成借来的那本，并记住原本的功法。"""

        snapshot = await self._database.get(StateAddress(user_id, "cultivation", "main"))
        if snapshot is None:
            raise CharacterStateError("人物缺少修行构筑")
        cultivation = dict(_mapping(snapshot.value, "cultivation/main"))
        slots = list(_state_slots(cultivation.get("功法"), "功法"))
        if slot < 1 or slot > len(slots):
            raise CharacterStateError(f"人物只有{len(slots)}个功法槽")
        current = slots[slot - 1]
        original = current
        if isinstance(current, Mapping):
            borrowed = current.get("藏经阁借阅")
            if isinstance(borrowed, Mapping):
                original = borrowed.get("原功法")
        slots[slot - 1] = {
            "编号": content_id,
            "品级": grade_id,
            "藏经阁借阅": {"宗门编号": sect_id, "原功法": original},
        }
        cultivation["功法"] = slots
        return CharacterSlotPlan(
            snapshot.version,
            (StateMutation(user_id, "cultivation", "main", cultivation, snapshot.version),),
        )

    async def plan_restore_borrowed(self, user_id: str, keep_sect_id: str) -> "CharacterSlotPlan":
        """离开宗门：把借自其他宗门的槽还原成原本的功法；没有可清的就返回空计划。"""

        snapshot = await self._database.get(StateAddress(user_id, "cultivation", "main"))
        if snapshot is None:
            return CharacterSlotPlan(0, ())
        cultivation = dict(_mapping(snapshot.value, "cultivation/main"))
        slots = list(_state_slots(cultivation.get("功法"), "功法"))
        cleared = 0
        for index, raw in enumerate(slots):
            if not isinstance(raw, Mapping):
                continue
            borrowed = raw.get("藏经阁借阅")
            if not isinstance(borrowed, Mapping):
                continue
            sect_id = str(borrowed.get("宗门编号") or "")
            if keep_sect_id and sect_id == keep_sect_id:
                continue
            slots[index] = borrowed.get("原功法")
            cleared += 1
        if not cleared:
            return CharacterSlotPlan(0, ())
        cultivation["功法"] = slots
        return CharacterSlotPlan(
            snapshot.version,
            (StateMutation(user_id, "cultivation", "main", cultivation, snapshot.version),),
            cleared,
        )

    async def plan_equip(
        self,
        user_id: str,
        *,
        category: str,
        content_id: str,
        grade_id: str,
        slot: int,
    ) -> CharacterEquipPlan:
        """验证道藏所有权，并生成一个人物修行槽替换。

        五个阶段各自成函数：校验入参（`_equip_target`）、读修行快照
        （`_equip_slots`，顺带做槽位范围与重复装配检查）、写槽、取内容来源
        （`_equip_source`，功法查道藏所有权、真意与气机扣一份储备）、组装计划。
        """

        normalized_user_id, normalized_category, normalized_content_id, grade = (
            self._equip_target(user_id, category, slot, content_id, grade_id)
        )
        snapshot, cultivation, slots = await self._equip_slots(
            normalized_user_id, normalized_category, slot
        )
        replaced = self._equip_replaced(
            normalized_category, normalized_content_id, grade.grade_id, slots, slot
        )
        slots[slot - 1] = {
            "编号": normalized_content_id,
            "品级": grade.grade_id,
        }
        cultivation[normalized_category] = slots
        content_name, reserve_operation = await self._equip_source(
            normalized_user_id, normalized_category, normalized_content_id, grade.grade_id
        )
        replaced_id, replaced_grade_id = self._equip_replaced_ids(replaced)
        return CharacterEquipPlan(
            normalized_category,
            slot,
            normalized_content_id,
            content_name,
            grade.grade_id,
            replaced_id,
            replaced_grade_id,
            StateMutation(
                normalized_user_id,
                "cultivation",
                "main",
                cultivation,
                snapshot.version,
            ),
            reserve_operation,
        )

    def assembly_limits(self) -> dict[str, int]:
        """公开工具的槽位上限；人物和器律上限均来自现有规则。"""
        self._require_initialized()
        limits = dict(self._role_rule["修行槽位"])
        maximum = self._forging.status().weapon_maximum_level
        limits["器律"] = self._forging.weapon_stage(maximum).open_law_slots
        return limits

    async def plan_assembly(
        self, user_id: str,
        build: Mapping[str, Sequence[Mapping[str, str] | None]],
        *, retain_replaced: bool = False,
    ) -> CharacterAssemblyPlan:
        """整套计划只校验最终构筑；保持槽位不重复消耗，所有写入一次提交。"""
        from .assembly import plan_assembly

        self._require_initialized()
        return await plan_assembly(self, user_id, build, retain_replaced=retain_replaced)

    def _equip_target(
        self, user_id: str, category: str, slot: int, content_id: str, grade_id: str
    ) -> tuple[str, str, str, AssetGrade]:
        """入参校验：编号、类别、槽位，并把实体记录与品级取出来。

        实体记录与品级放在同一个 `try` 里，报错统一转成修行错误——这一段别拆开。
        """

        normalized_user_id = _required_user_id(user_id)
        normalized_category = str(category or "").strip()
        if normalized_category not in {"功法", "真意", "气机"}:
            raise CharacterCultivationError("人物只能装配功法、真意或气机")
        if isinstance(slot, bool) or not isinstance(slot, int) or slot < 1:
            raise CharacterCultivationError("修行槽位必须是正整数")
        normalized_content_id = str(content_id or "").strip()
        if not normalized_content_id:
            raise CharacterCultivationError("修行编号不能为空")
        try:
            record = self._data.entity_record(
                normalized_category, normalized_content_id
            )
            if record.number_category != normalized_category:
                raise CharacterCultivationError("修行编号类别不匹配")
            grade = self._asset.grade(grade_id)
        except (AssetStateError, JsonDataError, ValueError) as exc:
            raise CharacterCultivationError(str(exc)) from exc
        return normalized_user_id, normalized_category, normalized_content_id, grade

    async def _equip_slots(self, user_id: str, category: str, slot: int) -> tuple[StateSnapshot, dict[str, object], list[object | None]]:
        """读修行快照并取出该类别的槽位；顺手校验槽位号在范围内。"""

        snapshot = await self._database.get(
            StateAddress(user_id, "cultivation", "main")
        )
        if snapshot is None:
            raise CharacterStateError("人物缺少修行槽状态")
        cultivation = dict(_state_mapping(snapshot.value, "cultivation/main"))
        slots = list(_state_slots(cultivation.get(category), category))
        if slot > len(slots):
            raise CharacterCultivationError(f"{category}槽位只有{len(slots)}个")
        return snapshot, cultivation, slots

    def _equip_replaced(
        self, category: str, content_id: str, grade_id: str, slots: list, slot: int
    ) -> object | None:
        """同一个内容不能占两个槽，也不能重复装进同一个槽；返回被替换的那个槽。"""

        for equipped_slot, raw in enumerate(slots, start=1):
            if raw is None or equipped_slot == slot:
                continue
            equipped = _state_mapping(raw, f"{category}槽[{equipped_slot}]")
            if _state_text(equipped.get("编号"), f"{category}槽.编号") == content_id:
                raise CharacterCultivationError(
                    f"该{category}已装配在{equipped_slot}号槽"
                )
        replaced = slots[slot - 1]
        if replaced is not None:
            replaced_value = _state_mapping(replaced, "原修行槽")
            if (
                _state_text(replaced_value.get("编号"), "原修行槽.编号") == content_id
                and _state_text(replaced_value.get("品级"), "原修行槽.品级") == grade_id
            ):
                raise CharacterCultivationError("该槽位已经装配相同内容")
        return replaced

    async def _equip_source(
        self, user_id: str, category: str, content_id: str, grade_id: str
    ) -> tuple[str, StateMutation | None]:
        """内容从哪来：功法查道藏所有权；真意与气机扣一份储备。"""

        try:
            if category == "功法":
                ownership = await self._asset.cultivation_ownership(
                    user_id, category, content_id, grade_id
                )
                return ownership.name, None
            reserve = await self._asset.plan_cultivation_reserve_change(
                user_id,
                category=category,
                content_id=content_id,
                grade_id=grade_id,
                quantity_delta=-1,
            )
            return reserve.stack.name, reserve.operation
        except (AssetStateError, ValueError) as exc:
            raise CharacterCultivationError(str(exc)) from exc

    def _equip_replaced_ids(self, replaced: object) -> tuple[str, str]:
        """被替换槽位的编号与品级；空槽给空串。"""

        if replaced is None:
            return "", ""
        value = _state_mapping(replaced, "原修行槽")
        return (
            _state_text(value.get("编号"), "原修行槽.编号"),
            _state_text(value.get("品级"), "原修行槽.品级"),
        )

    async def plan_spirit_stone_change(
        self, user_id: str, *, delta: int, contribution_delta: int = 0
    ) -> CharacterSpiritStonePlan:
        """生成灵石余额变更，并可在同一角色状态中增加宗门贡献。"""

        self._require_initialized()
        normalized_user_id = _required_user_id(user_id)
        stone_delta = _request_int(delta, "灵石变化")
        gained_contribution = _nonnegative_request_int(
            contribution_delta, "宗门贡献变化"
        )
        if stone_delta == 0:
            raise CharacterCultivationError("灵石变化不能为零")
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "character", "main")
        )
        if snapshot is None:
            raise CharacterNotFoundError("尚未创建人物")
        character = dict(_state_mapping(snapshot.value, "character/main"))
        before = await self._asset.spirit_stone_balance(normalized_user_id)
        after = before + stone_delta
        if after < 0:
            raise CharacterCultivationError(
                f"灵石不足：现有{before}，需要{-stone_delta}"
            )
        stone_plan = await self._asset.plan_spirit_stone_change(
            normalized_user_id, stone_delta
        )
        if gained_contribution:
            character["宗门贡献"] = (
                _state_nonnegative_int(character.get("宗门贡献", 0), "人物.宗门贡献")
                + gained_contribution
            )
        return CharacterSpiritStonePlan(
            before,
            after,
            stone_delta,
            (
                StateMutation(
                    normalized_user_id,
                    "character",
                    "main",
                    character,
                    snapshot.version,
                ),
            )
            + stone_plan.operations,
        )

    async def plan_contribution_change(
        self, user_id: str, *, delta: int
    ) -> CharacterContributionPlan:
        """生成个人宗门贡献变更；贡献随角色保存，不属于宗门状态。"""

        self._require_initialized()
        normalized_user_id = _required_user_id(user_id)
        contribution_delta = _nonnegative_request_int(delta, "宗门贡献变化")
        if contribution_delta == 0:
            raise CharacterCultivationError("宗门贡献变化不能为零")
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "character", "main")
        )
        if snapshot is None:
            raise CharacterNotFoundError("尚未创建人物")
        character = dict(_state_mapping(snapshot.value, "character/main"))
        before = _state_nonnegative_int(character.get("宗门贡献", 0), "人物.宗门贡献")
        after = before + contribution_delta
        character["宗门贡献"] = after
        return CharacterContributionPlan(
            before,
            after,
            contribution_delta,
            StateMutation(
                normalized_user_id,
                "character",
                "main",
                character,
                snapshot.version,
            ),
        )

    async def plan_technique_grade_sync(
        self,
        user_id: str,
        upgrades: Sequence[tuple[str, str]],
    ) -> CharacterTechniqueUpgradePlan:
        """把已装配功法同步到本次取得的最高品级。"""

        self._require_initialized()
        normalized_user_id = _required_user_id(user_id)
        highest: dict[str, str] = {}
        for content_id, grade_id in upgrades:
            normalized_content_id = str(content_id or "").strip()
            if not normalized_content_id:
                raise CharacterCultivationError("升品功法编号不能为空")
            record = self._data.entity_record("功法", normalized_content_id)
            if record.number_category != "功法":
                raise CharacterCultivationError("升品功法编号类别不匹配")
            grade = self._asset.grade(grade_id)
            previous = highest.get(normalized_content_id)
            if previous is None or grade.order > self._asset.grade(previous).order:
                highest[normalized_content_id] = grade.grade_id
        if not highest:
            return CharacterTechniqueUpgradePlan(0, None)

        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "cultivation", "main")
        )
        if snapshot is None:
            raise CharacterStateError("人物缺少修行槽状态")
        cultivation = dict(_state_mapping(snapshot.value, "cultivation/main"))
        slots = list(_state_slots(cultivation.get("功法"), "功法"))
        updated = 0
        for index, raw in enumerate(slots):
            if raw is None:
                continue
            entry = dict(_state_mapping(raw, f"功法槽[{index + 1}]"))
            if isinstance(entry.get("藏经阁借阅"), Mapping):
                continue
            content_id = _state_text(entry.get("编号"), "功法槽.编号")
            target_grade_id = highest.get(content_id)
            if target_grade_id is None:
                continue
            current_grade = self._asset.grade(
                _state_text(entry.get("品级"), "功法槽.品级")
            )
            target_grade = self._asset.grade(target_grade_id)
            if target_grade.order <= current_grade.order:
                continue
            entry["品级"] = target_grade.grade_id
            slots[index] = entry
            updated += 1
        if not updated:
            return CharacterTechniqueUpgradePlan(0, None)
        cultivation["功法"] = slots
        return CharacterTechniqueUpgradePlan(
            updated,
            StateMutation(
                normalized_user_id,
                "cultivation",
                "main",
                cultivation,
                snapshot.version,
            ),
        )

    async def breakthrough_preview(self, user_id: str) -> CharacterBreakthroughPreview:
        """只读：当前境界、下一境界与「能不能突破」。

        口径与 `plan_breakthrough` 的校验逐条一致（满级 → 有下一境界 → 该境界还没突破过），
        不能突破时给出原因，供卡片照直说。
        """

        self._require_initialized()
        normalized_user_id = _required_user_id(user_id)
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "character", "main")
        )
        if snapshot is None:
            raise CharacterNotFoundError("尚未创建人物")
        character = dict(_state_mapping(snapshot.value, "character/main"))
        realm_id = _state_text(character.get("境界"), "人物.境界")
        realm = self._growth.realm(realm_id)
        level = _state_positive_int(character.get("等级"), "人物.等级")
        if level != realm.maximum_level:
            return CharacterBreakthroughPreview(
                realm_id=realm_id,
                realm_name=realm.name,
                level=level,
                maximum_level=realm.maximum_level,
                reason=f"达到{realm.maximum_level}级后才能突破{realm.name}",
            )
        try:
            next_realm = self._growth.next_realm(realm_id)
        except GrowthError:
            return CharacterBreakthroughPreview(
                realm_id=realm_id,
                realm_name=realm.name,
                level=level,
                maximum_level=realm.maximum_level,
                reason="已至当前修行尽头",
            )
        records = [
            dict(record)
            for record in _state_records(character.get("突破记录"), "人物.突破记录")
        ]
        if any(record.get("目标境界") == next_realm.realm_id for record in records):
            return CharacterBreakthroughPreview(
                realm_id=realm_id,
                realm_name=realm.name,
                level=level,
                maximum_level=realm.maximum_level,
                next_realm_id=next_realm.realm_id,
                next_realm_name=next_realm.name,
                reason="该境界已经完成突破",
            )
        return CharacterBreakthroughPreview(
            realm_id=realm_id,
            realm_name=realm.name,
            level=level,
            maximum_level=realm.maximum_level,
            next_realm_id=next_realm.realm_id,
            next_realm_name=next_realm.name,
            can_breakthrough=True,
        )

    async def plan_breakthrough(
        self,
        user_id: str,
        *,
        medicine_id: str,
        permanent_attribute_ratio: float = 0.0,
        permanent_attribute_multiplier: float = 1.0,
    ) -> CharacterBreakthroughPlan:
        """校验突破丹并结算人物境界、永久属性和积压经验。"""

        self._require_initialized()
        normalized_user_id = _required_user_id(user_id)
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "character", "main")
        )
        if snapshot is None:
            raise CharacterNotFoundError("尚未创建人物")
        character = dict(_state_mapping(snapshot.value, "character/main"))
        current_realm_id = _state_text(character.get("境界"), "人物.境界")
        current_realm = self._growth.realm(current_realm_id)
        level_before = _state_positive_int(character.get("等级"), "人物.等级")
        if level_before != current_realm.maximum_level:
            raise CharacterCultivationError(
                f"达到{current_realm.maximum_level}级后才能突破{current_realm.name}"
            )
        next_realm = self._growth.next_realm(current_realm_id)
        medicine, permanent = self._breakthrough_medicine(
            medicine_id, next_realm.realm_id
        )
        if (
            isinstance(permanent_attribute_ratio, bool)
            or not isinstance(permanent_attribute_ratio, (int, float))
            or permanent_attribute_ratio < 0
        ):
            raise CharacterCultivationError("突破永久属性倍率不能为负数")
        if permanent and permanent_attribute_ratio:
            permanent = {
                key: value + max(1, math.ceil(float(value) * permanent_attribute_ratio))
                for key, value in permanent.items()
            }
        if permanent and permanent_attribute_multiplier != 1.0:
            permanent = {
                key: float(value) * permanent_attribute_multiplier
                for key, value in permanent.items()
            }
        records = [
            dict(record)
            for record in _state_records(character.get("突破记录"), "人物.突破记录")
        ]
        if any(record.get("目标境界") == next_realm.realm_id for record in records):
            raise CharacterCultivationError("该境界已经完成突破")
        attributes = _add_numbers(
            _state_mapping(character.get("属性"), "人物.属性"), permanent
        )
        bonuses = _add_numbers(
            _state_mapping(character.get("属性加成"), "人物.属性加成"), permanent
        )
        advance = self._growth.advance_cultivator(
            level=level_before,
            experience=_state_nonnegative_int(character.get("经验"), "人物.经验"),
            realm_id=next_realm.realm_id,
            gained=0,
        )
        attributes = _add_numbers(
            attributes,
            self._growth.cultivator_attribute_growth(advance.levels_gained),
        )
        records.append(
            {
                "目标境界": next_realm.realm_id,
                "突破丹": str(medicine.get("编号")),
                "补正来源丹药": None,
            }
        )
        character.update(
            {
                "境界": next_realm.realm_id,
                "等级": advance.level_after,
                "经验": advance.experience_after,
                "属性": attributes,
                "属性加成": bonuses,
                "突破记录": records,
            }
        )
        # 意境道行：这次突破把阶上限抬上去了才发。**第 1 阶没有自己的抬升事件**（开局上限就是 1），
        # 所以第一次抬升（1 → 2）时连它的价一起补——不补，九阶的价只发到 111，而升满九阶要 112，
        # 最后一阶永远差一点、够不到（二十境界九阶，八次抬升发满九阶的价）。
        cap_before = _yijing_tier_cap(
            _realm_order(self._data.entity("境界", current_realm_id).get("等级下限"))
        )
        cap_after = _yijing_tier_cap(
            _realm_order(self._data.entity("境界", next_realm.realm_id).get("等级下限"))
        )
        if cap_after > cap_before:
            cell = dict(character.get("意境") or {})
            grant = _yijing_tier_cost(cap_after)
            if cap_before == 1:
                grant += _yijing_tier_cost(1)
            cell["道行"] = int(cell.get("道行") or 0) + grant
            cell.setdefault("编号", "")
            cell.setdefault("阶", 0)
            character["意境"] = cell
        return CharacterBreakthroughPlan(
            current_realm_id,
            next_realm.realm_id,
            next_realm.name,
            str(medicine.get("编号")),
            tuple(sorted(permanent.items())),
            StateMutation(
                normalized_user_id,
                "character",
                "main",
                character,
                snapshot.version,
            ),
        )

    async def plan_weapon_law(
        self, user_id: str, *, law_id: str, slot: int
    ) -> CharacterLawPlan:
        """生成玩家本命武器指定孔位的器律覆炼。"""

        self._require_initialized()
        normalized_user_id = _required_user_id(user_id)
        if isinstance(slot, bool) or not isinstance(slot, int) or slot < 1:
            raise CharacterCultivationError("器律孔位必须是正整数")
        law = self._data.entity("器律", str(law_id or "").strip())
        law_name = str(law.get("名称") or "").strip()
        law_stage = str(law.get("器阶") or "").strip()
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "weapon", "main")
        )
        if snapshot is None:
            raise CharacterStateError("人物缺少本命武器状态")
        weapon = dict(_state_mapping(snapshot.value, "weapon/main"))
        level = _state_positive_int(weapon.get("等级"), "本命武器.等级")
        open_slots = self._forging.weapon_stage(level).open_law_slots
        if slot > open_slots:
            raise CharacterCultivationError(f"当前本命武器只开放{open_slots}个器律孔")
        if not self._forging.law_allowed(level, law_stage):
            raise CharacterCultivationError("该器律的器阶高于当前本命武器")
        laws = list(_state_law_slots(weapon.get("器律"), "本命武器.器律"))
        laws.extend([None] * (slot - len(laws)))
        replaced = laws[slot - 1]
        laws[slot - 1] = str(law.get("编号") or law_id)
        weapon["器律"] = laws
        return CharacterLawPlan(
            slot,
            str(law.get("编号") or law_id),
            law_name,
            "" if replaced is None else replaced,
            StateMutation(
                normalized_user_id,
                "weapon",
                "main",
                weapon,
                snapshot.version,
            ),
        )

    async def plan_breakthrough_correction(
        self, user_id: str, *, source_medicine_id: str
    ) -> CharacterBreakthroughCorrectionPlan:
        """为尚未补正的人物纯突破节点写入一项永久属性。"""

        self._require_initialized()
        normalized_user_id = _required_user_id(user_id)
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "character", "main")
        )
        if snapshot is None:
            raise CharacterNotFoundError("尚未创建人物")
        character = dict(_state_mapping(snapshot.value, "character/main"))
        records = [
            dict(record)
            for record in _state_records(character.get("突破记录"), "人物.突破记录")
        ]
        realm_id = _state_text(character.get("境界"), "人物.境界")
        record = next((row for row in records if row.get("目标境界") == realm_id), None)
        if record is None:
            raise CharacterCultivationError("当前境界没有可补正的突破节点")
        if record.get("补正来源丹药"):
            raise CharacterCultivationError("当前突破节点已经补正")
        _, original_permanent = self._breakthrough_medicine(
            _state_text(record.get("突破丹"), "突破记录.突破丹"), realm_id
        )
        if original_permanent:
            raise CharacterCultivationError("只有纯突破节点可以补正")
        _, permanent = self._breakthrough_medicine(source_medicine_id, realm_id)
        if len(permanent) != 1:
            raise CharacterCultivationError("补正丹必须只提供一项永久属性")
        attributes = _add_numbers(
            _state_mapping(character.get("属性"), "人物.属性"), permanent
        )
        bonuses = _add_numbers(
            _state_mapping(character.get("属性加成"), "人物.属性加成"), permanent
        )
        record["补正来源丹药"] = str(source_medicine_id).strip()
        character["属性"] = attributes
        character["属性加成"] = bonuses
        character["突破记录"] = records
        return CharacterBreakthroughCorrectionPlan(
            realm_id,
            str(source_medicine_id).strip(),
            tuple((str(key), value) for key, value in permanent.items()),
            StateMutation(
                normalized_user_id, "character", "main", character, snapshot.version
            ),
        )

    async def plan_gender_change(self, user_id: str) -> CharacterGenderPlan:
        """只把玩家性别切换到另一项正式性别。"""

        self._require_initialized()
        normalized_user_id = _required_user_id(user_id)
        snapshot = await self._database.get(
            StateAddress(normalized_user_id, "character", "main")
        )
        if snapshot is None:
            raise CharacterNotFoundError("尚未创建人物")
        character = dict(_state_mapping(snapshot.value, "character/main"))
        before = _state_text(character.get("性别"), "人物.性别")
        choices = tuple(value for value in self._gender_values if value != before)
        if len(choices) != 1:
            raise CharacterCultivationError("当前性别定义不支持两仪易形")
        character["性别"] = choices[0]
        return CharacterGenderPlan(
            before,
            choices[0],
            StateMutation(
                normalized_user_id, "character", "main", character, snapshot.version
            ),
        )

    async def _growth_snapshots(self, user_id: str) -> tuple[StateSnapshot, StateSnapshot]:
        snapshots = await self._database.get_many(
            (
                StateAddress(user_id, "character", "main"),
                StateAddress(user_id, "weapon", "main"),
            )
        )
        by_type = {snapshot.address.state_type: snapshot for snapshot in snapshots}
        if "character" not in by_type:
            raise CharacterNotFoundError("尚未创建人物")
        if "weapon" not in by_type:
            raise CharacterStateError("人物缺少本命武器状态")
        return by_type["character"], by_type["weapon"]

    def _breakthrough_medicine(
        self, medicine_id: str, target_realm_id: str
    ) -> tuple[Mapping[str, object], Mapping[str, int | float]]:
        normalized = str(medicine_id or "").strip()
        medicine = self._data.entity("丹药", normalized)
        if self._data.entity_record("丹药", normalized).number_category != "丹药":
            raise CharacterCultivationError("只能使用突破丹突破境界")
        effect = _mapping(medicine.get("使用效果"), "突破丹.使用效果")
        if (
            effect.get("类型") != "境界突破"
            or effect.get("目标境界") != target_realm_id
        ):
            raise CharacterCultivationError("该突破丹不对应下一境界")
        permanent = _mapping(effect.get("永久属性", {}), "突破丹.永久属性")
        return medicine, {
            str(name): _number(raw, f"突破丹.永久属性.{name}")
            for name, raw in permanent.items()
        }

    def _validate_static_rules(self) -> None:
        creation = _mapping(self._role_rule.get("创建"), "人物.json.创建")
        name_rule = _mapping(creation.get("姓名"), "人物.json.创建.姓名")
        minimum = _positive_int(name_rule.get("最短长度"), "姓名最短长度")
        maximum = _positive_int(name_rule.get("最长长度"), "姓名最长长度")
        if minimum > maximum:
            raise JsonDataError("人物.json.创建.姓名长度范围无效")
        pattern = str(name_rule.get("匹配") or "")
        if not pattern:
            raise JsonDataError("人物.json.创建.姓名缺少匹配规则")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise JsonDataError("人物.json.创建.姓名匹配规则无效") from exc
        self._data.entity("境界", str(creation.get("初始境界") or ""))
        _mapping(creation.get("初始出生地"), "人物.json.创建.初始出生地")
        _mapping(creation.get("初始本命武器"), "人物.json.创建.初始本命武器")
        _initial_items(self._role_rule)
        for dataset, item_id, grade, _ in _initial_items(self._role_rule):
            self._data.entity(dataset, item_id)
            if grade not in self._grade_values:
                raise JsonDataError(f"人物初始物品使用未知品级：{item_id} -> {grade}")
        if not self._attributes:
            raise JsonDataError("战斗定义.属性不能为空")

    def _cultivation_profile(
        self, cultivation: Mapping[str, object]
    ) -> tuple[tuple[tuple[str, int], ...], tuple[EquippedContent, ...]]:
        slot_counts: list[tuple[str, int]] = []
        equipped: list[EquippedContent] = []
        for category in ("功法", "真意", "气机"):
            raw_slots = cultivation.get(category)
            if not isinstance(raw_slots, Sequence) or isinstance(
                raw_slots, (str, bytes)
            ):
                raise CharacterStateError(f"修行槽.{category}必须是数组")
            slot_counts.append((category, len(raw_slots)))
            for slot, raw in enumerate(raw_slots, start=1):
                if raw is None:
                    continue
                entry = _state_mapping(raw, f"修行槽.{category}[{slot}]")
                content_id = _state_text(
                    entry.get("编号"), f"修行槽.{category}[{slot}].编号"
                )
                grade = _state_text(
                    entry.get("品级"), f"修行槽.{category}[{slot}].品级"
                )
                name = _state_text(
                    self._data.entity(category, content_id).get("名称"),
                    f"{category} {content_id}.名称",
                )
                equipped.append(
                    EquippedContent(
                        category,
                        slot,
                        content_id,
                        name,
                        grade,
                        self._asset.grade(grade).name,
                    )
                )
        return tuple(slot_counts), tuple(equipped)

    def _weapon_profile(self, weapon: Mapping[str, object]) -> WeaponProfile:
        level = _state_positive_int(weapon.get("等级"), "本命武器.等级")
        stage = self._forging.weapon_stage(level)
        stage_name = stage.name
        stored_stage = _state_text(weapon.get("器阶"), "本命武器.器阶")
        if stored_stage != stage_name:
            raise CharacterStateError(
                f"本命武器器阶与等级不符：{stored_stage} != {stage_name}"
            )
        open_slots = stage.open_law_slots
        raw_laws = weapon.get("器律")
        if not isinstance(raw_laws, Sequence) or isinstance(raw_laws, (str, bytes)):
            raise CharacterStateError("本命武器.器律必须是编号数组")
        if len(raw_laws) > open_slots:
            raise CharacterStateError("本命武器已装器律超过当前开放孔数")
        equipped_laws: list[EquippedContent] = []
        for slot, raw in enumerate(raw_laws, start=1):
            if raw is None:
                continue
            content_id = _state_text(raw, f"本命武器.器律[{slot}]")
            name = _state_text(
                self._data.entity("器律", content_id).get("名称"),
                f"器律 {content_id}.名称",
            )
            equipped_laws.append(EquippedContent("器律", slot, content_id, name))
        return WeaponProfile(
            name=_state_text(weapon.get("名称"), "本命武器.名称"),
            level=level,
            experience=_state_nonnegative_int(weapon.get("经验"), "本命武器.经验"),
            attack=self._forging.weapon_attack(level),
            stage=stage_name,
            open_law_slots=open_slots,
            equipped_laws=tuple(equipped_laws),
        )

    def _validate_command(self, command: CharacterCreateCommand) -> None:
        if not command.user_id.strip() or not command.request_id.strip():
            raise CharacterInputError("身份和请求编号不能为空")
        if not command.birth_xy or len(command.birth_xy) != 2:
            raise CharacterInputError("出生地坐标无效")
        name = command.name.strip()
        if name != command.name:
            raise CharacterInputError("姓名不能带首尾空白")
        creation = _mapping(self._role_rule.get("创建"), "人物.json.创建")
        name_rule = _mapping(creation.get("姓名"), "人物.json.创建.姓名")
        minimum = int(name_rule["最短长度"])
        maximum = int(name_rule["最长长度"])
        if not minimum <= len(name) <= maximum:
            raise CharacterInputError(
                f"姓名长度必须在 {minimum} 到 {maximum} 个字符之间"
            )
        pattern = str(name_rule["匹配"])
        if re.fullmatch(pattern, name) is None:
            raise CharacterInputError("姓名只能使用中文、字母或数字")
        # 名字不许"长得像指称"：像了就会和编号撞车（查看 100005 到底是人还是丹药）。
        # 编号是 6 位（项目规范：2 位前缀 + 4 位流水），所以名字里出现 6 位以上连续数字即算 id 化；
        # 中文数字混排（如"晓楠3号"）不算。
        name_id_width = 6
        if name.isdigit() or re.search(rf"\d{{{name_id_width},}}", name):
            raise CharacterInputError("姓名不能写成编号或物品指称的样子")
        # 再让唯一解析口兜一层：能解析成指称、且带品级/灵宝/扩展位的名字同样拒掉。
        try:
            parsed = parse_item_ref(name)
        except ItemRefError:
            parsed = None
        if parsed is not None and (parsed.grade or parsed.treasure or parsed.extra):
            raise CharacterInputError("姓名不能写成编号或物品指称的样子")
        if command.gender not in self._gender_values:
            choices = "或".join(self._gender_values)
            raise CharacterInputError(f"性别只能填写{choices}")
        if command.race and command.race not in self._races:
            raise CharacterInputError(f"种族只能填写登记的种族：{command.race}")

    def _character_state(
        self, command: CharacterCreateCommand, realm_id: str
    ) -> dict[str, object]:
        overrides = _mapping(self._role_rule.get("属性覆盖"), "人物.json.属性覆盖")
        unknown = set(overrides) - self._coverable
        if unknown:
            raise JsonDataError(
                "人物.json.属性覆盖只能覆盖成长属性：" + "、".join(sorted(unknown))
            )
        attributes: dict[str, object] = {
            name: _mapping(raw, f"属性.{name}").get("默认值")
            for name, raw in self._attributes.items()
        }
        attributes.update(materialize(overrides))
        blood = _number(attributes.get("血气上限"), "血气上限")
        spirit = _number(attributes.get("精神上限"), "精神上限")
        soul = _number(attributes.get("神魂上限"), "神魂上限")
        source = random.Random(f"人物五行:{command.user_id}")
        five_elements = generate_five_elements(self._five_element_rules, source)
        from datetime import datetime, timezone

        return {
            "姓名": command.name,
            #: 诞生时间戳：年龄展示的锚点，只在创建时写一次，之后不再改动。
            "诞生": datetime.now(timezone.utc).isoformat(),
            "性别": command.gender,
            "种族": command.race or self._initial_race,
            "角色类型": str(self._role_rule.get("角色类型") or "修士"),
            "境界": realm_id,
            "等级": _positive_int(self._role_rule.get("等级"), "人物初始等级"),
            "经验": int(self._role_rule.get("经验") or 0),
            "宗门贡献": 0,
            "属性": attributes,
            "属性加成": {},
            "五行根性": five_elements,
            "资源": {"血气": blood, "精神": spirit, "神魂": soul, "护盾": 0},
            "自动用药": self._medicine_default,
            "待战战丹": self._role_rule.get("待战战丹"),
            "突破记录": [],
        }

    def _cultivation_state(self) -> dict[str, object]:
        slots = _mapping(self._role_rule.get("修行槽位"), "人物.json.修行槽位")
        return {
            category: [None] * _positive_int(slots.get(category), f"{category}槽位")
            for category in ("功法", "真意", "气机")
        }

    def _weapon_state(self, creation: Mapping[str, object]) -> dict[str, object]:
        weapon_creation = _mapping(
            creation.get("初始本命武器"), "人物.json.创建.初始本命武器"
        )
        level = self._forging.initial_weapon_level()
        stage = self._forging.weapon_stage(level)
        return {
            "名称": str(weapon_creation.get("名称") or "无名器胚"),
            "等级": level,
            "经验": 0,
            "器阶": stage.name,
            "器律": [],
        }

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("角色核心微服务尚未初始化")


def _state_mapping(value: object, label: str) -> Mapping[str, object]:
    return mapping(value, label, error=CharacterStateError)


def _clamp_life_resources(
    resources: Mapping[str, float], attributes: Mapping[str, float]
) -> dict[str, float]:
    """寿元将尽后属性上限下降，当前资源不能高于新上限。"""

    caps = {"血气": "血气上限", "神魂": "神魂上限", "精神": "精神上限"}
    result = dict(resources)
    for resource, attribute in caps.items():
        if resource in result and attribute in attributes:
            result[resource] = min(float(result[resource]), float(attributes[attribute]))
    return result


def _clamp_age(lifetime: int, lifespan: int) -> tuple[int, bool]:
    """把「一生累计岁数」钳进「寿元上限」——**边界只在这里处理**。

    两个方向都要自洽：
    · 累计 ≥ 上限（努力不够，或上限被换种族/换境界压低）：年龄 = 上限，标志为「已满」；
    · 上限 ≥ 累计（换到长寿种族、突破抬高上限）：**把之前被上限盖住的年岁放回来**，年龄 = 累计。

    所以「超过上限」永远不表现为越界数字，而是表现为「年龄 = 上限」；上限一变，年龄自动重算。
    """

    if lifespan <= 0:
        return 0, True
    return min(lifetime, lifespan), lifetime >= lifespan

def _state_text(value: object, label: str) -> str:
    return strict_text(value, label, error=CharacterStateError)


def _prepared_battle_medicine(
    value: object, label: str
) -> PreparedBattleMedicine | None:
    if value is None:
        return None
    row = _state_mapping(value, label)
    if set(row) != {"编号", "品级"}:
        raise CharacterStateError(f"{label}字段不完整")
    return PreparedBattleMedicine(
        _state_text(row.get("编号"), f"{label}.编号"),
        _state_text(row.get("品级"), f"{label}.品级"),
    )


def _prepared_battle_value(
    value: PreparedBattleMedicine | None,
) -> dict[str, str] | None:
    if value is None:
        return None
    return {"编号": value.medicine_id, "品级": value.grade_id}


def _medicine_resource(value: object) -> str:
    result = str(value or "").strip()
    if result not in {"血气", "精神"}:
        raise CharacterCultivationError("恢复资源只能是血气或精神")
    return result


def _positive_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise CharacterCultivationError(f"{label}必须是正数")
    return float(value)


def _clean_number(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 4)


def _state_positive_int(value: object, label: str) -> int:
    return positive_int(value, label, error=CharacterStateError)


def _state_nonnegative_int(value: object, label: str) -> int:
    return nonnegative_int(value, label, error=CharacterStateError)


def _nonnegative_request_int(value: object, label: str) -> int:
    return nonnegative_int(value, label, error=CharacterCultivationError)


def _request_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CharacterCultivationError(f"{label}必须是整数")
    return value




def _required_user_id(value: object) -> str:
    result = str(value or "").strip()
    if not result:
        raise CharacterCultivationError("user_id不能为空")
    return result


def _state_slots(value: object, category: str) -> tuple[object | None, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CharacterStateError(f"修行槽.{category}必须是数组")
    return tuple(value)


def _state_law_slots(value: object, label: str) -> tuple[str | None, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CharacterStateError(f"{label}必须是数组")
    result: list[str | None] = []
    for index, raw in enumerate(value, start=1):
        result.append(None if raw is None else _state_text(raw, f"{label}[{index}]"))
    return tuple(result)


def _state_records(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CharacterStateError(f"{label}必须是数组")
    return tuple(_state_mapping(raw, f"{label}[]") for raw in value)


def _add_numbers(
    source: Mapping[str, object], additions: Mapping[str, int | float]
) -> dict[str, int | float]:
    result: dict[str, int | float] = {}
    for name, raw in source.items():
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise CharacterStateError(f"属性.{name}必须是数值")
        result[str(name)] = raw
    for name, raw in additions.items():
        before = result.get(str(name), 0)
        value = float(before) + float(raw)
        result[str(name)] = int(value) if value.is_integer() else round(value, 4)
    return result


def _subtract_numbers(
    source: Mapping[str, object], subtractions: Mapping[str, int | float]
) -> dict[str, int | float]:
    """从生效属性里扣掉一份来源；结果不落到负数。"""

    result: dict[str, int | float] = {
        str(name): raw for name, raw in source.items() if isinstance(raw, (int, float)) and not isinstance(raw, bool)
    }
    for name, raw in subtractions.items():
        before = float(result.get(str(name), 0.0))
        value = max(0.0, before - float(raw))
        result[str(name)] = int(value) if value.is_integer() else round(value, 4)
    return result


def _state_bool(value: object, label: str) -> bool:
    return boolean(value, label, error=CharacterStateError)


def _user_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(str(value or "").strip() for value in values)
    if any(not value for value in normalized):
        raise ValueError("user_id不能为空")
    if normalized != values:
        raise ValueError("user_id不能带首尾空白")
    if len(normalized) != len(set(normalized)):
        raise ValueError("user_id不能重复")
    return normalized


def _state_numbers(value: object, label: str) -> tuple[tuple[str, int | float], ...]:
    fields = _state_mapping(value, label)
    result: list[tuple[str, int | float]] = []
    for name, raw in fields.items():
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise CharacterStateError(f"{label}.{name}必须是数值")
        result.append((str(name), raw))
    return tuple(result)


def _state_five_elements(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise CharacterStateError("人物.五行根性必须是对象")
    expected = {"木", "火", "土", "金", "水"}
    if set(value) != expected:
        raise CharacterStateError("人物.五行根性必须完整包含木火土金水")
    result = {str(key): float(raw) for key, raw in value.items()}
    if (
        any(raw < 0 or raw > 100 for raw in result.values())
        or abs(sum(result.values()) - 100) > 1e-6
    ):
        raise CharacterStateError("人物.五行根性每项须在0到100且总和为100")
    return result


def _yijing_tier_cost(tier: int) -> int:
    """升到第 N 阶要多少道行：一境界一阶那条线用的就是它。"""

    return (0, 1, 2, 4, 6, 9, 13, 18, 25, 34)[tier]


def _realm_order(lower_level: object) -> int:
    """境界序号：每境界五级，用现成的等级下限推，不新增字段（1~20）。"""

    return (_positive_int(lower_level, "境界.等级下限") - 1) // 5 + 1


def _yijing_tier_cap(realm_order: int) -> int:
    """该境界允许的意境阶上限：二十个境界对应九阶，第 20 境界正好九阶。"""

    return max(1, min(9, -(-realm_order * 9 // 20)))


def _state_redeemed(value: object) -> tuple[str, ...]:
    """已兑换的码：一串六位编号，不许重复；没有这一格就是还没兑过。"""

    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise CharacterStateError("人物.已兑换码必须是编号清单")
    items = tuple(str(item) for item in value)
    for item in items:
        if len(item) != 6 or not item.isdigit():
            raise CharacterStateError("人物.已兑换码每一项都必须是六位数字")
    if len(set(items)) != len(items):
        raise CharacterStateError("人物.已兑换码不许重复")
    return items


def _check_yijing_id(content_id: str) -> None:
    """意境编号：六位数字，与其它编号实体同一形状。"""

    if len(content_id) != 6 or not content_id.isdigit():
        raise CharacterStateError("人物.意境.编号必须是六位数字")


def _state_yijing(value: object) -> tuple[dict[str, int], int] | None:
    """意境：状态里存「路」（编号 → 阶）与**六路共享**的道行；名称按编号现取。"""

    if value is None:
        return None
    row = _state_mapping(value, "人物.意境")
    if set(row) - {"路", "道行"}:
        raise CharacterStateError("人物.意境只认「路」「道行」")
    paths: dict[str, int] = {}
    raw_paths = row.get("路")
    if raw_paths is not None:
        mapping = _state_mapping(raw_paths, "人物.意境.路")
        for key, raw_tier in mapping.items():
            content_id = str(key)
            _check_yijing_id(content_id)
            if isinstance(raw_tier, bool) or not isinstance(raw_tier, int) or not 1 <= raw_tier <= 9:
                raise CharacterStateError("人物.意境.路.阶必须是1到9的整数（点过的路才有键）")
            paths[content_id] = raw_tier
    points = row.get("道行", 0)
    if isinstance(points, bool) or not isinstance(points, int) or points < 0:
        raise CharacterStateError("人物.意境.道行必须是不小于0的整数")
    return paths, points


def _yijing_profiles(
    data: object, value: object, realm_id: object = None
) -> tuple[YijingProfile, ...]:
    """把状态里的（路 → 阶）补成带名称的意境档案；**同一份道行给每条路**。

    一条都没点过就是空元组（人物面板与装配台整段不显示）。按编号排序，展示顺序稳定。
    """

    state = _state_yijing(value)
    if state is None:
        return ()
    paths, points = state
    if not paths:
        return ()
    cap = yijing_tier_cap_for(data, realm_id)
    profiles: list[YijingProfile] = []
    for content_id in sorted(paths):
        tier = paths[content_id]
        row = data.entity("意境", content_id)
        name = _state_text(row.get("名称"), "意境.名称")
        cost = _yijing_tier_cost(tier + 1) if tier < min(9, cap) else 0
        profiles.append(
            YijingProfile(
                content_id=content_id,
                name=name,
                tier=tier,
                daoxing=points,
                next_cost=cost,
                missing=max(0, cost - points) if cost else 0,
            )
        )
    return tuple(profiles)


def yijing_tier_cap_for(data: object, realm_id: object) -> int:
    """按境界算意境阶上限：给面板与命令共用，避免各处各算一遍。"""

    if not realm_id:
        return 9
    realm = data.entity("境界", str(realm_id))
    return _yijing_tier_cap(_realm_order(realm.get("等级下限")))


def _inventory_summary(
    states: Mapping[tuple[str, str], Mapping[str, object]],
) -> InventorySummary:
    quantities = tuple(
        _state_positive_int(value.get("数量"), f"背包.{state_key}.数量")
        for (state_type, state_key), value in states.items()
        if state_type == "inventory"
    )
    return InventorySummary(len(quantities), sum(quantities))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _number(value: object, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise JsonDataError(f"{label}必须是数值")
    return value


def _request_ratio(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 0 <= value <= 1
    ):
        raise CharacterCultivationError(f"{label}必须在0至1之间")
    return float(value)


def _initial_items(
    role_rule: Mapping[str, object],
) -> tuple[tuple[str, str, str, int], ...]:
    """人物初始物品，每项形如 `(数据集, 编号, 品级, 数量)`。

    数据集由**数据自己声明**：初始物品可以来自任何数据集（现在是丹药），Python 不猜。
    校验与创建共用这一处解析。
    """

    raw_items = role_rule.get("初始物品")
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        raise JsonDataError("人物.json.初始物品必须是字典列表")
    result: list[tuple[str, str, str, int]] = []
    for index, raw in enumerate(raw_items):
        entry = _mapping(raw, f"人物.json.初始物品[{index}]")
        dataset = str(entry.get("数据集") or "").strip()
        item_id = str(entry.get("编号") or "").strip()
        grade = str(entry.get("品级") or "").strip()
        quantity = entry.get("数量")
        if (
            not dataset
            or not item_id
            or not grade
            or isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity < 1
        ):
            raise JsonDataError(f"人物.json.初始物品[{index}]字段无效")
        result.append((dataset, item_id, grade, quantity))
    if len({(dataset, item_id, grade) for dataset, item_id, grade, _ in result}) != len(
        result
    ):
        raise JsonDataError("人物.json.初始物品不能重复同一数据集、编号和品级")
    return tuple(result)


def _in_range(value: int, lower: object, upper: object) -> bool:
    return (
        isinstance(lower, int)
        and not isinstance(lower, bool)
        and isinstance(upper, int)
        and not isinstance(upper, bool)
        and lower <= value <= upper
    )


__all__ = ["CharacterService"]
