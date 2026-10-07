"""命名判据：主动 / 被动的短名在全库唯一，全名也唯一，**卡名也唯一**。

负责人口径（第 74 轮）：**每个名字全局不一样**，而且「符合环境就行」——撞名的补这张卡
自己的身份词前缀（`雁回旧痛复响` / `太古留魂（亡后）`），不另起新词。

正文显示的是短名（`卡名·短名` 取 `·` 之后那段），所以短名撞车才是玩家看得见的那一半；
全名撞车说明连「哪张卡的哪个技能」都分不出来。

卡名是第 76 轮补上的：全库编号实体 3615 个里，名称撞车正好三处（`破格` 气机/伤势、
`移星易宿` 真意/器律、`婴变滞涩` 伤势 ×2），负责人给了话一并改，改法见
**卡名撞车比能力名更外面一层**：玩家在纳戒、查看页、
战报里看到的第一行就是它。

**退出码：0 = 名字全库唯一，1 = 有撞名。**
"""

from __future__ import annotations

import collections
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

from 全库扫描 import 全库文档  # noqa: E402


def 短名(全名: str) -> str:
    return str(全名 or "").rsplit("·", 1)[-1]


def main() -> int:
    能力数 = 0
    短名们: collections.Counter = collections.Counter()
    全名们: collections.Counter = collections.Counter()
    卡名们: collections.Counter = collections.Counter()
    卡内: list[str] = []
    归属: dict[str, list[str]] = collections.defaultdict(list)
    卡名归属: dict[str, list[str]] = collections.defaultdict(list)
    for 相对, 文档 in 全库文档():
        条目 = 文档 if isinstance(文档, list) else [文档]
        for 实体 in 条目:
            if not isinstance(实体, dict) or not 实体.get("编号"):
                continue
            卡名 = str(实体.get("名称") or "")
            if 卡名:
                卡名们[卡名] += 1
                卡名归属[卡名].append(f"{实体.get('编号')}（{相对}）")
            本卡: collections.Counter = collections.Counter()
            for 节点 in 实体.get("能力") or ():
                if not (isinstance(节点, dict) and 节点.get("能力") in ("主动技能", "被动技能")):
                    continue
                能力数 += 1
                全名 = str(节点.get("名称") or "")
                短 = 短名(全名)
                短名们[短] += 1
                全名们[全名] += 1
                归属[短].append(f"{实体.get('编号')} {实体.get('名称')}")
                本卡[短] += 1
            for 名, 次 in 本卡.items():
                if 次 > 1:
                    卡内.append(f"{实体.get('编号')} {实体.get('名称')} 的 {名} ×{次}")

    短重 = {名: 次 for 名, 次 in 短名们.items() if 次 > 1}
    全重 = {名: 次 for 名, 次 in 全名们.items() if 次 > 1}
    卡名重 = {名: 次 for 名, 次 in 卡名们.items() if 次 > 1}
    print(f"能力 {能力数} 个 · 短名 {len(短名们)} 个 · 全名 {len(全名们)} 个 · 卡名 {len(卡名们)} 个")
    print(
        f"短名撞车 {len(短重)} 处 · 全名撞车 {len(全重)} 处 · "
        f"卡内同名 {len(卡内)} 处 · 卡名撞车 {len(卡名重)} 处"
    )
    for 名, 次 in sorted(短重.items(), key=lambda x: -x[1])[:20]:
        print(f"    {名} ×{次}：{'、'.join(sorted(set(归属[名]))[:4])}")
    for 名, 次 in sorted(全重.items())[:10]:
        print(f"    全名 {名} ×{次}")
    for 名, 次 in sorted(卡名重.items(), key=lambda x: -x[1])[:20]:
        print(f"    卡名 {名} ×{次}：{'、'.join(卡名归属[名][:4])}")
    for 行 in 卡内[:10]:
        print(f"    卡内 {行}")
    return 1 if (短重 or 全重 or 卡内 or 卡名重) else 0


if __name__ == "__main__":
    raise SystemExit(main())
