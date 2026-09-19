"""把「丹方」并进「丹药」：一份丹药里同时写清「怎么炼」与「炼出来是什么」。

## 为什么并

负责人口径（第 76 轮）：**方法与实体合并在一起**，照炼器的写法——器律一条实体里既写着
器阶 / 铸法 / 兽引，又写着完整能力树；炼丹却拆成「丹方（怎么炼）」与「丹药（是什么）」
两份实体，看一颗丹得两边对着读。

而且两边是**严格一一对应**的：359 份丹方、359 颗丹药，每份丹方的 `成丹` 唯一、没有悬空、
也没有多余的丹药（实测核过）。并起来不会丢东西，`成丹` 那一格也不用写了——就是它自己。

## 合成什么样

    丹药 = 编号 / 名称 / 说明 /〔强度〕/ 炼制难度 / 炉法 / 权重 / 使用效果 / 参考价

炼器那条路本来就长这样：实体自带「它怎么被造出来」的信息。丹方目录与「丹方」数据集一并消失。

## 跑在哪一步

跑在 `重建数据与库.py` 的「展开成原文」之后、「规范化」之前（它只是普通内容改写，
与能力改名、模板都无关；放在建库之前就行）。`从提交恢复` 的目录清单也加上了
`data/物品/炼丹/内容/丹方`，这样每次重跑都从提交里的丹方重新并一遍。

幂等：没有丹方目录时报「已合并」。

用法：
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/合并丹方.py            # 试算
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/合并丹方.py --落盘
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

丹方目录 = ROOT / "data/物品/炼丹/内容/丹方"
丹药目录 = ROOT / "data/物品/炼丹/内容/丹药"

#: 并进丹药的字段，按这个先后插在描述之后。
配方字段 = ("炼制难度", "炉法")


def 读条目(path: pathlib.Path):
    文档 = json.loads(path.read_text(encoding="utf-8"))
    条目 = 文档 if isinstance(文档, list) else [文档]
    return 文档, [e for e in 条目 if isinstance(e, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--落盘", action="store_true", help="写回数据（默认为试算）")
    args = parser.parse_args()

    if not 丹方目录.is_dir():
        print("没有丹方目录，已合并（重跑无效果）")
        return 0

    成丹表: dict[str, dict] = {}
    for path in sorted(丹方目录.rglob("*.json")):
        _, 条目们 = 读条目(path)
        for e in 条目们:
            成丹 = str(e.get("成丹") or "")
            if not 成丹:
                print(f"  {path.relative_to(ROOT)} {e.get('编号')} 没写成丹，跳过")
                continue
            成丹表[成丹] = e

    改动: list[str] = []
    脏文件: dict[pathlib.Path, object] = {}
    for path in sorted(丹药目录.rglob("*.json")):
        文档, 条目们 = 读条目(path)
        for 丹药 in 条目们:
            编号 = str(丹药.get("编号") or "")
            丹方 = 成丹表.get(编号)
            if 丹方 is None:
                print(f"  {path.relative_to(ROOT)} {编号} 没有对应丹方")
                continue
            # 键序：配方字段插在「描述」之后（有强度就排在强度后，否则排在说明后）。
            基准 = "强度" if "强度" in 丹药 else "说明"
            顺序: dict[str, object] = {}
            for 键, 值 in 丹药.items():
                顺序[键] = 值
                if 键 == 基准:
                    for 字段 in 配方字段:
                        if 字段 in 丹方:
                            顺序[字段] = 丹方[字段]
            if "强度" in 丹方 and "强度" not in 顺序:
                顺序["强度"] = 丹方["强度"]
            if 顺序 == 丹药:
                continue
            丹药.clear()
            丹药.update(顺序)
            改动.append(
                f"{编号} {丹药.get('名称')}：并入 炼制难度={丹方.get('炼制难度')}、炉法={丹方.get('炉法')}"
            )
            脏文件[path] = 文档

    print(f"并入丹药 {len(改动)} 条（丹方 {len(成丹表)} 份）")
    for 行 in 改动[:8]:
        print("  " + 行)
    if len(改动) > 8:
        print(f"  …… 其余 {len(改动) - 8} 条从略")
    if not args.落盘:
        print("（试算，未落盘；加 --落盘 写入）")
        return 0
    for path, 文档 in 脏文件.items():
        path.write_text(
            json.dumps(文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    shutil.rmtree(丹方目录)
    print(f"已写入 {len(脏文件)} 个文件；删掉 {丹方目录.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
