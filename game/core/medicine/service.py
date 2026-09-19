"""只解释正式服丹规则和丹药效果，不持有玩家状态。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from game.core.asset import AssetService
from game.core.combat import CombatStatusSpec
from game.core.data import (
    JsonDataError,
    JsonDataService,
    SchemaValidator,
    mapping as _mapping,
    materialize,
    nonempty_text as _text,
)

from .contracts import (
    BattleMedicine,
    MedicineError,
    MedicineStatus,
    RecoveryMedicine,
    RecoveryMedicineStack,
)
from game.core.data import boolean as _bool, number as _number


class MedicineService:
    """统一解释恢复丹、战丹与主动服丹边界。"""

    def __init__(self, data: JsonDataService, asset: AssetService) -> None:
        self._data = data
        self._asset = asset
        self._initialized = False
        self._rules: Mapping[str, object] = {}
        self._recovery: dict[str, Mapping[str, object]] = {}
        self._battle: dict[str, Mapping[str, object]] = {}
        self._special: dict[str, Mapping[str, object]] = {}
        self._medicines: dict[str, Mapping[str, object]] = {}
        self._default_auto = True
        self._threshold = 0.3
        self._selection_strategy = ""
        self._selection_order: tuple[str, ...] = ()
        self._active_guard_rule = ""
        self._setting_guard_rule = ""

    def initialize(self) -> MedicineStatus:
        if self._initialized:
            raise RuntimeError("丹药核心微服务已经初始化")
        if not self._data.status().loaded:
            raise RuntimeError("JSON 数据微服务必须先于丹药核心启动")
        if not self._asset.status().initialized:
            raise RuntimeError("玩家资产核心必须先于丹药核心启动")
        rules = self._data.dataset("服丹规则").get("服丹")
        if not isinstance(rules, Mapping):
            raise JsonDataError("玩法/服丹/规则/服丹.json 必须是对象")
        self._rules = rules
        auto = _mapping(rules.get("自动用药"), "服丹.自动用药")
        threshold_range = _number_range(
            auto.get("阈值范围"), "服丹.自动用药.阈值范围"
        )
        threshold = _number(auto.get("阈值"), "服丹.自动用药.阈值")
        if not threshold_range[0] <= threshold <= threshold_range[1]:
            raise JsonDataError("服丹.自动用药.阈值超出JSON定义范围")
        self._threshold = threshold
        self._default_auto = _bool(auto.get("默认开启"), "服丹.自动用药.默认开启")
        self._selection_strategy = _text(
            auto.get("选药策略"), "服丹.自动用药.选药策略"
        )
        if self._selection_strategy != "缺口优先":
            raise JsonDataError("服丹.自动用药.选药策略目前必须是缺口优先")
        self._selection_order = _strings(
            auto.get("选药排序"), "服丹.自动用药.选药排序"
        )
        if self._selection_order != (
            "最少溢出",
            "最大实际恢复",
            "低品级",
            "编号升序",
        ):
            raise JsonDataError("服丹.自动用药.选药排序不符合正式执行顺序")
        if auto.get("共享库存键") != "user_id":
            raise JsonDataError("服丹.自动用药.共享库存键必须是user_id")
        if auto.get("人物与道侣独立开关") is not True:
            raise JsonDataError("人物与道侣必须使用独立自动用药开关")
        recovery_rules = _mapping(rules.get("恢复丹"), "服丹.恢复丹")
        if recovery_rules.get("允许主动服用") is not True:
            raise JsonDataError("恢复丹必须允许主动服用")
        if recovery_rules.get("允许自动用药") is not True:
            raise JsonDataError("恢复丹必须允许自动用药")
        if recovery_rules.get("满值拒绝") is not True:
            raise JsonDataError("恢复丹必须在资源满值时拒绝服用")
        if recovery_rules.get("恢复不超过上限") is not True:
            raise JsonDataError("恢复丹不得让资源超过上限")
        if _strings(recovery_rules.get("资源"), "服丹.恢复丹.资源") != (
            "血气",
            "精神",
        ):
            raise JsonDataError("恢复丹资源必须是血气、精神")
        battle_rules = _mapping(rules.get("战丹"), "服丹.战丹")
        if battle_rules.get("每个角色上限") != 1:
            raise JsonDataError("每个角色只能寄存一枚战丹")
        if battle_rules.get("重复处理") != "已有待战战丹时拒绝":
            raise JsonDataError("待战战丹重复处理必须是拒绝")
        if battle_rules.get("服下即扣除") is not True:
            raise JsonDataError("战丹必须在服下时扣除")
        if battle_rules.get("生效战斗") != "下一场正式战斗":
            raise JsonDataError("战丹只能在下一场正式战斗生效")
        if battle_rules.get("测试战斗生效") is not False:
            raise JsonDataError("战丹不得在测试战斗生效")
        if battle_rules.get("正常结束清除") is not True:
            raise JsonDataError("战丹必须在正式战斗正常创建后清除")
        if battle_rules.get("创建失败或中止保留") is not True:
            raise JsonDataError("战丹在正式战斗创建失败时必须保留")
        if battle_rules.get("人物与道侣独立") is not True:
            raise JsonDataError("人物与道侣必须独立寄存战丹")
        if battle_rules.get("共享库存键") != "user_id":
            raise JsonDataError("战丹共享库存键必须是user_id")
        active_rules = _mapping(rules.get("主动服用"), "服丹.主动服用")
        if _strings(active_rules.get("目标"), "服丹.主动服用.目标") != (
            "人物",
            "同行道侣",
        ):
            raise JsonDataError("主动服丹目标必须是人物、同行道侣")
        self._active_guard_rule = _text(
            active_rules.get("状态守卫"), "服丹.主动服用.状态守卫"
        )
        if active_rules.get("品级省略") != "消耗最低品级":
            raise JsonDataError("主动服丹省略品级时必须消耗最低品级")
        if active_rules.get("指定品级") != "精确消耗":
            raise JsonDataError("主动服丹指定品级时必须精确消耗")
        if active_rules.get("资源已满") != "拒绝且不扣除":
            raise JsonDataError("资源满值时必须拒绝且不扣除丹药")
        setting_rules = _mapping(rules.get("开关设置"), "服丹.开关设置")
        self._setting_guard_rule = _text(
            setting_rules.get("状态守卫"), "服丹.开关设置.状态守卫"
        )
        if _strings(setting_rules.get("取值"), "服丹.开关设置.取值") != (
            "开",
            "关",
        ):
            raise JsonDataError("服丹.开关设置.取值必须是开、关")
        self._index_medicines()
        self._initialized = True
        return self.status()

    def status(self) -> MedicineStatus:
        return MedicineStatus(
            self._initialized,
            len(self._recovery),
            len(self._battle),
            len(self._special),
            self._default_auto,
            self._threshold,
        )

    @property
    def default_auto_medicine(self) -> bool:
        self._require_initialized()
        return self._default_auto

    @property
    def auto_medicine_threshold(self) -> float:
        self._require_initialized()
        return self._threshold

    @property
    def selection_strategy(self) -> str:
        self._require_initialized()
        return self._selection_strategy

    @property
    def active_guard_rule(self) -> str:
        self._require_initialized()
        return self._active_guard_rule

    @property
    def setting_guard_rule(self) -> str:
        self._require_initialized()
        return self._setting_guard_rule

    async def recovery_stacks(
        self, user_id: str
    ) -> tuple[RecoveryMedicineStack, ...]:
        """把纳戒事实解释成可供主动或自动服用的恢复丹堆叠。"""

        self._require_initialized()
        snapshot = await self._asset.snapshot(user_id)
        result: list[RecoveryMedicineStack] = []
        for entry in snapshot.entries:
            if entry.category != "基础物品" or entry.subcategory != "恢复丹":
                continue
            medicine = self.recovery(entry.content_id, entry.grade_id)
            result.append(
                RecoveryMedicineStack(
                    entry.instance_key,
                    medicine.medicine_id,
                    medicine.name,
                    medicine.grade_id,
                    medicine.grade_name,
                    medicine.grade_order,
                    entry.quantity,
                    medicine.resource,
                    medicine.recovery_percent,
                )
            )
        return tuple(result)

    def resolve(self, identifier: str) -> str:
        self._require_initialized()
        query = str(identifier or "").strip()
        if not query:
            raise MedicineError("丹药编号或名称不能为空")
        if query in self._recovery or query in self._battle or query in self._special:
            return query
        matches = tuple(
            medicine_id
            for medicine_id, value in self._all().items()
            if str(value.get("名称") or "").strip() == query
        )
        if len(matches) != 1:
            raise MedicineError(f"未找到唯一丹药：{query}")
        return matches[0]

    def recovery(self, medicine_id: str, grade_id: str) -> RecoveryMedicine:
        self._require_initialized()
        normalized = self._required_id(medicine_id)
        raw = self._recovery.get(normalized)
        if raw is None:
            raise MedicineError("该丹药不是恢复丹")
        effect = _mapping(raw.get("使用效果"), "恢复丹.使用效果")
        effect_type = str(effect.get("类型") or "")
        resource = effect_type.removeprefix("恢复")
        if resource not in {"血气", "精神"}:
            raise MedicineError("恢复丹资源类型无效")
        base = effect.get("恢复百分比")
        if isinstance(base, bool) or not isinstance(base, (int, float)) or base <= 0:
            raise JsonDataError(f"恢复丹 {normalized} 缺少正数恢复百分比")
        grade = self._asset.grade(grade_id)
        return RecoveryMedicine(
            normalized,
            _text(raw.get("名称"), "恢复丹.名称"),
            grade.grade_id,
            grade.name,
            resource,
            round(float(base) * float(grade.ability_multiplier), 4),
            grade.order,
        )

    def battle(self, medicine_id: str, grade_id: str) -> BattleMedicine:
        self._require_initialized()
        normalized = self._required_id(medicine_id)
        raw = self._battle.get(normalized)
        if raw is None:
            raise MedicineError("该丹药不是战丹")
        effect = _mapping(raw.get("使用效果"), "战丹.使用效果")
        listeners = tuple(
            dict(materialize(node))
            for node in _mappings(effect.get("监听", ()), "战丹.监听")
        )
        prepared = _mapping(effect.get("战前状态"), "战丹.战前状态")
        grade = self._asset.grade(grade_id)
        attributes = _mapping(prepared.get("属性", {}), "战丹.战前状态.属性")
        prepared = dict(prepared)
        prepared["属性"] = {
            str(name): _clean_number(_number(value, f"战丹.战前状态.属性.{name}") * float(grade.ability_multiplier))
            for name, value in attributes.items()
        }
        return BattleMedicine(
            normalized,
            _text(raw.get("名称"), "战丹.名称"),
            grade.grade_id,
            grade.name,
            listeners,
            dict(prepared),
            grade.order,
        )

    def prepared_status(self, medicine: BattleMedicine) -> CombatStatusSpec:
        """把战丹定义转换为战斗核心的纯状态快照。"""

        raw = medicine.prepared_status
        modifiers_value = raw.get("属性", {})
        if not isinstance(modifiers_value, Mapping):
            raise JsonDataError("战丹.战前状态.属性必须是对象")
        modifiers = tuple(
            (str(name), _number(value, f"战丹.战前状态.属性.{name}"))
            for name, value in modifiers_value.items()
        )
        name = _text(raw.get("名称"), "战丹.战前状态.名称")
        category = _text(raw.get("类别"), "战丹.战前状态.类别")
        remaining = raw.get("剩余行动")
        if isinstance(remaining, bool) or not isinstance(remaining, int) or remaining < 1:
            raise JsonDataError("战丹.战前状态.剩余行动必须是正整数")
        duration = _text(raw.get("持续单位"), "战丹.战前状态.持续单位")
        tags = _strings(raw.get("标签", []), "战丹.战前状态.标签", allow_empty=True)
        return CombatStatusSpec(
            name=name,
            category=category,
            remaining_actions=remaining,
            duration_unit=duration,
            modifiers=modifiers,
            tags=tags,
            listeners=tuple(
                dict(_mapping(node, "战丹.监听[]")) for node in medicine.listeners
            ),
            source="丹药",
            source_name=medicine.name,
            metadata=(("丹药编号", medicine.medicine_id), ("品级编号", medicine.grade_id)),
        )

    def is_recovery(self, medicine_id: str) -> bool:
        return self._required_id(medicine_id) in self._recovery

    def is_battle(self, medicine_id: str) -> bool:
        return self._required_id(medicine_id) in self._battle

    def is_special(self, medicine_id: str) -> bool:
        return self._required_id(medicine_id) in self._special

    def _index_medicines(self) -> None:
        """按物品契约索引丹药，并校验每个实体真的符合契约。

        契约来自 `data/物品/基础物品` 的 `分类.json` 与 `使用效果.json`：
        `分类.json` 声明丹药必须有 `使用效果`、可选 `强度`；`使用效果.json` 按效果
        类型声明各自的必填与可选字段。此前这两份契约没有任何消费者，改动它们不影响
        游戏；现在启动即按契约校验，不再静默跳过缺字段的实体。
        """

        self._medicines.clear()
        self._recovery.clear()
        self._battle.clear()
        self._special.clear()
        validator = SchemaValidator()
        category_required, category_optional = self._medicine_category_contract()
        effect_contract = self._effect_contract()

        for medicine_id, raw in self._data.entities("丹药").items():
            label = f"丹药 {medicine_id}"
            validator.validate_declared_fields(
                raw,
                category_required,
                category_optional,
                label,
                discriminator="",
            )
            effect_value = raw.get("使用效果")
            if effect_value is None:
                raise JsonDataError(f"{label}：物品契约要求填写使用效果")
            effect = _mapping(effect_value, f"{label}.使用效果")
            effect_type = _text(effect.get("类型"), f"{label}.使用效果.类型")
            if effect_type not in effect_contract:
                raise JsonDataError(f"{label}：使用效果类型未在契约中声明 {effect_type}")
            required, optional = effect_contract[effect_type]
            validator.validate_declared_fields(
                effect, required, optional, f"{label}.使用效果"
            )
            self._medicines[medicine_id] = raw
            if effect_type in {"恢复血气", "恢复精神"}:
                self._recovery[medicine_id] = raw
            elif effect_type == "寄存战丹":
                self._battle[medicine_id] = raw
            else:
                self._special[medicine_id] = raw

    def _medicine_category_contract(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """从物品契约取得「丹药」类别的完整字段契约。

        契约分两处：`物品定义/公共字段.json` 声明全部编号实体共有的字段（例如
        `编号`/`名称`/`参考价`），`物品规则/分类.json` 声明类别专属字段。合并后
        才是完整契约——只查类别专属字段会把公共字段当成未知字段拒绝。
        """

        common_required = self._common_entity_fields()
        rows = self._data.dataset("物品规则").get("分类")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise JsonDataError("物品/基础物品/规则/分类.json 必须是字典列表")
        for raw_category in rows:
            entry = _mapping(raw_category, "分类[]")
            if str(entry.get("类别") or "").strip() != "丹药":
                continue
            required = _strings(
                entry.get("必填字段", []), "分类.丹药.必填字段", allow_empty=True
            )
            optional = _strings(
                entry.get("可选字段", []), "分类.丹药.可选字段", allow_empty=True
            )
            return (tuple(dict.fromkeys((*common_required, *required))), optional)
        raise JsonDataError("物品分类契约缺少「丹药」类别")

    def _common_entity_fields(self) -> tuple[str, ...]:
        """从 `物品定义/公共字段.json` 取得编号实体的公共字段。"""

        rows = self._data.dataset("物品定义").get("公共字段")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise JsonDataError("物品/基础物品/定义/公共字段.json 必须是字典列表")
        for raw in rows:
            entry = _mapping(raw, "公共字段[]")
            if str(entry.get("类别") or "").strip() != "编号实体":
                continue
            return _strings(entry.get("必填字段", []), "公共字段.必填字段", allow_empty=True)
        raise JsonDataError("物品契约缺少「编号实体」公共字段声明")

    def _effect_contract(self) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
        """从 `物品定义/使用效果.json` 取得每种效果类型的字段契约。"""

        rows = self._data.dataset("物品定义").get("使用效果")
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise JsonDataError("物品/基础物品/定义/使用效果.json 必须是字典列表")
        contract: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
        for raw in rows:
            entry = _mapping(raw, "使用效果[]")
            effect_type = _text(entry.get("类型"), "使用效果.类型")
            if effect_type in contract:
                raise JsonDataError(f"使用效果契约重复声明类型：{effect_type}")
            contract[effect_type] = (
                _strings(entry.get("必填字段", []), f"使用效果.{effect_type}.必填字段", allow_empty=True),
                _strings(entry.get("可选字段", []), f"使用效果.{effect_type}.可选字段", allow_empty=True),
            )
        if not contract:
            raise JsonDataError("使用效果契约不能为空")
        return contract

    def _all(self) -> Mapping[str, Mapping[str, object]]:
        return self._medicines

    def _required_id(self, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise MedicineError("丹药编号不能为空")
        if normalized not in self._all():
            raise MedicineError(f"丹药不存在：{normalized}")
        return normalized

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("丹药核心微服务尚未初始化")


def _mappings(value: object, label: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是对象数组")
    return tuple(_mapping(item, f"{label}[]") for item in value)


def _strings(
    value: object, label: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是字符串数组")
    result = tuple(str(item).strip() for item in value)
    if (
        (not allow_empty and not result)
        or any(not item for item in result)
        or len(result) != len(set(result))
    ):
        raise JsonDataError(f"{label}不能为空或重复")
    return result


def _number_range(value: object, label: str) -> tuple[float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是两个数值")
    values = tuple(_number(item, f"{label}[]") for item in value)
    if len(values) != 2 or values[0] > values[1]:
        raise JsonDataError(f"{label}必须是递增的两个数值")
    return values


def _clean_number(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 4)


__all__ = ["MedicineService"]
