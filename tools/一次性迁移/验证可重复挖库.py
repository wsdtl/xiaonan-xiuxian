"""验证内容寻址的核心承诺：**从原文重挖得到同一份库**。

## 为什么不能直接在仓库上重挖

数据迁移成引用之后，引用节点没有 `能力` 键，收集器认不出它们是候选（实测仓库上只挖到
73 个簇，而库里有 1,378 份模板）。这正是旧方案的病根：**库不可复现**，于是「重新生成库」
必须与「重挂引用」严格同步，拆开跑就毁数据。

内容寻址下这件事变成可验证的命题：把数据展开成原文再挖一遍，**编号应该逐一相同**——
因为编号是主体内容的哈希，与「第几次挖、按什么顺序挖」无关。

本工具在**临时副本**上做这件事，不碰仓库数据。

用法：

    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/验证可重复挖库.py
"""

from __future__ import annotations

import importlib
import json
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

import 构筑模板 as 模板  # noqa: E402
from game.core.combat import templates as 引擎  # noqa: E402
from game.core.combat.template_data import library  # noqa: E402

工作区 = pathlib.Path(tempfile.gettempdir()) / "可重复性工作区"


def main() -> int:
    库 = library()
    指纹 = {编号: json.dumps(条目["主体"], ensure_ascii=False, sort_keys=True)
            for 编号, 条目 in 库.items()}
    print(f"现行库 {len(库)} 份模板")

    # 1) 把仓库数据展开成原文，写进工作区
    仓库 = {面: 配置["目录"] for 面, 配置 in 模板.SEGMENTS.items()}
    if 工作区.exists():
        shutil.rmtree(工作区)
    for 面, 配置 in 模板.SEGMENTS.items():
        目标 = 工作区 / 面
        目标.mkdir(parents=True, exist_ok=True)
        for path in sorted(仓库[面].glob(配置["模式"])):
            文档 = json.loads(path.read_text(encoding="utf-8"))
            for 实体 in (文档 if isinstance(文档, list) else [文档]):
                if isinstance(实体, dict):
                    引擎.expand_in_place(实体, 库)
            (目标 / path.name).write_text(
                json.dumps(文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        print(f"面 {面:<6} 已展开成原文")

    # 2) 从原文重挖（生成器读 SEGMENTS 指向的目录）
    模板.SEGMENTS = {面: {**配置, "目录": 工作区 / 面} for 面, 配置 in 模板.SEGMENTS.items()}
    生成器 = importlib.import_module("构筑模板代码化")
    条目表 = {}
    for unit in 模板._ranked_units(模板._collect_units()):
        条目 = 生成器._entry(unit)
        if 条目 is not None:
            条目表[条目[0]] = 条目
    print(f"重挖得到 {len(条目表)} 份模板")

    # 3) 比对
    少 = sorted(set(库) - set(条目表))
    多 = sorted(set(条目表) - set(库))
    变 = [编号 for 编号 in set(库) & set(条目表)
          if json.dumps(条目表[编号][1], ensure_ascii=False, sort_keys=True) != 指纹[编号]]
    print(f"重挖缺失 {len(少)}；多出 {len(多)}；主体不同 {len(变)}")
    for 编号 in 少[:5]:
        print("   缺:", 编号, 库[编号]["说明"])
    for 编号 in 多[:5]:
        print("   多:", 编号, json.dumps(条目表[编号][1], ensure_ascii=False)[:80])
    for 编号 in 变[:5]:
        print("   变:", 编号, 库[编号]["说明"])

    # 4) 结论：已落盘的引用在新库上是否仍全部成立
    坏 = 0
    for 面, 配置 in 仓库.items():
        for path in sorted(配置.glob(模板.SEGMENTS[面]["模式"])):
            文档 = json.loads(path.read_text(encoding="utf-8"))
            for 实体 in (文档 if isinstance(文档, list) else [文档]):
                if not isinstance(实体, dict):
                    continue
                引用: list = []

                def 走(n):
                    if isinstance(n, dict):
                        if "模板" in n:
                            引用.append(n)
                            return
                        for v in n.values():
                            走(v)
                    elif isinstance(n, list):
                        for v in n:
                            走(v)

                走(实体)
                for r in 引用:
                    if str(r.get("模板")) not in 库:
                        坏 += 1
    print(f"仓库引用里指向「现行库没有的编号」的：{坏}")
    return 1 if (少 or 变 or 坏) else 0


if __name__ == "__main__":
    raise SystemExit(main())
