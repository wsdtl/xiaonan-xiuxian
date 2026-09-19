"""换源·按已损失恢复：把「按自身上限恢复」改成「按缺口恢复」。

第 26 轮验证过的改法（`真意-绝境`/`献祭`/`返照` 50 处，镜像差异 11 ⊆ 授权、强度 −0.77pt）：

    `恢复资源{X} = 读取数值(自身属性: {X}上限) × N%`
      → 恢复对象是自身      读 `自身已损失{X}`（越残回得越多，满血回 0）
      → 恢复对象是己方/其他 读 `目标已损失{X}`（谁缺得多补谁）

百分比不动：`已损失 ≤ 上限`，所以是**前期略弱、后期略强**的形状改动，不是单纯加号。
语义要求：卡的主题得对得上（绝境 / 献祭 / 疗愈 / 救急）。对不上就别用这个工具。

    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/换源恢复.py --文件 真意-众生 真意-制心   # 试算
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/换源恢复.py --文件 真意-众生 --写入 --授权集 _授权.json

**退出码：0 = 正常，2 = 没匹配到任何可改处（口径不对或已经改过）。**
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SURFACES = ("功法", "真意", "气机", "器律")
DIRS = {
    "功法": "data/战斗/内容/功法",
    "真意": "data/战斗/内容/真意",
    "气机": "data/战斗/内容/气机",
    "器律": "data/物品/炼器/内容/器律",
}
#: 资源上限 → 对应资源名。
CAP_TO_RESOURCE = {"血气上限": "血气", "精神上限": "精神", "护盾上限": "护盾"}


def locate(name: str) -> pathlib.Path:
    """按 `功法-医经` 这种名字找到文件（也接受相对/绝对路径）。"""
    direct = pathlib.Path(name)
    if direct.is_file():
        return direct
    for surface, folder in DIRS.items():
        candidate = ROOT / folder / f"{name}.json"
        if candidate.is_file():
            return candidate
    raise SystemExit(f"找不到卡文件：{name}（可用名字形如 真意-众生 / 功法-医经）")


def rewrite(path: pathlib.Path, *, write: bool) -> tuple[int, list[str]]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    cards: list[str] = []

    def walk(node: object, card: str, heal_scope: str | None) -> None:
        nonlocal changed
        if isinstance(node, dict):
            ability = str(node.get("能力") or "")
            if ability == "恢复资源":
                target = node.get("目标") or {}
                heal_scope = str(target.get("范围") or "目标") if isinstance(target, dict) else "目标"
            if (
                ability == "读取数值"
                and node.get("来源") == "自身属性"
                and str(node.get("属性") or "") in CAP_TO_RESOURCE
                and heal_scope is not None
            ):
                resource = CAP_TO_RESOURCE[str(node["属性"])]
                node["来源"] = (f"自身已损失{resource}" if heal_scope == "自身"
                                else f"目标已损失{resource}")
                node.pop("属性", None)
                changed += 1
                if card not in cards:
                    cards.append(card)
            for value in node.values():
                walk(value, card, heal_scope)
        elif isinstance(node, list):
            for value in node:
                walk(value, card, heal_scope)

    for entry in entries:
        walk(entry, str(entry["编号"]), None)
    if write and changed:
        path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed, sorted(cards)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--文件", nargs="+", required=True, help="卡文件名（如 真意-众生 功法-医经）")
    parser.add_argument("--写入", action="store_true", help="默认只试算，加这个才落盘")
    parser.add_argument("--授权集", default="", help="把授权卡清单写到这个 json")
    args = parser.parse_args()

    grant: dict[str, list[str]] = {}
    total = 0
    for name in args.文件:
        path = locate(name)
        changed, cards = rewrite(path, write=args.写入)
        total += changed
        print(f"{path.stem}: {'换' if args.写入 else '可换'} {changed} 处，"
              f"涉及 {len(cards)} 张卡")
        if changed:
            grant[path.relative_to(ROOT).as_posix()] = cards

    if not total:
        print("没匹配到可改处：口径不对、或这批已经改过。")
        return 2
    if args.授权集:
        pathlib.Path(args.授权集).write_text(
            json.dumps(grant, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"授权集写入 {args.授权集}（{sum(len(v) for v in grant.values())} 张）")
    if not args.写入:
        print("这是试算；确认后再加 --写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
