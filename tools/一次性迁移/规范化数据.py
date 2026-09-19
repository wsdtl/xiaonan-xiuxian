"""把 `data/` 里所有效果数组按「一个结算点只算一次」折叠一遍。

迁移只处理**能换成引用**的候选项，所以没能换引用的裸项会原样留在数据里——里面若有
「同一时点两笔增量」，就绕过了折叠（实测 `器律 700024` 漏了 1 处）。本工具补这一刀：
遍历每个实体的全部效果数组，逐数组折叠后落盘。

顺序上要在「生成库之前」跑，这样库与数据看到的是同一份形状。

用法：

    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/规范化数据.py --落盘
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

import 构筑模板 as 模板  # noqa: E402
from game.core.combat.fold import TEMPLATE_KEY, fold_repeats  # noqa: E402

#: 装着「一串动作」的字段名。只折这些，避免把目标/状态定义也当动作序列。
序列键 = ("效果", "尝试效果", "成功效果", "失败效果", "成立效果", "不成立效果", "选项")


def 折实体(node: object) -> int:
    """递归折叠一个实体里的全部效果数组，返回改动的数组个数。"""

    改动 = 0
    if isinstance(node, dict):
        if TEMPLATE_KEY in node:
            return 0
        for key, value in list(node.items()):
            if key in 序列键 and isinstance(value, list):
                折 = fold_repeats(value)
                if 折 != value:
                    node[key] = 折
                    改动 += 1
                value = node[key]
            改动 += 折实体(value)
    elif isinstance(node, list):
        for item in node:
            改动 += 折实体(item)
    return 改动


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--落盘", action="store_true")
    args = parser.parse_args()

    总 = 0
    文件数 = 0
    for 面, 配置 in 模板.SEGMENTS.items():
        for path in sorted(配置["目录"].glob(配置["模式"])):
            文档 = json.loads(path.read_text(encoding="utf-8"))
            条目表 = 文档 if isinstance(文档, list) else [文档]
            改动 = sum(折实体(e) for e in 条目表 if isinstance(e, dict))
            if not 改动:
                continue
            总 += 改动
            文件数 += 1
            print(f"  {面:<6} {path.name:<28} 折叠 {改动} 个数组")
            if args.落盘:
                path.write_text(
                    json.dumps(文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
    print(f"共折叠 {总} 个数组，涉及 {文件数} 个文件")
    if not args.落盘:
        print("（试运行，未写盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
