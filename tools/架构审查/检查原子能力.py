"""原子能力的双向核对：数据只许用登记过的，登记过的必须有人实现。

## 检查什么

1. **数据侧只用登记能力**：六个面展开后的每个 `能力` 取值都必须在
   `data/战斗/定义/原子能力.json` 里。
2. **节点字段不越界**：每个能力节点的键都必须在该能力的 `字段` 声明里
   （`能力` 自身与 `$参数` 占位符除外）。
3. **登记侧不缺实现**：每个登记能力的 `执行器` 都必须在
   `executors.EXECUTOR_CATEGORIES` 里（那是**登记侧执行器 -> 类别**的权威表），
   且能力自己声明的 `类别` 必须与该执行器的类别一致；每个能力都要有卡面渲染路径
   （效果查 `card_text.ABILITY_RENDERERS`、条件查 `CONDITION_RENDERERS`、目标走 `_target`、
   根能力走 `body`）。数据键是中文，**方法名是英文**，所以渲染路径按显式映射表核对，
   不拼 `f"_ability_{能力名}"`。

   为什么不直接核「引擎有没有这个方法」：引擎的派发用**英文**方法名
   （`damage` / `recover_resource`），与登记侧的中文执行器名不是同一个命名空间，
   硬对会全体误报（我第一版就这么错过一次）。执行器真的能不能跑，由语料通道
   （1967 场）与交叉对局（5901 场）覆盖；这里只保证**登记与实现表不脱钩**。

## 为什么要有它

前两条在**启动期**由 `foundation` 的规则校验挡着（实测塞一个未登记能力名或多余字段，
启动直接报 `未知原子能力` / `规则不认识字段`）。但启动期拦不住**反向漂移**：
登记表里多出一个没人实现、或实现了却和登记对不上的能力，游戏照常起来，
只在真被用到时才炸。第 3 条就是补这一段。

## 不判失败的两类「信息」

- **登记了但六个面没用到**：那是等人用的设计面（例如 `固定属性加成` 是气机的根能力，
  不在构筑三段里），不是缺陷。
- **声明了但数据没写的字段**：可选字段本来就允许不写。数量会打印出来，供人扫一眼。

```powershell
.venv/Scripts/python.exe -X utf8 tools/架构审查/检查原子能力.py
```
"""

from __future__ import annotations

import pathlib as _pathlib
import sys as _sys

# 共用库住在 tools/库/：脚本按文件运行时 sys.path[0] 是自己的目录，得手动加。
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1] / "库"))

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
for _path in (str(ROOT), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

REGISTRY = ROOT / "data" / "战斗" / "定义" / "原子能力.json"


def _collect(root: pathlib.Path):
    """把六个面展开后遍历一遍，返回 (能力计数, 未声明键, 声明未用字段)。"""

    import importlib

    模板 = importlib.import_module("构筑模板")
    from 构筑模板展开 import load_build_json

    registry: dict[str, dict] = json.loads(REGISTRY.read_text(encoding="utf-8"))
    used: collections.Counter = collections.Counter()
    undeclared: collections.Counter = collections.Counter()
    used_fields: dict[str, set[str]] = collections.defaultdict(set)

    def walk(node: object) -> None:
        if isinstance(node, dict):
            ability = node.get("能力")
            if isinstance(ability, str):
                used[ability] += 1
                spec = registry.get(ability)
                if spec is not None:
                    declared = set(spec.get("字段") or {})
                    for key in node:
                        if key == "能力" or key.startswith("$"):
                            continue
                        if key not in declared:
                            undeclared[f"{ability}.{key}"] += 1
                        else:
                            used_fields[ability].add(key)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    entities = 0
    for _segment, config in 模板.SEGMENTS.items():
        for path in sorted(config["目录"].glob(config["模式"])):
            for entry in load_build_json(path):
                entities += 1
                walk(entry)

    unused_fields = {
        ability: sorted(set(spec.get("字段") or {}) - used_fields.get(ability, set()))
        for ability, spec in registry.items()
        if used.get(ability) and set(spec.get("字段") or {}) - used_fields.get(ability, set())
    }
    return registry, entities, used, undeclared, unused_fields


def main() -> int:
    import contextlib
    import io

    import game.app as app
    from game.core.combat.card_text import (
        ABILITY_RENDERERS,
        CONDITION_RENDERERS,
        CardText,
    )
    from game.core.combat.executors import EXECUTOR_CATEGORIES

    # 引擎与渲染器都要真起来：判据是「登记的能力有没有渲染路径」。
    with contextlib.redirect_stdout(io.StringIO()):
        services = app.build_game_services(data_dir=ROOT / "data")
    renderer = CardText({})
    inside = services.core.combat._require_engine()  # 确保战斗核心真是初始化的

    registry, entities, used, undeclared, unused_fields = _collect(ROOT)
    problems: list[str] = []

    # ① 数据用了但没登记
    unknown = sorted(set(used) - set(registry))
    if unknown:
        problems.append(
            "数据用了未登记的能力：" + "、".join(f"{n}({used[n]}处)" for n in unknown)
        )

    # ② 节点字段越界
    if undeclared:
        sample = "、".join(f"{k}({v}处)" for k, v in undeclared.most_common(8))
        problems.append(f"{sum(undeclared.values())} 处节点字段未声明：{sample}")

    # ③ 登记侧：执行器必须在权威表里，且声明的类别要与执行器一致；渲染路径要齐
    missing_executor: list[str] = []
    category_drift: list[str] = []
    missing_render: list[str] = []
    for ability, spec in sorted(registry.items()):
        executor = str(spec.get("执行器") or "")
        cats = EXECUTOR_CATEGORIES.get(executor)
        if cats is None:
            missing_executor.append(f"{ability}(执行器 {executor or '<空>'})")
            continue
        declared = str(spec.get("类别") or "")
        if declared and declared not in cats:
            category_drift.append(f"{ability}(声明 {declared}，执行器属 {'、'.join(sorted(cats))})")
        if declared == "条件":
            name = CONDITION_RENDERERS.get(ability)
        elif declared == "目标":
            name = "_target"
        elif declared == "装配":
            name = "body"
        else:
            name = ABILITY_RENDERERS.get(ability)
        ok = bool(name) and hasattr(renderer, name)
        if not ok:
            missing_render.append(ability)
    if missing_executor:
        problems.append("登记能力用了权威表外的执行器：" + "、".join(missing_executor))
    if category_drift:
        problems.append("声明的类别与执行器不一致：" + "、".join(category_drift))
    if missing_render:
        problems.append("登记能力缺渲染路径：" + "、".join(missing_render))
    if not inside.catalog.abilities:
        problems.append("战斗核心没有登记任何能力（初始化异常）")

    unused_registered = sorted(set(registry) - set(used))
    unused_declared = sum(len(v) for v in unused_fields.values())

    print("原子能力双向核对")
    print(f"  实体 {entities} 个；数据用到能力 {len(used)} 种；登记 {len(registry)} 个")
    print(f"  登记但六个面未用到：{len(unused_registered)} 个"
          + (f"（{'、'.join(unused_registered)}）" if unused_registered else ""))
    print(f"  声明但数据未写的字段：{unused_declared} 个（可选字段允许不写）")
    if problems:
        print(f"  {len(problems)} 项问题：")
        for item in problems:
            print(f"    {item}")
        return 1
    print("  数据只用登记能力 · 节点字段全在声明内 · 执行器在权威表内 · 类别与执行器一致 · 渲染路径齐备")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
