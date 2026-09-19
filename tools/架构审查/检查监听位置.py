"""审查：主动技能的效果数组里不该出现 `监听事件`。

## 为什么

战斗核心登记监听时**只遍历被动槽位**（`mechanics._collect_fighter_listeners` →
`owner.passives`），而 `_ability_listener` 是个空操作（直接 `return True`）。所以写在
**主动技能**效果数组里的 `监听事件` 永远不会触发——效果白写，卡面正文却会把它渲染出来，
再叠一句「出现在非被动槽位」，玩家读到的是一个看不到效果的句子。

`data/战斗/内容/功法/说明.md` 也是这个口径：主动技能承载「精神消耗、冷却、目标与效果」，
监听节点归被动技能。

## 判据

扫描六个面里**每个面的匹配单位**（根能力的效果数组 / 配置指定的位置），找 `监听事件`：
- 被动技能 / 战场环境阶段 / 伤势与战丹的 `监听` 位置 —— 正常；
- **主动技能的效果数组** —— 报错，并给出卡号与技能名。

不入 `tools/全量核对.py` 的必过项：现存一处已知例外（`功法 400397`），
它需要设计决定（把监听挪进被动槽位，还是删掉），不该用一条红灯替你决定。

```powershell
.venv/Scripts/python.exe -X utf8 tools/架构审查/检查监听位置.py
```
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
for _path in (str(ROOT), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def main() -> int:
    import importlib

    模板 = importlib.import_module("构筑模板")
    from 构筑模板展开 import load_build_json

    problems: list[str] = []
    checked = 0
    for segment, config in 模板.SEGMENTS.items():
        for path in sorted(config["目录"].glob(config["模式"])):
            for entry in load_build_json(path):
                if not isinstance(entry, dict):
                    continue
                for root in entry.get("能力") or []:
                    if root.get("能力") != "主动技能":
                        continue
                    # 只看主动技能**自己的效果数组**里的直接项。更深的监听
                    # （`监听事件.效果` 里再套监听）不是这个话题。
                    for node in root.get("效果") or []:
                        checked += 1
                        if isinstance(node, dict) and node.get("能力") == "监听事件":
                            problems.append(
                                "%s %s %s（事件=%s）"
                                % (segment, entry.get("编号"),
                                   root.get("名称"), node.get("事件"))
                            )

    print("监听位置审查")
    print(f"  检查主动技能效果项 {checked} 个；发现监听写在主动槽位 {len(problems)} 处")
    if problems:
        for item in problems[:20]:
            print(f"    {item}")
        print("  处理方式：把监听挪进该卡的被动技能，或删掉——写在主动槽位里从不生效。")
        return 1
    print("  主动槽位没有监听节点")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
