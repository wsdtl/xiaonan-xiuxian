"""炼丹形状判据：**方法与实体合在一处**，不再有单独的丹方。

负责人口径（第 76 轮）：炼器那边一条器律里同时写着「怎么造」（器阶 / 铸法 / 兽引）
和「造出来是什么」（属性构成 / 能力树）；炼丹原先却拆成「丹方（怎么炼）」与
「丹药（是什么）」两份严格 1:1 的实体，看一颗丹得两边对着读。现在并成一条丹药：
`编号 / 名称 / 说明 /〔强度〕/ 炼制难度 / 炉法 / 权重 / 使用效果 / 参考价`。

这一条挡住五类退化：

* 又分出一份「丹方」数据集、目录或编号段（11/13/15/17）；
* 丹药漏了处方那一半（`炼制难度` / `炉法`），退回「只有成品、没法炼」；
* 丹药又写回 `成丹` 那一格——并了之后它就是它自己，写回去就是两份实体的残影；
* `物品/炼丹/组件.json` 的实体类别 / 编号类别 / 路径与 `基础/定义/编号.json` 的前缀段对不上；
* 字段契约的必填 / 可选与实体实际写的字段脱钩（契约变成装饰）；
* 物品层（`物品/基础物品/规则/分类.json`）那一份丹药条目与炼丹侧各写一套、互相漂移。
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

from 全库扫描 import 全库文档  # noqa: E402

#: 丹药的编号前缀 → 主体。恢复 / 战斗 / 突破 / 特殊四段，与 `编号.json` 一致。
丹药前缀 = {"10": "恢复丹", "12": "战丹", "14": "突破丹", "16": "特殊丹"}
#: 并进丹药之后必须消失的旧丹方编号段。
死丹方前缀 = {"11", "13", "15", "17"}
必填 = {"编号", "名称", "说明", "炉法", "炼制难度", "使用效果", "权重", "参考价"}
可选 = {"强度"}
#: 丹药字段的书写顺序（`合并丹方.py` 定下来的那个）。
字段序 = ["编号", "名称", "说明", "强度", "炼制难度", "炉法", "权重", "使用效果", "参考价"]


def _读json(相对: str) -> Any:
    return json.loads((ROOT / "data" / 相对).read_text(encoding="utf-8"))


def main() -> int:
    问题: list[str] = []

    # 一、目录与数据集形状
    if (ROOT / "data/物品/炼丹/内容/丹方").exists():
        问题.append("data/物品/炼丹/内容/丹方 又出现了（丹方已并进丹药）")
    if not (ROOT / "data/物品/炼丹/内容/丹药").is_dir():
        问题.append("data/物品/炼丹/内容/丹药 不见了")

    组件 = _读json("物品/炼丹/组件.json")
    数据集 = collections.Counter(
        str(规则.get("数据集")) for 规则 in 组件["读取规则"]
    )
    for 名 in 数据集:
        if 名 == "丹方":
            问题.append("物品/炼丹/组件.json 又登记了「丹方」数据集")
    if 数据集.get("丹药") != 1:
        问题.append(f"物品/炼丹/组件.json 的「丹药」数据集应为 1 条，实为 {数据集.get('丹药', 0)}")
    for 规则 in 组件["读取规则"]:
        if 规则.get("数据集") != "丹药":
            continue
        if 规则.get("路径") != "物品/炼丹/内容/丹药/*/*.json":
            问题.append(f"丹药数据集路径变了：{规则.get('路径')}")
        if 规则.get("实体类别") != "丹药" or 规则.get("编号类别") != "丹药":
            问题.append(
                f"丹药数据集的实体/编号类别应为「丹药」："
                f"{规则.get('实体类别')} / {规则.get('编号类别')}"
            )

    # 二、编号前缀段
    前缀表 = _读json("基础/定义/编号.json")["编号前缀"]
    丹药段 = {str(项["前缀"]): str(项["主体"]) for 项 in 前缀表 if 项.get("类别") == "丹药"}
    if 丹药段 != 丹药前缀:
        问题.append(f"编号.json 的丹药前缀段是 {丹药段}，应为 {丹药前缀}")
    for 项 in 前缀表:
        if "丹方" in f"{项.get('类别')}{项.get('主体')}":
            问题.append(f"编号.json 里还有丹方前缀：{项}")
        if str(项["前缀"]) in 死丹方前缀:
            问题.append(f"编号.json 里还有旧丹方号段 {项['前缀']}：{项}")

    # 三、丹药实体
    实体数 = 0
    段计数: collections.Counter = collections.Counter()
    字段集合: set[frozenset[str]] = set()
    for 相对, 文档 in 全库文档():
        if not 相对.startswith("data/物品/炼丹/内容/丹药/"):
            continue
        for 实体 in 文档 if isinstance(文档, list) else [文档]:
            if not (isinstance(实体, dict) and 实体.get("编号")):
                continue
            实体数 += 1
            编号 = str(实体["编号"])
            标签 = f"{相对} {编号} {实体.get('名称')}"
            段计数[编号[:2]] += 1
            if 编号[:2] not in 丹药前缀:
                问题.append(f"{标签}：编号前缀 {编号[:2]} 不是丹药四段之一")
            if "成丹" in 实体:
                问题.append(f"{标签}：并了之后不该再有「成丹」字段")
            键 = set(实体)
            字段集合.add(frozenset(键))
            缺 = 必填 - 键
            if 缺:
                问题.append(f"{标签}：缺必填字段 {'、'.join(sorted(缺))}")
            多 = 键 - 必填 - 可选
            if 多:
                问题.append(f"{标签}：契约外的字段 {'、'.join(sorted(多))}")
            难度 = 实体.get("炼制难度")
            if not isinstance(难度, int) or 难度 < 1:
                问题.append(f"{标签}：炼制难度应为 ≥1 的整数，实为 {难度!r}")
            if not isinstance(实体.get("炉法"), str) or not 实体.get("炉法"):
                问题.append(f"{标签}：炉法为空")
            序 = [字段序.index(k) for k in 实体 if k in 字段序]
            if 序 != sorted(序):
                问题.append(f"{标签}：字段顺序不是 { '/'.join(字段序) }，实为 {'/'.join(实体)}")

    # 四、字段契约与实体实际字段对齐
    契约 = _读json("物品/炼丹/规则/炼丹字段契约.json")
    类别 = {str(项.get("类别")) for 项 in 契约}
    if 类别 != {"丹药"}:
        问题.append(f"炼丹字段契约的类别应为 {{'丹药'}}，实为 {类别}")
    for 项 in 契约:
        声明的必填 = {str(x) for x in 项.get("必填字段") or ()}
        声明的可选 = {str(x) for x in 项.get("可选字段") or ()}
        if 声明的必填 != 必填:
            问题.append(f"契约必填字段与实体不符：{sorted(声明的必填)}")
        if 声明的可选 != 可选:
            问题.append(f"契约可选字段与实体不符：{sorted(声明的可选)}")

    # 五、物品层那一份丹药条目：与炼丹侧同源，只能更窄，不能各写一套
    分类 = _读json("物品/基础物品/规则/分类.json")
    物品条目 = [项 for 项 in 分类 if 项.get("类别") == "丹药"]
    if len(物品条目) != 1:
        问题.append(f"物品/基础物品/规则/分类.json 的丹药条目应有 1 条，实为 {len(物品条目)}")
    else:
        条目 = 物品条目[0]
        物品必填 = {str(x) for x in 条目.get("必填字段") or ()}
        物品声明 = 物品必填 | {str(x) for x in 条目.get("可选字段") or ()}
        越界 = 物品声明 - 必填 - 可选
        if 越界:
            问题.append(f"物品层的丹药条目声明了炼丹侧没有的字段：{sorted(越界)}")
        缺 = {"使用效果", "炉法", "炼制难度"} - 物品必填
        if 缺:
            问题.append(f"物品层的丹药必填字段少了：{sorted(缺)}")

    print(f"丹药 {实体数} 颗 · 号段 " + " · ".join(
        f"{段}({丹药前缀.get(段, '?')}) {次}" for 段, 次 in sorted(段计数.items())
    ))
    print("丹药字段组合：" + " · ".join(
        "[" + "、".join(sorted(键)) + "]" for 键 in sorted(字段集合, key=sorted)
    ))
    print(f"问题 {len(问题)} 处")
    for 条 in 问题[:20]:
        print(f"    {条}")
    return 1 if 问题 else 0


if __name__ == "__main__":
    raise SystemExit(main())
