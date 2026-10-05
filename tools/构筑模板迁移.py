"""把六个面里能由模板还原的效果替换成**内容寻址**的模板引用（只做这一件事）。

## 与旧迁移的区别

* 引用编号是**主体内容哈希**，不是排名序号；
* 参数是**键名或位置路径**（`{"层数": 1}`），不是 `p1`/`p2`。

## 判据

只有**引擎展开后与原效果逐字节相同**的效果才会被替换（`templates.restore_reference`，
生成、迁移、校验共用同一份判据）。不一致就跳过那一条，绝不替换。

## 全量回写

迁移完成后**整个面**都回写，不只是改动过的文件。曾经只写「有改动」的文件，导致其余
文件里旧参数表的引用一直留着，累积成 219 条展不开的引用。既然同一轮里库可能刚换过，
就不能只看「这一条改了没有」。

用法：

    .venv/Scripts/python.exe -X utf8 tools/构筑模板迁移.py --落盘
"""

from __future__ import annotations

import argparse
import importlib
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _path in (str(ROOT), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

模板 = importlib.import_module("构筑模板")

from game.core.combat import templates as 引擎模板  # noqa: E402

ABILITY = 模板.ABILITY
EFFECT = 模板.EFFECT
TEMPLATE_KEY = 引擎模板.TEMPLATE_KEY
PARAMETER_KEY = 引擎模板.PARAMETER_KEY
ORDER_KEY = 引擎模板.ORDER_KEY


def _库():
    """现取模板库模块，**进程内只加载一次**。

    清缓存是必要的：库可能刚被重写，而模块级 `from ... import` 在首次 import 时就把
    符号绑死了，迁移会拿着旧库去重挂引用。只加载一次也是必要的：库有 10MB，每次调用
    都重载会让迁移从秒级变成分钟级（实测一跑就超十分钟）。
    """

    global _库缓存
    if _库缓存 is not None:
        return _库缓存
    for 名 in [k for k in sys.modules if "template_data" in k]:
        del sys.modules[名]
    importlib.invalidate_caches()
    import game.core.combat.template_data as 数据

    _库缓存 = 数据
    return _库缓存


_库缓存 = None


def _targets() -> dict[tuple, tuple[str, Any, dict]]:
    """结构签名 -> (模板编号, 主体, **单条库**)。

    单条库是为了让 `restore_reference` 只看得见这一份模板：它的回环判据会把引用展开，
    展开需要一个库。随条目带上就不用每条都拷贝整库（1,400+ 份模板，那样慢到不可接受）。
    """

    数据 = _库()
    库 = 数据.library()
    出: dict[tuple, list] = {}
    for 编号, (序列, 路径) in 数据.TEMPLATE_CLUSTERS.items():
        签名 = (数据.TEMPLATE_FACES[编号], tuple(序列), tuple(路径))
        出.setdefault(签名, []).append((编号, 库[编号]["主体"],
            {编号: {"主体": 库[编号]["主体"], "参数位置": 引擎模板.index_map(库[编号]["主体"])}}))
    for 签名 in 出:
        出[签名].sort(key=lambda 项: (-json.dumps(项[1], ensure_ascii=False).count("$参数"), 项[0]))
    return 出


def _signature(effect: dict, face: str) -> tuple:
    """一条效果的**结构签名**：面 + 动作序列 + 叶子路径表。"""

    return (
        face,
        tuple(模板._ability_sequence(effect, [])),
        模板._shape(effect),
    )


def _migrate_array(array: list, targets, face: str) -> tuple[list, int, int]:
    """把一个效果数组里的项能换就换成引用，返回 `(新数组, 替换数, 保留数)`。

    每项先过 `模板._fold_repeats`——与收集器**同一口径**。生成器折叠了「同一结算点上
    重复的增量」，迁移若不折叠就会拿着未折叠的形状去找原型，永远命中不了；两边口径
    一旦脱节，覆盖率会凭空掉一截（实测漏掉 1,669 条顶层效果）。
    """

    replaced = 0
    skipped = 0
    new_items = []
    # 与收集器**同一口径**：整数组先折叠一遍，相邻重复项（含两张一模一样的引用）才会
    # 互相比出来。逐项折永远发现不了相邻重复。
    for item in 模板._fold_repeats(array):
        if not 模板._is_unit_item(item):
            new_items.append(item)
            continue
        # 折叠后的项**同时**用于找原型和拼引用：两处必须是同一份形状。
        # 曾经拿折叠后的去找原型、又拿未折叠的去拼引用，形状不同必然失配。
        candidates = targets.get(_signature(item, face))
        reference = None
        if candidates:
            for 编号, 主体, 单库 in candidates:
                reference = _try_reference(item, 编号, 主体, 单库)
                if reference is not None:
                    break
        if reference is None:
            skipped += 1
            new_items.append(item)
        else:
            replaced += 1
            new_items.append(reference)
    return new_items, replaced, skipped


def _try_reference(effect: dict, template_id: str, body: Any, one: dict) -> dict | None:
    """能无损还原就返回引用节点，否则返回 None。

    实参由 `restore_reference` 自己从 `effect` 里按位置取——这是内容寻址的关键：调用方
    不必知道参数怎么编号，只把「原文」和「哪份主体」给它。

    曾经这里先做一次「空实参探测展开」，那是旧方案为了从展开结果里反推实参编号用的
    （编号是 `p1`/`p2`，位置对不上就只能反推）。现在实参直接来自原文，探测不但没必要，
    还会**误杀带参数的模板**——空实参必然报「缺少参数」，覆盖率因此从 23,645 掉到 925。
    """

    return 引擎模板.restore_reference(template_id, body, effect, one)


def _sources() -> list[tuple[str, pathlib.Path]]:
    """全部参与迁移的面文件：`(面名, 文件)`。"""

    out: list[tuple[str, pathlib.Path]] = []
    for segment, config in 模板.SEGMENTS.items():
        for path in sorted(config["目录"].glob(config["模式"])):
            out.append((segment, path))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--落盘", action="store_true", help="真正写回 data/（默认只读）")
    args = parser.parse_args()

    lib = _库().library()
    targets = _targets()
    print(f"模板库 {len(lib)} 份；可替换原型 {len(targets)} 个")

    replaced = 0
    skipped = 0
    per_segment: dict[str, int] = {}
    lines_before = 0
    lines_after = 0

    for segment, path in _sources():
        raw = path.read_text(encoding="utf-8")
        document = json.loads(raw)
        lines_before += len(raw.splitlines())
        config = 模板.SEGMENTS[segment]
        entries = document if isinstance(document, list) else [document]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            # 位置口径与收集器共用（`模板.unit_arrays`）：三段取根能力的效果数组，
            # 战场环境 / 伤势 / 战丹取配置里指定的路径。更内层的效果属于模板主体，
            # 由展开还原，不单独替换。
            for _label, _root_index, _item_index, array in 模板.unit_arrays(entry, config):
                new_items, got, kept = _migrate_array(array, targets, segment)
                if got:
                    replaced += got
                    array[:] = new_items
                skipped += kept
        payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        lines_after += len(payload.splitlines())
        per_segment[segment] = per_segment.get(segment, 0) + 1
        if args.落盘:
            path.write_text(payload, encoding="utf-8")

    print(f"替换 {replaced} 条效果；保留 {skipped} 条（无法无损还原或不属任何原型）")
    for segment in 模板.SEGMENTS:
        print(f"  {segment}：处理 {per_segment.get(segment, 0)} 个文件")
    print(f"行数 {lines_before} -> {lines_after}（省 {lines_before - lines_after} 行）")
    if not args.落盘:
        print("（试运行，未写盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
