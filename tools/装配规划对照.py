"""装配规划的终局对照：把 `plan_equip` 对全部道藏组合的产出做成可比对的摘要。

`plan_equip` 是人物装配的决策核心（135 行、21 个决策、密度 15.6），但它读的是**玩家状态**
（道藏所有权 + cultivation 快照），既不进战斗语料，也不进查看页语料——是那种"改完只能靠
跑起来看"的函数。本工具给它补上判据。

做法：

1. 把组合根指向一个**临时库**（打补丁到 `game.app.game_config`，不写 `.env`、不改游戏代码）；
2. 建一个测试人物，批量授予道藏（`plan_cultivation_acquisitions` 的计划 + 提交，
   照抄 `retreat/service.py` 的真实用法）；
3. 对每张卡在若干槽位上跑一次 `plan_equip`，把计划或异常收进摘要。

**按品级分趟**：`修行所得` 规则写明「相同或更低品级 → 复悟（不新增实例）；更高品级 →
覆盖并同步已装配槽位」，所以每个 (体裁, 编号) 玩家只持有一个实例，一批里混多个品级只会
互相覆盖。每趟用独立 user_id，同一趟内品级固定。

    # 与入库基准对照（推荐；有差异则非零退出）
    .venv/Scripts/python.exe -X utf8 tools/装配规划对照.py

    # 重新取基准
    .venv/Scripts/python.exe -X utf8 tools/装配规划对照.py --写基准

    # 先小样本验证 harness（不入库）
    .venv/Scripts/python.exe -X utf8 tools/装配规划对照.py --抽样 20

判据看改动性质：**纯结构等价（把 plan_equip 拆成若干段）应当 100% 一致**。

**退出码约定（与另五条通道一致）：0 = 一致，1 = 有差异，2 = 有抛错或基准缺失。**
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_BASELINE = ROOT / "tools" / "基准" / "装配规划摘要.json"

#: 道藏的三个体裁；`器律` 走的是器律储备，不在本判据里。
CATEGORIES = (
    ("功法", "战斗/内容/功法/功法-*.json"),
    ("真意", "战斗/内容/真意/真意-*.json"),
    ("气机", "战斗/内容/气机/气机-*.json"),
)
#: 人物主体的修行槽位数量来自 `data/角色/规则/主体/人物.json`，取上界即可。
SLOTS = (0, 1, 5)
GRADE_FILE = "基础/定义/品级.json"


def _temp_config(database_path: pathlib.Path):
    """把组合根的数据库指到临时库。

    `app.py` 是 `from .config import game_config`——它持有自己的引用，所以补丁必须打在
    `game.app` 上；打在 `game.config` 上无效。路径是在 `build_game_services` 函数体内读的，
    因此在调用前打补丁即可生效。
    """

    import game.app as app_module
    import game.config as config_module

    class _Source:
        base_dir = ROOT

        def get(self, name: str, default: str = "") -> str:
            if name == "DATABASE_PATH":
                return str(database_path)
            return default

    app_module.game_config = config_module.load_game_config(_Source())


def _canonical(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonical(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _operations(plan: object) -> tuple[object, ...]:
    """取出计划里的状态变更。

    两类计划的字段名不同（道藏取得是 `operations`，储备增减是 `operation`），
    这里一次认全，免得改一处忘一处。
    """

    for name in ("operations", "operation"):
        value = getattr(plan, name, None)
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            return tuple(value)
        return (value,)
    raise AttributeError(f"{type(plan).__name__} 里找不到状态变更字段")


def _cards(root: pathlib.Path, pattern: str, sample: int) -> list[str]:
    ids: list[str] = []
    for path in sorted(root.glob(pattern)):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            ids.append(str(entry["编号"]))
    if sample > 0:
        ids = ids[::sample]
    return ids


def _grades(root: pathlib.Path) -> list[str]:
    document = json.loads((root / GRADE_FILE).read_text(encoding="utf-8"))
    entries = document if isinstance(document, list) else list(document.values())
    ids: list[str] = []
    for entry in entries:
        if isinstance(entry, dict):
            value = entry.get("编号") or entry.get("名称")
            if value:
                ids.append(str(value))
        elif isinstance(entry, str):
            ids.append(entry)
    return ids


def digest(root: pathlib.Path, sample: int) -> tuple[dict[str, object], list[str]]:
    # 临时库落在 _输出/ 下（已被 .gitignore 忽略）：本环境的 TEMP/TMP 没设，
    # 用默认 mkdtemp 会把目录丢在仓库根，而且这份摘要跑一次要留一个库。
    scratch = ROOT / "_输出" / "测试临时"
    scratch.mkdir(parents=True, exist_ok=True)
    database_path = pathlib.Path(tempfile.mkdtemp(prefix="装配判据-", dir=scratch)) / "game.db"
    _temp_config(database_path)

    from game.app import build_game_services
    from game.core.asset.contracts import CultivationAcquisition
    from game.core.database.contracts import TransactionCommand
    from game.features.chuangjian_renwu.contracts import CreateCharacterRequest

    services = build_game_services(data_dir=root)
    summary: dict[str, object] = {}
    failures: list[str] = []
    catalogue = {name: _cards(root, pattern, sample) for name, pattern in CATEGORIES}
    grades = _grades(root)

    async def run() -> None:
        for grade in grades:
            user_id = f"P:{grade}"
            try:
                await services.features.chuangjian_renwu.create(
                    CreateCharacterRequest(
                        user_id=user_id,
                        request_id=f"创建:{grade}",
                        name=f"判据{grade}",
                        gender="男",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"创建人物 {grade}：{type(exc).__name__}: {exc}")
                continue
            try:
                operations: list[object] = []
                # 功法进道藏（唯一实例），真意与气机进储备——两条通道不同，混用会被拒。
                guild = await services.core.asset.plan_cultivation_acquisitions(
                    user_id,
                    tuple(
                        CultivationAcquisition("功法", content_id, grade)
                        for content_id in catalogue["功法"]
                    ),
                )
                operations.extend(_operations(guild))
                for name in ("真意", "气机"):
                    for content_id in catalogue[name]:
                        reserve = (
                            await services.core.asset.plan_cultivation_reserve_change(
                                user_id,
                                category=name,
                                content_id=content_id,
                                grade_id=grade,
                                quantity_delta=1,
                            )
                        )
                        operations.extend(_operations(reserve))
                await services.core.database.commit(
                    TransactionCommand(
                        user_id,
                        f"授予:{grade}",
                        "装配判据授予",
                        tuple(operations),
                        {"品级": grade},
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"授予 {grade}：{type(exc).__name__}: {exc}")
                continue
            for name, ids in catalogue.items():
                for content_id in ids:
                    for slot in SLOTS:
                        key = f"{grade}|{name}|{content_id}|{slot}"
                        try:
                            plan = await services.core.character.plan_equip(
                                user_id,
                                category=name,
                                content_id=content_id,
                                grade_id=grade,
                                slot=slot,
                            )
                            summary[key] = _canonical(plan)
                        except Exception as exc:  # noqa: BLE001
                            summary[key] = {
                                "错误": f"{type(exc).__name__}: {exc}",
                            }
        services.core.database.close()

    asyncio.run(run())
    for leftover in database_path.parent.glob("*"):
        leftover.unlink(missing_ok=True)
    database_path.parent.rmdir()
    return summary, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--基准", default=str(DEFAULT_BASELINE), help="入库基准摘要")
    parser.add_argument("--写基准", action="store_true", help="把当前摘要写进 --基准")
    parser.add_argument("--数据", default=str(ROOT / "data"), help="要跑的数据目录")
    parser.add_argument("--抽样", type=int, default=0, help="每隔 N 张卡取一张；0 = 全部")
    args = parser.parse_args()

    root = pathlib.Path(args.数据)
    summary, failures = digest(root, args.抽样)
    print(f"{len(summary)} 条，失败 {len(failures)} 条；数据目录 {root}")
    for failure in failures[:10]:
        print(f"  {failure}")

    baseline = pathlib.Path(args.基准)
    if args.写基准:
        if failures:
            print("有抛错，拒绝写基准——否则会把坏状态固化成判据。")
            return 2
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        print(f"已写入 {baseline}")
        return 0

    if args.抽样:
        print("抽样运行只用来验证 harness，不写盘、不对照。")
        return 0
    if not baseline.is_file():
        print(f"基准不存在：{baseline}；先跑一次 --写基准")
        return 2
    try:
        expected = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"基准无法读取：{exc}")
        return 2

    changed = sorted(
        key for key in summary.keys() & expected.keys() if summary[key] != expected[key]
    )
    added = sorted(summary.keys() - expected.keys())
    missing = sorted(expected.keys() - summary.keys())
    same = len(summary.keys() & expected.keys()) - len(changed)
    print(
        f"对照 {baseline}（{len(expected)} 条）：一致 {same} / {len(summary)}"
        f" · 差异 {len(changed)} · 新增 {len(added)} · 缺失 {len(missing)}"
    )
    for key in changed[:20]:
        print(f"  [差异] {key}")
        print(f"      - {json.dumps(expected[key], ensure_ascii=False)[:150]}")
        print(f"      + {json.dumps(summary[key], ensure_ascii=False)[:150]}")
    if failures:
        return 2
    return 1 if (changed or added or missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
