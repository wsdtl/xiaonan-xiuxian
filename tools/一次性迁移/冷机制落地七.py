"""冷机制落地（第七批）：给援护 / 同契丹新加 `造成伤害前` 监听，把 `转移伤害` 推过 20。

第六批的结论：`转移伤害`（19）与 `分摊伤害`（21）都只能挂在伤害事件的监听里，而战丹里
监听伤害事件的丹已经挂满——**再涨只能新加一条监听**，不能往别的监听里硬塞
（硬塞就是 `ValueError: 当前事件不是造成伤害前`）。

本批给"队友挨打"这个场景补监听：`造成伤害前` + `观察角色=承受者` + `阵营关系=其他己方`
（即"挨打的是别人"），里面放转移或分摊。

    python tools/一次性迁移/冷机制落地七.py --试运行
    python tools/一次性迁移/冷机制落地七.py
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
PILLS = ROOT / "data/物品/炼丹/内容/丹药/战丹"
PARTY = ("援护", "同契", "合炼")


def nodes(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from nodes(value)


def self_target() -> dict:
    return {"能力": "选择目标", "范围": "自身"}


def listeners(entry: dict) -> list[dict]:
    raw = (entry.get("使用效果") or {}).get("监听")
    return raw if isinstance(raw, list) else []


def has(entry: dict, ability: str) -> bool:
    return any(node.get("能力") == ability for node in nodes(entry.get("使用效果")))


def watcher(effect: dict) -> dict:
    """队友挨打时触发的一条监听。"""

    return {"能力": "监听事件", "事件": "造成伤害前", "观察角色": "承受者",
            "阵营关系": "其他己方", "效果": [effect], "每场战斗最多触发": 2}


def transfer() -> dict:
    return {"能力": "转移伤害", "目标": self_target(),
            "数值": {"能力": "读取数值", "来源": "本次数值", "百分比": 100}}


def share() -> dict:
    return {"能力": "分摊伤害",
            "目标": {"能力": "选择目标", "范围": "己方", "排除自身": True,
                     "选择全部": True},
            "比例": 40}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--试运行", action="store_true")
    args = parser.parse_args()

    files = sorted(PILLS.glob("*.json"))
    documents = {path: json.loads(path.read_text(encoding="utf-8")) for path in files}
    rows = [(path, entry) for path in files for entry in documents[path]]
    touched: list[str] = []

    def theme(path: pathlib.Path) -> str:
        return path.stem.split("-")[1]

    def place(mechanism: str, quota: int, effect: dict, text: str) -> int:
        done = 0
        for path, entry in rows:
            if done >= quota:
                break
            if theme(path) not in PARTY or has(entry, mechanism):
                continue
            if any(str(node.get("事件")) == "造成伤害前" for node in listeners(entry)):
                continue  # 已经有伤害前监听：交给别的丹
            listeners(entry).append(watcher(effect()))
            done += 1
            touched.append(f"  {entry['编号']} {entry['名称']:<7}({theme(path)}) {text}")
        return done

    place("转移伤害", 4, transfer, "新增 造成伤害前 监听：队友挨的这一下转到我身上")
    place("分摊伤害", 4, share, "新增 造成伤害前 监听：队友挨的这一下全队分摊")

    print(f"落点 {len(touched)} 枚")
    for line in touched:
        print(line)
    if args.试运行:
        print("\n（试运行，未落盘）")
        return 0

    for path, document in documents.items():
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"\n已写入 {len(documents)} 个战丹文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
