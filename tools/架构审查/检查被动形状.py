"""被动形状判据：**一个被动只挂一条监听**，而且同一张卡里能力名不重复。

负责人口径（第 73 轮）：被动里混着 5~8 条监听，正文看起来就是「一个被动做了五件事」；
拆完之后每个被动各占一条、各有各的名字（`原短名（事件简称）`）。

这一条同时挡住三类退化：

* 新的被动又被写成「一个挂多条」；
* 拆完再被别的步骤（往被动里补监听的那种）拼回去；
* 拆出来的名字撞车（同一卡里两条被动同名——起名后缀没接上时就会这样）。
"""

from __future__ import annotations

import collections
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

from 全库扫描 import 全库文档  # noqa: E402


def main() -> int:
    实体数 = 0
    被动数 = 0
    混装: list[tuple[str, str, str, int]] = []
    重名: list[tuple[str, str, str]] = []
    计数: collections.Counter = collections.Counter()
    for 相对, 文档 in 全库文档():
        条目 = 文档 if isinstance(文档, list) else [文档]
        for 实体 in 条目:
            if not isinstance(实体, dict) or not 实体.get("编号"):
                continue
            实体数 += 1
            名字: collections.Counter = collections.Counter()
            for 节点 in 实体.get("能力") or ():
                if not (isinstance(节点, dict) and 节点.get("能力") == "被动技能"):
                    continue
                被动数 += 1
                名字[str(节点.get("名称") or "")] += 1
                监听 = [
                    x for x in (节点.get("效果") or ())
                    if isinstance(x, dict) and x.get("能力") == "监听事件"
                ]
                计数[len(监听)] += 1
                if len(监听) > 1:
                    混装.append(
                        (相对, str(实体.get("编号")), str(节点.get("名称")), len(监听))
                    )
            for 名, 次 in 名字.items():
                if 次 > 1:
                    重名.append((相对, str(实体.get("编号")), f"{名} ×{次}"))

    print(f"实体 {实体数} 个 · 被动 {被动数} 个")
    print("每个被动挂的监听条数：" + " · ".join(
        f"{条数} 条 × {次}" for 条数, 次 in sorted(计数.items())
    ))
    print(f"混装被动 {len(混装)} 个")
    for 相对, 编号, 名, 次 in 混装[:20]:
        print(f"    {相对} {编号} {名} 挂了 {次} 条监听")
    print(f"同名被动 {len(重名)} 处")
    for 相对, 编号, 名 in 重名[:20]:
        print(f"    {相对} {编号} {名}")
    return 1 if (混装 or 重名) else 0


if __name__ == "__main__":
    raise SystemExit(main())
