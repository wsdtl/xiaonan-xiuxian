"""构筑模板库的结构审查。

## 检查什么

模板库是**代码**（`game/core/combat/template_data.py`，由 `tools/构筑模板代码化.py`
从真实实例机械生成）。

1. **每份模板都有非空 `说明`**，且说明只讲机制形状、不含词条字眼。写进「蓄元」「归元」
   这类随卡变化的内容词，会让同一机制的模板因卡而异名，反而更难认。
2. **编号就是主体内容的地址**：`body_digest(主体) == 编号`。这是「重新生成库不会让
   已有引用失效」的前提，也是唯一能拦住「编号与实际内容脱节」的检查。
3. **结构簇表与主体一致**：动作序列、叶子路径表都要能从主体现算出来
   （`describe` / `paths_in`）。存那一份只是为了迁移 O(1) 查表——
   **不再另存「动作序列表」与「参数位置表」**：那是同一件事写两遍，实测漂移过。
4. **面表与库一一对应**：面是唯一不能从主体算出来的信息（主体里没有「属于哪个面」）。
5. **每个面的目录真的存在、且真的有卡**：`构筑模板.SEGMENTS` 写的是磁盘路径，
   布局搬过之后最容易坏的就是它——路径一错，那个面会被**静默跳过**（挖库少一片、
   迁移少替换一片），而库本身仍然自洽，只有这条判据能当场报出来。

非零退出即失败。属于数据维护审查，不进入游戏启动流程。
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
for _path in (str(ROOT), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

#: 说明里不该出现的内容词。词条名多以「元」「势」「印」「契」「锋」等收尾。
CONTENT_HINTS = (
    "蓄元", "归元", "养元", "护元", "灵印", "灵契", "蓄势", "锐势", "愈势",
    "气痕", "裂锋", "斩锋", "灵标",
)


def main() -> int:
    from game.core.combat.template_data import (
        TEMPLATE_CLUSTERS,
        TEMPLATE_FACES,
        library,
    )
    from game.core.combat.templates import _ability_sequence, body_digest, paths_in
    from 构筑模板 import SEGMENTS

    problems: list[str] = []
    lib = library()

    面计数: dict[str, int] = {}
    for 面, 配置 in SEGMENTS.items():
        目录 = pathlib.Path(配置["目录"])
        if not 目录.is_dir():
            problems.append(
                f"{面} 的目录不存在：{目录}（布局搬过之后没跟着改？）"
            )
            continue
        命中 = sorted(目录.glob(配置["模式"]))
        面计数[面] = len(命中)
        if not 命中:
            problems.append(
                f"{面} 的目录里没有匹配 {配置['模式']} 的文件：{目录}"
            )
    未登记 = sorted(set(TEMPLATE_FACES.values()) - set(SEGMENTS))
    if 未登记:
        problems.append(f"面表里有没在 SEGMENTS 登记的体裁：{'、'.join(未登记)}")

    if set(TEMPLATE_CLUSTERS) != set(lib):
        problems.append("TEMPLATE_CLUSTERS 与模板库的编号集合不一致")
    if set(TEMPLATE_FACES) != set(lib):
        problems.append("TEMPLATE_FACES 与模板库的编号集合不一致")

    编号错 = [k for k, v in lib.items() if body_digest(v["主体"]) != k]
    if 编号错:
        problems.append(f"{len(编号错)} 份模板的编号与主体哈希不符：{'、'.join(编号错[:5])}")

    序列错 = [
        编号 for 编号, (序列, _路径) in TEMPLATE_CLUSTERS.items()
        if _ability_sequence(lib[编号]["主体"]) != list(序列)
    ]
    if 序列错:
        problems.append(f"{len(序列错)} 份模板的簇动作序列与主体不一致：{'、'.join(序列错[:5])}")

    路径错 = [
        编号 for 编号, (_序列, 路径) in TEMPLATE_CLUSTERS.items()
        if paths_in(lib[编号]["主体"]) != list(路径)
    ]
    if 路径错:
        problems.append(f"{len(路径错)} 份模板的簇叶子路径表与主体不一致：{'、'.join(路径错[:5])}")

    checked = 0
    for template_id, entry in sorted(lib.items()):
        text = str(entry.get("说明") or "").strip()
        if not text:
            problems.append(f"{template_id} 缺少说明")
            continue
        hit = [word for word in CONTENT_HINTS if word in text]
        if hit:
            problems.append(f"{template_id} 的说明含内容词：{text}（{'、'.join(hit)}）")
        checked += 1

    print("构筑模板库结构审查")
    print(f"  模板 {len(lib)} 份；说明检查 {checked} 份")
    print("  各面卡数：" + " · ".join(f"{面} {数}" for 面, 数 in 面计数.items()))
    if problems:
        print(f"  {len(problems)} 项问题：")
        for item in problems[:20]:
            print(f"    {item}")
        return 1
    print("  说明完整 · 不含内容词 · 编号=主体哈希 · 簇表与主体一致 · 面表一一对应 · 各面目录有卡")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

