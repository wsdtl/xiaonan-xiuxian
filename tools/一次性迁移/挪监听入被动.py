"""把 `400397` 里挂错槽位的监听事件挪进被动技能。

`偷天换日禁术·偷天化影`（主动技能 `能力[0]`）的效果里塞了一个 `监听事件`。监听属于
**常驻能力**，放在主动技能的释放序列里语义不成立——渲染时直接报
「〈未支持：出现在非被动槽位〉」，引擎也不会把它注册成常驻监听。

同一张卡的被动技能 `偷天换日禁术·偷天留章`（`能力[2]`）本来就是这张卡的监听容器
（里面 4 条监听）。把这条挪到它末尾即可，不新建被动、不改结构。

用法：

    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/挪监听入被动.py
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

文件 = ROOT / "data/战斗/内容/功法/功法-禁术.json"
编号 = "400397"


def main() -> int:
    文档 = json.loads(文件.read_text(encoding="utf-8"))
    for 实体 in 文档:
        if str(实体.get("编号")) != 编号:
            continue
        能力 = 实体.get("能力")
        if not isinstance(能力, list):
            raise SystemExit("能力不是数组")
        源 = 能力[0].get("效果")
        目标 = None
        for 槽 in 能力:
            if 槽.get("能力") == "被动技能" and isinstance(槽.get("效果"), list):
                目标 = 槽["效果"]
                break
        if 目标 is None:
            raise SystemExit("找不到被动技能槽")

        搬走 = [x for x in 源 if isinstance(x, dict) and x.get("能力") == "监听事件"]
        if not 搬走:
            print("没有需要搬的监听，已处理过")
            return 0
        源[:] = [x for x in 源 if x not in 搬走]
        目标.extend(搬走)
        文件.write_text(
            json.dumps(文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{编号}：从 {能力[0].get('名称')} 挪走 {len(搬走)} 条监听，"
              f"并入被动技能（现 {len(目标)} 项）")
        return 0
    raise SystemExit(f"找不到 {编号}")


if __name__ == "__main__":
    raise SystemExit(main())
