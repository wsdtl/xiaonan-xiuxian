"""查看结果的终局对照：把全部正式编号实体的查看页做成可比对的摘要。

另三条通道读的是**战斗**与**卡面正文**，读不到命令层为查看页拼的结构化行
（`game/cmd/通用/查看/items.py` 的 `_definition_lines` 与 `_build_description_lines`）。
那部分改动此前是零判据的：把某个领域的详情行少拼一行、把字段名换掉，战斗语料一场都
测不到。

本工具补上这一段：对每个正式编号实体调用一次真实的 `查看` 回复构造，把冻结后的
消息逐字段收进摘要。**对照的是玩家实际看到的东西**，不是中间结构。

    # 与入库基准对照（推荐；有差异则非零退出）
    .venv/Scripts/python.exe -X utf8 tools/查看结果对照.py

    # 重新取基准（改显示层之后）
    .venv/Scripts/python.exe -X utf8 tools/查看结果对照.py --写基准

判据看改动性质：**纯结构等价（把一张大分派拆成若干小函数）应当 100% 一致**；改措辞或
改版式则差异必须恰好是你要改的那批实体。有实体抛错时拒绝写基准。

**退出码约定（与另三条通道一致）：0 = 一致，1 = 有差异，2 = 有抛错或基准缺失。**
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.cmd.通用.查看.reply import inspection  # noqa: E402

DEFAULT_BASELINE = ROOT / "tools" / "基准" / "查看结果摘要.json"


def _canonical(value: object) -> object:
    """把冻结消息变成可比较的普通结构（元组与映射都归一化）。

    归一化的意义不只是「变成普通结构」：基准是用 `sort_keys=True` 写盘的，键序被排过；
    而内存里的摘要是插入序。Python 的 `dict.__eq__` 对嵌套字典是**键序敏感**的，直接比
    会把每一条都判成差异（实测 3987 条全红）。所以**读基准之后也要过这里**，让两边
    的键序落到同一个规范形。
    """

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


def _stable(value: object) -> str:
    """规范化并且**键序无关**的序列化，用于比较。"""

    return json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True)


async def digest(root: pathlib.Path) -> tuple[dict[str, object], list[str]]:
    """返回（摘要, 失败清单）。失败要记账：抛错当成空页会掩盖最该看见的回归。"""

    services = build_game_services(data_dir=root)
    summary: dict[str, object] = {}
    failures: list[str] = []
    for entity in services.core.data.numbered_entities():
        try:
            result = await services.features.chakan_wupin.inspect(entity.entity_id)
            message = inspection(result)
        except Exception as exc:  # noqa: BLE001 - 任何异常都要变成可见的失败
            failures.append(f"{entity.entity_id}：{type(exc).__name__}: {exc}")
            continue
        detail = result.detail
        summary[entity.entity_id] = {
            "体裁": detail.section if detail is not None else "",
            "类别": detail.category if detail is not None else "",
            "查看页": _canonical(message),
        }
    return summary, failures


def _line_diff(field: str, old: object, new: object) -> list[str]:
    before = _stable(old)
    after = _stable(new)
    if before == after:
        return []
    return [f"-{field} {before[:160]}", f"+{field} {after[:160]}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--基准", default=str(DEFAULT_BASELINE), help="入库基准摘要")
    parser.add_argument("--写基准", action="store_true", help="把当前摘要写进 --基准")
    parser.add_argument("--数据", default=str(ROOT / "data"), help="要跑的数据目录")
    parser.add_argument("--差异名单", default="",
                        help="把完整差异清单写到这个文件（大批次逐条验收用；终端只列前 20 条）")
    args = parser.parse_args()

    root = pathlib.Path(args.数据)
    summary, failures = asyncio.run(digest(root))
    print(f"{len(summary)} 条，失败 {len(failures)} 条；数据目录 {root}")
    for failure in failures:
        print(f"  {failure}")

    baseline = pathlib.Path(args.基准)
    if args.写基准:
        if failures:
            print("有实体抛错，拒绝写基准——否则会把坏状态固化成判据。")
            return 2
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        print(f"已写入 {baseline}")
        return 0

    if not baseline.is_file():
        print(f"基准不存在：{baseline}；先跑一次 --写基准")
        return 2
    try:
        expected = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"基准无法读取：{exc}")
        return 2
    if not isinstance(expected, dict):
        print(f"基准结构不对：{baseline} 应为对象")
        return 2
    # 基准过一遍规范化：两边键序才会落到同一规范形（见 `_canonical` 的说明）。
    expected = _canonical(expected)

    changed = sorted(
        key for key in summary.keys() & expected.keys() if summary[key] != expected[key]
    )
    added = sorted(summary.keys() - expected.keys())
    missing = sorted(expected.keys() - summary.keys())
    same = len(summary.keys() & expected.keys()) - len(changed)
    print(
        f"对照 {baseline}（{len(expected)} 条）："
        f"一致 {same} / {len(summary)} · 差异 {len(changed)}"
        f" · 新增 {len(added)} · 缺失 {len(missing)}"
    )
    for key in changed[:20]:
        print(f"  [差异] {key}")
        before = expected[key] if isinstance(expected[key], dict) else {}
        after = summary[key] if isinstance(summary[key], dict) else {}
        for field in ("体裁", "类别", "查看页"):
            for line in _line_diff(field, before.get(field), after.get(field)):
                print(f"      {line}")
    if len(changed) > 20:
        print(f"  …… 其余 {len(changed) - 20} 条差异从略")
    if args.差异名单:
        listing = pathlib.Path(args.差异名单)
        listing.parent.mkdir(parents=True, exist_ok=True)
        listing.write_text(
            json.dumps({"差异": changed, "新增": added, "缺失": missing},
                       ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        print(f"  完整差异清单已写入 {listing}（{len(changed)} 条）")
    for key in added[:10]:
        print(f"  [新增] {key}")
    for key in missing[:10]:
        print(f"  [缺失] {key}")
    if failures:
        return 2
    return 1 if (changed or added or missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
