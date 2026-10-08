"""游戏微服务的唯一组合根。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from launch import C, OnEvent, config, logger

from .config import game_config
from .core.action_group import ActionGroupService
from .core.activity import ActivityLifecycleService
from .core.alchemy import AlchemyService
from .core.asset import AssetService
from .core.character import CharacterService
from .core.combat import CombatService
from .core.companion import CompanionService
from .core.cultivation_transfer import CultivationTransferService
from .core.data import JsonDataService
from .core.database import DatabaseService
from .core.duel import DuelService
from .core.enemy import EnemyService
from .core.exploration import ExplorationService
from .core.forging import ForgingService
from .core.formation import FormationService
from .core.gathering import GatheringService
from .core.gift import GiftService
from .core.growth import GrowthService
from .core.hosting import HostingService
from .core.injury import InjuryService
from .core.innate_treasure import InnateTreasureService
from .core.item_catalog import ItemCatalogService
from .core.location import LocationService
from .core.medicine import MedicineService
from .core.player_state import PlayerStateService
from .core.pool import PoolService
from .core.raid import RaidService
from .core.retreat import RetreatService
from .core.sect import SectService
from .core.sect_assets import SectAssetService
from .core.sect_facilities import SectFacilityService
from .core.sect_library import SectLibraryService
from .core.sect_production import SectProductionService
from .core.sect_progress import SectProgressService
from .core.sect_war import SectWarService
from .core.team import TeamService
from .core.trade import TradeService
from .core.world import WorldService
from .features.biguan import RetreatFeature
from .features.butian import ButianFeature
from .features.buzhen import FormationArmFeature
from .features.caikuang import OreGatheringFeature
from .features.caiyao import HerbGatheringFeature
from .features.chakan_juese import CharacterOverviewFeature
from .features.chakan_wupin import ItemInspectionFeature
from .features.chuangjian_renwu import CreateCharacterFeature
from .features.daolv_jiejiao import CompanionInteractionFeature
from .features.daolv_peiyang import CompanionCultivationFeature
from .features.ditu import WorldMapFeature
from .features.duiwu import TeamFeature
from .features.fudan import MedicineFeature
from .features.guiyuan import GuiyuanFeature
from .features.jiaoyi import TradeFeature
from .features.liandan import AlchemyFeature
from .features.lianqi import ForgingFeature
from .features.lianzhen import FormationCraftFeature
from .features.najie import NajieFeature
from .features.qiecuo import DuelFeature
from .features.renwu_peiyang import CharacterCultivationFeature
from .features.tanxian import ExplorationFeature
from .features.taofa import RaidFeature
from .features.tongquetai import TongquetaiFeature
from .features.tuoguan import HostingFeature
from .features.weizhi import PositionFeature
from .features.xiantian_lingbao import InnateTreasureFeature
from .features.xinglu import TravelFeature
from .features.yixing import YixingFeature
from .features.zengsong import GiftFeature
from .features.zhanbao import BattleReportFeature
from .features.zhongzu import ZhongzuFeature
from .features.zongmen import SectFeature
from .features.zongmen_cangjing import CangjingFeature
from .features.zongmen_lingcang import LingcangFeature
from .features.zongmen_shanmen import GateFeature
from .features.zongmen_shengchan import SectProductionFeature
from .features.zongmen_sheshi import SectFacilityFeature
from .features.zongmen_tongxing import SectFollowFeature
from .features.zongmen_wanzhen import WanzhenFeature
from .features.zhuangpei import ZhuangpeiFeature
from .features.zongmen_zhan import SectWarFeature
from .startup import validate_startup_contracts


@dataclass(frozen=True)
class CoreServices:
    """全局基础微服务。"""

    data: JsonDataService
    item_catalog: ItemCatalogService
    combat: CombatService
    pool: PoolService
    growth: GrowthService
    forging: ForgingService
    alchemy: AlchemyService
    formation: FormationService
    world: WorldService
    companion: CompanionService
    cultivation_transfer: CultivationTransferService
    database: DatabaseService
    location: LocationService
    player_state: PlayerStateService
    team: TeamService
    sect: SectService
    sect_library: SectLibraryService
    sect_assets: SectAssetService
    sect_facilities: SectFacilityService
    sect_production: SectProductionService
    sect_progress: SectProgressService
    action_group: ActionGroupService
    activity: ActivityLifecycleService
    hosting: HostingService
    injury: InjuryService
    innate_treasure: InnateTreasureService
    character: CharacterService
    asset: AssetService
    medicine: MedicineService
    enemy: EnemyService
    raid: RaidService
    exploration: ExplorationService
    sect_war: SectWarService
    retreat: RetreatService
    gathering: GatheringService
    trade: TradeService
    duel: DuelService
    gift: GiftService


@dataclass(frozen=True)
class FeatureServices:
    """具体玩法微服务；后续按 JSON 契约逐项加入。"""

    chuangjian_renwu: CreateCharacterFeature
    chakan_juese: CharacterOverviewFeature
    chakan_wupin: ItemInspectionFeature
    ditu: WorldMapFeature
    zhongzu: ZhongzuFeature
    najie: NajieFeature
    weizhi: PositionFeature
    xinglu: TravelFeature
    daolv_jiejiao: CompanionInteractionFeature
    renwu_peiyang: CharacterCultivationFeature
    daolv_peiyang: CompanionCultivationFeature
    tanxian: ExplorationFeature
    taofa: RaidFeature
    duiwu: TeamFeature
    biguan: RetreatFeature
    caiyao: HerbGatheringFeature
    caikuang: OreGatheringFeature
    lianqi: ForgingFeature
    liandan: AlchemyFeature
    lianzhen: FormationCraftFeature
    buzhen: FormationArmFeature
    jiaoyi: TradeFeature
    fudan: MedicineFeature
    tongquetai: TongquetaiFeature
    guiyuan: GuiyuanFeature
    butian: ButianFeature
    yixing: YixingFeature
    zongmen: SectFeature
    zongmen_lingcang: LingcangFeature
    zongmen_wanzhen: WanzhenFeature
    zongmen_cangjing: CangjingFeature
    zongmen_tongxing: SectFollowFeature
    zongmen_shanmen: GateFeature
    zongmen_sheshi: SectFacilityFeature
    zongmen_shengchan: SectProductionFeature
    zongmen_zhan: SectWarFeature
    tuoguan: HostingFeature
    xiantian_lingbao: InnateTreasureFeature
    qiecuo: DuelFeature
    zengsong: GiftFeature
    zhanbao: BattleReportFeature
    zhuangpei: ZhuangpeiFeature


@dataclass(frozen=True)
class GameServices:
    """当前进程已经装配完成的游戏微服务。"""

    core: CoreServices
    features: FeatureServices


def build_game_services(*, data_dir: str | Path | None = None) -> GameServices:
    """按依赖顺序创建微服务；JSON 数据服务永远最先初始化。"""

    data = JsonDataService(data_dir or (config.base_dir / "data"))
    status = data.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("JSON 数据微服务已启动"),
            C.kv("documents", status.document_count),
            C.kv("entities", status.entity_count),
            C.kv("pools", status.pool_count),
        )
    )
    item_catalog = ItemCatalogService(data)
    item_status = item_catalog.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("物品查询核心微服务已启动"),
            C.kv("items", item_status.item_count),
            C.kv("categories", len(item_status.category_counts)),
        )
    )
    pool = PoolService(data)
    pool_status = pool.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("资源池微服务已启动"),
            C.kv("modes", len(pool_status.modes)),
        )
    )
    growth = GrowthService(data, pool)
    growth_status = growth.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("角色成长核心微服务已启动"),
            C.kv("realms", growth_status.realm_count),
            C.kv("max_level", growth_status.maximum_level),
        )
    )
    world = WorldService(data)
    world_status = world.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("世界地点服务已启动"),
            C.kv("locations", world_status.location_count),
            C.kv("regions", world_status.region_count),
            C.kv("roads", world_status.road_count),
            C.kv("terrain_cells", world_status.terrain_cell_count),
        )
    )
    database = DatabaseService(
        game_config.database.path,
        busy_timeout_ms=game_config.database.busy_timeout_ms,
    )
    database_status = database.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("核心数据库微服务已启动"),
            C.kv("states", database_status.state_count),
            C.kv("locations", database_status.location_count),
            C.kv("transactions", database_status.transaction_count),
        )
    )
    innate_treasure = InnateTreasureService(data, database)
    innate_treasure_status = innate_treasure.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("先天灵宝核心微服务已启动"),
            C.kv("treasures", innate_treasure_status.treasure_count),
            C.kv("slots", innate_treasure_status.slot_count),
        )
    )
    activity = ActivityLifecycleService()
    activity.initialize()
    logger.opt(colors=True).success(C.ok("异步玩法生命周期核心已启动"))
    player_state = PlayerStateService(data, database)
    player_state_status = player_state.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("人物状态核心微服务已启动"),
            C.kv("statuses", player_state_status.state_count),
            C.kv("guard_rules", player_state_status.guard_rule_count),
        )
    )
    team = TeamService(data, database, player_state)
    team_status = team.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("队伍核心微服务已启动"),
            C.kv("maximum_players", team_status.maximum_players),
            C.kv("invitation_seconds", team_status.invitation_seconds),
        )
    )
    location = LocationService(data, database, world)
    location_status = location.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("玩家位置核心微服务已启动"),
            C.kv("players", location_status.player_count),
            C.kv("radius", location_status.nearby_radius_meters),
            C.kv("page_size", location_status.nearby_page_size),
        )
    )
    asset = AssetService(data, database)
    asset_status = asset.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("玩家资产核心微服务已启动"),
            C.kv("categories", asset_status.category_count),
            C.kv("subcategories", asset_status.subcategory_count),
            C.kv("page_limit", asset_status.page_limit),
        )
    )
    forging = ForgingService(data, database, asset, world, location, innate_treasure)
    forging_status = forging.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("炼器核心微服务已启动"),
            C.kv("laws", forging_status.law_count),
            C.kv("methods", forging_status.method_count),
            C.kv("artisans", forging_status.artisan_count),
        )
    )
    sect = SectService(data, database, player_state)
    sect_status = sect.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("宗门核心微服务已启动"),
            C.kv("maximum_followers", sect_status.maximum_followers),
            C.kv("invitation_seconds", sect_status.invitation_seconds),
        )
    )
    sect_library = SectLibraryService(data, database, sect, asset, growth)
    sect_library_status = sect_library.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("藏经阁核心微服务已启动"),
            C.kv("initialized", sect_library_status.initialized),
        )
    )
    action_group = ActionGroupService(data, team, sect)
    action_group.initialize()
    logger.opt(colors=True).success(C.ok("行动组核心微服务已启动"))
    hosting = HostingService(data, database, player_state, action_group)
    hosting.initialize()
    logger.opt(colors=True).success(C.ok("托管核心微服务已启动"))
    medicine = MedicineService(data, asset)
    medicine_status = medicine.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("丹药核心微服务已启动"),
            C.kv("recovery", medicine_status.recovery_count),
            C.kv("battle", medicine_status.battle_count),
            C.kv("special", medicine_status.special_count),
        )
    )
    cultivation_transfer = CultivationTransferService(data, growth, world)
    transfer_status = cultivation_transfer.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("修为转移核心微服务已启动"),
            C.kv("function", transfer_status.location_function),
            C.kv("medicine", transfer_status.medicine_id),
        )
    )
    alchemy = AlchemyService(data, database, asset, world, location, innate_treasure)
    alchemy_status = alchemy.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("炼丹核心微服务已启动"),
            C.kv("recipes", alchemy_status.recipe_count),
            C.kv("medicines", alchemy_status.medicine_count),
            C.kv("alchemists", alchemy_status.alchemist_count),
        )
    )
    formation = FormationService(
        data, database, asset, world, location, innate_treasure
    )
    formation_status = formation.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("阵法核心微服务已启动"),
            C.kv("formations", formation_status.formation_count),
            C.kv("masters", formation_status.master_count),
        )
    )
    combat = CombatService(data, formation)
    combat_status = combat.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("战斗核心微服务已启动"),
            C.kv("builds", combat_status.build_count),
            C.kv("abilities", combat_status.ability_count),
            C.kv("events", combat_status.event_count),
            C.kv("environments", combat_status.environment_count),
            C.kv("formations", combat_status.formation_count),
        )
    )
    companion = CompanionService(data, database, growth, forging)
    companion_status = companion.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("世界道侣核心微服务已启动"),
            C.kv("companions", companion_status.companion_count),
            C.kv("locations", companion_status.location_count),
        )
    )
    character = CharacterService(
        data,
        database,
        player_state,
        location,
        asset,
        growth,
        forging,
        sect_library,
    )
    character_service_status = character.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("角色核心微服务已启动"),
            C.kv("role", character_service_status.role_name),
            C.kv("genders", character_service_status.gender_count),
            C.kv("initial_items", character_service_status.initial_item_count),
        )
    )
    # 种族表归角色核心读（`角色/规则/种族/种族.json`）。道侣核心比它先构造，所以在这里回填：
    # 回填当场校验 `道侣.json.种族池`，池子里写了没登记的族名照样是启动错误。
    companion.attach_races(character.races())
    injury = InjuryService(data, database)
    injury_status = injury.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("长期伤势核心微服务已启动"),
            C.kv("external", injury_status.external_count),
            C.kv("self_generated", injury_status.self_generated_count),
        )
    )
    sect_progress = SectProgressService(data, sect, character)
    sect_progress_status = sect_progress.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("宗门贡献等级核心微服务已启动"),
            C.kv("maximum_level", sect_progress_status.maximum_level),
        )
    )
    sect_assets = SectAssetService(
        data, database, sect, asset, character, innate_treasure
    )
    sect_assets_status = sect_assets.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("宗门公共资产核心微服务已启动"),
            C.kv("materials", len(sect_assets_status.material_categories)),
            C.kv("products", len(sect_assets_status.product_categories)),
        )
    )
    sect_facilities = SectFacilityService(
        data,
        database,
        sect,
        sect_assets,
        asset,
        alchemy,
        forging,
        formation,
        location,
        sect_progress,
    )
    sect_facilities_status = sect_facilities.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("宗门洞天设施核心微服务已启动"),
            C.kv("facilities", len(sect_facilities_status.facilities)),
            C.kv("roles", len(sect_facilities_status.roles)),
        )
    )
    sect_production = SectProductionService(
        data,
        database,
        sect,
        sect_assets,
        asset,
        pool,
        location,
        sect_progress,
    )
    sect_production_status = sect_production.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("宗门资源生产核心微服务已启动"),
            C.kv("facilities", len(sect_production_status.facilities)),
        )
    )
    trade = TradeService(data, database, world, location, character, asset)
    trade_status = trade.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("地点交易核心微服务已启动"),
            C.kv("shops", trade_status.shop_count),
        )
    )
    enemy = EnemyService(data, pool, growth, asset, forging)
    enemy_status = enemy.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("敌人实例核心微服务已启动"),
            C.kv("enemies", enemy_status.enemy_count),
        )
    )
    # 战报是**非资产数据**：登记进非资产库（同一个 runtime_log 库与清理任务）。
    from launch.battle_log import (
        BATTLE_RETENTION_SECONDS,
        BattleReportStore,
        runtime_log_database_path,
    )

    battle_reports = BattleReportStore(
        runtime_log_database_path(),
        retention_seconds=BATTLE_RETENTION_SECONDS,
    )
    battle_reports.initialize()

    duel = DuelService(
        data,
        database,
        location,
        character,
        companion,
        player_state,
        action_group,
        combat,
        battle_reports=battle_reports,
    )
    duel.initialize()
    logger.opt(colors=True).success(C.ok("切磋核心微服务已启动"))
    gift = GiftService(data, database, location, character, asset, item_catalog)
    gift.initialize()
    logger.opt(colors=True).success(C.ok("赠送核心微服务已启动"))
    raid = RaidService(
        data,
        enemy,
        database,
        world,
        location,
        character,
        companion,
        player_state,
        combat,
        activity,
        asset,
        pool,
    )
    raid.initialize()
    logger.opt(colors=True).success(C.ok("讨伐编组核心微服务已启动"))
    exploration = ExplorationService(
        data,
        database,
        world,
        location,
        character,
        companion,
        asset,
        player_state,
        enemy,
        formation,
        combat,
        activity,
        innate_treasure,
        medicine,
        injury,
    )
    exploration_status = exploration.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("普通探险核心微服务已启动"),
            C.kv("seconds_per_battle", exploration_status.seconds_per_battle),
            C.kv("maximum_battles", exploration_status.maximum_battles),
        )
    )
    sect_war = SectWarService(
        data,
        database,
        sect,
        sect_assets,
        asset,
        world,
        location,
        character,
        companion,
        player_state,
        medicine,
        combat,
        activity,
        injury,
        battle_reports,
    )
    sect_war_status = sect_war.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("宗门战核心微服务已启动"),
            C.kv("seconds", sect_war_status.seconds),
        )
    )
    retreat = RetreatService(
        data,
        database,
        world,
        location,
        character,
        companion,
        asset,
        player_state,
        pool,
        activity,
        injury,
        innate_treasure,
    )
    retreat_status = retreat.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("闭关核心微服务已启动"),
            C.kv("seconds_per_round", retreat_status.seconds_per_round),
            C.kv("maximum_rounds", retreat_status.maximum_rounds),
        )
    )
    gathering = GatheringService(
        data,
        database,
        world,
        location,
        character,
        companion,
        asset,
        player_state,
        pool,
        innate_treasure,
        sect,
        sect_progress,
    )
    gathering_status = gathering.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("采集核心微服务已启动"),
            C.kv("modes", len(gathering_status.modes)),
        )
    )
    core = CoreServices(
        data=data,
        item_catalog=item_catalog,
        combat=combat,
        pool=pool,
        growth=growth,
        forging=forging,
        alchemy=alchemy,
        formation=formation,
        world=world,
        companion=companion,
        cultivation_transfer=cultivation_transfer,
        database=database,
        location=location,
        player_state=player_state,
        team=team,
        sect=sect,
        sect_library=sect_library,
        sect_assets=sect_assets,
        sect_facilities=sect_facilities,
        sect_production=sect_production,
        sect_progress=sect_progress,
        action_group=action_group,
        activity=activity,
        hosting=hosting,
        injury=injury,
        innate_treasure=innate_treasure,
        character=character,
        asset=asset,
        medicine=medicine,
        enemy=enemy,
        raid=raid,
        exploration=exploration,
        sect_war=sect_war,
        retreat=retreat,
        gathering=gathering,
        trade=trade,
        duel=duel,
        gift=gift,
    )
    create_character = CreateCharacterFeature(data, world, character)
    birthplace = create_character.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("创建人物玩法微服务已启动"),
            C.kv("birthplace", birthplace),
        )
    )
    chakan_wupin = ItemInspectionFeature(item_catalog, combat, asset)
    chakan_wupin.initialize()
    chakan_juese = CharacterOverviewFeature(
        character,
        player_state,
        world,
        location,
        injury,
        innate_treasure,
        hosting,
    )
    chakan_juese.initialize()
    ditu = WorldMapFeature(world)
    map_overview = ditu.initialize()
    logger.opt(colors=True).success(
        C.join(
            C.ok("公开地图玩法微服务已启动"),
            C.kv("regions", map_overview.region_count),
            C.kv("locations", map_overview.location_count),
            C.kv("roads", map_overview.road_count),
        )
    )
    zhongzu = ZhongzuFeature(data, character, combat)
    zhongzu.initialize()
    najie = NajieFeature(asset)
    najie.initialize()
    jiaoyi = TradeFeature(data, trade)
    jiaoyi.initialize()
    fudan = MedicineFeature(
        data,
        medicine,
        character,
        companion,
        asset,
        player_state,
        database,
        innate_treasure,
    )
    fudan.initialize()
    tongquetai = TongquetaiFeature(
        data,
        cultivation_transfer,
        character,
        companion,
        asset,
        player_state,
        location,
        world,
        database,
        innate_treasure,
    )
    tongquetai.initialize()
    guiyuan = GuiyuanFeature(
        data, medicine, companion, asset, player_state, location, world, database
    )
    guiyuan.initialize()
    butian = ButianFeature(
        data,
        medicine,
        character,
        companion,
        asset,
        player_state,
        location,
        world,
        database,
    )
    butian.initialize()
    yixing = YixingFeature(
        data, medicine, character, asset, player_state, location, world, database
    )
    yixing.initialize()
    zongmen = SectFeature(
        data,
        sect,
        character,
        location,
        world,
        player_state,
        sect_progress,
        sect_library,
    )
    zongmen.initialize()
    zongmen_tongxing = SectFollowFeature(
        data, sect, character, location, player_state, team
    )
    zongmen_tongxing.initialize()
    zongmen_shanmen = GateFeature(data, sect, location, player_state, action_group)
    zongmen_shanmen.initialize()
    zongmen_lingcang = LingcangFeature(
        data, sect_assets, item_catalog, sect, location, player_state
    )
    zongmen_lingcang.initialize()
    zongmen_wanzhen = WanzhenFeature(
        data,
        sect_assets,
        item_catalog,
        character,
        sect,
        location,
        player_state,
    )
    zongmen_wanzhen.initialize()
    zongmen_cangjing = CangjingFeature(data, sect_library, sect, location, player_state)
    zongmen_cangjing.initialize()
    zongmen_sheshi = SectFacilityFeature(data, sect_facilities)
    zongmen_sheshi.initialize()
    zongmen_shengchan = SectProductionFeature(data, sect_production)
    zongmen_shengchan.initialize()
    zongmen_zhan = SectWarFeature(data, sect_war)
    zongmen_zhan.initialize()
    tuoguan = HostingFeature(data, hosting)
    tuoguan.initialize()
    weizhi = PositionFeature(
        data,
        world,
        location,
        character,
        player_state,
        companion,
        team,
        sect,
    )
    weizhi.initialize()
    xinglu = TravelFeature(world, character, location, action_group, player_state)
    xinglu.initialize()
    daolv_jiejiao = CompanionInteractionFeature(
        data,
        companion,
        item_catalog,
        asset,
        character,
        location,
        world,
        database,
        innate_treasure,
    )
    daolv_jiejiao.initialize()
    renwu_peiyang = CharacterCultivationFeature(
        data,
        character,
        asset,
        item_catalog,
        medicine,
        growth,
        forging,
        database,
        innate_treasure,
    )
    renwu_peiyang.initialize()
    xiantian_lingbao = InnateTreasureFeature(data, innate_treasure, database)
    xiantian_lingbao.initialize()
    qiecuo = DuelFeature(data, duel, character)
    qiecuo.initialize()
    zengsong = GiftFeature(data, gift, item_catalog, character)
    zengsong.initialize()
    zhanbao = BattleReportFeature(combat, sect_war, duel, battle_reports)
    zhanbao.initialize()
    zhuangpei = ZhuangpeiFeature(data, asset, character, database, innate_treasure, player_state, combat)
    daolv_peiyang = CompanionCultivationFeature(
        data,
        companion,
        asset,
        item_catalog,
        growth,
        forging,
        database,
    )
    daolv_peiyang.initialize()
    duiwu = TeamFeature(data, team, character, location, player_state)
    duiwu.initialize()
    tanxian = ExplorationFeature(data, exploration, item_catalog, asset, action_group)
    tanxian.initialize()
    taofa = RaidFeature(data, raid, action_group)
    taofa.initialize()
    biguan = RetreatFeature(data, retreat, asset, action_group)
    biguan.initialize()
    caiyao = HerbGatheringFeature(data, gathering, asset, action_group)
    caiyao.initialize()
    caikuang = OreGatheringFeature(data, gathering, asset, action_group)
    caikuang.initialize()
    lianqi = ForgingFeature(data, forging)
    lianqi.initialize()
    liandan = AlchemyFeature(data, alchemy)
    liandan.initialize()
    lianzhen = FormationCraftFeature(data, formation)
    lianzhen.initialize()
    buzhen = FormationArmFeature(data, formation)
    buzhen.initialize()
    features = FeatureServices(
        chuangjian_renwu=create_character,
        chakan_juese=chakan_juese,
        chakan_wupin=chakan_wupin,
        ditu=ditu,
        zhongzu=zhongzu,
        najie=najie,
        weizhi=weizhi,
        xinglu=xinglu,
        daolv_jiejiao=daolv_jiejiao,
        renwu_peiyang=renwu_peiyang,
        daolv_peiyang=daolv_peiyang,
        tanxian=tanxian,
        taofa=taofa,
        duiwu=duiwu,
        biguan=biguan,
        caiyao=caiyao,
        caikuang=caikuang,
        lianqi=lianqi,
        liandan=liandan,
        lianzhen=lianzhen,
        buzhen=buzhen,
        jiaoyi=jiaoyi,
        fudan=fudan,
        tongquetai=tongquetai,
        guiyuan=guiyuan,
        butian=butian,
        yixing=yixing,
        zongmen=zongmen,
        zongmen_lingcang=zongmen_lingcang,
        zongmen_wanzhen=zongmen_wanzhen,
        zongmen_cangjing=zongmen_cangjing,
        zongmen_tongxing=zongmen_tongxing,
        zongmen_shanmen=zongmen_shanmen,
        zongmen_sheshi=zongmen_sheshi,
        zongmen_shengchan=zongmen_shengchan,
        zongmen_zhan=zongmen_zhan,
        tuoguan=tuoguan,
        xiantian_lingbao=xiantian_lingbao,
        qiecuo=qiecuo,
        zengsong=zengsong,
        zhanbao=zhanbao,
        zhuangpei=zhuangpei,
    )
    return GameServices(core=core, features=features)


_services: GameServices | None = None


def current_game_services() -> GameServices:
    """取得当前进程唯一的游戏微服务集合。"""

    if _services is None:
        raise RuntimeError("游戏微服务尚未初始化；请检查 game.app 启动注册")
    return _services


@OnEvent.connect(priority=1000)
def initialize_game_services() -> None:
    """在其他游戏入口运行前完成全部微服务装配。"""

    global _services
    if _services is not None:
        raise RuntimeError("游戏微服务已经初始化")
    from launch.adapter.request_scope import register_request_scope

    from .cmd.access_guard import (
        register_game_access_guard,
        unregister_game_access_guard,
    )
    from .core.database import open_request_connections

    services = build_game_services()
    try:
        validate_startup_contracts(services.core.player_state)
        register_game_access_guard()
        # 核心库的连接只在**一条命令**内复用：驱动器进出请求范围时开、关，
        # 句柄不跨请求存活（见 game/core/database/说明.md）。
        register_request_scope(open_request_connections)
    except Exception:
        unregister_request_scope(open_request_connections)
        unregister_game_access_guard()
        services.core.database.close()
        raise
    _services = services


@OnEvent.disconnect(priority=-1000)
def shutdown_game_services() -> None:
    """在具体玩法停止后释放本进程的游戏微服务集合。"""

    global _services
    from launch.adapter.request_scope import unregister_request_scope

    from .cmd.access_guard import unregister_game_access_guard
    from .core.database import open_request_connections

    unregister_request_scope(open_request_connections)
    unregister_game_access_guard()
    if _services is not None:
        _services.core.database.close()
    _services = None


__all__ = [
    "CoreServices",
    "FeatureServices",
    "GameServices",
    "build_game_services",
    "current_game_services",
    "initialize_game_services",
    "shutdown_game_services",
]
